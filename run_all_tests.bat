@echo off
REM ============================================================
REM  HiveMind — Run All Tests
REM ============================================================
REM  Usage:
REM    run_all_tests.bat              Run all tests
REM    run_all_tests.bat --verbose    Verbose output
REM    run_all_tests.bat --unit       Unit tests only
REM    run_all_tests.bat --integration Integration tests only
REM ============================================================

cd /d "%~dp0"
python run_all_tests.py %*
