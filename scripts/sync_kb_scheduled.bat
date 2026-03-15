@echo off
REM HiveMind KB Sync — Scheduled Task (runs at 7am daily via Task Scheduler)
REM Syncs ALL clients with --auto-yes (no prompts)

cd /d "%~dp0.."
.venv\Scripts\python scripts\sync_kb.py --auto-yes
