@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ==========================================
echo    Building SnapMatch with Vosk by WETQV
echo ==========================================
echo.
echo Current directory: %CD%
echo Python version:
python --version 2>nul || (
    echo ERROR: Python not found! Please install Python first.
    pause
    exit /b 1
)
echo.

echo Installing dependencies...
pip install -r requirements-local-stt.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies!
    pause
    exit /b 1
)
echo.

echo Checking PyInstaller...
pip show pyinstaller >nul 2>&1 || (
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo Creating version info file...
if exist "version_info.txt" del "version_info.txt"
(
    echo # UTF-8 > version_info.txt
    echo # >> version_info.txt
    echo # SnapMatch Version Information >> version_info.txt
    echo # Created by: WETQV >> version_info.txt
    echo # >> version_info.txt
    echo. >> version_info.txt
    echo VSVersionInfo^( >> version_info.txt
    echo   ffi=FixedFileInfo^( >> version_info.txt
    echo     filevers=^(1, 0, 4, 3^), >> version_info.txt
    echo     prodvers=^(1, 0, 4, 3^), >> version_info.txt
    echo     mask=0x3f, >> version_info.txt
    echo     flags=0x0, >> version_info.txt
    echo     OS=0x40004, >> version_info.txt
    echo     fileType=0x1, >> version_info.txt
    echo     subtype=0x0, >> version_info.txt
    echo     date=^(0, 0^) >> version_info.txt
    echo   ^), >> version_info.txt
    echo   kids=[ >> version_info.txt
    echo     StringFileInfo^( >> version_info.txt
    echo       [ >> version_info.txt
    echo         StringTable^( >> version_info.txt
    echo           u'040904B0', >> version_info.txt
    echo           [ >> version_info.txt
    echo             StringStruct^(u'CompanyName', u'WETQV Development'^), >> version_info.txt
    echo             StringStruct^(u'FileDescription', u'SnapMatch'^), >> version_info.txt
    echo             StringStruct^(u'FileVersion', u'1.0.4.3'^), >> version_info.txt
    echo             StringStruct^(u'InternalName', u'SnapMatch'^), >> version_info.txt
    echo             StringStruct^(u'LegalCopyright', u'2026 WETQV. All rights reserved.'^), >> version_info.txt
    echo             StringStruct^(u'OriginalFilename', u'SnapMatch.exe'^), >> version_info.txt
    echo             StringStruct^(u'ProductName', u'SnapMatch'^), >> version_info.txt
    echo             StringStruct^(u'ProductVersion', u'1.0.4.3'^), >> version_info.txt
    echo             StringStruct^(u'Comments', u'Desktop AI Assistant with Telegram Bot Integration'^), >> version_info.txt
    echo           ] >> version_info.txt
    echo         ^) >> version_info.txt
    echo       ] >> version_info.txt
    echo     ^), >> version_info.txt
    echo     VarFileInfo^([VarStruct^(u'Translation', [1033, 1200]^)]^) >> version_info.txt
    echo   ] >> version_info.txt
    echo ^) >> version_info.txt
)
echo Version info file created!
echo.

echo Cleaning previous builds...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
echo Cleaned build directories
echo.

echo Checking icon file...
set ICON_PATH=assets\icon3.ico
if not exist "%ICON_PATH%" (
    echo WARNING: Icon file not found at %ICON_PATH%
    echo The build will continue without a custom icon.
)
echo.

echo Running PyInstaller using snapmatch.spec...
set "SNAPMATCH_BUNDLE_VOSK=1"
pyinstaller --noconfirm --clean snapmatch.spec
if exist "dist\SnapMatch.exe" move /y "dist\SnapMatch.exe" "dist\SnapMatch_Vosk.exe" >nul

echo.
if exist "dist\SnapMatch_Vosk.exe" (
    echo ==========================================
    echo SUCCESS! SnapMatch.exe built successfully!
    echo ==========================================
    echo.
    echo File location: %CD%\dist\SnapMatch_Vosk.exe
    for %%I in (dist\SnapMatch_Vosk.exe) do (
        set /a size_mb=%%~zI/1024/1024
        echo File size: %%~zI bytes (~!size_mb! MB^)
    )
    echo Building Vosk installer...
    call build_installer.bat SnapMatch_Installer_Vosk.iss SnapMatch_Setup_Vosk_v1.0.4.3.exe nopause
    if errorlevel 1 exit /b 1
    echo.
    echo Created by: WETQV
    echo Build time: %date% %time%
    echo.
    echo Launch the application? (y/n^)
    set /p choice=
    if /i "!choice!"=="y" (
        echo Starting SnapMatch...
        start "" "dist\SnapMatch_Vosk.exe"
    )
) else (
    echo ==========================================
    echo BUILD FAILED! SnapMatch_Vosk.exe was not created.
    echo ==========================================
    echo Check the logs above for error details.
    echo.
    echo Common issues:
    echo - Missing dependencies (install with: pip install -r requirements.txt)
    echo - Icon file not found (check assets\icon3.ico)
    echo - PyInstaller errors (check Python version compatibility)
)

echo.
echo Build process completed by WETQV.
pause
