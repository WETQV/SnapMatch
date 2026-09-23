# Сборка и релиз

## Windows

Требования:

- Windows 10/11 x64;
- Python 3.12+;
- установленный `pip`;
- доступ к интернету для установки зависимостей.

Сборка приложения:

```bat
build.bat
```

Скрипт устанавливает зависимости из `requirements.txt`, создаёт `version_info.txt`, очищает старые `build/` и `dist/`, запускает PyInstaller и собирает обычный установщик. Исполняемый файл кладётся в:

```txt
dist\SnapMatch.exe
```

Сборка использует готовый `snapmatch.spec`:

```bat
pyinstaller --noconfirm --clean snapmatch.spec
```

UPX для `SnapMatch.exe` отключён через `upx=False` в `snapmatch.spec`. Это делает сборку проще для повторения и уменьшает шанс ложных срабатываний антивирусов. Inno Setup при этом может сжимать сам installer-файл, но это не перепаковывает исполняемый файл приложения через UPX.

Обычный Windows installer не включает локальное распознавание Vosk и FFmpeg. Для облачного распознавания голосовых сообщений они не нужны.

Вариант с локальным Vosk собирается отдельно командой `build_vosk.bat`. Для него нужны `requirements-local-stt.txt`, модель Vosk и FFmpeg. Сборка ищет FFmpeg в соседней папке:

```txt
..\ffmpeg-2026-01-26-git-fe0813d6e2-essentials_build\bin\ffmpeg.exe
```

Если FFmpeg найден, PyInstaller положит его в:

```txt
{app}\assets\ffmpeg\ffmpeg.exe
```

Локальную Vosk-сборку следует публиковать только после проверки, что модель и FFmpeg действительно вошли в установщик.

## Linux

Требования:

- Debian/Ubuntu x64;
- Python 3.12+;
- `python3-pip`;
- `dpkg-deb`;
- `ffmpeg` только для локального Vosk;
- системные библиотеки для PyQt6: `libegl1`, `libxcb-cursor0`, `libxkbcommon-x11-0`.

Команда:

```sh
bash build_linux.sh
```

Результат:

```txt
dist/SnapMatch
dist/SnapMatch_1.0.4.3_amd64.deb
```

Пакет устанавливает приложение в:

```txt
/opt/snapmatch/SnapMatch
```

и добавляет команду:

```txt
snapmatch
```

Установка `.deb`:

```sh
sudo apt install ./dist/SnapMatch_1.0.4.3_amd64.deb
```

Для кастомной версии можно передать переменную:

```sh
SNAPMATCH_VERSION=1.0.4.3 bash build_linux.sh
```

Linux-пакет собирается в GitHub Actions на `ubuntu-24.04`. Ручная установка и запуск GUI на отдельной Debian/Ubuntu-машине пока не проверялись. Локально из Windows такой пакет не собрать без WSL/Docker, потому что PyInstaller не делает нормальную cross-platform сборку Windows -> Linux.

## Установщик Windows

Для сборки установщика нужен уже собранный `dist\SnapMatch.exe` и установленный Inno Setup 6 или 7.

Команда:

```bat
build_installer.bat
```

Результат:

```txt
installer_output\SnapMatch_Setup_v1.0.4.3.exe
```

## Inno Setup

`SnapMatch_Installer.iss` описывает, как готовый `SnapMatch.exe` упаковывается в обычный Windows-установщик.

Основные поля:

- `MyAppName` - имя приложения;
- `MyAppVersion` - версия релиза;
- `MyAppPublisher` - автор или организация;
- `OutputBaseFilename` - имя установщика;
- `SetupIconFile` - иконка установщика;
- `DefaultDirName` - папка установки;
- `Compression` и `SolidCompression` - сжатие installer-файла;
- `[Files]` - файлы, которые попадут в установщик;
- `[Icons]` - ярлыки в меню Пуск и на рабочем столе;
- `[Run]` - запуск приложения после установки.

Чтобы выпустить свою сборку:

1. Обновите `MyAppVersion` в `SnapMatch_Installer.iss`.
2. При необходимости измените `MyAppPublisher`.
3. Выполните `build.bat`.
4. `build.bat` сам вызовет `build_installer.bat` после сборки EXE.
5. Проверьте установку на чистой Windows-машине или виртуальной машине.

Типичные ошибки:

- `dist\SnapMatch.exe was not found` - сначала выполните `build.bat`;
- `ISCC.exe was not found` - Inno Setup не установлен или установлен в нестандартную папку;
- для локального Vosk нет модели или FFmpeg - добавьте их перед сборкой `build_vosk.bat`;
- ошибка иконки - проверьте `assets\icon3.ico`;
- предупреждения антивируса для unsigned exe - для публичного распространения лучше использовать code signing certificate.

## GitHub Actions

Workflow `.github/workflows/release-build.yml` собирает Debian/Ubuntu `.deb`.

Ручной запуск:

1. Откройте вкладку Actions в GitHub.
2. Выберите `Build release packages`.
3. Укажите tag, например `v1.0.4.3`.
4. Оставьте `upload_release=true`, если asset нужно приложить к GitHub Release.

Workflow загружает `.deb` как artifact и, при включённом `upload_release`, прикладывает его к указанному релизу.
