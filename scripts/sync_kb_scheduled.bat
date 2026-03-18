@echo off
REM HiveMind KB Sync — Scheduled Task (runs at 7am daily via Task Scheduler)
REM Syncs ALL clients with --auto-yes (no prompts)

cd /d "%~dp0.."
.venv\Scripts\python scripts\sync_kb.py --auto-yes
.venv\Scripts\python scripts\hti_index_all.py >> memory\sync_log.txt 2>&1
