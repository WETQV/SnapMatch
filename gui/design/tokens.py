"""Токены дизайн-системы SnapMatch и единый QSS-шаблон.

Принципы:
  * сдержанная палитра: нейтральные поверхности + ОДИН акцент (цвета статусов — только для статусов);
  * без градиентов и «свечения»: глубина — через уровни поверхностей, тонкие линии и анимацию;
  * режимы: системная / тёмная / светлая / OLED; акцент: системный / фирменный / свой;
  * hex-цвета допускаются ТОЛЬКО в этом файле. Остальной код берёт цвета из tokens()/QSS по objectName.
"""
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

BRAND_ACCENT = "#22C58B"

# Общие для всех тем цвета «поверх акцента/на тёмном»: ручка переключателя, красная кнопка закрытия окна.
_COMMON = {"knob": "#FFFFFF", "win_close": "#E5484D"}

DARK = {
    "bg": "#0E1015", "surface": "#151821", "surface_alt": "#1B1F2A", "border": "#272C39",
    "text": "#E7EAF1", "text_muted": "#8C95A8", "input_bg": "#10131A",
    "danger": "#F26B67", "warning": "#E5B34A", "info": "#6DA7F2",
    "hover_fill": "rgba(255, 255, 255, 0.045)", "is_dark": True,
}
OLED = {
    "bg": "#000000", "surface": "#08090B", "surface_alt": "#101216", "border": "#1D2026",
    "text": "#E7EAF1", "text_muted": "#80899B", "input_bg": "#050607",
    "danger": "#F26B67", "warning": "#E5B34A", "info": "#6DA7F2",
    "hover_fill": "rgba(255, 255, 255, 0.04)", "is_dark": True,
}
LIGHT = {
    "bg": "#F3F5F9", "surface": "#FFFFFF", "surface_alt": "#EEF1F6", "border": "#DCE1EA",
    "text": "#161B2B", "text_muted": "#66718A", "input_bg": "#FFFFFF",
    "danger": "#D6403C", "warning": "#B9780F", "info": "#2477E0",
    "hover_fill": "rgba(30, 45, 90, 0.05)", "is_dark": False,
}
MODES = {"dark": DARK, "oled": OLED, "light": LIGHT}

RADIUS = 12
FONT_UI = '"Manrope", "Inter", "Segoe UI", "Noto Sans", "Ubuntu", sans-serif'
FONT_MONO = '"JetBrains Mono", "DejaVu Sans Mono", "Consolas", monospace'


def rgba(hex_color: str, alpha: float) -> str:
    """8-значный hex в Qt — это #AARRGGBB, поэтому прозрачность задаём через rgba()."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def derive_accent(hex_color: str, dark: bool) -> dict:
    """Из одного цвета получаем акцент, наведение и читаемый цвет текста на нём."""
    c = QColor(hex_color)
    h, s, l, _a = c.getHslF()
    if dark:
        l = min(max(l, 0.50), 0.66)       # на тёмном фоне акцент не должен быть тусклым
    else:
        l = min(max(l, 0.30), 0.46)       # на светлом — не должен быть бледным
    base = QColor.fromHslF(max(h, 0.0), min(max(s, 0.45), 0.9), l)   # у серого h == -1
    hover = QColor.fromHslF(max(h, 0.0), base.saturationF(), min(l + 0.07, 0.8))
    luminance = 0.2126 * base.redF() + 0.7152 * base.greenF() + 0.0722 * base.blueF()
    return {
        "accent": base.name(),
        "accent_hover": hover.name(),
        "accent_text": "#06110C" if luminance > 0.45 else "#FFFFFF",
    }


def make_tokens(mode: str, accent_hex: str | None = None) -> dict:
    """Полный набор токенов для режима ('dark' | 'light' | 'oled') и акцента (hex или None = фирменный)."""
    t = dict(MODES.get(mode, DARK))
    t.update(_COMMON)
    t.update(derive_accent(accent_hex or BRAND_ACCENT, t["is_dark"]))
    return t


def tokens() -> dict:
    """Текущие токены приложения (их кладёт appearance.apply в app.property('tokens'))."""
    app = QApplication.instance()
    return (app.property("tokens") if app is not None else None) or {}


def build_qss(t: dict, check_icon: str = "", chevron_up: str = "", chevron_down: str = "") -> str:
    """Собирает QSS приложения. Иконки-картинки (галочка, шевроны) передаются путями к PNG."""
    r = RADIUS
    acc = t["accent"]
    check_rule = f"image: url({check_icon});" if check_icon else ""
    up_rule = f"image: url({chevron_up});" if chevron_up else ""
    down_rule = f"image: url({chevron_down});" if chevron_down else ""
    sel = rgba(acc, 0.15)
    row_sel = rgba(acc, 0.10)
    return f"""
