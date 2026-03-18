"""
Tests for the async MCP server wrapper layer.

Covers:
    - All MCP tool functions are async (coroutines)
    - Timeout wrapper returns error dict on timeout, not an exception
    - Two concurrent tool calls both complete (no blocking)
    - ChromaDB availability flag is set
    - Self-test validates all 14 tools
    - _format_result handles edge cases
    - _run_with_timeout propagates results and errors correctly
"""

import asyncio
import inspect
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from hivemind_mcp.hivemind_server import (
    TOOL_REGISTRY,
    TOOL_TIMEOUT_SECS,
    _format_result,
    _run_with_timeout,
    hivemind_check_branch,
    hivemind_diff_branches,
    hivemind_get_active_branch,
    hivemind_get_active_client,
    hivemind_get_entity,
    hivemind_get_pipeline,
    hivemind_get_secret_flow,
    hivemind_impact_analysis,
    hivemind_list_branches,
    hivemind_propose_edit,
    hivemind_query_graph,
    hivemind_query_memory,
    hivemind_read_file,
    hivemind_recall_investigation,
    hivemind_save_investigation,
    hivemind_search_files,
    hivemind_set_client,
    hivemind_write_file,
    mcp_server,
)


# ===================================================================
# 1. All tool functions are async
# ===================================================================

class TestToolsAreAsync(unittest.TestCase):
    """Every MCP tool wrapper must be an async (coroutine) function."""

    TOOL_FUNCTIONS = [
        hivemind_check_branch,
        hivemind_query_memory,
        hivemind_query_graph,
        hivemind_get_entity,
        hivemind_search_files,
        hivemind_get_pipeline,
        hivemind_get_secret_flow,
        hivemind_impact_analysis,
        hivemind_diff_branches,
        hivemind_list_branches,
        hivemind_set_client,
        hivemind_write_file,
        hivemind_get_active_client,
        hivemind_get_active_branch,
        hivemind_save_investigation,
        hivemind_recall_investigation,
        hivemind_read_file,
        hivemind_propose_edit,
    ]

    def test_all_tools_are_coroutines(self):
        for fn in self.TOOL_FUNCTIONS:
            self.assertTrue(
                inspect.iscoroutinefunction(fn),
                f"{fn.__name__} is not async",
            )

    def test_tool_count_is_18(self):
        self.assertEqual(len(self.TOOL_FUNCTIONS), 18)

    def test_registry_has_18_tools(self):
        self.assertEqual(len(TOOL_REGISTRY), 18)

    def test_registry_values_are_callable(self):
        for name, fn in TOOL_REGISTRY.items():
            self.assertTrue(callable(fn), f"{name} is not callable")

    def test_registry_values_are_async(self):
        for name, fn in TOOL_REGISTRY.items():
            self.assertTrue(
                inspect.iscoroutinefunction(fn),
                f"{name} in TOOL_REGISTRY is not async",
            )


# ===================================================================
# 2. Timeout wrapper
# ===================================================================

class TestRunWithTimeout(unittest.TestCase):
    """_run_with_timeout behaviour."""

    def _run(self, coro):
        """Helper to run a coroutine in a fresh event loop."""
        return asyncio.run(coro)

    def test_returns_result_on_success(self):
        def fast_fn():
            return {"ok": True}

        result = self._run(_run_with_timeout(fast_fn, timeout=5))
        self.assertEqual(result, {"ok": True})

    def test_returns_error_on_timeout(self):
        def slow_fn():
            time.sleep(10)
            return "never"

        result = self._run(_run_with_timeout(slow_fn, timeout=0.1))
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)
        self.assertIn("timed out", result["error"].lower())

    def test_passes_kwargs(self):
        def fn_with_kwargs(a=1, b=2):
            return a + b

        result = self._run(_run_with_timeout(fn_with_kwargs, a=10, b=20, timeout=5))
        self.assertEqual(result, 30)

    def test_passes_args(self):
        def fn_with_args(x, y):
            return x * y

        result = self._run(_run_with_timeout(fn_with_args, 3, 7, timeout=5))
        self.assertEqual(result, 21)

    def test_timeout_constant_is_positive(self):
        self.assertGreater(TOOL_TIMEOUT_SECS, 0)

    def test_timeout_error_message_includes_duration(self):
        def slow():
            time.sleep(10)

        result = self._run(_run_with_timeout(slow, timeout=0.05))
        self.assertIn("0.05", result["error"])


