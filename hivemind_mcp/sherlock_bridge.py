"""Sherlock Bridge — MCP-to-MCP subprocess integration.

Spawns Sherlock as a child MCP server (stdio transport) and proxies
tool calls from HiveMind.  The subprocess is started lazily on the
first tool call and kept alive for the lifetime of the HiveMind
server.  If the subprocess dies it is automatically restarted on the
next call.

Architecture:
    HiveMind MCP Server (parent)
        → SherlockBridge (this module)
            → Sherlock MCP Server (child process, stdio)
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

# Sherlock project root — configurable via env var or default path
SHERLOCK_ROOT = Path(
    os.environ.get(
        "SHERLOCK_ROOT",
        str(Path.home() / "Documents" / "sherlock"),
    )
)

# Sherlock Python interpreter — prefer its own venv if present
_SHERLOCK_VENV_PYTHON = SHERLOCK_ROOT / ".venv" / "Scripts" / "python.exe"
if not _SHERLOCK_VENV_PYTHON.exists():
    # Linux/macOS fallback
    _SHERLOCK_VENV_PYTHON = SHERLOCK_ROOT / ".venv" / "bin" / "python"

SHERLOCK_PYTHON = str(_SHERLOCK_VENV_PYTHON) if _SHERLOCK_VENV_PYTHON.exists() else sys.executable

# Timeout for individual tool calls through the bridge (seconds)
BRIDGE_TOOL_TIMEOUT = 120


class SherlockBridge:
    """Manages a persistent MCP client connection to the Sherlock subprocess."""

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
        """Start the Sherlock subprocess and establish an MCP session.

        Idempotent — if already connected, this is a no-op.
        """
        if self._connected and self._session is not None:
            return

        async with self._lock:
            # Double-check after acquiring lock
            if self._connected and self._session is not None:
                return

            if not SHERLOCK_ROOT.exists():
                raise FileNotFoundError(
                    f"Sherlock project not found at {SHERLOCK_ROOT}. "
                    f"Set SHERLOCK_ROOT env var to the correct path."
                )

            main_py = SHERLOCK_ROOT / "main.py"
            if not main_py.exists():
                raise FileNotFoundError(
                    f"Sherlock main.py not found at {main_py}."
                )

            logger.info(
                "Starting Sherlock subprocess: %s %s (cwd=%s)",
                SHERLOCK_PYTHON, main_py, SHERLOCK_ROOT,
            )

            server_params = StdioServerParameters(
                command=SHERLOCK_PYTHON,
                args=[str(main_py)],
                cwd=str(SHERLOCK_ROOT),
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
                "Sherlock connected — %d tools available: %s",
                len(tool_names),
                ", ".join(tool_names),
            )

    async def disconnect(self) -> None:
        """Shut down the Sherlock subprocess gracefully."""
        async with self._lock:
            if self._cm_session is not None:
                try:
                    await self._cm_session.__aexit__(None, None, None)
                except Exception:
                    logger.debug("Error closing Sherlock session", exc_info=True)
                self._cm_session = None

            if self._cm_stdio is not None:
                try:
                    await self._cm_stdio.__aexit__(None, None, None)
                except Exception:
                    logger.debug("Error closing Sherlock stdio", exc_info=True)
                self._cm_stdio = None

            self._session = None
            self._connected = False
            self._tools = {}
            logger.info("Sherlock disconnected")

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
        """Return the list of tools available on the Sherlock server."""
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
        """Call a Sherlock tool by name and return the text result.

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
                "Sherlock connection lost (%s), reconnecting…", exc
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
                    f"Sherlock tool '{tool_name}' timed out after "
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

_bridge: SherlockBridge | None = None


def get_sherlock_bridge() -> SherlockBridge:
    """Return the module-level SherlockBridge singleton."""
    global _bridge  # noqa: PLW0603
    if _bridge is None:
        _bridge = SherlockBridge()
    return _bridge


async def sherlock_available() -> bool:
    """Check whether Sherlock is available (project exists on disk)."""
    return SHERLOCK_ROOT.exists() and (SHERLOCK_ROOT / "main.py").exists()
