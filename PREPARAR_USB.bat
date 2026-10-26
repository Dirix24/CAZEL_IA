@echo off
cd /d "%~dp0"
py -3 -m pip install --upgrade --target libs numpy pyserial || python -m pip install --upgrade --target libs numpy pyserial
echo Listo: libs preparada.
pause
