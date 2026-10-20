"""Макет темы SnapMatch: токены цветов + один QSS-шаблон.

Это ТОЛЬКО макет (в приложение не подключён). Идея: все цвета, радиусы и отступы
живут в одном словаре токенов, а QSS генерируется из шаблона — светлая и тёмная
темы отличаются только значениями токенов.
"""

DARK = {
    "bg": "#0F1117",
    "surface": "#171A22",
    "surface_alt": "#1E222C",
    "border": "#2A2F3B",
    "text": "#E8ECF4",
    "text_muted": "#8B96AB",
    "accent": "#18B476",
    "accent_hover": "#1FCB87",
    "accent_text": "#06130D",
    "danger": "#F5524F",
    "warning": "#E8B341",
    "info": "#5BA4F5",
    "input_bg": "#12151C",
}

LIGHT = {
    "bg": "#F4F6FA",
    "surface": "#FFFFFF",
    "surface_alt": "#F0F2F7",
    "border": "#DDE1EA",
    "text": "#1B2030",
    "text_muted": "#69738A",
    "accent": "#0E9F68",
    "accent_hover": "#0B8858",
    "accent_text": "#FFFFFF",
    "danger": "#D93A37",
    "warning": "#B7791F",
    "info": "#2B7BDB",
    "input_bg": "#FFFFFF",
}

RADIUS = 10


def rgba(hex_color: str, alpha: float) -> str:
    """QSS понимает rgba(), а 8-значный hex у Qt — это #AARRGGBB, поэтому прозрачность задаём так."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"

FONT_FAMILY = '"Inter", "Segoe UI", "Noto Sans", "Ubuntu", sans-serif'


def build_qss(t: dict) -> str:
    r = RADIUS
    sel = rgba(t["accent"], 0.16)
    row_sel = rgba(t["accent"], 0.10)
    ok_bg, err_bg, warn_bg = rgba(t["accent"], 0.15), rgba(t["danger"], 0.15), rgba(t["warning"], 0.15)
    danger_border, danger_hover = rgba(t["danger"], 0.4), rgba(t["danger"], 0.10)
    return f"""
* {{ font-family: {FONT_FAMILY}; font-size: 13px; }}
QWidget {{ background: transparent; color: {t['text']}; }}
QMainWindow, QWidget#root {{ background: {t['bg']}; }}

/* ── Боковая навигация ─────────────────────────────── */
QWidget#sidebar {{ background: {t['surface']}; border-right: 1px solid {t['border']}; }}
QLabel#brand {{ font-size: 17px; font-weight: 700; padding: 4px 6px; }}
QListWidget#nav {{ background: transparent; border: none; outline: none; }}
QListWidget#nav::item {{
    padding: 10px 12px; margin: 2px 0; border-radius: {r - 2}px; color: {t['text_muted']};
}}
QListWidget#nav::item:hover {{ background: {t['surface_alt']}; color: {t['text']}; }}
QListWidget#nav::item:selected {{ background: {sel}; color: {t['accent']}; font-weight: 600; }}

/* ── Карточки ──────────────────────────────────────── */
QFrame#card {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: {r + 2}px;
}}
QLabel#h1 {{ font-size: 22px; font-weight: 700; }}
QLabel#h2 {{ font-size: 14px; font-weight: 600; }}
QLabel#muted {{ color: {t['text_muted']}; }}
QLabel#chip_ok, QLabel#chip_err, QLabel#chip_empty {{
    border-radius: 9px; padding: 2px 10px; font-size: 11px; font-weight: 600;
}}
QLabel#chip_ok {{ background: {ok_bg}; color: {t['accent']}; }}
QLabel#chip_err {{ background: {err_bg}; color: {t['danger']}; }}
QLabel#chip_empty {{ background: {warn_bg}; color: {t['warning']}; }}

/* ── Кнопки ────────────────────────────────────────── */
QPushButton {{
    background: {t['surface_alt']}; border: 1px solid {t['border']};
    border-radius: {r - 2}px; padding: 7px 14px; min-height: 18px;
}}
QPushButton:hover {{ border-color: {t['accent']}; }}
QPushButton:pressed {{ background: {sel}; }}
QPushButton:disabled {{ color: {t['text_muted']}; }}
QPushButton#primary {{
    background: {t['accent']}; color: {t['accent_text']}; border: none; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {t['accent_hover']}; }}
QPushButton#danger {{ color: {t['danger']}; border-color: {danger_border}; }}
QPushButton#danger:hover {{ background: {danger_hover}; border-color: {t['danger']}; }}

/* ── Поля ввода ────────────────────────────────────── */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {t['input_bg']}; border: 1px solid {t['border']};
    border-radius: {r - 2}px; padding: 6px 10px; selection-background-color: {t['accent']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {t['accent']};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {t['surface']}; border: 1px solid {t['border']};
    selection-background-color: {sel}; selection-color: {t['accent']};
}}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {t['border']}; background: {t['input_bg']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}
QSlider::groove:horizontal {{ height: 4px; background: {t['border']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {t['accent']}; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }}

/* ── Таблицы ───────────────────────────────────────── */
QTableWidget {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: {r}px;
    gridline-color: transparent; alternate-background-color: {t['surface_alt']}; outline: none;
}}
QTableWidget::item {{ padding: 6px 10px; border: none; }}
QTableWidget::item:selected {{ background: {row_sel}; color: {t['text']}; }}
QTableView {{ selection-background-color: {row_sel}; selection-color: {t['text']}; }}
QHeaderView::section {{
    background: {t['surface']}; color: {t['text_muted']}; border: none;
    border-bottom: 1px solid {t['border']}; padding: 8px 10px; font-weight: 600; font-size: 12px; text-align: left;
}}

/* ── Скроллбары ────────────────────────────────────── */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['text_muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 4px; min-width: 30px; }}

QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 4px 8px; }}
"""
