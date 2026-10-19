"""Свои подсказки при наведении: скруглённая панель, плавное появление, заголовок + пояснение.

Первая строка toolTip — заголовок (жирным), остальное — пояснение приглушённым цветом.
Подсказки с HTML остаются как есть. Включается одной строкой: TooltipManager(app).
"""
from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, Qt, QTimer
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import QApplication, QFrame, QGraphicsOpacityEffect, QLabel, QVBoxLayout, QWidget

from gui.design import motion

MAX_WIDTH = 340


class FxTooltip(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame()
        self.panel.setObjectName("tipPanel")
        outer.addWidget(self.panel)
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(12, 9, 12, 10)
        lay.setSpacing(3)
        self.title = QLabel()
        self.title.setObjectName("tipTitle")
        self.title.setWordWrap(True)
        self.body = QLabel()
        self.body.setObjectName("tipBody")
        self.body.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.body)
        self._fade: QPropertyAnimation | None = None

    def show_text(self, text: str, global_pos: QPoint) -> None:
        if "<" in text and ">" in text:           # HTML — показываем как есть
            self.title.hide()
            self.body.setTextFormat(Qt.TextFormat.RichText)
            self.body.setText(text)
            self.body.show()
        else:
            head, _, rest = text.partition("\n")
            self.title.setText(head)
            self.title.setVisible(bool(head))
            self.body.setTextFormat(Qt.TextFormat.PlainText)
            self.body.setText(rest.strip())
            self.body.setVisible(bool(rest.strip()))
        self.panel.setMaximumWidth(MAX_WIDTH)
        self.setMaximumWidth(MAX_WIDTH)
        self.adjustSize()
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(global_pos.x() + 14, area.right() - self.width() - 8)
        y = global_pos.y() + 20
        if y + self.height() > area.bottom() - 8:
            y = global_pos.y() - self.height() - 12
        self.move(max(area.left() + 4, x), y)
        self.show()
        if motion.ENABLED:
            effect = QGraphicsOpacityEffect(self.panel)
            self.panel.setGraphicsEffect(effect)
            fade = QPropertyAnimation(effect, b"opacity", self)
            fade.setDuration(130)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(QEasingCurve.Type.OutCubic)
            fade.finished.connect(lambda: self.panel.setGraphicsEffect(None))
            fade.start()
            self._fade = fade


class TooltipManager(QObject):
    """Перехватывает штатные подсказки Qt (QEvent.ToolTip) и показывает вместо них FxTooltip."""

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.tip = FxTooltip()
        app.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.ToolTip and isinstance(obj, QWidget):
            text = obj.toolTip()
            if text:
                self.tip.show_text(text, event.globalPos())
            else:
                self.tip.hide()
            return True
        if kind in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress,
                    QEvent.Type.Wheel, QEvent.Type.WindowDeactivate, QEvent.Type.Hide):
            if self.tip.isVisible():
                self.tip.hide()
        return False
