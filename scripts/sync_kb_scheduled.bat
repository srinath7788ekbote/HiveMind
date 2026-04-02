@echo off
REM HiveMind KB Sync — Scheduled Task (runs at 7am daily via Task Scheduler)
REM Syncs ALL clients with --auto-yes (no prompts) using parallel workers

cd /d "%~dp0.."
.venv\Scripts\python scripts\sync_kb.py --auto-yes --workers 4
.venv\Scripts\python scripts\hti_index_all.py --workers 4 >> memory\sync_log.txt 2>&1