* {{ font-family: {FONT_UI}; font-size: 13px; }}
QWidget {{ background: transparent; color: {t['text']}; }}
QMainWindow {{ background: transparent; }}
QDialog, QMessageBox, QInputDialog, QFileDialog {{ background: {t['surface']}; }}
QMessageBox QLabel, QInputDialog QLabel {{ color: {t['text']}; }}

/* ── Боковая панель и навигация ───────────────────── */
QWidget#sidebar {{ background: transparent; }}
QLabel#brand {{ font-size: 18px; font-weight: 800; padding: 4px 6px; }}
QListWidget#nav {{ background: transparent; border: none; outline: none; }}
QListWidget#nav::item {{ padding: 11px 14px; margin: 2px 0; border-radius: {r - 2}px; color: {t['text_muted']}; font-weight: 600; }}
QListWidget#nav::item:hover {{ background: {t['hover_fill']}; color: {t['text']}; }}
QListWidget#nav::item:selected {{ background: transparent; color: {t['text']}; }}
QFrame#navHighlight {{ background: {rgba(acc, 0.14)}; border: 1px solid {rgba(acc, 0.34)}; border-radius: {r - 2}px; }}
QFrame#tabHighlight {{ background: {rgba(acc, 0.14)}; border: 1px solid {rgba(acc, 0.34)}; border-radius: {r - 3}px; }}
QFrame#popupPanel {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: {r}px; }}
QWidget#titlebar {{ background: transparent; }}

/* ── Карточки и текст ─────────────────────────────── */
QFrame#card, QFrame#statTile {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: {r + 2}px; }}
QFrame#rowCard {{ background: {t['surface_alt']}; border: 1px solid {t['border']}; border-radius: {r - 2}px; }}
QLabel#statValue {{ font-family: {FONT_MONO}; font-size: 26px; font-weight: 700; }}
QLabel#h1 {{ font-size: 24px; font-weight: 800; }}
QLabel#h2 {{ font-size: 14px; font-weight: 700; }}
QLabel#muted {{ color: {t['text_muted']}; font-size: 12px; }}
QLabel#cardTitle {{ font-size: 14px; font-weight: 700; }}
QLabel#mono {{ font-family: {FONT_MONO}; font-size: 11px; color: {t['text_muted']}; }}
QLabel#sectionLabel {{ color: {t['text_muted']}; font-size: 11px; font-weight: 700; letter-spacing: 1.2px; }}
QFrame#divider {{ background: {t['border']}; max-height: 1px; border: none; }}

/* ── Кнопки ───────────────────────────────────────────
   Обычный QPushButton (старые экраны) получает запасной стиль: фон, рамка, наведение.
   Фирменная FxButton помечена свойством fx=true: фон и рамку она рисует сама (плавное наведение),
   поэтому для неё QSS оставляет только размеры и цвет текста. */
