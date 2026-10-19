"""Диалоги в стиле SnapMatch: замена QMessageBox / QInputDialog / QColorDialog и база для больших окон.

FxDialog — безрамочное окно с карточкой (скругление FRAME_RADIUS, рамка 1px, мягкая тень), своим заголовком
(логотип, название, только кнопка «закрыть»; перетаскивание за заголовок), затемнением родительского окна,
центрированием по родителю и коротким появлением (прозрачность ~130 мс; при motion.ENABLED=False — без анимации).
Esc = reject, Enter = основная кнопка.

Таблица замены (механическая):

    QMessageBox.question(self, T, X) == QMessageBox.StandardButton.Yes     ->  ask(self, T, X)
    QMessageBox.question(..., defaultButton=No)                           ->  ask(self, T, X, default="no")
    удаление/сброс/необратимое действие                                   ->  ask(self, T, X, yes="Удалить", danger=True)
    QMessageBox.question(..., Yes | No | Cancel)  (Yes/No/Cancel)        ->  ask3(self, T, X)  -> True | False | None
    QMessageBox.information(self, T, X)                                   ->  inform(self, T, X)
    QMessageBox.warning(self, T, X)                                       ->  warn(self, T, X)
    QMessageBox.critical(self, T, X)                                      ->  error(self, T, X)
    text, ok = QInputDialog.getText(self, T, L[, QLineEdit.Normal, D])    ->  text, ok = prompt_text(self, T, L, D)
    пароль: getText(..., QLineEdit.EchoMode.Password)                     ->  prompt_text(self, T, L, password=True)
    color = QColorDialog.getColor(QColor(c), self, T);                    ->  color = choose_color(self, QColor(c), T)
    if not color.isValid(): return                                            if color is None: return

Все функции блокирующие (exec) и принимают parent=None (тогда без затемнения, по центру экрана).
Тексты вида «Да/Нет/OK/Отмена» — по-русски, меняются параметрами yes/no/ok.

Как база для сложных окон (ModelDialog, PromptEditorDialog):

    class ModelDialog(FxDialog):
        def __init__(self, parent=None):
            super().__init__(parent, "Новая модель")
            self.resize_content(720, 680)          # размер КАРТОЧКИ (без полей под тень)
            lay = self.body                        # QVBoxLayout контентной области (поля 20/0/20/18)
            lay.addWidget(...)
            row = self.add_button_row(("Отмена", self.reject, ""), ("Сохранить", self.accept, "primary"))

self.accept()/reject()/exec()/result() работают как у QDialog; self.setWindowTitle(...) обновляет заголовок.
"""
import re
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QEvent, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from gui.design import icons, motion
from gui.design.shell import FRAME_RADIUS
from gui.design.tokens import COLOR_PRESETS, tokens
from gui.design.widgets import FxButton, IconTile, Swatch, WinButton, tint

SHADOW = 20            # поле вокруг карточки под тень, px
FADE_MS = 130
DIM_ALPHA = 0.5
_HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})$")


def _logo_path() -> str:
    try:
        from utils.resource_manager import get_resource_path
        p = get_resource_path("assets/icon3.png")
        if p and Path(p).exists():
            return str(p)
    except Exception:  # noqa: BLE001
        pass
    return str(Path(__file__).resolve().parents[2] / "assets" / "icon3.png")


class _Dim(QWidget):
    """Затемнение родительского окна: полупрозрачный оверлей поверх всего окна (скругление повторяет окно)."""

    def __init__(self, win: QWidget) -> None:
        super().__init__(win)
        self.win = win
        self.level = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        win.installEventFilter(self)
        self._fit()

    def _fit(self) -> None:
        self.setGeometry(self.win.rect())
        self.raise_()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.win and event.type() in (QEvent.Type.Resize, QEvent.Type.ChildAdded):
            self._fit()
        return False

    def set_level(self, v: float) -> None:
        self.level = v
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if self.level <= 0:
            return
        radius = 0
        w = self.win
        if bool(w.windowFlags() & Qt.WindowType.FramelessWindowHint) and not w.isMaximized() and not w.isFullScreen():
            radius = FRAME_RADIUS
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), radius, radius)
        p.fillPath(path, QColor(0, 0, 0, int(255 * DIM_ALPHA * self.level)))


