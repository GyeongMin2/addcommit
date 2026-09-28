@echo off
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --console --name addcommit --distpath "%~dp0..\app" --workpath "%TEMP%\addcommit-pyi" --specpath "%TEMP%\addcommit-pyi" addcommit_app.py
if errorlevel 1 exit /b 1
copy /Y "%~dp0schedule_config.json" "%~dp0..\app\schedule_config.json" >nul
echo built "%~dp0..\app\addcommit.exe"