QPushButton {{
    background: {t['surface_alt']}; border: 1px solid {t['border']}; border-radius: 9px;
    padding: 7px 14px; min-height: 18px; font-weight: 600;
}}
QPushButton:hover {{ background: {t['hover_fill']}; border-color: {t['text_muted']}; }}
QPushButton:pressed {{ background: {sel}; border-color: {acc}; }}
QPushButton:checked {{ background: {sel}; border-color: {acc}; color: {acc}; }}
QPushButton:default {{ border-color: {acc}; }}
QPushButton:disabled {{ color: {t['text_muted']}; background: transparent; }}
QPushButton[accessibleName="spinbox_up"], QPushButton[accessibleName="spinbox_down"] {{
    padding: 2px 4px; border-radius: 4px; min-width: 20px; min-height: 12px;
}}
QPushButton[fx="true"], QPushButton[fx="true"]:hover, QPushButton[fx="true"]:pressed,
QPushButton[fx="true"]:checked, QPushButton[fx="true"]:default, QPushButton[fx="true"]:disabled {{
    background: transparent; border: none; border-radius: 9px; padding: 8px 15px; min-height: 18px;
}}
QPushButton[fx="true"]:disabled {{ color: {t['text_muted']}; }}
QPushButton#primary {{ color: {t['accent_text']}; font-weight: 800; }}
QPushButton#primary:checked {{ color: {t['accent_text']}; }}
QPushButton#danger {{ color: {t['danger']}; }}
QPushButton#pill {{ color: {t['text_muted']}; padding: 6px 14px; }}
QPushButton#pill:checked {{ color: {acc}; }}
QPushButton#tab {{ color: {t['text_muted']}; font-weight: 700; padding: 8px 16px; border-radius: 9px; }}
QPushButton#tab:hover {{ color: {t['text']}; }}
QPushButton#tab:checked {{ color: {acc}; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 4px 8px; }}
QToolButton:hover {{ background: {t['hover_fill']}; border-color: {t['border']}; }}
QToolButton:pressed, QToolButton:checked {{ background: {sel}; }}

