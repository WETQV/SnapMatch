"""Оформление приложения: настройки (ui_theme / ui_accent / ui_frameless / ui_animations),
применение (QPalette + QSS + токены в app.property('tokens')), реакция на смену системной темы,
загрузка шрифтов и виджет AppearanceCard («Оформление») для экрана «Доп. настройки».

Точка входа в main.py:
    appearance.load_fonts(app); ctrl = appearance.init(app); ctrl.apply()
Остальной код получает контроллер через appearance.controller() и подписывается на его сигналы:
    changed(dict)            — тема/акцент применены, пришли новые токены;
    frameless_changed(bool)  — пользователь включил/выключил собственную рамку окна.
"""
import os
import re

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PyQt6.QtWidgets import QApplication, QColorDialog, QFrame, QHBoxLayout, QWidget

from gui.design import icons, motion
from gui.design.tokens import ACCENT_PRESETS as PRESETS, BRAND_ACCENT, build_qss, make_tokens
from gui.design.widgets import (
    FxButton, GlowRoot, IconTile, ServerCard, StatusBadge, Swatch, Switch, SwitchRow, ThemeCard, WinButton,
    card, label, refresh_icons,
)
from utils.logger import setup_logger
from utils.resource_manager import get_resource_path

logger = setup_logger(__name__)

DEFAULTS = {"ui_theme": "dark", "ui_accent": "brand", "ui_frameless": False, "ui_animations": True}
THEMES = (("system", "Системная"), ("dark", "Тёмная"), ("light", "Светлая"), ("oled", "OLED"))
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_REPAINT = (GlowRoot, StatusBadge, IconTile, ServerCard, WinButton, Switch, FxButton, ThemeCard, Swatch)


# ───────────────────────── шрифты ─────────────────────────
def load_fonts(app: QApplication | None = None) -> bool:
    """Регистрирует Manrope и JetBrains Mono из статических TTF (переменные шрифты Qt читает только как
    ExtraLight) и ставит Manrope шрифтом приложения. False, если каталог шрифтов не найден."""
    fonts_dir = get_resource_path(os.path.join("gui", "design", "fonts"))
    if not fonts_dir or not os.path.isdir(fonts_dir):
        logger.warning("Каталог шрифтов дизайн-системы не найден — используются системные шрифты")
        return False
    loaded = 0
    for fname in sorted(os.listdir(fonts_dir)):
        if fname.lower().endswith(".ttf") and QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fname)) >= 0:
            loaded += 1
    app = app or QApplication.instance()
    if app is not None and loaded:
        app.setFont(QFont("Manrope", 10))
    return loaded > 0


# ───────────────────────── хранение настроек ─────────────────────────
def normalize(raw: dict) -> dict:
    """Приводит словарь настроек к допустимым значениям (мусор заменяется значениями по умолчанию)."""
    theme = raw.get("ui_theme")
    accent = raw.get("ui_accent")
    if not (isinstance(accent, str) and (accent in ("system", "brand") or _HEX_RE.match(accent))):
        accent = DEFAULTS["ui_accent"]
    return {
        "ui_theme": theme if theme in dict(THEMES) else DEFAULTS["ui_theme"],
        "ui_accent": accent,
        "ui_frameless": bool(raw.get("ui_frameless", DEFAULTS["ui_frameless"])),
        "ui_animations": bool(raw.get("ui_animations", DEFAULTS["ui_animations"])),
    }


def load_settings() -> dict:
    """Читает настройки оформления из config.json (через settings_manager)."""
    from config.settings import settings_manager
    return normalize(settings_manager.get_settings())


def save_settings(**changes) -> None:
    """Сохраняет настройки оформления. oled_mode держим в синхроне для старого кода."""
    from config.settings import settings_manager
    current = load_settings()
    current.update(changes)
    current = normalize(current)
    current["oled_mode"] = current["ui_theme"] == "oled"
    settings_manager.update_settings(**current)


