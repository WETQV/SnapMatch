@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ==========================================
echo    Building SnapMatch to EXE by WETQV
echo ==========================================
echo.
echo Current directory: %CD%
echo Python version:
python --version 2>nul || (
    echo ERROR: Python not found. Install Python 3.12+ and run this file again.
    pause
    exit /b 1
)
echo.

echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)
echo.

echo Checking PyInstaller...
pip show pyinstaller >nul 2>&1 || pip install pyinstaller
echo.

echo Creating version info file...
if exist "version_info.txt" del "version_info.txt"
(
    echo VSVersionInfo^(> version_info.txt
    echo   ffi=FixedFileInfo^(>> version_info.txt
    echo     filevers=^(1, 0, 4, 0^),>> version_info.txt
    echo     prodvers=^(1, 0, 4, 0^),>> version_info.txt
    echo     mask=0x3f,>> version_info.txt
    echo     flags=0x0,>> version_info.txt
    echo     OS=0x40004,>> version_info.txt
    echo     fileType=0x1,>> version_info.txt
    echo     subtype=0x0,>> version_info.txt
    echo     date=^(0, 0^)>> version_info.txt
    echo   ^),>> version_info.txt
    echo   kids=[>> version_info.txt
    echo     StringFileInfo^(>> version_info.txt
    echo       [>> version_info.txt
    echo         StringTable^(>> version_info.txt
    echo           u'040904B0',>> version_info.txt
    echo           [>> version_info.txt
    echo             StringStruct^(u'CompanyName', u'WETQV Development'^),>> version_info.txt
    echo             StringStruct^(u'FileDescription', u'SnapMatch'^),>> version_info.txt
    echo             StringStruct^(u'FileVersion', u'1.0.4.0'^),>> version_info.txt
    echo             StringStruct^(u'InternalName', u'SnapMatch'^),>> version_info.txt
    echo             StringStruct^(u'LegalCopyright', u'2026 WETQV'^),>> version_info.txt
    echo             StringStruct^(u'OriginalFilename', u'SnapMatch.exe'^),>> version_info.txt
    echo             StringStruct^(u'ProductName', u'SnapMatch'^),>> version_info.txt
    echo             StringStruct^(u'ProductVersion', u'1.0.4.0'^),>> version_info.txt
    echo           ]>> version_info.txt
    echo         ^)>> version_info.txt
    echo       ]>> version_info.txt
    echo     ^),>> version_info.txt
    echo     VarFileInfo^([VarStruct^(u'Translation', [1033, 1200]^)]^)>> version_info.txt
    echo   ]>> version_info.txt
    echo ^)>> version_info.txt
)
echo.

echo Cleaning previous builds...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
echo.

echo Running PyInstaller...
pyinstaller --noconfirm --clean snapmatch.spec
if errorlevel 1 (
    echo BUILD FAILED. Check the log above.
    pause
    exit /b 1
)
echo.

if exist "dist\SnapMatch.exe" (
    echo ==========================================
    echo SUCCESS. SnapMatch.exe built successfully.
    echo ==========================================
    echo File location: %CD%\dist\SnapMatch.exe
    for %%I in (dist\SnapMatch.exe) do (
        set /a size_mb=%%~zI/1024/1024
        echo File size: %%~zI bytes (~!size_mb! MB^)
    )
) else (
    echo BUILD FAILED. dist\SnapMatch.exe was not created.
    pause
    exit /b 1
)
echo.
echo Build process completed.
pause
