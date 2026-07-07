@echo off
REM Runs the ATRIA daily report download + import script.
REM Edit the path below if python.exe isn't on your PATH, e.g.:
REM   "C:\Users\Ashley\AppData\Local\Programs\Python\Python312\python.exe"
python "%~dp0fetch_atria_sales.py"