# ───────────────────────── контроллер ─────────────────────────
class AppearanceController(QObject):
    """Применяет оформление. Один экземпляр на приложение (appearance.controller())."""

    changed = pyqtSignal(dict)
    frameless_changed = pyqtSignal(bool)

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.app = app
        # системный акцент запоминаем ДО того, как приложение переопределит палитру
        self.system_accent = app.palette().color(QPalette.ColorRole.Highlight).name()
        self.settings = load_settings()
        self.tokens: dict = {}
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_system_scheme)

    # ── системная тема ──
    @staticmethod
    def system_mode() -> str:
        dark = QGuiApplication.styleHints().colorScheme() != Qt.ColorScheme.Light
        return "dark" if dark else "light"

    def effective_mode(self) -> str:
        theme = self.settings["ui_theme"]
        return self.system_mode() if theme == "system" else theme

    def accent_hex(self) -> str | None:
        accent = self.settings["ui_accent"]
        if accent == "brand":
            return None
        return self.system_accent if accent == "system" else accent

    def system_info(self) -> str:
        scheme = "тёмная" if self.system_mode() == "dark" else "светлая"
        return f"Система: тема {scheme}, акцент {self.system_accent}. Сейчас показана: {self.effective_mode()}"

    def _on_system_scheme(self, *_args) -> None:
        if self.settings["ui_theme"] == "system":
            self.apply()

    # ── применение ──
    def apply(self) -> dict:
        """Строит токены, палитру и QSS и применяет их ко всему приложению. Возвращает токены."""
        t = make_tokens(self.effective_mode(), self.accent_hex())
        self.tokens = t
        app = self.app
        app.setProperty("tokens", t)
        pal = QPalette()
        for role, key in ((QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.WindowText, "text"),
                          (QPalette.ColorRole.Base, "input_bg"), (QPalette.ColorRole.AlternateBase, "surface_alt"),
                          (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "surface_alt"),
                          (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.ToolTipBase, "surface"),
                          (QPalette.ColorRole.ToolTipText, "text"), (QPalette.ColorRole.Highlight, "accent"),
                          (QPalette.ColorRole.HighlightedText, "accent_text"),
                          (QPalette.ColorRole.PlaceholderText, "text_muted")):
            pal.setColor(role, QColor(t[key]))
        pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t["text_muted"]))
        pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t["text_muted"]))
        pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(t["text_muted"]))
        app.setPalette(pal)
        motion.set_enabled(self.settings["ui_animations"])
        app.setStyleSheet(build_qss(
            t,
            check_icon=icons.png_path("mdi6.check-bold", t["accent_text"], 14),
            chevron_up=icons.png_path("mdi6.chevron-up", t["text_muted"], 12),
            chevron_down=icons.png_path("mdi6.chevron-down", t["text_muted"], 12),
        ))
        refresh_icons()
        for w in app.allWidgets():
            if isinstance(w, _REPAINT):
                w.update()
        self.changed.emit(t)
        return t

    # ── изменение настроек (применяется сразу и сохраняется) ──
    def _set(self, **changes) -> None:
        self.settings = normalize({**self.settings, **changes})
        try:
            save_settings(**self.settings)
        except Exception as exc:  # noqa: BLE001 - UI не должен падать из-за записи конфига
            logger.error("Не удалось сохранить оформление: %s", exc)

    def set_theme(self, theme: str) -> None:
        self._set(ui_theme=theme)
        self.apply()

    def set_accent(self, accent: str) -> None:
        self._set(ui_accent=accent)
        self.apply()

    def set_animations(self, on: bool) -> None:
        self._set(ui_animations=bool(on))
        self.apply()

    def set_frameless(self, on: bool) -> None:
        self._set(ui_frameless=bool(on))
        self.frameless_changed.emit(bool(on))

    def reset(self) -> None:
        """Сброс темы и акцента (рамку и анимации не трогаем)."""
        self._set(ui_theme=DEFAULTS["ui_theme"], ui_accent=DEFAULTS["ui_accent"])
        self.apply()


_controller: AppearanceController | None = None


def init(app: QApplication | None = None) -> AppearanceController:
    """Создаёт контроллер (однократно): стиль Fusion + запоминание системного акцента."""
    global _controller
    if _controller is None:
        app = app or QApplication.instance()
        app.setStyle("Fusion")
        _controller = AppearanceController(app)
    return _controller


def controller() -> AppearanceController:
    return _controller or init()


