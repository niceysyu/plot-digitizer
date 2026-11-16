@echo off
REM Plot Digitizer - Windows local build (Python 3.8+ required)
cd /d "%~dp0"
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller || goto :err
pyinstaller --noconfirm --onefile --windowed --name PlotDigitizer --icon icon.ico plot_digitizer.py || goto :err
echo.
echo Done: %~dp0dist\PlotDigitizer.exe
pause
exit /b 0
:err
echo Build failed.
pause
exit /b 1
