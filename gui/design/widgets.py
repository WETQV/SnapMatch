"""Виджеты дизайн-системы SnapMatch, у которых есть собственная отрисовка и плавные состояния:
FxButton, Switch/SwitchRow, ServerCard, StatTile, StatusBadge, IconTile, WinButton, GlowRoot (фон окна),
FxComboBox, FxSlider, ThemeCard, Swatch, Collapsible; плюс помощники card/label/page_header/primary/
icon_button/make_table.

QSS не умеет переходов, поэтому у каждого виджета есть «прогресс» 0..1, который анимируется
QVariantAnimation, а цвета рисуются в paintEvent. Всё уважает глобальный переключатель motion.ENABLED.
Цвета берутся только из токенов (tokens())."""
import math

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QAbstractButton, QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from gui.design import icons, motion
from gui.design.tokens import tokens

KIND_COLOR = {"ok": "accent", "error": "danger", "warn": "warning", "idle": "text_muted", "info": "info"}


def tint(color: str, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def lerp(a: QColor, b: QColor, k: float) -> QColor:
    k = max(0.0, min(1.0, k))
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * k, a.greenF() + (b.greenF() - a.greenF()) * k,
        a.blueF() + (b.blueF() - a.blueF()) * k, a.alphaF() + (b.alphaF() - a.alphaF()) * k,
    )


class Progress:
    """Плавный прогресс 0..1 для hover/selected/checked. set(target) анимирует, а при выключенных
    анимациях переключает мгновенно."""

    def __init__(self, owner: QWidget, duration: int = 150, start: float = 0.0) -> None:
        self.value = start
        self._owner = owner
        self._anim = QVariantAnimation(owner)
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._tick)

    def _tick(self, v) -> None:
        self.value = float(v)
        self._owner.update()

    def set(self, target: float) -> None:
        self._anim.stop()
        if not motion.ENABLED or not self._owner.isVisible():
            self.value = target
            self._owner.update()
            return
        self._anim.setStartValue(self.value)
        self._anim.setEndValue(target)
        self._anim.start()


