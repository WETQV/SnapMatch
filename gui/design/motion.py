"""Анимации дизайн-системы SnapMatch.

В QSS нет transition, поэтому всё делается кодом через QPropertyAnimation. Правила (из ui-animation):
  * анимируем только прозрачность и сдвиг, не размеры раскладки (кроме раскрывающихся секций);
  * вход 180–250 мс с кривой OutCubic, выход быстрее входа;
  * лесенка карточек 40 мс на элемент, всего меньше 300 мс;
  * действия с клавиатуры не анимируем;
  * один глобальный переключатель «меньше анимации» (ENABLED).
"""
from PyQt6.QtCore import (
    QAbstractAnimation, QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation,
    Qt, QTimer,
)
from PyQt6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget,
)

ENABLED = True   # глобальный переключатель анимаций; меняйте через set_enabled()
ENTER_MS = 220
EXIT_MS = 140
STAGGER_MS = 40


def set_enabled(on: bool) -> None:
    """Включает/выключает все анимации дизайн-системы (читается как motion.ENABLED)."""
    global ENABLED
    ENABLED = bool(on)


def _opacity(widget: QWidget) -> QGraphicsOpacityEffect:
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    return effect


def fade_in(widget: QWidget, rise: int = 0, delay: int = 0, duration: int = ENTER_MS) -> None:
    """Плавное появление (только прозрачность). Позицией виджетов в раскладке управляет сама раскладка —
    анимировать её нельзя, получаются наложения. Повторный вызов безопасно останавливает прошлую анимацию."""
    if not ENABLED:
        return
    old = getattr(widget, "_anim_ref", None)
    if old is not None:
        old.stop()
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(0.0)
    fade = QPropertyAnimation(effect, b"opacity", widget)
    fade.setDuration(duration)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    def done() -> None:
        if getattr(widget, "_anim_ref", None) is fade and widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)

    fade.finished.connect(done)
    timer = QTimer(widget)           # дочерний таймер: умрёт вместе с виджетом
    timer.setSingleShot(True)
    timer.timeout.connect(fade.start)
    timer.start(max(0, delay))
    widget._anim_ref = fade          # type: ignore[attr-defined]


class FadeStack(QStackedWidget):
    """QStackedWidget со сменой страниц: новая страница плавно появляется и слегка поднимается,
    карточки внутри появляются лесенкой."""

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 (имя Qt)
        changed = index != self.currentIndex()
        super().setCurrentIndex(index)
        if not (ENABLED and changed):
            return
        page = self.currentWidget()
        if page is None:
            return
        QTimer.singleShot(0, lambda: self._enter(page))

    @staticmethod
    def _enter(page: QWidget) -> None:
        from gui.design.widgets import StatTile
        for i, tile in enumerate(page.findChildren(StatTile)):
            tile.play(delay_ms=60 + i * STAGGER_MS)
        cards = [w for w in page.findChildren(QFrame, "card") if w.parent() is not None]
        # верхние карточки страницы, без вложенных
        top = [c for c in cards if not isinstance(c.parent(), QFrame) or c.parent().objectName() != "card"]
        if not top:
            fade_in(page, rise=8)
            return
        for i, card in enumerate(top[:6]):
            fade_in(card, rise=12, delay=i * STAGGER_MS)


class Toast(QLabel):
    """Всплывающее уведомление в правом нижнем углу: въезжает снизу, держится, плавно гаснет."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.hide()
        self._effect = _opacity(self)
        self._effect.setOpacity(0.0)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)
        self._anim: QAbstractAnimation | None = None

    def show_message(self, text: str, hold_ms: int = 2200) -> None:
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        left = getattr(parent, "sidebar_w", 0)
        x = left + (parent.width() - left - self.width()) // 2
        y = getattr(parent, "top_offset", 0) + 16     # сверху по центру: не перекрывает кнопки действий
        self.move(x, y)
        self.show()
        self.raise_()
        if not ENABLED:
            self._effect.setOpacity(1.0)
        else:
            self._run(0.0, 1.0, ENTER_MS, QPoint(x, y - 14), QPoint(x, y))
        self._hide_timer.start(hold_ms)

    def _fade_out(self) -> None:
        if not ENABLED:
            self.hide()
            return
        self._run(1.0, 0.0, EXIT_MS, self.pos(), self.pos() + QPoint(0, -8), hide_after=True)

    def _run(self, a: float, b: float, ms: int, p0: QPoint, p1: QPoint, hide_after: bool = False) -> None:
        fade = QPropertyAnimation(self._effect, b"opacity", self)
        fade.setDuration(ms)
        fade.setStartValue(a)
        fade.setEndValue(b)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        move = QPropertyAnimation(self, b"pos", self)
        move.setDuration(ms)
        move.setStartValue(p0)
        move.setEndValue(p1)
        move.setEasingCurve(QEasingCurve.Type.OutCubic)
        group = QParallelAnimationGroup(self)
        group.addAnimation(fade)
        group.addAnimation(move)
        if hide_after:
            group.finished.connect(self.hide)
        self._anim = group
        group.start()


class NavIndicator(QFrame):
    """Подсветка выбранного пункта навигации: скруглённая «пилюля», которая плавно переезжает и меняет размер.
    Лежит поверх списка и пропускает клики сквозь себя."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("navHighlight")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()
        self._anim: QPropertyAnimation | None = None

    def move_to(self, rect_in_parent, animate: bool = True) -> None:
        from PyQt6.QtCore import QRect
        target = QRect(rect_in_parent).adjusted(1, 2, -1, -2)
        self.raise_()
        if not self.isVisible() or not (ENABLED and animate):
            self.setGeometry(target)
            self.show()
            return
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(240)
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()


class SegmentedControl(QWidget):
    """Вкладки с подчёркиванием: акцентная линия плавно переезжает под выбранную вкладку.
    (Имя осталось от v2, API прежний: changed(index).)"""

    from PyQt6.QtCore import pyqtSignal
    changed = pyqtSignal(int)

    def __init__(self, labels: list[str]) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.buttons: list[QPushButton] = []
        for i, text in enumerate(labels):
            b = QPushButton(text)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self._select(idx))
            row.addWidget(b)
            self.buttons.append(b)
        row.addStretch()
        outer.addLayout(row)
        self.buttons[0].setChecked(True)
        self.indicator = QFrame(self)
        self.indicator.setObjectName("tabHighlight")
        self.indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.indicator.lower()
        self._anim: QPropertyAnimation | None = None
        self._current = 0

    def _target_rect(self, idx: int):
        b = self.buttons[idx]
        return b.x(), b.y(), b.width(), b.height()

    def _select(self, idx: int) -> None:
        self._current = idx
        self._move_indicator(animate=True)
        self.changed.emit(idx)

    def _move_indicator(self, animate: bool) -> None:
        x, y, w, h = self._target_rect(self._current)
        from PyQt6.QtCore import QRect
        target = QRect(x, y, w, h)
        if not (ENABLED and animate) or not self.indicator.isVisible():
            self.indicator.setGeometry(target)
            self.indicator.show()
            return
        self._anim = QPropertyAnimation(self.indicator, b"geometry", self)
        self._anim.setDuration(220)
        self._anim.setStartValue(self.indicator.geometry())
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self._move_indicator(animate=False))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._move_indicator(animate=False)
