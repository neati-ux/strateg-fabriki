@echo off
setlocal
rem Run the first Python 3.9+ interpreter that actually starts.
set PYTHONUTF8=1
if defined STRATEG_PYTHON (
    "%STRATEG_PYTHON%" "%~dp0tools\strateg.py" %*
    exit /b
)
py -3 -c "import sys;sys.exit(sys.version_info < (3,9))" >nul 2>nul
if not errorlevel 1 goto py
python -c "import sys;sys.exit(sys.version_info < (3,9))" >nul 2>nul
if not errorlevel 1 goto python
for /d %%P in ("%LOCALAPPDATA%\Python\pythoncore-*" "%LOCALAPPDATA%\Programs\Python\Python*" "%USERPROFILE%\AppData\Local\Python\pythoncore-*" "%USERPROFILE%\AppData\Local\Programs\Python\Python*") do (
    "%%P\python.exe" -c "import sys;sys.exit(sys.version_info < (3,9))" >nul 2>nul
    if not errorlevel 1 (
        set "STRATEG_PYTHON=%%P\python.exe"
        goto direct
    )
)
echo Python 3.9+ not found. Set STRATEG_PYTHON to the path of python.exe. 1>&2
exit /b 127
:py
py -3 "%~dp0tools\strateg.py" %*
exit /b
:python
python "%~dp0tools\strateg.py" %*
exit /b
:direct
"%STRATEG_PYTHON%" "%~dp0tools\strateg.py" %*
exit /b
