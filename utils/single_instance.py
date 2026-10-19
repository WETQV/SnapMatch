import os
import tempfile
from pathlib import Path
from typing import IO, Optional


def _lock_path(app_name: str) -> Path:
    from utils.app_paths import get_runtime_dir

    lock_dir = get_runtime_dir()
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        lock_dir = Path(tempfile.gettempdir()) / f"{app_name}-{os.getuid() if hasattr(os, 'getuid') else 'user'}"
        lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / f"{app_name}.lock"


def acquire_single_instance_lock(app_name: str = "SnapMatch") -> Optional[IO[str]]:
    path = _lock_path(app_name)
    try:
        handle = path.open("a+", encoding="utf-8")
    except OSError:
        # Файл заблокирован правами (создан другим пользователем) — не роняем запуск
        return None

    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None

    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def release_single_instance_lock(handle: Optional[IO[str]]) -> None:
    if handle is None:
        return

    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        handle.close()
