import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_SESSION_STATS_FILE = PROJECT_ROOT.parent / "session_stats.txt"
SESSION_STATS_FILENAME = "session_stats.txt"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _get_executable_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _get_user_data_dir() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "SnapMatch"

    return Path.home() / ".snapmatch"


def _is_directory_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".session_stats_write_test"
        with probe.open("w", encoding="utf-8") as handle:
            handle.write("ok")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def get_session_stats_file() -> Path:
    """Возвращает актуальный путь к session_stats.txt для текущего режима запуска."""
    if _is_frozen():
        exe_dir = _get_executable_dir()
        if _is_directory_writable(exe_dir):
            return exe_dir / SESSION_STATS_FILENAME
        return _get_user_data_dir() / SESSION_STATS_FILENAME

    return PROJECT_ROOT / SESSION_STATS_FILENAME


SESSION_STATS_FILE = get_session_stats_file()


def _iter_legacy_candidates(canonical: Path) -> list[Path]:
    candidates = [LEGACY_SESSION_STATS_FILE]

    project_local = PROJECT_ROOT / SESSION_STATS_FILENAME
    if project_local != canonical:
        candidates.append(project_local)

    exe_local = _get_executable_dir() / SESSION_STATS_FILENAME if _is_frozen() else None
    if exe_local and exe_local != canonical:
        candidates.append(exe_local)

    unique_candidates = []
    seen = set()
    for path in candidates:
        resolved = str(path.resolve(strict=False))
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_candidates.append(path)
    return unique_candidates


def _merge_session_stats(source: Path, target: Path) -> None:
    if not source.exists() or source.resolve() == target.resolve():
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    existing_blocks = set()

    if target.exists():
        existing_blocks = {
            block.strip()
            for block in target.read_text(encoding="utf-8").split("\n\n")
            if block.strip()
        }

    source_blocks = [
        block.strip()
        for block in source.read_text(encoding="utf-8").split("\n\n")
        if block.strip()
    ]

    missing_blocks = [block for block in source_blocks if block not in existing_blocks]
    if not missing_blocks:
        return

    prefix = "\n\n" if target.exists() and target.read_text(encoding="utf-8").strip() else ""
    with target.open("a", encoding="utf-8") as handle:
        handle.write(prefix + "\n\n".join(missing_blocks) + "\n")


def migrate_legacy_session_stats() -> Path:
    """Возвращает канонический путь и переносит записи из старых мест хранения."""
    canonical = get_session_stats_file()
    for legacy in _iter_legacy_candidates(canonical):
        _merge_session_stats(legacy, canonical)
    return canonical