/* ── Поля ввода ───────────────────────────────────── */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit, QPlainTextEdit, QTextEdit {{
    background: {t['input_bg']}; border: 1px solid {t['border']};
    border-radius: {r - 3}px; padding: 8px 11px; selection-background-color: {acc}; selection-color: {t['accent_text']};
}}
QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit {{ padding: 6px 8px; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QPlainTextEdit:hover, QTextEdit:hover {{ border-color: {t['text_muted']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {acc}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {{ color: {t['text_muted']}; }}
QLineEdit#mono, QPlainTextEdit#mono {{ font-family: {FONT_MONO}; font-size: 12px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; width: 20px; border: none; background: transparent;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ width: 10px; height: 10px; {up_rule} }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ width: 10px; height: 10px; {down_rule} }}
QComboBox {{ padding-right: 34px; }}
QComboBox::drop-down {{ border: none; width: 30px; }}
QComboBox::down-arrow {{ width: 12px; height: 12px; {down_rule} }}
QComboBox[fx="true"]::down-arrow {{ image: none; }}
QComboBox QAbstractItemView, QComboBoxPrivateContainer {{
    background: {t['surface']}; border: 1px solid {t['border']};
    selection-background-color: {sel}; selection-color: {acc}; outline: none;
}}
QCheckBox {{ spacing: 9px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 6px; border: 1px solid {t['border']}; background: {t['input_bg']}; }}
QCheckBox::indicator:checked {{ background: {acc}; border-color: {acc}; {check_rule} }}
QCheckBox::indicator:hover {{ border-color: {acc}; }}
QRadioButton {{ spacing: 9px; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 9px; border: 1px solid {t['border']}; background: {t['input_bg']}; }}
QRadioButton::indicator:checked {{ border: 5px solid {acc}; background: {t['input_bg']}; }}
QRadioButton::indicator:hover {{ border-color: {acc}; }}
/* Слайдер: обычный рисует QSS, FxSlider (fx=true) — сам; размер ручки 18px одинаков, мышь считается верно */
QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {t['border']}; }}
QSlider::sub-page:horizontal {{ height: 4px; border-radius: 2px; background: {acc}; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; border-radius: 8px; background: {t['knob']}; border: 2px solid {acc}; }}
QSlider[fx="true"]::groove:horizontal {{ height: 4px; background: transparent; }}
QSlider[fx="true"]::sub-page:horizontal {{ background: transparent; }}
QSlider[fx="true"]::handle:horizontal {{ width: 18px; height: 18px; margin: -7px 0; background: transparent; border: none; }}
QProgressBar {{ background: {t['border']}; border: none; border-radius: 4px; text-align: center; min-height: 8px; }}
QProgressBar::chunk {{ background: {acc}; border-radius: 4px; }}

/* ── Группы и вложенные вкладки (старые экраны) ───── */
QGroupBox {{
    border: 1px solid {t['border']}; border-radius: {r - 2}px; margin-top: 14px; padding: 18px 12px 10px 12px;
    font-weight: 700; background: transparent;
}}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 6px; color: {t['text']}; }}
QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: {r - 2}px; top: -1px; background: transparent; }}
QTabWidget::tab-bar {{ alignment: left; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {t['text_muted']}; font-weight: 700; padding: 9px 16px; margin-right: 2px;
    border: none; border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{ color: {t['text']}; }}
QTabBar::tab:selected {{ color: {acc}; border-bottom: 2px solid {acc}; }}

/* ── Списки, таблицы ──────────────────────────────── */
QListWidget, QListView, QTreeWidget, QTreeView {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: {r - 2}px; outline: none;
    selection-background-color: {row_sel}; selection-color: {t['text']}; alternate-background-color: {t['hover_fill']};
}}
QListWidget::item:hover, QListView::item:hover, QTreeView::item:hover {{ background: {t['hover_fill']}; }}
QListWidget::item:selected, QListView::item:selected, QTreeView::item:selected {{ background: {row_sel}; color: {t['text']}; }}
QListWidget#nav {{ background: transparent; border: none; border-radius: 0; }}
QTableWidget, QTableView {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: {r}px;
    gridline-color: transparent; alternate-background-color: {t['hover_fill']}; outline: none;
    selection-background-color: {row_sel}; selection-color: {t['text']};
}}
QTableWidget::item {{ padding: 6px 10px; border: none; }}
QTableWidget::item:hover {{ background: {t['hover_fill']}; }}
QTableWidget::item:selected {{ background: {row_sel}; color: {t['text']}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: transparent; color: {t['text_muted']}; border: none;
    border-bottom: 1px solid {t['border']}; padding: 9px 10px; font-weight: 700; font-size: 11px;
}}
QTableCornerButton::section {{ background: transparent; border: none; }}
QMenu {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: {r - 2}px; padding: 4px; }}
QMenu::item {{ padding: 7px 22px; border-radius: 6px; color: {t['text']}; }}
QMenu::item:selected {{ background: {sel}; color: {acc}; }}
QMenu::item:disabled {{ color: {t['text_muted']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {t['border']}; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}

/* ── Скроллбары ───────────────────────────────────── */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['text_muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {t['text_muted']}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ── Служебные элементы ───────────────────────────── */
QLabel#toast {{
    background: {t['surface_alt']}; color: {t['text']}; border: 1px solid {rgba(acc, 0.6)};
    border-radius: {r}px; padding: 11px 18px; font-weight: 700;
}}
QFrame#savebar {{ background: {t['surface']}; border: 1px solid {rgba(acc, 0.55)}; border-radius: {r + 2}px; }}
QProgressBar#busy {{ background: {t['border']}; border: none; border-radius: 1px; min-height: 0; }}
QProgressBar#busy::chunk {{ background: {acc}; border-radius: 1px; }}
QToolButton#collapseToggle {{ background: transparent; border: none; color: {t['text']}; font-weight: 700; padding: 4px 0; }}
QLabel#fieldError {{ color: {t['danger']}; font-size: 12px; }}
QToolTip {{ background: {t['surface_alt']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 5px 9px; }}
QFrame#tipPanel {{ background: {t['surface_alt']}; border: 1px solid {t['border']}; border-radius: {r - 2}px; }}
QLabel#tipTitle {{ font-weight: 700; font-size: 12px; }}
QLabel#tipBody {{ color: {t['text_muted']}; font-size: 12px; }}
"""