# ───────────────────────── карточка «Оформление» ─────────────────────────
class AppearanceCard(QFrame):
    """Карточка «Оформление»: тема (ThemeCard ×4), акцент (Swatch), собственная рамка, анимации.
    Изменения применяются сразу и сохраняются в config.json. notify(text) — необязательный показ тоста."""

    def __init__(self, notify=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.notify = notify
        self.ctrl = controller()
        frame, lay = card()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(label("Оформление", "h2"))
        head.addStretch()
        reset = FxButton("Сбросить")
        reset.setToolTip("Сбросить оформление\nВернёт тёмную тему и фирменный акцент.")
        reset.clicked.connect(self._reset)
        head.addWidget(reset)
        lay.addLayout(head)
        self.info = label("", "muted")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        lay.addWidget(label("ТЕМА", "sectionLabel"))
        row = QHBoxLayout()
        row.setSpacing(12)
        self.theme_cards: dict[str, ThemeCard] = {}
        for key, title in THEMES:
            tc = ThemeCard(key, title, make_tokens("dark"))
            tc.clicked.connect(self._pick_theme)
            row.addWidget(tc)
            self.theme_cards[key] = tc
        row.addStretch()
        lay.addLayout(row)

        lay.addWidget(label("АКЦЕНТНЫЙ ЦВЕТ", "sectionLabel"))
        srow = QHBoxLayout()
        srow.setSpacing(8)
        self.swatches: dict[str, Swatch] = {}
        specs = [("system", self.ctrl.system_accent, "Системный\nЦвет из настроек вашей ОС", "mdi6.monitor"),
                 ("brand", BRAND_ACCENT, "Фирменный\nИзумрудный цвет SnapMatch", None)]
        specs += [(hex_, hex_, name, None) for hex_, name in PRESETS]
        specs += [("custom", None, "Свой цвет\nОткроет выбор цвета", "mdi6.plus")]
        for key, color, tip, icon in specs:
            sw = Swatch(key, color, tip, icon)
            sw.clicked.connect(self._pick_accent)
            srow.addWidget(sw)
            self.swatches[key] = sw
        self.accent_label = label("", "muted")
        srow.addSpacing(10)
        srow.addWidget(self.accent_label)
        srow.addStretch()
        lay.addLayout(srow)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        lay.addWidget(divider)
        self.frameless = SwitchRow("Собственная рамка окна — заголовок и кнопки окна в стиле приложения")
        self.frameless.toggled.connect(self._toggle_frameless)
        lay.addWidget(self.frameless)
        self.motion = SwitchRow("Анимации интерфейса")
        self.motion.toggled.connect(self._toggle_motion)
        lay.addWidget(self.motion)

        self.ctrl.changed.connect(self._refresh)     # смена системной темы тоже отражается в карточке
        self._refresh()

    # ── выбор ──
    def _say(self, text: str) -> None:
        if self.notify:
            self.notify(text)

    def _pick_theme(self, key: str) -> None:
        self.ctrl.set_theme(key)
        self._say(f"Тема: {dict(THEMES)[key]}")

    def _pick_accent(self, key: str) -> None:
        if key == "custom":
            start = self.ctrl.settings["ui_accent"]
            start = start if _HEX_RE.match(start) else self.ctrl.tokens.get("accent", BRAND_ACCENT)
            color = QColorDialog.getColor(QColor(start), self, "Цвет акцента")
            if not color.isValid():
                return
            key = color.name()
        self.ctrl.set_accent(key)
        self._say(f"Акцент: {self._accent_name()}")

    def _toggle_frameless(self, on: bool) -> None:
        self.ctrl.set_frameless(on)
        self._say("Своя рамка включена" if on else "Системная рамка включена")

    def _toggle_motion(self, on: bool) -> None:
        self.ctrl.set_animations(on)

    def _reset(self) -> None:
        self.ctrl.reset()
        self._say("Оформление сброшено")

    # ── отображение ──
    def _selected_accent_key(self) -> str:
        accent = self.ctrl.settings["ui_accent"]
        if accent in ("system", "brand"):
            return accent
        return accent.upper() if accent.upper() in self.swatches else "custom"

    def _accent_name(self) -> str:
        key = self._selected_accent_key()
        names = {"system": "Системный", "brand": "Фирменный", "custom": "Свой"}
        names.update({h: n for h, n in PRESETS})
        return names.get(key, "Свой")

    def _refresh(self, *_args) -> None:
        s = self.ctrl.settings
        accent = self.ctrl.accent_hex() or BRAND_ACCENT
        for key, tc in self.theme_cards.items():
            tc.set_preview(make_tokens(self.ctrl.system_mode() if key == "system" else key, accent))
            tc.set_selected(key == s["ui_theme"])
        sel = self._selected_accent_key()
        self.swatches["custom"].set_color(s["ui_accent"] if sel == "custom" else None)
        for key, sw in self.swatches.items():
            sw.set_selected(key == sel)
        self.accent_label.setText(f"{self._accent_name()}  ·  {self.ctrl.accent_hex() or BRAND_ACCENT}")
        self.info.setText(f"Изменения применяются сразу, сохранять не нужно. {self.ctrl.system_info()}")
        for sw_row, value in ((self.frameless, s["ui_frameless"]), (self.motion, s["ui_animations"])):
            if sw_row.isChecked() != value:
                sw_row.switch.blockSignals(True)
                sw_row.setChecked(value)
                sw_row.switch.blockSignals(False)
                sw_row.switch._pos.value = 1.0 if value else 0.0
                sw_row.switch.update()
