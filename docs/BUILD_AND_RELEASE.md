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

Скрипт устанавливает зависимости из `requirements.txt`, создаёт `version_info.txt`, очищает старые `build/` и `dist/`, запускает PyInstaller и кладёт результат в:

```txt
dist\SnapMatch.exe
```

Сборка использует готовый `snapmatch.spec`:

```bat
pyinstaller --noconfirm --clean snapmatch.spec
```

UPX для `SnapMatch.exe` отключён через `upx=False` в `snapmatch.spec`. Это делает сборку проще для повторения и уменьшает шанс ложных срабатываний антивирусов. Inno Setup при этом может сжимать сам installer-файл, но это не перепаковывает исполняемый файл приложения через UPX.

FFmpeg для Windows installer не хранится в репозитории. Официальная сборка берёт его из соседней папки:

```txt
..\ffmpeg-2026-01-26-git-fe0813d6e2-essentials_build\bin\ffmpeg.exe
```

Если FFmpeg найден, Inno Setup положит его в:

```txt
{app}\assets\ffmpeg\ffmpeg.exe
```

Это нужно для локального Vosk и обработки голосовых сообщений. Если FFmpeg не найден при сборке, installer всё равно соберётся, но голосовая конвертация будет работать только при наличии `ffmpeg` в `PATH`.

## Linux

Требования:

- Debian/Ubuntu x64;
- Python 3.12+;
- `python3-pip`;
- `dpkg-deb`;
- `ffmpeg`;
- системные библиотеки для PyQt6: `libegl1`, `libxcb-cursor0`, `libxkbcommon-x11-0`.

Команда:

```sh
bash build_linux.sh
```

Результат:

```txt
dist/SnapMatch
dist/SnapMatch_1.0.4_amd64.deb
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
sudo apt install ./dist/SnapMatch_1.0.4_amd64.deb
```

Для кастомной версии можно передать переменную:

```sh
SNAPMATCH_VERSION=1.0.4.0 bash build_linux.sh
```

Linux-пакет собирается в GitHub Actions на `ubuntu-24.04`. Локально из Windows его не собрать без WSL/Docker, потому что PyInstaller не делает нормальную cross-platform сборку Windows -> Linux.

## Установщик Windows

Для сборки установщика нужен уже собранный `dist\SnapMatch.exe` и установленный Inno Setup 6 или 7.

Команда:

```bat
build_installer.bat
```

Результат:

```txt
installer_output\SnapMatch_Setup_v1.0.4.0.exe
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
4. Выполните `build_installer.bat`.
5. Проверьте установку на чистой Windows-машине или виртуальной машине.

Типичные ошибки:

- `dist\SnapMatch.exe was not found` - сначала выполните `build.bat`;
- `ISCC.exe was not found` - Inno Setup не установлен или установлен в нестандартную папку;
- FFmpeg не попал в installer - положите `ffmpeg.exe` в `assets\ffmpeg\ffmpeg.exe` или соседнюю папку `..\ffmpeg-2026-01-26-git-fe0813d6e2-essentials_build\bin\`;
- ошибка иконки - проверьте `assets\icon3.ico`;
- предупреждения антивируса для unsigned exe - для публичного распространения лучше использовать code signing certificate.

## GitHub Actions

Workflow `.github/workflows/release-build.yml` собирает Debian/Ubuntu `.deb`.

Ручной запуск:

1. Откройте вкладку Actions в GitHub.
2. Выберите `Build release packages`.
3. Укажите tag, например `v1.0.4`.
4. Оставьте `upload_release=true`, если asset нужно приложить к GitHub Release.

Workflow загружает `.deb` как artifact и, при включённом `upload_release`, прикладывает его к указанному релизу.
