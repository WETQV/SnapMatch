"""Дизайн-система SnapMatch (PyQt6). Публичный API — всё, что реэкспортируется здесь.

    from gui.design import card, label, page_header, primary, FxButton, SwitchRow, FadeStack, current_tokens, icons

Подробности и правила — в docs/UI_DESIGN_SYSTEM.md.
"""
from gui.design import icons, motion
from gui.design.appearance import (
    AppearanceCard, AppearanceController, controller, init as init_appearance, load_fonts,
)
from gui.design.motion import FadeStack, NavIndicator, SegmentedControl, Toast, fade_in
from gui.design.shell import FrameController, TitleBar, prepare_translucent
from gui.design.tokens import BRAND_ACCENT, FONT_MONO, FONT_UI, RADIUS, build_qss, make_tokens, rgba
from gui.design.tokens import tokens as current_tokens   # не называем tokens: имя занято модулем gui.design.tokens
from gui.design.tooltip import FxTooltip, TooltipManager
from gui.design.widgets import (
    Collapsible, Reveal, FxButton, FxComboBox, FxSlider, GlowRoot, IconTile, ServerCard, StatTile, StatusBadge, Swatch,
    Switch, SwitchRow, ThemeCard, WinButton, card, icon_button, label, make_table, page_header, primary,
    refresh_icons,
)

__all__ = [
    "icons", "motion", "current_tokens", "make_tokens", "build_qss", "rgba", "BRAND_ACCENT", "FONT_UI", "FONT_MONO", "RADIUS",
    "AppearanceCard", "AppearanceController", "controller", "init_appearance", "load_fonts",
    "FadeStack", "NavIndicator", "SegmentedControl", "Toast", "fade_in",
    "FrameController", "TitleBar", "prepare_translucent", "FxTooltip", "TooltipManager",
    "Collapsible", "Reveal", "FxButton", "FxComboBox", "FxSlider", "GlowRoot", "IconTile", "ServerCard", "StatTile",
    "StatusBadge", "Swatch", "Switch", "SwitchRow", "ThemeCard", "WinButton",
    "card", "icon_button", "label", "make_table", "page_header", "primary", "refresh_icons",
]