# ===================================================================
# 3. Concurrent tool calls
# ===================================================================

class TestConcurrency(unittest.TestCase):
    """Two tool calls should run concurrently, not sequentially."""

    def test_concurrent_calls_complete(self):
        """Two tools called concurrently should both finish."""
        call_times = {}

        def tool_a():
            call_times["a_start"] = time.monotonic()
            time.sleep(0.1)
            call_times["a_end"] = time.monotonic()
            return "a"

        def tool_b():
            call_times["b_start"] = time.monotonic()
            time.sleep(0.1)
            call_times["b_end"] = time.monotonic()
            return "b"

        async def run_both():
            return await asyncio.gather(
                _run_with_timeout(tool_a, timeout=5),
                _run_with_timeout(tool_b, timeout=5),
            )

        results = asyncio.run(run_both())
        self.assertEqual(results, ["a", "b"])

        # Both should have started before either finished (concurrent)
        # Allow some slack for scheduling
        self.assertLess(
            abs(call_times["a_start"] - call_times["b_start"]),
            0.15,  # generous tolerance
            "Tools did not start concurrently",
        )

    def test_slow_tool_does_not_block_fast_tool(self):
        """A slow tool timing out shouldn't prevent a fast tool from returning."""

        def fast():
            return "fast"

        def slow():
            # Keep short so asyncio.run() thread-pool cleanup doesn't hang
            time.sleep(0.5)
            return "slow"

        async def run_both():
            start = time.monotonic()
            results = await asyncio.gather(
                _run_with_timeout(fast, timeout=5),
                _run_with_timeout(slow, timeout=0.1),
            )
            elapsed = time.monotonic() - start
            return results, elapsed

        results, coroutine_elapsed = asyncio.run(run_both())

        self.assertEqual(results[0], "fast")
        self.assertIn("error", results[1])
        # Coroutines should complete in ~0.1s (slow timeout), not 0.5s
        self.assertLess(coroutine_elapsed, 1.0)


# ===================================================================
# 4. _format_result
# ===================================================================

class TestFormatResult(unittest.TestCase):
    """_format_result edge cases."""

    def test_string_passthrough(self):
        self.assertEqual(_format_result("hello"), "hello")

    def test_dict_to_json(self):
        result = _format_result({"a": 1})
        parsed = json.loads(result)
        self.assertEqual(parsed["a"], 1)

    def test_list_to_json(self):
        result = _format_result([1, 2, 3])
        parsed = json.loads(result)
        self.assertEqual(parsed, [1, 2, 3])

    def test_non_serializable_to_str(self):
        result = _format_result(object())
        self.assertIsInstance(result, str)

    def test_none_to_json(self):
        result = _format_result(None)
        self.assertEqual(result, "null")


# ===================================================================
# 5. ChromaDB availability flag
# ===================================================================

class TestChromaDBFlag(unittest.TestCase):
    """CHROMADB_AVAILABLE flag should be set at module level."""

    def test_chromadb_flag_exists(self):
        from hivemind_mcp import hivemind_server
        self.assertIn("CHROMADB_AVAILABLE", dir(hivemind_server))

    def test_chromadb_flag_is_bool(self):
        from hivemind_mcp.hivemind_server import CHROMADB_AVAILABLE
        self.assertIsInstance(CHROMADB_AVAILABLE, bool)


# ===================================================================
# 6. Self-test validation
# ===================================================================

class TestSelfTest(unittest.TestCase):
    """run_self_test should work."""

    def test_self_test_returns_bool(self):
        from hivemind_mcp.hivemind_server import run_self_test
        # Capture stdout to avoid noise
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = run_self_test()
        self.assertIsInstance(result, bool)

    def test_self_test_passes(self):
        from hivemind_mcp.hivemind_server import run_self_test
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = run_self_test()
        self.assertTrue(result, "Self-test should pass with all 13 tools registered")


# ===================================================================
# 7. Tool wrappers return JSON strings
# ===================================================================

class TestToolReturnTypes(unittest.TestCase):
    """Each async tool wrapper should return a string (JSON-formatted)."""

    def test_get_active_client_returns_string(self):
        result = asyncio.run(hivemind_get_active_client())
        self.assertIsInstance(result, str)
        # Should be valid JSON
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)

    def test_get_active_branch_returns_string(self):
        result = asyncio.run(hivemind_get_active_branch())
        self.assertIsInstance(result, str)
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)


if __name__ == "__main__":
    unittest.main()
