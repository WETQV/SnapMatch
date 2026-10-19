# gui/admin_panel/ui_common.py
"""Общие помощники для экранов нового интерфейса (без цветов и стилей: всё берётся из gui.design)."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from gui.design import StatusBadge, label


class BadgeSlot(QWidget):
    """Контейнер под StatusBadge: StatusBadge не меняет текст на лету, поэтому бейдж пересоздаётся."""

    def __init__(self, text: str = "", kind: str = "idle", pulse: bool | None = False) -> None:
        super().__init__()
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._badge: StatusBadge | None = None
        self._pulse = pulse
        self.set(text, kind)

    def set(self, text: str, kind: str) -> None:
        if self._badge is not None and self._badge.text == text and self._badge.kind == kind:
            return
        if self._badge is not None:
            self._lay.removeWidget(self._badge)
            self._badge.deleteLater()
        self._badge = StatusBadge(text, kind, pulse=self._pulse)
        self._lay.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    @property
    def badge(self) -> "StatusBadge | None":
        return self._badge


def vertical_scroll(content: QWidget) -> QScrollArea:
    """Прокрутка только по вертикали: содержимое подстраивается под ширину окна, горизонтальной полосы нет."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    return scroll


def field(caption: str, widget: QWidget, tip: str = "") -> QVBoxLayout:
    """Поле с подписью над ним (sectionLabel). Подсказка переносится и на подпись."""
    col = QVBoxLayout()
    col.setSpacing(6)
    cap = label(caption, "sectionLabel")
    col.addWidget(cap)
    col.addWidget(widget)
    if tip:
        cap.setToolTip(tip)
    return col


def shrinkable(combo):
    """Выпадающий список не диктует ширину по самому длинному пункту — сжимается вместе с раскладкой."""
    from PyQt6.QtWidgets import QComboBox
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(6)
    return combo
