@echo off
setlocal

set SITE_PKG=C:\Users\Ionut.Emilian\AppData\Local\Programs\Python\Python313\Lib\site-packages

echo ============================================
echo  SamsungPy - Building standalone EXE
echo ============================================

py -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --noupx ^
    --runtime-tmpdir "%LOCALAPPDATA%\SamsungPyRuntime" ^
    --name "SamsungMDCDashboard" ^
    --add-data "%SITE_PKG%\customtkinter;customtkinter" ^
    --add-data "%SITE_PKG%\darkdetect;darkdetect" ^
    --hidden-import customtkinter ^
    --hidden-import darkdetect ^
    --hidden-import samsung_mdc ^
    --hidden-import samsungtvws ^
    --hidden-import websocket ^
    --hidden-import requests ^
    --hidden-import PIL ^
    --hidden-import PIL._tkinter_finder ^
    launch_dashboard.py

if errorlevel 1 (
    echo.
    echo BUILD FAILED.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  BUILD SUCCESSFUL!
echo  EXE is at:  dist\SamsungMDCDashboard.exe
echo  Copy that single file to any Windows PC.
echo ============================================

echo.
echo Creating desktop shortcut...
set EXE_PATH=%~dp0dist\SamsungMDCDashboard.exe
set SHORTCUT=%USERPROFILE%\Desktop\SamsungMDC Dashboard.lnk
set PS1_TMP=%TEMP%\create_shortcut.ps1

(
  echo $ws = New-Object -ComObject WScript.Shell
  echo $s = $ws.CreateShortcut('%SHORTCUT%')
  echo $s.TargetPath = '%EXE_PATH%'
  echo $s.WorkingDirectory = '%~dp0dist'
  echo $s.Description = 'Samsung MDC Dashboard'
  echo $s.Save()
) > "%PS1_TMP%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1_TMP%"
del /q "%PS1_TMP%" 2>nul

if exist "%SHORTCUT%" (
    echo Desktop shortcut created: %SHORTCUT%
) else (
    echo WARNING: Could not create desktop shortcut.
)

pause
