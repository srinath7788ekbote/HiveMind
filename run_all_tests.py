"""
run_all_tests.py — HiveMind Test Runner

Discovers and runs all unit and integration tests.
Produces a formatted report with pass/fail counts.

Usage:
    python run_all_tests.py              # Run all tests
    python run_all_tests.py --verbose    # Verbose output
    python run_all_tests.py --unit       # Unit tests only
    python run_all_tests.py --integration # Integration tests only
"""

import os
import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
TESTS_DIR = PROJECT_ROOT / "tests"


def discover_tests(pattern="test_*.py", test_dir=None):
    """Discover test modules."""
    if test_dir is None:
        test_dir = str(TESTS_DIR)
    loader = unittest.TestLoader()
    suite = loader.discover(test_dir, pattern=pattern, top_level_dir=str(PROJECT_ROOT))
    return suite


def filter_suite(suite, prefix):
    """Filter a test suite to only include tests matching prefix."""
    filtered = unittest.TestSuite()
    for group in suite:
        if hasattr(group, "__iter__"):
            for test_group in group:
                if hasattr(test_group, "__iter__"):
                    for test in test_group:
                        test_id = test.id()
                        if prefix in test_id:
                            filtered.addTest(test)
                else:
                    test_id = test_group.id()
                    if prefix in test_id:
                        filtered.addTest(test_group)
        else:
            test_id = group.id()
            if prefix in test_id:
                filtered.addTest(group)
    return filtered


UNIT_TESTS = [
    "test_discovery",
    "test_classify",
    "test_relationships",
    "test_query_memory",
    "test_query_graph",
    "test_impact_analysis",
    "test_secret_flow",
    "test_agent_files",
    "test_search_files",
    "test_get_entity",
    "test_get_pipeline",
    "test_set_client",
    "test_diff_branches",
    "test_list_branches",
    "test_mcp_server",
]

INTEGRATION_TESTS = [
    "test_full_ingest",
    "test_branch_awareness",
    "test_mcp_integration",
]


def get_suite(mode="all"):
    """Get appropriate test suite based on mode."""
    all_suite = discover_tests()

    if mode == "unit":
        combined = unittest.TestSuite()
        for name in UNIT_TESTS:
            combined.addTests(filter_suite(all_suite, name))
        return combined
    elif mode == "integration":
        combined = unittest.TestSuite()
        for name in INTEGRATION_TESTS:
            combined.addTests(filter_suite(all_suite, name))
        return combined
    else:
        return all_suite


def count_tests(suite):
    """Count total tests in a suite (recursive)."""
    count = 0
    for item in suite:
        if hasattr(item, "__iter__"):
            count += count_tests(item)
        else:
            count += 1
    return count


def print_header():
    """Print test run header."""
    print("=" * 70)
    print("  HiveMind — Test Runner")
    print("=" * 70)
    print()


def print_summary(result, elapsed):
    """Print formatted test summary."""
    print()
    print("=" * 70)
    print("  TEST SUMMARY")
    print("=" * 70)
    print()

    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failures - errors - skipped

    print(f"  Total:    {total}")
    print(f"  Passed:   {passed}")
    print(f"  Failed:   {failures}")
    print(f"  Errors:   {errors}")
    print(f"  Skipped:  {skipped}")
    print(f"  Time:     {elapsed:.2f}s")
    print()

    if result.failures:
        print("-" * 70)
        print("  FAILURES:")
        print("-" * 70)
        for test, traceback in result.failures:
            print(f"\n  FAIL: {test}")
            for line in traceback.strip().split("\n"):
                print(f"    {line}")
        print()

    if result.errors:
        print("-" * 70)
        print("  ERRORS:")
        print("-" * 70)
        for test, traceback in result.errors:
            print(f"\n  ERROR: {test}")
            for line in traceback.strip().split("\n"):
                print(f"    {line}")
        print()

    if failures == 0 and errors == 0:
        print("  PASS: ALL TESTS PASSED")
    else:
        print("  FAIL: SOME TESTS FAILED")

    print("=" * 70)
    return failures == 0 and errors == 0


def main():
    """Main entry point."""
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    verbosity = 2 if verbose else 1

    mode = "all"
    if "--unit" in sys.argv:
        mode = "unit"
    elif "--integration" in sys.argv:
        mode = "integration"

    print_header()
    print(f"  Mode: {mode}")
    print(f"  Test dir: {TESTS_DIR}")
    print()

    suite = get_suite(mode)
    total = count_tests(suite)
    print(f"  Discovered {total} tests")
    print()

    runner = unittest.TextTestRunner(verbosity=verbosity, stream=sys.stdout)

    start = time.time()
    result = runner.run(suite)
    elapsed = time.time() - start

    success = print_summary(result, elapsed)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