class GlowRoot(QWidget):
    """Фон окна. Рисует сам: скруглённое окно, полосу боковой панели и границу. Боковая панель и заголовок
    прозрачные — поэтому у скруглённого окна нет «торчащих» квадратных уголков."""

    corner_radius = 0
    sidebar_w = 0
    top_offset = 0

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = tokens()
        if not t:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        win = QPainterPath()
        win.addRoundedRect(rect, self.corner_radius, self.corner_radius)
        p.fillPath(win, QColor(t["bg"]))
        if self.sidebar_w:
            strip = QPainterPath()
            strip.addRect(QRectF(0, self.top_offset, self.sidebar_w, self.height() - self.top_offset))
            p.fillPath(win.intersected(strip), QColor(t["surface"]))
            p.setPen(QPen(QColor(t["border"]), 1))
            p.drawLine(QPointF(self.sidebar_w - 0.5, self.top_offset), QPointF(self.sidebar_w - 0.5, self.height()))
        if self.corner_radius:
            p.setPen(QPen(QColor(t["border"]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(win)


class FxButton(QPushButton):
    """Кнопка с плавным наведением. Вариант задаётся objectName: primary / danger / pill / (обычная)."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.setProperty("fx", True)   # QSS: фон и рамку рисует сам виджет, а не стиль
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = Progress(self, 140)
        self._check = Progress(self, 180)
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self._check.set(1.0 if checked else 0.0)
        if self.objectName() == "pill":
            self.setIcon(icons.icon("mdi6.check", color="accent") if checked else QIcon())

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover.set(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover.set(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = tokens()
        if t:
            name = self.objectName()
            h, c = self._hover.value, self._check.value
            acc, border = QColor(t["accent"]), QColor(t["border"])
            if name == "primary":
                bg = lerp(acc, QColor(t["accent_hover"]), h)
                line = bg
            elif name == "danger":
                bg = tint(t["danger"], 0.14 * h)
                line = lerp(tint(t["danger"], 0.45), QColor(t["danger"]), h)
            elif name == "pill":
                bg = lerp(tint(t["text"], 0.0 + 0.05 * h), tint(t["accent"], 0.15), c)
                line = lerp(lerp(border, tint(t["text_muted"], 0.9), h), tint(t["accent"], 0.6), c)
            else:
                bg = lerp(QColor(t["surface_alt"]), lerp(QColor(t["surface_alt"]), tint(t["accent"], 0.16), 1.0), h * 0.6)
                line = lerp(border, tint(t["accent"], 0.7), h)
            if self.isDown():
                bg = lerp(bg, QColor(0, 0, 0, 255), 0.14)
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            if not self.isEnabled():
                p.setOpacity(0.5)
            radius = self.height() / 2 if name == "pill" else 9
            p.setBrush(bg)
            p.setPen(QPen(line, 1))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
            p.end()
        super().paintEvent(event)


class Switch(QAbstractButton):
    """Переключатель со скользящим кружком."""

    def __init__(self, checked: bool = False) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._pos = Progress(self, 170, 1.0 if checked else 0.0)
        self._hover = Progress(self, 120)
        self.toggled.connect(lambda on: self._pos.set(1.0 if on else 0.0))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(42, 24)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover.set(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover.set(0.0)
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = tokens()
        if not t:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.45)
        k = self._pos.value
        off = lerp(QColor(t["border"]), QColor(t["text_muted"]), 0.35 + 0.25 * self._hover.value)
        track = lerp(off, QColor(t["accent"]), k)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 2, self.width(), self.height() - 4), 10, 10)
        d = 14
        x = 4 + k * (self.width() - d - 8)
        p.setBrush(QColor(t["knob"]))
        p.drawEllipse(QRectF(x, (self.height() - d) / 2, d, d))


class SwitchRow(QWidget):
    """Подпись + переключатель в одну строку. API как у QCheckBox: toggled, isChecked, setChecked."""

    toggled = pyqtSignal(bool)

    def __init__(self, text: str, checked: bool = False, compact: bool = False) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 3, 0, 3)
        lay.setSpacing(12)
        self.label = QLabel(text)
        self.label.setWordWrap(not compact)
        self.switch = Switch(checked)
        lay.addWidget(self.label, 0 if compact else 1)
        lay.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)
        self.switch.toggled.connect(self.toggled)

    def isChecked(self) -> bool:  # noqa: N802
        return self.switch.isChecked()

    def setChecked(self, on: bool) -> None:  # noqa: N802
        self.switch.setChecked(on)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.isEnabled():
            self.switch.toggle()
        super().mousePressEvent(event)


class StatusBadge(QWidget):
    """Пилюля статуса: тонированная заливка, рамка и точка. У kind='ok' точка мягко пульсирует."""

    def __init__(self, text: str, kind: str = "idle", pulse: bool | None = None) -> None:
        super().__init__()
        self.text, self.kind = text, kind
        self._phase = 0.0
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._font = QFont(QApplication.font())
        self._font.setPointSizeF(9.0)
        self._font.setWeight(QFont.Weight.DemiBold)
        self._anim = None
        if pulse if pulse is not None else kind == "ok":
            self._anim = QVariantAnimation(self)
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(math.tau)
            self._anim.setDuration(2400)
            self._anim.setLoopCount(-1)
            self._anim.valueChanged.connect(self._on_tick)
            self._anim.start()

    def _on_tick(self, value) -> None:
        self._phase = float(value)
        if motion.ENABLED and self.isVisible():
            self.update()

    def set(self, text: str, kind: str | None = None) -> None:
        """Меняет текст и вид бейджа без пересоздания (пульсация включается только для kind='ok')."""
        self.text = text
        if kind is not None and kind != self.kind:
            self.kind = kind
            if kind == "ok" and self._anim is None:
                self._anim = QVariantAnimation(self)
                self._anim.setStartValue(0.0)
                self._anim.setEndValue(math.tau)
                self._anim.setDuration(2400)
                self._anim.setLoopCount(-1)
                self._anim.valueChanged.connect(self._on_tick)
                self._anim.start()
            elif kind != "ok" and self._anim is not None:
                self._anim.stop()
                self._anim.deleteLater()
                self._anim = None
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(QFontMetrics(self._font).horizontalAdvance(self.text) + 36, 24)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = tokens()
        if not t:
            return
        color = t[KIND_COLOR[self.kind]]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(tint(color, 0.12))
        p.setPen(QPen(tint(color, 0.32), 1))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        cx, cy = 13.0, r.center().y()
        pulse = (0.5 + 0.5 * math.sin(self._phase)) if (self._anim and motion.ENABLED) else 0.0
        p.setPen(Qt.PenStyle.NoPen)
        if self._anim:
            p.setBrush(tint(color, 0.28 * (1.0 - pulse)))
            ring = 3.2 + 4.0 * pulse
            p.drawEllipse(QPointF(cx, cy), ring, ring)
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(cx, cy), 3.2, 3.2)
        p.setFont(self._font)
        p.setPen(QColor(color))
        p.drawText(QRectF(23, 0, r.width() - 25, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text)


class IconTile(QLabel):
    """Иконка в скруглённой плитке, тон зависит от kind (по умолчанию нейтральный)."""

    def __init__(self, icon_name: str, kind: str = "idle", size: int = 40) -> None:
        super().__init__()
        self.icon_name, self.kind, self._size = icon_name, kind, size
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = tokens()
        if not t:
            return
        color = t[KIND_COLOR[self.kind]]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(tint(color, 0.13))
        p.setPen(QPen(tint(color, 0.30), 1))
        p.drawRoundedRect(r, self._size * 0.28, self._size * 0.28)
        s = int(self._size * 0.52)
        icons.icon(self.icon_name, color=color).paint(p, int((self._size - s) / 2), int((self._size - s) / 2), s, s)


class ServerCard(QFrame):
    """Строка списка: плавное наведение и выбор (заливка + рамка акцентного цвета по всему периметру)."""

    clicked = pyqtSignal(object)

    def __init__(self, name: str, subtitle: str, status_text: str, kind: str, tools: int, icon: str) -> None:
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.name = name
        self._hover = Progress(self, 140)
        self._sel = Progress(self, 200)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 14, 10)
        lay.setSpacing(12)
        lay.addWidget(IconTile(icon, kind, 40))
        col = QVBoxLayout()
        col.setSpacing(1)
        title = QLabel(name)
        title.setObjectName("cardTitle")
        sub = QLabel(subtitle)
        sub.setObjectName("mono")
        col.addWidget(title)
        col.addWidget(sub)
        lay.addLayout(col, 1)
        right = QVBoxLayout()
        right.setSpacing(4)
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(StatusBadge(status_text, kind), 0, Qt.AlignmentFlag.AlignRight)
        count = QLabel(f"{tools} tools")
        count.setObjectName("mono")
        count.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(count)
        lay.addLayout(right)

    def set_selected(self, on: bool) -> None:
        self._sel.set(1.0 if on else 0.0)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover.set(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover.set(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self)
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = tokens()
        if not t:
            return
        h, s = self._hover.value, self._sel.value
        base = QColor(t["surface"])
        bg = lerp(base, QColor(t["surface_alt"]), h)
        bg = lerp(bg, _over(base, tint(t["accent"], 0.11)), s)
        line = lerp(lerp(QColor(t["border"]), tint(t["accent"], 0.45), h), tint(t["accent"], 0.85), s)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(bg)
        p.setPen(QPen(line, 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)


def _over(base: QColor, top: QColor) -> QColor:
    a = top.alphaF()
    return QColor.fromRgbF(base.redF() * (1 - a) + top.redF() * a, base.greenF() * (1 - a) + top.greenF() * a,
                           base.blueF() * (1 - a) + top.blueF() * a, 1.0)


class StatTile(QFrame):
    """Плитка метрики: моноширинное число (при показе «набегает» от нуля) и подпись."""

    def __init__(self, value: str, caption: str, icon: str, kind: str = "idle") -> None:
        super().__init__()
        self.setObjectName("statTile")
        self._target = int(value) if value.isdigit() else None
        self._text = value
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.num = QLabel(value)
        self.num.setObjectName("statValue")
        self.num.setMinimumHeight(40)
        self.setMinimumHeight(88)
        cap = QLabel(caption)
        cap.setObjectName("muted")
        col.addWidget(self.num)
        col.addWidget(cap)
        lay.addLayout(col, 1)
        lay.addWidget(IconTile(icon, kind, 38), 0, Qt.AlignmentFlag.AlignTop)
        self._count = QVariantAnimation(self)
        self._count.setDuration(650)
        self._count.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._count.valueChanged.connect(lambda v: self.num.setText(str(int(v))))

    def set_value(self, value: str) -> None:
        """Обновляет значение плитки (с анимацией счёта, если значение целое и анимации включены)."""
        self._text = value
        self._target = int(value) if value.isdigit() else None
        self.num.setText(value)

    def play(self, delay_ms: int = 0) -> None:
        """Запускает счёт от нуля до значения (вызывается при показе страницы)."""
        if self._target is None or not motion.ENABLED:
            self.num.setText(self._text)
            return
        self.num.setText("0")
        self._count.stop()
        self._count.setStartValue(0)
        self._count.setEndValue(self._target)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(delay_ms, self._count.start)


class WinButton(QAbstractButton):
    """Кнопка окна (свернуть / развернуть / закрыть) с плавной подсветкой; у «закрыть» — красная."""

    def __init__(self, icon_name: str, danger: bool = False) -> None:
        super().__init__()
        self.icon_name, self.danger = icon_name, danger
        self.setFixedSize(46, 32)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._hover = Progress(self, 130)

    def set_icon_name(self, name: str) -> None:
        self.icon_name = name
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover.set(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover.set(0.0)
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = tokens()
        if not t:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._hover.value
        if self.danger:
            p.setBrush(tint(t["win_close"], 0.92 * h))
        else:
            p.setBrush(tint(t["text"], 0.09 * h))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(4, 3, -4, -3), 8, 8)
        color = t["knob"] if (self.danger and h > 0.5) else t["text_muted" if h < 0.5 else "text"]
        s = 15
        icons.icon(self.icon_name, color=color).paint(p, int((self.width() - s) / 2), int((self.height() - s) / 2), s, s)


# ───────────────────────── выпадающий список ─────────────────────────
from PyQt6.QtCore import QPoint, QPropertyAnimation
from PyQt6.QtGui import QPainterPath
from PyQt6.QtWidgets import QComboBox, QGraphicsOpacityEffect, QScrollArea, QSlider


class _PopupRow(QWidget):
    clicked = pyqtSignal(int)

    def __init__(self, index: int, text: str, selected: bool) -> None:
        super().__init__()
        self.index, self.text, self.selected = index, text, selected
        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = Progress(self, 110)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover.set(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover.set(0.0)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._hover.value
        fill = tint(t["accent"], 0.16) if self.selected else tint(t["text"], 0.07 * h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 1, -2, -1), 8, 8)
        p.setFont(self.font())
        p.setPen(QColor(t["accent"] if self.selected else t["text"]))
        p.drawText(QRectF(14, 0, self.width() - 44, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(self.font()).elidedText(self.text, Qt.TextElideMode.ElideRight, self.width() - 44))
        if self.selected:
            icons.icon("mdi6.check", color=t["accent"]).paint(p, self.width() - 28, int((self.height() - 15) / 2), 15, 15)


class _ComboPopup(QFrame):
    """Своё выпадающее окно списка: скруглённая панель, строки с плавным наведением, плавное появление."""

    def __init__(self, combo: "FxComboBox") -> None:
        super().__init__(combo.window(), Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.combo = combo
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame()
        self.panel.setObjectName("popupPanel")
        outer.addWidget(self.panel)
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(4, 4, 4, 4)
        pl.setSpacing(0)
        rows = QWidget()
        rl = QVBoxLayout(rows)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        for i in range(combo.count()):
            row = _PopupRow(i, combo.itemText(i), i == combo.currentIndex())
            row.clicked.connect(self._choose)
            rl.addWidget(row)
        visible_rows = min(combo.count(), 8)
        if combo.count() > 8:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(rows)
            scroll.setFixedHeight(visible_rows * 36)
            pl.addWidget(scroll)
        else:
            pl.addWidget(rows)
        self.setFixedWidth(max(combo.width(), 160))
        self.adjustSize()

    def _choose(self, index: int) -> None:
        self.combo.setCurrentIndex(index)
        self.close()

    def open_below(self) -> None:
        combo = self.combo
        pos = combo.mapToGlobal(QPoint(0, combo.height() + 4))
        screen = combo.screen().availableGeometry()
        if pos.y() + self.height() > screen.bottom():
            pos = combo.mapToGlobal(QPoint(0, -self.height() - 4))
        self.move(pos)
        self.show()
        if motion.ENABLED:
            effect = QGraphicsOpacityEffect(self.panel)
            self.panel.setGraphicsEffect(effect)
            fade = QPropertyAnimation(effect, b"opacity", self)
            fade.setDuration(140)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(QEasingCurve.Type.OutCubic)
            fade.finished.connect(lambda: self.panel.setGraphicsEffect(None))
            fade.start()
            self._fade = fade

    def closeEvent(self, event) -> None:  # noqa: N802
        self.combo._on_popup_closed()
        super().closeEvent(event)


class FxComboBox(QComboBox):
    """QComboBox со своим выпадающим списком и шевроном, который поворачивается при открытии."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.setProperty("fx", True)   # QSS: стрелку рисует сам виджет
        self._open = Progress(self, 160)
        self._popup: _ComboPopup | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def showPopup(self) -> None:  # noqa: N802
        if self._popup is not None or self.count() == 0:
            return
        self._popup = _ComboPopup(self)
        self._open.set(1.0)
        self._popup.open_below()

    def hidePopup(self) -> None:  # noqa: N802
        if self._popup is not None:
            self._popup.close()

    def _on_popup_closed(self) -> None:
        self._popup = None
        self._open.set(0.0)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        t = tokens()
        if not t:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width() - 20, self.height() / 2)
        p.rotate(180 * self._open.value)
        pix = icons.icon("mdi6.chevron-down", color=t["accent"] if self._open.value > 0.5 else t["text_muted"]).pixmap(16, 16)
        p.drawPixmap(-8, -8, pix)


# ───────────────────────── слайдер ─────────────────────────
class FxSlider(QSlider):
    """Горизонтальный слайдер с собственной отрисовкой: ничего не обрезается, ручка плавно «оживает»
    при наведении и перетаскивании. Размеры ручки в QSS заданы такими же (18px) — мышь считается верно."""

    def __init__(self, *args) -> None:
        super().__init__(Qt.Orientation.Horizontal, *args)
        self.setProperty("fx", True)   # QSS: дорожку и ручку рисует сам виджет
        self.setMinimumHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = Progress(self, 130)
        self._drag = Progress(self, 130)
        self.sliderPressed.connect(lambda: self._drag.set(1.0))
        self.sliderReleased.connect(lambda: self._drag.set(0.0))

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover.set(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover.set(0.0)
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = tokens()
        if not t:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = 10.0
        cy = self.height() / 2
        span = max(1, self.maximum() - self.minimum())
        frac = (self.value() - self.minimum()) / span
        x = m + frac * (self.width() - 2 * m)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t["border"]))
        p.drawRoundedRect(QRectF(m, cy - 2, self.width() - 2 * m, 4), 2, 2)
        p.setBrush(QColor(t["accent"]))
        p.drawRoundedRect(QRectF(m, cy - 2, x - m, 4), 2, 2)
        k = max(self._hover.value, self._drag.value)
        p.setBrush(tint(t["accent"], 0.20 * k))
        p.drawEllipse(QPointF(x, cy), 9 + 5 * k, 9 + 5 * k)
        p.setBrush(QColor(t["knob"]))
        p.setPen(QPen(QColor(t["accent"]), 2.5))
        p.drawEllipse(QPointF(x, cy), 7.5 + 0.8 * k, 7.5 + 0.8 * k)


# ───────────────────────── выбор темы и акцента ─────────────────────────
class ThemeCard(QWidget):
    """Карточка режима темы с миниатюрой окна: сразу видно, как будет выглядеть."""

    clicked = pyqtSignal(str)

    def __init__(self, key: str, title: str, preview_tokens: dict) -> None:
        super().__init__()
        self.key, self.title, self.pt = key, title, preview_tokens
        self.selected = False
        # ширина подстраивается под окно (миниатюра рисуется по текущей ширине), высота фиксирована
        self.setMinimumWidth(126)
        self.setMaximumWidth(176)
        self.setFixedHeight(112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = Progress(self, 130)
        self._sel = Progress(self, 190)

    def set_selected(self, on: bool) -> None:
        self.selected = on
        self._sel.set(1.0 if on else 0.0)

    def set_preview(self, preview_tokens: dict) -> None:
        self.pt = preview_tokens
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover.set(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover.set(0.0)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t, pt = tokens(), self.pt
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h, s = self._hover.value, self._sel.value
        frame = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        line = lerp(lerp(QColor(t["border"]), tint(t["text_muted"], 0.9), h), QColor(t["accent"]), s)
        p.setBrush(QColor(t["surface"]))
        p.setPen(QPen(line, 1 + s))
        p.drawRoundedRect(frame, 12, 12)
        # миниатюра окна
        pv = QRectF(10, 10, self.width() - 20, 62)
        path = QPainterPath()
        path.addRoundedRect(pv, 7, 7)
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(path, QColor(pt["bg"]))
        side = QPainterPath()
        side.addRect(QRectF(pv.left(), pv.top(), 26, pv.height()))
        p.fillPath(path.intersected(side), QColor(pt["surface"]))
        p.setBrush(QColor(pt["surface"]))
        p.setPen(QPen(QColor(pt["border"]), 1))
        p.drawRoundedRect(QRectF(pv.left() + 32, pv.top() + 8, pv.width() - 40, 20), 4, 4)
        p.drawRoundedRect(QRectF(pv.left() + 32, pv.top() + 33, (pv.width() - 46) / 2, 20), 4, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pt["accent"]))
        p.drawRoundedRect(QRectF(pv.left() + 6, pv.top() + 8, 14, 4), 2, 2)
        p.drawRoundedRect(QRectF(pv.left() + 38, pv.top() + 39, 22, 4), 2, 2)
        p.setBrush(QColor(pt["text_muted"]))
        for i in range(2):
            p.drawRoundedRect(QRectF(pv.left() + 6, pv.top() + 20 + i * 9, 14, 3), 1.5, 1.5)
        f = QFont(self.font())
        f.setPointSizeF(10)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(t["accent"] if self.selected else t["text"]))
        p.drawText(QRectF(12, 78, self.width() - 38, 28), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.title)
        if s > 0.01:
            p.setOpacity(s)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["accent"]))
            p.drawEllipse(QRectF(self.width() - 31, 82, 18, 18))
            icons.icon("mdi6.check-bold", color=t["accent_text"]).paint(p, self.width() - 28, 85, 12, 12)


