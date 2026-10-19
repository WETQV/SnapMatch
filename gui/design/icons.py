"""Иконки дизайн-системы: тонкая обёртка над qtawesome (набор Material Design Icons, префикс 'mdi6.').

  * кэш по (имя, цвет) — иконки не перерисовываются на каждый кадр;
  * цвет берётся из токенов темы (роль: 'text_muted', 'accent', 'text', ...) или задаётся явно;
  * если qtawesome недоступен или имя неизвестно — возвращается пустой QIcon(), приложение не падает.
"""
import os
import tempfile
from functools import lru_cache

from PyQt6.QtGui import QIcon, QPixmap

from gui.design.tokens import tokens
from utils.logger import setup_logger

logger = setup_logger(__name__)

try:  # qtawesome — необязательная зависимость времени выполнения
    import qtawesome as _qta
except Exception as exc:  # noqa: BLE001 - любая ошибка импорта = деградация к пустым иконкам
    _qta = None
    logger.warning("qtawesome недоступен, иконки отключены: %s", exc)


def available() -> bool:
    """True, если иконки реально доступны."""
    return _qta is not None


def _resolve_color(color: str | None) -> str:
    """color — hex, роль токена ('accent', 'text_muted', ...) или None (= text_muted темы)."""
    t = tokens()
    if color is None:
        return t.get("text_muted", "gray")
    return t.get(color, color)


@lru_cache(maxsize=512)
def _cached_icon(name: str, color: str) -> QIcon:
    if _qta is None:
        return QIcon()
    try:
        return _qta.icon(name, color=color)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Иконка %s недоступна: %s", name, exc)
        return QIcon()


def icon(name: str, color: str | None = None) -> QIcon:
    """Иконка по имени ('mdi6.check'). Цвет: роль токена, hex или None (приглушённый цвет темы)."""
    return _cached_icon(name, _resolve_color(color))


def nav_icon(name: str) -> QIcon:
    """Иконка пункта навигации: приглушённая, при выборе — цвет акцента (Active/Selected)."""
    t = tokens()
    if _qta is None:
        return QIcon()
    try:
        return _qta.icon(name, color=t.get("text_muted", "gray"), color_active=t.get("accent", "gray"),
                         color_selected=t.get("accent", "gray"))
    except Exception:  # noqa: BLE001
        return QIcon()


def pixmap(name: str, size: int, color: str | None = None) -> QPixmap:
    return icon(name, color).pixmap(size, size)


@lru_cache(maxsize=64)
def _png_path(name: str, color: str, size: int) -> str:
    """PNG-файл иконки (нужен QSS: image: url(...)). Лежит во временном каталоге; '' если не вышло."""
    if _qta is None:
        return ""
    safe = name.replace(".", "_").replace("-", "_")
    path = os.path.join(tempfile.gettempdir(), f"snapmatch-{safe}-{color.lstrip('#')}-{size}.png")
    try:
        if not os.path.exists(path):
            _qta.icon(name, color=color).pixmap(size, size).save(path)
        return path.replace(os.sep, "/") if os.path.exists(path) else ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("Не удалось сохранить иконку %s: %s", name, exc)
        return ""


def png_path(name: str, color: str | None = None, size: int = 14) -> str:
    """Путь к PNG иконки в нужном цвете — для QSS (галочка чекбокса, шевроны спинбокса/комбобокса)."""
    return _png_path(name, _resolve_color(color), size)

