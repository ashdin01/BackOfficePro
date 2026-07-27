@echo off
REM Runs the ATRIA daily report download + import script.
REM Edit the path below if python.exe isn't on your PATH, e.g.:
REM   "C:\Users\Ashley\AppData\Local\Programs\Python\Python312\python.exe"
REM
REM BACKOFFICEPRO_DATA_DIR points this standalone script at the same live
REM database the installed (frozen) app uses, instead of the repo-local
REM 'data' folder that unfrozen/dev runs use by default. Only set this when
REM running on the same machine as the real installed app via Task Scheduler.
set BACKOFFICEPRO_DATA_DIR=%LOCALAPPDATA%\BackOfficePro\data
python "%~dp0fetch_atria_sales.py"
