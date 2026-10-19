"""Выполнение блокирующих функций (БД, сеть, subprocess) вне GUI-потока."""

from typing import Any, Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from utils.logger import setup_logger

logger = setup_logger(__name__)


class _Signals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[..., Any], args: tuple, kwargs: dict) -> None:
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001 — ошибка уходит в сигнал, не роняет поток
            logger.error("Фоновая задача завершилась ошибкой: %s", exc)
            self.signals.failed.emit(str(exc))
            return
        self.signals.done.emit(result)


# Держим ссылки на задачи до завершения, иначе PyQt может собрать сигналы раньше времени
_alive: set = set()


def run_in_background(
    fn: Callable[..., Any],
    *args: Any,
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> None:
    """Запускает fn(*args, **kwargs) в пуле потоков.

    on_done / on_error вызываются в GUI-потоке (если вызывающий объект живёт в нём).
    """
    task = _Task(fn, args, kwargs)
    _alive.add(task)

    def _finish(callback, value):
        _alive.discard(task)
        if callback:
            callback(value)

    task.signals.done.connect(lambda r: _finish(on_done, r))
    task.signals.failed.connect(lambda e: _finish(on_error, e))
    QThreadPool.globalInstance().start(task)
