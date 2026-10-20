"""Каталоги данных SnapMatch для Windows и Linux.

Приложение хранит config.json, database.db, app.log, загрузки и модели в текущей
папке (относительные пути). Это удобно при запуске из исходников, но ломается при
установке в /opt или Program Files (нет прав записи, рабочая папка ярлыка — $HOME).

enter_data_dir() выбирает рабочую папку один раз при старте — до импорта config.settings:
  1. SNAPMATCH_DATA_DIR — явное указание;
  2. config.json уже лежит в текущей папке — «портативный» режим, ничего не меняем;
  3. запуск из исходников и config.json лежит в корне проекта — работаем из корня;
  4. иначе — пользовательский каталог данных:
     Windows: %LOCALAPPDATA%/SnapMatch, Linux: $XDG_DATA_HOME/snapmatch (~/.local/share/snapmatch).
"""

import os
import sys
import tempfile
from pathlib import Path

APP_DIR_NAME_WIN = "SnapMatch"
APP_DIR_NAME_POSIX = "snapmatch"
SETTINGS_FILENAME = "config.json"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_user_data_dir() -> Path:
    """Стандартный пользовательский каталог данных (совпадает с каталогом ключа шифрования)."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / APP_DIR_NAME_WIN
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME_POSIX


def get_runtime_dir() -> Path:
    """Каталог для lock-файлов и прочего временного: XDG_RUNTIME_DIR на Linux, LOCALAPPDATA на Windows."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
        return Path(base) / APP_DIR_NAME_WIN
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime and os.access(runtime, os.W_OK):
        return Path(runtime) / APP_DIR_NAME_POSIX
    return Path.home() / ".cache" / APP_DIR_NAME_POSIX


def resolve_data_dir() -> Path:
    configured = os.environ.get("SNAPMATCH_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    if Path.cwd().joinpath(SETTINGS_FILENAME).exists():
        return Path.cwd()
    if not getattr(sys, "frozen", False) and _project_root().joinpath(SETTINGS_FILENAME).exists():
        return _project_root()
    return get_user_data_dir()


def enter_data_dir() -> Path:
    """Делает каталог данных рабочей папкой процесса. Вызывать самым первым в main.py."""
    target = resolve_data_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
        os.chdir(target)
    except OSError as exc:
        print(f"Не удалось перейти в каталог данных {target}: {exc}", file=sys.stderr)
        return Path.cwd()
    return target
