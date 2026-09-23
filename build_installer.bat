@echo off
:: SnapMatch AI Assistant - Сборка установщика
:: WETQV Development 2026

echo.
echo ========================================
echo    SnapMatch AI Assistant Installer
echo         WETQV Development
echo ========================================
echo.

:: Переходим в директорию скрипта
cd /d "%~dp0"

set "ISS_FILE=%~1"
if "%ISS_FILE%"=="" set "ISS_FILE=SnapMatch_Installer.iss"
set "OUTPUT_FILE=%~2"
if "%OUTPUT_FILE%"=="" set "OUTPUT_FILE=SnapMatch_Setup_v1.0.4.3.exe"

:: Устанавливаем кодировку UTF-8
chcp 65001 > nul

:: Проверяем наличие Inno Setup
echo [1/5] Проверка Inno Setup Compiler...
set "INNO_PATH="
if exist "C:\Program Files\Inno Setup 7\ISCC.exe" (
    set "INNO_PATH=C:\Program Files\Inno Setup 7\ISCC.exe"
) else if exist "C:\Program Files (x86)\Inno Setup 7\ISCC.exe" (
    set "INNO_PATH=C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
) else if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "INNO_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set "INNO_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"
) else if exist "C:\Program Files (x86)\Inno Setup 5\ISCC.exe" (
    set "INNO_PATH=C:\Program Files (x86)\Inno Setup 5\ISCC.exe"
) else if exist "C:\Program Files\Inno Setup 5\ISCC.exe" (
    set "INNO_PATH=C:\Program Files\Inno Setup 5\ISCC.exe"
)

if "%INNO_PATH%"=="" (
    echo ❌ ОШИБКА: Inno Setup Compiler не найден!
    echo.
    echo Пожалуйста, установите Inno Setup:
    echo https://jrsoftware.org/isdl.php
    echo.
    pause
    exit /b 1
)

echo ✅ Найден: %INNO_PATH%

:: Проверяем наличие исполняемого файла
echo [2/5] Проверка исполняемого файла...
if /I "%ISS_FILE%"=="SnapMatch_Installer_Vosk.iss" (set "APP_EXE=dist\SnapMatch_Vosk.exe") else (set "APP_EXE=dist\SnapMatch.exe")
if not exist "%APP_EXE%" (
    echo ❌ ОШИБКА: Файл %APP_EXE% не найден!
    echo.
    echo Сначала соберите приложение командой:
    echo python -m PyInstaller snapmatch.spec
    echo.
    pause
    exit /b 1
)

echo ✅ Найден: %APP_EXE%

:: Проверяем наличие ресурсов
echo [3/5] Проверка ресурсов...
if not exist "assets\icon3.ico" (
    echo ❌ ОШИБКА: Файл assets\icon3.ico не найден!
    pause
    exit /b 1
)

if not exist "LICENSE" (
    echo ❌ ОШИБКА: Файл LICENSE не найден!
    pause
    exit /b 1
)

if not exist "README.md" (
    echo ❌ ОШИБКА: Файл README.md не найден!
    pause
    exit /b 1
)

echo ✅ Все ресурсы найдены

:: Создаем папку для вывода
echo [4/5] Подготовка папки вывода...
if not exist "installer_output" (
    mkdir "installer_output"
    echo ✅ Создана папка installer_output
) else (
    echo ✅ Папка installer_output уже существует
)

:: Компиляция установщика
echo [5/5] Компиляция установщика...
echo.
echo Запуск Inno Setup Compiler...
echo Командная строка: "%INNO_PATH%" "%ISS_FILE%"
echo.

"%INNO_PATH%" "%ISS_FILE%"
set "ISCC_RESULT=%ERRORLEVEL%"

if %ISCC_RESULT% EQU 0 (
    echo.
    echo ========================================
    echo     🎉 УСТАНОВЩИК СОБРАН УСПЕШНО! 🎉
    echo ========================================
    echo.
    echo Файл установщика сохранен в:
    echo installer_output\%OUTPUT_FILE%
    echo.
    echo Размер исполняемого файла:
    for %%F in ("installer_output\%OUTPUT_FILE%") do echo %%~zF байт
    echo.
    echo Теперь вы можете распространять этот установщик!
    echo.

    echo.
    :: Открываем папку с результатом
    if /I not "%~3"=="nopause" explorer "installer_output"

) else (
    echo.
    echo ========================================
    echo      ❌ ОШИБКА ПРИ СБОРКЕ! ❌
    echo ========================================
    echo.
    echo Код ошибки: %ISCC_RESULT%
    echo.
    echo Проверьте:
    echo - Правильность скрипта %ISS_FILE%
    echo - Наличие всех файлов
    echo - Лог компиляции выше
    echo.
)

echo.
if /I not "%~3"=="nopause" (
    echo Нажмите любую клавишу для выхода...
    pause >nul
)
exit /b %ISCC_RESULT%