class Swatch(QWidget):
    """Круглый образец цвета акцента: выбранный получает кольцо и галочку, наведение — плавное увеличение."""

    clicked = pyqtSignal(str)

    def __init__(self, key: str, color: str | None, tip: str, icon: str | None = None) -> None:
        super().__init__()
        self.key, self.color, self.icon = key, color, icon
        self.selected = False
        self.setFixedSize(38, 38)
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = Progress(self, 120)
        self._sel = Progress(self, 180)

    def set_selected(self, on: bool) -> None:
        self.selected = on
        self._sel.set(1.0 if on else 0.0)

    def set_color(self, color: str) -> None:
        self.color = color
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover.set(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover.set(0.0)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h, s = self._hover.value, self._sel.value
        c = QPointF(self.width() / 2, self.height() / 2)
        r = 12 + 1.5 * h
        if s > 0.01:
            p.setPen(QPen(tint(self.color or t["accent"], s), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, 16.5, 16.5)
        p.setPen(Qt.PenStyle.NoPen)
        if self.color:
            p.setBrush(QColor(self.color))
            p.drawEllipse(c, r, r)
        else:  # «свой цвет» — пунктирное кольцо с плюсом
            p.setPen(QPen(QColor(t["text_muted"]), 1.5, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, r, r)
        glyph = "mdi6.check-bold" if self.selected and self.color else self.icon
        if glyph:
            col = t["knob"] if self.color else t["text_muted"]
            icons.icon(glyph, color=col).paint(p, int(c.x() - 7), int(c.y() - 7), 14, 14)


# ───────────────────────── раскрывающаяся секция ─────────────────────────
from PyQt6.QtWidgets import QAbstractButton as _AB


class _CollapseHeader(_AB):
    """Заголовок секции: шеврон плавно поворачивается, при наведении мягкая подсветка."""

    def __init__(self, title: str, expanded: bool) -> None:
        super().__init__()
        self.title = title
        self.setCheckable(True)
        self.setChecked(expanded)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(36)
        self._rot = Progress(self, 220, 1.0 if expanded else 0.0)
        self._hover = Progress(self, 120)
        self.toggled.connect(lambda on: self._rot.set(1.0 if on else 0.0))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, 36)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover.set(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover.set(0.0)
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = tokens()
        if not t:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tint(t["text"], 0.05 * self._hover.value))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 2, 0, -2), 8, 8)
        p.save()
        p.translate(18, self.height() / 2)
        p.rotate(-90 + 90 * self._rot.value)
        icons.icon("mdi6.chevron-down", color=t["text_muted"]).paint(p, -8, -8, 16, 16)
        p.restore()
        f = QFont(self.font())
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(QColor(t["text"]))
        p.drawText(QRectF(36, 0, self.width() - 44, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.title)


class _ClipBody(QWidget):
    """Окно-обрезка: содержимое всегда имеет свою натуральную высоту и просто «выглядывает» из-под края,
    а не сжимается (так секция не «дублируется» и не дёргается при раскрытии)."""

    def __init__(self, content: QWidget) -> None:
        super().__init__()
        content.setParent(self)
        self.content = content
        self.natural = 0

    def measure(self) -> int:
        if self.width() > 0:
            self.content.setFixedWidth(self.width())
        self.natural = max(self.content.sizeHint().height(), self.content.minimumSizeHint().height()) + 6
        return self.natural

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.natural and self.width() > 0:
            # ширина содержимого всегда равна ширине окна-обрезки (иначе поля вылезают за край карточки)
            self.content.setFixedWidth(self.width())
            self.content.setGeometry(0, 0, self.width(), self.natural)


class Collapsible(QWidget):
    """Раскрывающаяся секция. Высота меняется мгновенно (иначе QScrollArea «дрыгается» и дублирует
    картинку), плавно проявляется только содержимое — через прозрачность."""

    FADE_MS = 150

    def __init__(self, title: str, content: QWidget, expanded: bool = False) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.header = _CollapseHeader(title, expanded)
        self.body = _ClipBody(content)
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        self._fade: QPropertyAnimation | None = None
        self.body.setFixedHeight(0)
        self.body.setVisible(False)
        self.header.toggled.connect(self._on_toggled)
        if expanded:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._on_toggled(True, animate=False))

    def _stop_fade(self) -> None:
        if self._fade is not None:
            self._fade.stop()
            self._fade = None
        if self.body.graphicsEffect() is not None:
            self.body.setGraphicsEffect(None)

    def _on_toggled(self, open_: bool, animate: bool = True) -> None:
        self._stop_fade()
        if not open_:
            self.body.setFixedHeight(0)
            self.body.setVisible(False)
            return
        target = self.body.measure()
        self.body.setFixedHeight(target)
        self.body.setVisible(True)
        self.body.content.setGeometry(0, 0, self.body.width(), self.body.natural)
        if not (motion.ENABLED and animate):
            return
        eff = QGraphicsOpacityEffect(self.body)
        eff.setOpacity(0.0)
        self.body.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(self.FADE_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(self._stop_fade)
        self._fade = anim
        anim.start()


# ───────────────────────── помощники сборки страниц ─────────────────────────
class Reveal(QWidget):
    """Плавно показывает и скрывает блок (например, панель «несохранённые изменения»).
    Анимируется ВЫСОТА контейнера, содержимое сохраняет натуральный размер и выезжает из-под края;
    позиции в раскладке не анимируются — наложений нет."""

    def __init__(self, content: QWidget) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.body = _ClipBody(content)
        lay.addWidget(self.body)
        self.body.setFixedHeight(0)
        self.body.setVisible(False)
        self._open = False
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(lambda v: self.body.setFixedHeight(int(v)))

    def is_open(self) -> bool:
        return self._open

    def set_open(self, open_: bool) -> None:
        if open_ == self._open:
            return
        self._open = open_
        self._anim.stop()
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        target = self.body.measure() if open_ else 0
        if open_:
            self.body.setVisible(True)
            self.body.content.setGeometry(0, 0, self.body.width(), self.body.natural)
        if not motion.ENABLED:
            self.body.setFixedHeight(target)
            self.body.setVisible(open_)
            return
        self._anim.setStartValue(self.body.height())
        self._anim.setEndValue(target)
        if not open_:
            self._anim.finished.connect(lambda: self.body.setVisible(False))
        self._anim.start()


from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem  # noqa: E402


def card(layout_cls=QVBoxLayout) -> tuple[QFrame, QVBoxLayout]:
    """Карточка (QFrame#card) с внутренней раскладкой. Возвращает (рамка, раскладка)."""
    frame = QFrame()
    frame.setObjectName("card")
    lay = layout_cls(frame)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(10)
    return frame, lay


def label(text: str, name: str = "") -> QLabel:
    """QLabel с objectName из словаря стилей: h1, h2, muted, mono, sectionLabel, cardTitle, fieldError."""
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    return w


def page_header(title: str, subtitle: str, *buttons: QPushButton) -> QHBoxLayout:
    """Заголовок экрана: h1 + muted-подзаголовок слева, кнопки справа."""
    row = QHBoxLayout()
    col = QVBoxLayout()
    col.setSpacing(2)
    col.addWidget(label(title, "h1"))
    col.addWidget(label(subtitle, "muted"))
    row.addLayout(col)
    row.addStretch()
    for b in buttons:
        row.addWidget(b)
    return row


def primary(text: str, icon: str | None = None) -> "FxButton":
    """Главная кнопка экрана (акцентная заливка). Не больше одной на экран."""
    b = FxButton(text)
    b.setObjectName("primary")
    if icon:
        b.setIcon(icons.icon(icon, color="accent_text"))
        b.setProperty("iconName", icon)
        b.setProperty("iconColor", "accent_text")
    return b


def icon_button(text: str, icon: str, variant: str = "") -> "FxButton":
    """Кнопка с иконкой. variant: '' (обычная) | 'primary' | 'danger' | 'pill' — это objectName FxButton."""
    b = FxButton(text)
    if variant:
        b.setObjectName(variant)
    color = {"primary": "accent_text", "danger": "danger"}.get(variant, "text_muted")
    b.setIcon(icons.icon(icon, color=color))
    b.setProperty("iconName", icon)
    b.setProperty("iconColor", color)     # appearance.apply перекрасит иконку при смене темы
    return b


def make_table(headers: list[str], rows: list[list[str]] | None = None) -> QTableWidget:
    """Таблица в стиле системы: без сетки, строки целиком, последняя колонка тянется."""
    rows = rows or []
    t = QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    header = t.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setStretchLastSection(True)
    t.verticalHeader().setDefaultSectionSize(44)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            t.setItem(r, c, QTableWidgetItem(value))
    return t


def refresh_icons(root: QWidget | None = None) -> None:
    """Перекрашивает иконки кнопок, созданных через icon_button()/primary(icon=...), под текущую тему."""
    app = QApplication.instance()
    widgets = root.findChildren(QAbstractButton) if root is not None else app.allWidgets()
    for w in widgets:
        name = w.property("iconName") if isinstance(w, QAbstractButton) else None
        if name:
            w.setIcon(icons.icon(name, color=w.property("iconColor") or "text_muted"))


class ElidedLabel(QLabel):
    """Однострочная подпись: длинный текст обрезается многоточием, полный текст — в подсказке."""

    def __init__(self, text: str = "", name: str = "") -> None:
        super().__init__()
        if name:
            self.setObjectName(name)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = str(text)
        super().setText(self._full)
        self.updateGeometry()
        self.update()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        shown = QFontMetrics(self.font()).elidedText(self._full, Qt.TextElideMode.ElideRight, self.width())
        p.drawText(self.rect(), int(self.alignment()) | int(Qt.AlignmentFlag.AlignVCenter), shown)


class ToolCard(QFrame):
    """Плитка MCP-инструмента: название, описание и краткий список параметров (рисуется токенами темы)."""

    def __init__(self, name: str, description: str, params: list[str], confirm: bool = False) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        title = ElidedLabel(name, "cardTitle")
        title.setToolTip(name)
        head.addWidget(title, 1)
        if confirm:
            head.addWidget(StatusBadge("Подтверждение", "warn"))
        lay.addLayout(head)
        text = " ".join((description or "").split())
        desc = QLabel(text if len(text) <= 240 else text[:237].rstrip() + "…")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        if text:
            desc.setToolTip(text)
        else:
            desc.setText("Без описания")
        lay.addWidget(desc)
        if params:
            shown = params[:6] + ([f"+{len(params) - 6}"] if len(params) > 6 else [])
            par = QLabel("  ".join(shown))
            par.setObjectName("mono")
            par.setWordWrap(True)
            par.setToolTip("Параметры (* — обязательные):\n" + "\n".join(params))
            lay.addWidget(par)
        else:
            none = QLabel("без параметров")
            none.setObjectName("mono")
            lay.addWidget(none)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = tokens()
        if not t:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(t["surface_alt"]))
        p.setPen(QPen(QColor(t["border"]), 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)


def tool_params(tool: dict) -> list[str]:
    """Краткий список параметров инструмента из JSON-схемы: «name: type», обязательные помечены *."""
    schema = tool.get("input_schema") or tool.get("inputSchema") or {}
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return []
    required = set(schema.get("required") or [])
    out = []
    for key, spec in props.items():
        kind = spec.get("type", "") if isinstance(spec, dict) else ""
        if isinstance(kind, list):
            kind = "|".join(str(k) for k in kind)
        out.append(f"{key}{'*' if key in required else ''}" + (f": {kind}" if kind else ""))
    return out
