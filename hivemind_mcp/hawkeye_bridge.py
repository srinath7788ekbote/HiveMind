"""Hawkeye Bridge — MCP-to-MCP subprocess integration.

Spawns Hawkeye as a child MCP server (stdio transport) and proxies
tool calls from HiveMind.  The subprocess is started lazily on the
first tool call and kept alive for the lifetime of the HiveMind
server.  If the subprocess dies it is automatically restarted on the
next call.

Architecture:
    HiveMind MCP Server (parent)
        → HawkeyeBridge (this module)
            → Hawkeye MCP Server (child process, stdio)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Hawkeye project root — configurable via env var or default path
HAWKEYE_ROOT = Path(
    os.environ.get(
        "HAWKEYE_ROOT",
        str(Path.home() / "Documents" / "Hawkeye"),
    )
)

# Hawkeye Python interpreter — prefer its own venv if present
_HAWKEYE_VENV_PYTHON = HAWKEYE_ROOT / ".venv" / "Scripts" / "python.exe"
if not _HAWKEYE_VENV_PYTHON.exists():
    # Linux/macOS fallback
    _HAWKEYE_VENV_PYTHON = HAWKEYE_ROOT / ".venv" / "bin" / "python"

HAWKEYE_PYTHON = str(_HAWKEYE_VENV_PYTHON) if _HAWKEYE_VENV_PYTHON.exists() else sys.executable

# Timeout for individual tool calls through the bridge (seconds)
BRIDGE_TOOL_TIMEOUT = 120


class HawkeyeBridge:
    """Manages a persistent MCP client connection to the Hawkeye subprocess."""

    def __init__(self) -> None:
        self._session: ClientSession | None = None
        self._cm_stdio: Any = None  # context-manager for stdio_client
        self._cm_session: Any = None  # context-manager for ClientSession
        self._lock = asyncio.Lock()
        self._tools: dict[str, dict[str, Any]] = {}
        self._connected = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the Hawkeye subprocess and establish an MCP session.

        Idempotent — if already connected, this is a no-op.
        """
        if self._connected and self._session is not None:
            return

        async with self._lock:
            # Double-check after acquiring lock
            if self._connected and self._session is not None:
                return

            if not HAWKEYE_ROOT.exists():
                raise FileNotFoundError(
                    f"Hawkeye project not found at {HAWKEYE_ROOT}. "
                    f"Set HAWKEYE_ROOT env var to the correct path."
                )

            main_py = HAWKEYE_ROOT / "main.py"
            if not main_py.exists():
                raise FileNotFoundError(
                    f"Hawkeye main.py not found at {main_py}."
                )

            logger.info(
                "Starting Hawkeye subprocess: %s %s (cwd=%s)",
                HAWKEYE_PYTHON, main_py, HAWKEYE_ROOT,
            )

            server_params = StdioServerParameters(
                command=HAWKEYE_PYTHON,
                args=[str(main_py)],
                cwd=str(HAWKEYE_ROOT),
            )

            # Enter the stdio_client context manager
            self._cm_stdio = stdio_client(server_params)
            read_stream, write_stream = await self._cm_stdio.__aenter__()

            # Enter the ClientSession context manager
            self._cm_session = ClientSession(read_stream, write_stream)
            self._session = await self._cm_session.__aenter__()

            # Initialize the MCP session (protocol handshake)
            await self._session.initialize()

            # Discover available tools
            tools_result = await self._session.list_tools()
            self._tools = {}
            for tool in tools_result.tools:
                self._tools[tool.name] = {
                    "name": tool.name,
                    "description": tool.description or "",
                    "schema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
                }

            self._connected = True
            tool_names = sorted(self._tools.keys())
            logger.info(
                "Hawkeye connected — %d tools available: %s",
                len(tool_names),
                ", ".join(tool_names),
            )

    async def disconnect(self) -> None:
        """Shut down the Hawkeye subprocess gracefully."""
        async with self._lock:
            if self._cm_session is not None:
                try:
                    await self._cm_session.__aexit__(None, None, None)
                except Exception:
                    logger.debug("Error closing Hawkeye session", exc_info=True)
                self._cm_session = None

            if self._cm_stdio is not None:
                try:
                    await self._cm_stdio.__aexit__(None, None, None)
                except Exception:
                    logger.debug("Error closing Hawkeye stdio", exc_info=True)
                self._cm_stdio = None

            self._session = None
            self._connected = False
            self._tools = {}
            logger.info("Hawkeye disconnected")

    async def _ensure_connected(self) -> ClientSession:
        """Ensure we have a live connection, reconnecting if needed."""
        if not self._connected or self._session is None:
            # Clean up any stale state
            if self._connected:
                await self.disconnect()
            await self.connect()

        assert self._session is not None
        return self._session

    # ------------------------------------------------------------------
    # Tool discovery
    # ------------------------------------------------------------------

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return the list of tools available on the Hawkeye server."""
        await self._ensure_connected()
        return list(self._tools.values())

    # ------------------------------------------------------------------
    # Tool invocation
    # ------------------------------------------------------------------

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> str:
        """Call a Hawkeye tool by name and return the text result.

        On connection failure, attempts one automatic reconnect before
        raising the error.
        """
        session = await self._ensure_connected()

        try:
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments or {}),
                timeout=BRIDGE_TOOL_TIMEOUT,
            )
        except (ConnectionError, BrokenPipeError, EOFError, OSError) as exc:
            logger.warning(
                "Hawkeye connection lost (%s), reconnecting…", exc
            )
            await self.disconnect()
            session = await self._ensure_connected()
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments or {}),
                timeout=BRIDGE_TOOL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return json.dumps({
                "error": (
                    f"Hawkeye tool '{tool_name}' timed out after "
                    f"{BRIDGE_TOOL_TIMEOUT}s."
                )
            })

        # Extract text from the MCP result
        if hasattr(result, "content") and result.content:
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            return "\n".join(parts)

        return str(result)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bridge: HawkeyeBridge | None = None


def get_bridge() -> HawkeyeBridge:
    """Return the module-level HawkeyeBridge singleton."""
    global _bridge  # noqa: PLW0603
    if _bridge is None:
        _bridge = HawkeyeBridge()
    return _bridge


async def hawkeye_available() -> bool:
    """Check whether Hawkeye is available (project exists on disk)."""
    return HAWKEYE_ROOT.exists() and (HAWKEYE_ROOT / "main.py").exists()