class _DragBar(QWidget):
    """Заголовок диалога: перетаскивание окна через startSystemMove (работает и на Wayland)."""

    def __init__(self, dialog: QDialog) -> None:
        super().__init__()
        self.dlg = dialog
        self.setFixedHeight(40)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.dlg.windowHandle():
            self.dlg.windowHandle().startSystemMove()
        super().mousePressEvent(event)


class _SolidDanger(FxButton):
    """Красная кнопка опасного действия (сплошная заливка)."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setObjectName("dangerSolid")

    def paintEvent(self, event) -> None:  # noqa: N802
        t = tokens()
        if t:
            from gui.design.widgets import lerp
            base = QColor(t["danger"])
            bg = lerp(base, base.lighter(115), self._hover.value)
            if self.isDown():
                bg = bg.darker(115)
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(bg)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
            p.end()
        QPushButton.paintEvent(self, event)    # только текст/иконка, без отрисовки FxButton


class FxDialog(QDialog):
    """Базовый безрамочный диалог. Контент кладётся в self.body (QVBoxLayout)."""

    def __init__(self, parent: QWidget | None = None, title: str = "SnapMatch", *, closable: bool = True) -> None:
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("fxDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self._dim: _Dim | None = None
        self._fade: QVariantAnimation | None = None
        self._shown_once = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        self.card = QFrame()
        self.card.setObjectName("fxDialogCard")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(SHADOW * 1.6)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        root = QVBoxLayout(self.card)
        root.setContentsMargins(1, 1, 1, 1)      # внутри рамки 1px
        root.setSpacing(0)

        self.titlebar = _DragBar(self)
        bar = QHBoxLayout(self.titlebar)
        bar.setContentsMargins(14, 0, 6, 0)
        bar.setSpacing(8)
        self.logo = QLabel()
        self.logo.setFixedSize(20, 20)
        pm = QPixmap(_logo_path())
        if not pm.isNull():
            dpr = self.devicePixelRatioF() or 1.0
            pm = pm.scaled(int(20 * dpr), int(20 * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self.logo.setPixmap(pm)
        bar.addWidget(self.logo)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("dlgTitle")
        bar.addWidget(self.title_label)
        bar.addStretch()
        self.btn_close = WinButton("mdi6.window-close", danger=True)
        self.btn_close.setToolTip("Закрыть")
        self.btn_close.clicked.connect(self.reject)
        self.btn_close.setVisible(closable)
        bar.addWidget(self.btn_close)
        root.addWidget(self.titlebar)

        host = QWidget()
        self.body = QVBoxLayout(host)
        self.body.setContentsMargins(20, 2, 20, 18)
        self.body.setSpacing(12)
        root.addWidget(host, 1)
        super().setWindowTitle(title)

    # ── API для наследников ──
    def setWindowTitle(self, title: str) -> None:  # noqa: N802
        super().setWindowTitle(title)
        if hasattr(self, "title_label"):
            self.title_label.setText(title)

    def resize_content(self, width: int, height: int) -> None:
        """Размер самой карточки; поля под тень добавляются автоматически."""
        self.resize(width + 2 * SHADOW, height + 2 * SHADOW)

    def add_button_row(self, *specs: tuple[str, object, str], default: int | None = None) -> list[QPushButton]:
        """Ряд кнопок справа внизу. spec = (текст, слот, вариант) где вариант: '' | 'primary' | 'danger'.
        'danger' = сплошная красная. default — индекс кнопки по Enter (по умолчанию первая primary/danger)."""
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch()
        buttons: list[QPushButton] = []
        for text, slot, variant in specs:
            if variant == "danger":
                b: QPushButton = _SolidDanger(text)
            else:
                b = FxButton(text)
                if variant:
                    b.setObjectName(variant)
            b.setMinimumWidth(96)
            b.setAutoDefault(False)
            b.clicked.connect(slot)
            row.addWidget(b)
            buttons.append(b)
        if default is None:
            default = next((i for i, (_t, _s, v) in enumerate(specs) if v in ("primary", "danger")), None)
        if default is not None:
            buttons[default].setDefault(True)
            buttons[default].setFocus()
        self.body.addLayout(row)
        return buttons

    # ── показ ──
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._center_on_parent()
        if self._shown_once:
            return
        self._shown_once = True
        win = self.parentWidget().window() if self.parentWidget() is not None else None
        if win is not None and win.isVisible():
            self._dim = _Dim(win)
            self._dim.show()
        if motion.ENABLED:
            self.setWindowOpacity(0.0)
            anim = QVariantAnimation(self)
            anim.setDuration(FADE_MS)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.valueChanged.connect(self._on_fade)
            anim.start()
            self._fade = anim
        else:
            self._on_fade(1.0)

    def _on_fade(self, v) -> None:
        v = float(v)
        self.setWindowOpacity(v)
        if self._dim is not None:
            self._dim.set_level(v)

    def _center_on_parent(self) -> None:
        par = self.parentWidget()
        if par is not None:
            center = par.window().frameGeometry().center()
        else:
            screen = QGuiApplication.primaryScreen()
            center = screen.availableGeometry().center() if screen else self.frameGeometry().center()
        geo = self.frameGeometry()
        geo.moveCenter(center)
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            geo.moveLeft(max(area.left(), min(geo.left(), area.right() - geo.width())))
            geo.moveTop(max(area.top(), min(geo.top(), area.bottom() - geo.height())))
        self.move(geo.topLeft())

    def hideEvent(self, event) -> None:  # noqa: N802
        if self._dim is not None:
            self._dim.hide()
            self._dim.deleteLater()
            self._dim = None
        super().hideEvent(event)


# ───────────────────────── сообщения ─────────────────────────
_KINDS = {
    "question": ("mdi6.help-circle-outline", "ok"),
    "info": ("mdi6.information-outline", "info"),
    "warn": ("mdi6.alert-outline", "warn"),
    "error": ("mdi6.alert-octagon-outline", "error"),
}


class _MessageDialog(FxDialog):
    def __init__(self, parent, title: str, text: str, kind: str) -> None:
        super().__init__(parent, title)
        icon_name, tone = _KINDS[kind]
        self.setMinimumWidth(420 + 2 * SHADOW)
        row = QHBoxLayout()
        row.setSpacing(14)
        tile = IconTile(icon_name, tone, 40)
        row.addWidget(tile, 0, Qt.AlignmentFlag.AlignTop)
        self.text_label = QLabel(text)
        self.text_label.setObjectName("dlgText")
        self.text_label.setWordWrap(True)
        self.text_label.setMaximumWidth(460)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.text_label, 1, Qt.AlignmentFlag.AlignVCenter)
        self.body.addLayout(row)
        self.body.addSpacing(6)
        self.result_value: object = None

    def finish(self, value: object) -> None:
        self.result_value = value
        self.accept()


def _run_message(parent, title, text, kind, buttons, default=None):
    """buttons: [(текст, значение, вариант)], последняя «отрицательная» отмена = reject → None."""
    dlg = _MessageDialog(parent, title, text, kind)
    specs = [(label, (lambda _=False, v=value: dlg.finish(v)), variant) for label, value, variant in buttons]
    dlg.add_button_row(*specs, default=default)
    dlg.adjustSize()
    dlg.exec()
    return dlg.result_value


def ask(parent, title: str, text: str, yes: str = "Да", no: str = "Нет", danger: bool = False,
        default: str | None = None) -> bool:
    """Вопрос Да/Нет -> True/False (Esc и крестик = False).
    danger=True: кнопка подтверждения красная, по Enter срабатывает «no». default='yes'|'no' задаёт кнопку явно."""
    default = default or ("no" if danger else "yes")
    dlg_buttons = [(no, False, ""), (yes, True, "danger" if danger else "primary")]
    return bool(_run_message(parent, title, text, "warn" if danger else "question", dlg_buttons,
                             default=0 if default == "no" else 1))


def ask3(parent, title: str, text: str, yes: str = "Да", no: str = "Нет", cancel: str = "Отмена"):
    """Вопрос Да/Нет/Отмена -> True | False | None (Esc/крестик/«Отмена» = None)."""
    return _run_message(parent, title, text, "question",
                        [(cancel, None, ""), (no, False, ""), (yes, True, "primary")], default=2)


def inform(parent, title: str, text: str, ok: str = "OK") -> None:
    _run_message(parent, title, text, "info", [(ok, None, "primary")])


def warn(parent, title: str, text: str, ok: str = "OK") -> None:
    _run_message(parent, title, text, "warn", [(ok, None, "primary")])


def error(parent, title: str, text: str, ok: str = "OK") -> None:
    _run_message(parent, title, text, "error", [(ok, None, "primary")])


# ───────────────────────── ввод текста ─────────────────────────
def prompt_text(parent, title: str, label: str, default: str = "", *, placeholder: str = "",
                password: bool = False, ok: str = "OK", cancel: str = "Отмена") -> tuple[str, bool]:
    """Как QInputDialog.getText: (текст, нажали_OK). При отмене текст — пустая строка."""
    dlg = FxDialog(parent, title)
    dlg.setMinimumWidth(400 + 2 * SHADOW)
    lab = QLabel(label)
    lab.setObjectName("dlgText")
    lab.setWordWrap(True)
    dlg.body.addWidget(lab)
    edit = QLineEdit(default)
    edit.setPlaceholderText(placeholder)
    if password:
        edit.setEchoMode(QLineEdit.EchoMode.Password)
    dlg.body.addWidget(edit)
    dlg.body.addSpacing(6)
    dlg.add_button_row((cancel, dlg.reject, ""), (ok, dlg.accept, "primary"))
    edit.setFocus()
    edit.selectAll()
    dlg.adjustSize()
    accepted = dlg.exec() == QDialog.DialogCode.Accepted
    return (edit.text(), True) if accepted else ("", False)


# ───────────────────────── выбор цвета ─────────────────────────
class _ColorPreview(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.color = QColor("transparent")
        self.setFixedSize(44, 34)

    def set_color(self, c: QColor) -> None:
        self.color = c
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(self.color if self.color.isValid() else tint(t.get("text_muted", "gray"), 0.2))
        p.setPen(QColor(t.get("border", "gray")))
        p.drawRoundedRect(r, 8, 8)


def _parse_hex(text: str) -> QColor | None:
    m = _HEX_RE.match(text.strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return QColor("#" + h)


def choose_color(parent, initial: QColor | str | None = None, title: str = "Выбор цвета") -> QColor | None:
    """Выбор цвета: палитра готовых цветов + поле HEX. Возвращает QColor или None при отмене."""
    start = QColor(initial) if initial is not None else QColor(tokens().get("accent", "#000000"))
    if not start.isValid():
        start = QColor(tokens().get("accent", "#000000"))
    dlg = FxDialog(parent, title)
    dlg.setMinimumWidth(420 + 2 * SHADOW)
    lab = QLabel("Выберите цвет из палитры или введите HEX")
    lab.setObjectName("muted")
    dlg.body.addWidget(lab)

    grid = QGridLayout()
    grid.setHorizontalSpacing(2)
    grid.setVerticalSpacing(2)
    swatches: dict[str, Swatch] = {}
    cols = 8
    for i, hex_color in enumerate(COLOR_PRESETS):
        sw = Swatch(hex_color, hex_color, hex_color)
        swatches[hex_color.upper()] = sw
        grid.addWidget(sw, i // cols, i % cols)
    dlg.body.addLayout(grid)

    row = QHBoxLayout()
    row.setSpacing(10)
    preview = _ColorPreview()
    row.addWidget(preview)
    edit = QLineEdit(start.name().upper())
    edit.setObjectName("mono")
    edit.setMaxLength(7)
    edit.setPlaceholderText("#RRGGBB")
    row.addWidget(edit, 1)
    dlg.body.addLayout(row)
    dlg.body.addSpacing(4)
    btn_cancel, btn_ok = dlg.add_button_row(("Отмена", dlg.reject, ""), ("Выбрать", dlg.accept, "primary"))

    state = {"color": start}

    def on_text(text: str) -> None:
        c = _parse_hex(text)
        bad = c is None
        edit.setProperty("invalid", bad)
        edit.style().unpolish(edit)
        edit.style().polish(edit)
        btn_ok.setEnabled(not bad)
        if c is not None:
            state["color"] = c
            preview.set_color(c)
            for key, sw in swatches.items():
                sw.set_selected(key == c.name().upper())

    def on_swatch(key: str) -> None:
        edit.setText(key.upper())

    for sw in swatches.values():
        sw.clicked.connect(on_swatch)
    edit.textChanged.connect(on_text)
    on_text(edit.text())
    dlg.adjustSize()
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return QColor(state["color"])
    return None
