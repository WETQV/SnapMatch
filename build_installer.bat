@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ==========================================
echo    Building SnapMatch installer
echo ==========================================
echo.

if not exist "dist\SnapMatch.exe" (
    echo dist\SnapMatch.exe was not found.
    echo Run build.bat first.
    pause
    exit /b 1
)

set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"

if "%ISCC%"=="" (
    echo Inno Setup compiler was not found.
    echo Install Inno Setup 6 or 7, then run this file again.
    pause
    exit /b 1
)

if exist "installer_output" rmdir /s /q "installer_output"
mkdir "installer_output"

"%ISCC%" "SnapMatch_Installer.iss"
if errorlevel 1 (
    echo Installer build failed.
    pause
    exit /b 1
)

echo.
echo Installer created in installer_output.
pause
