@echo off
rem Запуск команд в Windows: strateg check, strateg cost ...
set PYTHONUTF8=1
where py >nul 2>nul && (py -3 "%~dp0tools\strateg.py" %* & exit /b)
python "%~dp0tools\strateg.py" %*
