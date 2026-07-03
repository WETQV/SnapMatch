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

## Linux

Требования:

- Linux x64;
- Python 3.12+;
- `python3-pip`;
- системные библиотеки для PyQt6;
- зависимости, которые могут потребоваться `vosk`, `mcp` и PyInstaller.

Команда:

```sh
bash build_linux.sh
```

Ожидаемый результат:

```txt
dist/SnapMatch
```

Статус: Linux-сборка пока не проверялась на отдельной Linux-машине. Возможны дополнительные правки по системным библиотекам, PyQt6 platform plugins, путям к FFmpeg и правам запуска.

## Установщик Windows

Для сборки установщика нужен уже собранный `dist\SnapMatch.exe` и установленный Inno Setup 6 или 7.

Команда:

```bat
build_installer.bat
```

Результат:

```txt
installer_output\SnapMatch-Setup-1.0.4.0.exe
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
- ошибка иконки - проверьте `assets\icon3.ico`;
- предупреждения антивируса для unsigned exe - для публичного распространения лучше использовать code signing certificate.