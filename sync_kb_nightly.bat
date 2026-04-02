@echo off
cd /d C:\Users\sekbote\Documents\HiveMind
echo [%date% %time%] Starting HiveMind nightly sync >> memory\sync_log.txt 2>&1
.venv\Scripts\python.exe scripts\sync_kb.py --client dfin --fetch --workers 4 >> memory\sync_log.txt 2>&1
.venv\Scripts\python.exe scripts\hti_index_all.py --workers 4 >> memory\sync_log.txt 2>&1
echo [%date% %time%] Sync complete >> memory\sync_log.txt 2>&1
