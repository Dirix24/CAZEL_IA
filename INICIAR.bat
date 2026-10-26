@echo off
chcp 65001 >nul
cd /d "%~dp0"
title CAZEL IA
if exist "python_portatil\python.exe" goto portatil
where py >nul 2>nul
if %errorlevel%==0 goto conpy
where python >nul 2>nul
if %errorlevel%==0 goto conpython
echo No encontre Python 3. Instalalo desde python.org (marca "Add Python to PATH") y vuelve a abrir.
pause
exit /b 1
:portatil
"python_portatil\python.exe" iniciar.py %*
goto fin
:conpy
py -3 iniciar.py %*
goto fin
:conpython
python iniciar.py %*
:fin
pause
