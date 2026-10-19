import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt, QTimer

from gui.async_worker import run_in_background
from gui.design.dialogs import ask, inform, prompt_text, warn
from gui.design.widgets import ElidedLabel, ToolCard, tool_params
from gui.admin_panel.ui_common import BadgeSlot, shrinkable, vertical_scroll
from gui.design import (
    FxButton,
    FxComboBox,
    IconTile,
    SegmentedControl,
    ServerCard,
    StatTile,
    SwitchRow,
    card,
    icon_button,
    label,
    page_header,
    primary,
)
from bot.handlers.services.mcp_permissions import allowed_tools_for_context
from bot.handlers.services.mcp_registry import normalize_server_config, preview_servers
from bot.handlers.services.mcp_runtime import (
    McpRuntimeError,
    discover_server_capabilities,
    get_mcp_sdk_error,
    is_mcp_sdk_available,
    start_server_process,
    stop_server_process,
)
from config.settings import settings_manager
from utils.database.database_manager import DatabaseManager
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Статус из БД -> (текст бейджа, тон StatusBadge)
STATUS_VIEW = {
    "started": ("Запущен", "ok"),
    "discovered": ("Проверен", "info"),
    "failed": ("Ошибка", "error"),
    "stopped": ("Остановлен", "idle"),
}


# Короткие тексты бейджа в карточке списка (в шапке деталей — полные из STATUS_VIEW)
CARD_BADGE = {"started": "Запущен", "discovered": "Готов", "failed": "Ошибка", "stopped": "Стоп"}


def _tip(widget, title: str, text: str = "") -> None:
    """Подсказка: первая строка — заголовок, остальное — пояснение."""
    widget.setToolTip(f"{title}\n{text}" if text else title)


def _status_view(status: str | None) -> tuple[str, str]:
    if not status:
        return "Нет данных", "idle"
    return STATUS_VIEW.get(str(status), (str(status), "idle"))


def _mono_edit(placeholder: str, min_h: int, max_h: int, read_only: bool = False) -> QPlainTextEdit:
    edit = QPlainTextEdit()
    edit.setObjectName("mono")
    edit.setPlaceholderText(placeholder)
    edit.setMinimumHeight(min_h)
    edit.setMaximumHeight(max_h)
    edit.setReadOnly(read_only)
    return edit


class McpTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_row = -1
        self._loading_access = False
        self.cards: list[ServerCard] = []
        self._card_haystack: list[str] = []
        self._init_ui()
        self._init_tooltips()
        self.load_settings()

    @staticmethod
    def _caption_field(grid: QGridLayout, row: int, col: int, caption: str, widget: QWidget, span: int = 1) -> None:
        """Поле сетки: подпись над полем (экономит ширину)."""
        grid.addWidget(label(caption, "sectionLabel"), row * 2, col, 1, span)
        grid.addWidget(widget, row * 2 + 1, col, 1, span)

    def _init_ui(self):
        # Вся страница в вертикальной прокрутке: на низком окне плитки уезжают вверх, а детали остаются читаемыми
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        # ── Шапка: общий переключатель и добавление серверов ──
        self.enabled = SwitchRow("MCP включён", False, compact=True)
        self.add_button = icon_button("Добавить", "mdi6.plus")
        self.example_button = icon_button("Пример", "mdi6.flask-outline")
        head = page_header("MCP", "Внешние инструменты для модели", self.add_button, self.example_button)
        head.insertWidget(1, self.enabled)
        head.insertSpacing(2, 16)
        layout.addLayout(head)

        # ── Плитки метрик ──
        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.tile_servers = StatTile("0", "Серверов", "mdi6.server-network-outline", "idle")
        self.tile_running = StatTile("0", "Запущено", "mdi6.play-circle-outline", "ok")
        self.tile_tools = StatTile("0", "Инструментов", "mdi6.hammer-wrench", "idle")
        self.tile_denials = StatTile("0", "Отказов, 24 ч", "mdi6.shield-alert-outline", "error")
        for tile in (self.tile_servers, self.tile_running, self.tile_tools, self.tile_denials):
            tile.setMinimumWidth(0)
            stats.addWidget(tile, 1)
        layout.addLayout(stats)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)   # иначе holder добавляет ~9 px по бокам: колонки смещены относительно плиток метрик
        body.setSpacing(16)

        # ── Список серверов ──
        left, left_lay = card()
        left.setMinimumWidth(270)
        left.setMaximumWidth(340)
        left_lay.setSpacing(12)
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Фильтр по имени, статусу, команде или доступу")
        left_lay.addWidget(self.filter_input)
        left_lay.addWidget(label("СЕРВЕРЫ", "sectionLabel"))
        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        self.cards_layout = QVBoxLayout(holder)
        self.cards_layout.setContentsMargins(0, 0, 4, 0)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch()
        self.cards_scroll.setWidget(holder)
        # Глобальный QScrollArea закрашен цветом фона окна — внутри карточки это тёмный «ящик» (особенно заметно в OLED)
        self.cards_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.cards_scroll.viewport().setAutoFillBackground(False)
        left_lay.addWidget(self.cards_scroll, 1)
        self.empty_label = label("Серверов пока нет. Нажмите «Добавить» или «Пример».", "muted")
        self.empty_label.setWordWrap(True)
        left_lay.addWidget(self.empty_label)
        body.addWidget(left, 1)

        # ── Детали выбранного сервера ──
        right, right_lay = card()
        right.setMinimumWidth(340)
        right_lay.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(14)
        self.big_icon = IconTile("mdi6.server-outline", "idle", 52)
        top.addWidget(self.big_icon)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        self.title_label = ElidedLabel("Сервер не выбран", "h1")
        self.status_badge = BadgeSlot("Нет данных", "idle", pulse=None)
        name_row.addWidget(self.title_label, 1)
        name_row.addWidget(self.status_badge)
        titles.addLayout(name_row)
        self.cmdline_label = ElidedLabel("", "mono")
        titles.addWidget(self.cmdline_label)
        top.addLayout(titles, 1)
        right_lay.addLayout(top)

        # Кнопки управления процессом
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.start_button = icon_button("Старт", "mdi6.play-outline")
        self.stop_button = icon_button("Стоп", "mdi6.stop")
        self.discover_button = icon_button("Проверить", "mdi6.magnify-scan")
        self.refresh_audit_button = icon_button("Audit", "mdi6.clipboard-text-clock-outline")
        for button in (self.start_button, self.stop_button, self.discover_button):
            actions.addWidget(button)
        actions.addStretch()
        right_lay.addLayout(actions)

        # Индикатор фоновой операции
        self.busy = QProgressBar()
        self.busy.setObjectName("busy")
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setFixedHeight(3)
        self.busy.hide()
        right_lay.addWidget(self.busy)

        self.sections = SegmentedControl(["Настройка", "Инструменты", "Аудит"])
        right_lay.addWidget(self.sections)
        self.pages = QStackedWidget()
        self.pages.addWidget(vertical_scroll(self._build_config_page()))
        self.pages.addWidget(vertical_scroll(self._build_tools_page()))
        self.pages.addWidget(vertical_scroll(self._build_audit_page()))
        for page_scroll in self.pages.findChildren(QScrollArea, options=Qt.FindChildOption.FindDirectChildrenOnly):
            page_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.sections.changed.connect(self.pages.setCurrentIndex)
        right_lay.addWidget(self.pages, 1)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        right_lay.addWidget(divider)
        foot = QHBoxLayout()
        self.delete_button = icon_button("Удалить", "mdi6.trash-can-outline", "danger")
        self.cancel_button = FxButton("Отмена")
        self.save_button = primary("Сохранить", "mdi6.content-save-outline")
        foot.addWidget(self.delete_button)
        foot.addStretch()
        foot.addWidget(self.cancel_button)
        foot.addWidget(self.save_button)
        right_lay.addLayout(foot)
        body.addWidget(right, 2)

        body_holder = QWidget()
        body_holder.setLayout(body)
        body_holder.setMinimumHeight(560)
        layout.addWidget(body_holder, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(vertical_scroll(content))

        self.add_button.clicked.connect(self.add_server)
        self.example_button.clicked.connect(self.add_example_server)
        self.delete_button.clicked.connect(self.delete_server)
        self.cancel_button.clicked.connect(self._on_selection_changed)
        self.start_button.clicked.connect(self.start_server)
        self.stop_button.clicked.connect(self.stop_server)
        self.discover_button.clicked.connect(self.discover_tools)
        self.refresh_audit_button.clicked.connect(self.refresh_audit)
        self.preview_button.clicked.connect(self.preview_access)
        self.save_button.clicked.connect(self.save_settings)
        # Debounce: фильтр применяется через 200 мс после последнего ввода
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(self._apply_filter)
        self.filter_input.textChanged.connect(lambda _text: self._filter_timer.start())
        for pill in (self.access_admin, self.access_private, self.access_group, self.access_secretary):
            pill.toggled.connect(self._sync_access_json_from_checks)

    def _build_config_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 4, 8, 4)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 120)
        grid.setColumnMinimumWidth(1, 120)

        self.transport = FxComboBox()
        self.transport.addItems(["stdio", "sse", "streamable_http"])
        shrinkable(self.transport)
        self.command = QLineEdit()
        self.command.setObjectName("mono")
        self.command.setPlaceholderText("Команда запуска MCP-сервера")
        self.args = _mono_edit("Аргументы, по одному на строку", 78, 110)
        self.cwd = QLineEdit()
        self.cwd.setObjectName("mono")
        self.cwd.setPlaceholderText("Рабочая папка для stdio-сервера")
        self.url = QLineEdit()
        self.url.setObjectName("mono")
        self.url.setPlaceholderText("URL для sse/streamable_http")
        self.env = _mono_edit('Env JSON, например {"API_KEY":"..."}', 96, 140)
        self.access = _mono_edit('Access JSON, например {"admin":true,"private":false,"group":false,"secretary":false}', 88, 120)
        self.description = _mono_edit("Описание", 60, 110)
        self.description.setObjectName("")  # описание — обычный текст, не моноширинный

        self._caption_field(grid, 0, 0, "ТРАНСПОРТ", self.transport)
        self._caption_field(grid, 0, 1, "КОМАНДА", self.command)
        self._caption_field(grid, 1, 0, "АРГУМЕНТЫ", self.args, 2)
        self._caption_field(grid, 2, 0, "РАБОЧАЯ ПАПКА", self.cwd)
        self._caption_field(grid, 2, 1, "URL", self.url)
        self._caption_field(grid, 3, 0, "ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (JSON)", self.env, 2)

        # Состояние сервера
        self.server_enabled = SwitchRow("Сервер включён", False, compact=True)
        self.auto_start = SwitchRow("Запускать автоматически", False, compact=True)
        state = QWidget()
        state_row = QVBoxLayout(state)
        state_row.setContentsMargins(0, 0, 0, 0)
        state_row.setSpacing(0)
        state_row.addWidget(self.server_enabled)
        state_row.addWidget(self.auto_start)
        self._caption_field(grid, 4, 0, "СОСТОЯНИЕ", state, 2)

        # Доступ — переключаемые «пилюли»
        access_box = QWidget()
        access_grid = QGridLayout(access_box)
        access_grid.setContentsMargins(0, 0, 0, 0)
        access_grid.setHorizontalSpacing(6)
        access_grid.setVerticalSpacing(6)
        pills = []
        for index, text in enumerate(("Админ", "ЛС", "Группы", "Секретарь")):
            pill = FxButton(text)
            pill.setObjectName("pill")
            pill.setCheckable(True)
            pill.setMinimumWidth(0)
            access_grid.addWidget(pill, index // 2, index % 2)
            pills.append(pill)
        access_grid.setColumnStretch(0, 1)
        access_grid.setColumnStretch(1, 1)
        self.access_admin, self.access_private, self.access_group, self.access_secretary = pills
        self._caption_field(grid, 5, 0, "ДОСТУП", access_box, 2)
        self._caption_field(grid, 6, 0, "ACCESS JSON", self.access, 2)
        self._caption_field(grid, 7, 0, "ОПИСАНИЕ", self.description, 2)
        grid.setRowStretch(16, 1)
        return page

    def _build_tools_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 8, 4)
        lay.setSpacing(6)
        self.tools_preview = _mono_edit("Tools discovery result", 110, 100000, True)
        self._tools_data: list = []
        self.resources_preview = _mono_edit("Resources and resource templates discovery result", 92, 100000, True)
        self.prompts_preview = _mono_edit("Prompts discovery result", 92, 100000, True)
        tools_head = QHBoxLayout()
        tools_head.addWidget(label("TOOLS", "sectionLabel"))
        tools_head.addStretch()
        self.tools_view_button = FxButton("JSON")
        self.tools_view_button.setToolTip("Переключить вид инструментов: плитки или JSON")
        tools_head.addWidget(self.tools_view_button)
        lay.addLayout(tools_head)
        self.tools_tiles = QWidget()
        self.tools_tiles_lay = QVBoxLayout(self.tools_tiles)
        self.tools_tiles_lay.setContentsMargins(0, 0, 0, 0)
        self.tools_tiles_lay.setSpacing(8)
        self.tools_stack = QStackedWidget()
        self.tools_stack.addWidget(self.tools_tiles)
        self.tools_stack.addWidget(self.tools_preview)
        self.tools_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.tools_stack.currentChanged.connect(lambda _i: self._fit_tools_stack())
        self.tools_view_button.clicked.connect(self._toggle_tools_view)
        lay.addWidget(self.tools_stack)
        lay.addWidget(label("RESOURCES", "sectionLabel"))
        lay.addWidget(self.resources_preview, 1)
        lay.addWidget(label("PROMPTS", "sectionLabel"))
        lay.addWidget(self.prompts_preview, 1)
        return page

    def _set_tools(self, tools) -> None:
        """Обновляет оба вида инструментов: плитки и JSON."""
        self._tools_data = [t for t in (tools or []) if isinstance(t, dict)]
        self.tools_preview.setPlainText(json.dumps(tools, ensure_ascii=False, indent=2) if tools else "")
        while self.tools_tiles_lay.count():
            item = self.tools_tiles_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._tools_data:
            empty = label("Инструментов нет. Нажмите «Проверить», чтобы получить список с сервера.", "muted")
            empty.setWordWrap(True)
            self.tools_tiles_lay.addWidget(empty)
        for tool in self._tools_data:
            self.tools_tiles_lay.addWidget(ToolCard(
                str(tool.get("name") or "—"), str(tool.get("description") or ""),
                tool_params(tool), bool(tool.get("requires_confirmation")),
            ))
        self._fit_tools_stack()

    def _fit_tools_stack(self) -> None:
        """Плитки занимают ровно свою высоту (страница прокручивается целиком), JSON — своё поле."""
        tiles = self.tools_stack.currentWidget() is self.tools_tiles
        self.tools_stack.setMaximumHeight(16777215 if not tiles else max(40, self.tools_tiles.sizeHint().height()))
        self.tools_stack.setMinimumHeight(0 if tiles else 200)

    def _toggle_tools_view(self) -> None:
        to_json = self.tools_stack.currentWidget() is self.tools_tiles
        self.tools_stack.setCurrentWidget(self.tools_preview if to_json else self.tools_tiles)
        self.tools_view_button.setText("Плитки" if to_json else "JSON")

    def _build_audit_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 8, 4)
        lay.setSpacing(10)
        self.status_label = label("Статус: нет данных", "mono")
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.warning_label = label("", "fieldError")
        self.warning_label.setWordWrap(True)
        self.warning_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.status_label)
        lay.addWidget(self.warning_label)

        # Access preview: проверка доступа для произвольного контекста
        preview_box, preview_lay = card()
        preview_box.setObjectName("rowCard")
        preview_lay.addWidget(label("Access preview", "h2"))
        self.preview_actor = QLineEdit()
        self.preview_actor.setPlaceholderText("actor_telegram_id")
        self.preview_chat = QLineEdit()
        self.preview_chat.setPlaceholderText("chat_id")
        self.preview_source = FxComboBox()
        self.preview_source.addItems(["normal", "bot_to_bot", "secretary"])
        shrinkable(self.preview_source)
        self.preview_chat_type = FxComboBox()
        self.preview_chat_type.addItems(["private", "group", "supergroup"])
        shrinkable(self.preview_chat_type)
        self.preview_admin = SwitchRow("is_admin", False, compact=True)
        self.preview_button = icon_button("Проверить доступ", "mdi6.shield-check-outline")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self._caption_field(grid, 0, 0, "ACTOR", self.preview_actor)
        self._caption_field(grid, 0, 1, "CHAT", self.preview_chat)
        self._caption_field(grid, 1, 0, "ИСТОЧНИК", self.preview_source)
        self._caption_field(grid, 1, 1, "ТИП ЧАТА", self.preview_chat_type)
        preview_lay.addLayout(grid)
        action_row = QHBoxLayout()
        action_row.addWidget(self.preview_admin)
        action_row.addStretch()
        action_row.addWidget(self.preview_button)
        preview_lay.addLayout(action_row)
        self.preview_result = _mono_edit("Результат проверки доступа", 60, 140, True)
        preview_lay.addWidget(self.preview_result)
        lay.addWidget(preview_box)

        log_head = QHBoxLayout()
        log_head.addWidget(label("ЖУРНАЛ ВЫЗОВОВ", "sectionLabel"))
        log_head.addStretch()
        log_head.addWidget(self.refresh_audit_button)
        lay.addLayout(log_head)
        self.audit_log = _mono_edit("Последние вызовы и отказы", 200, 100000, True)
        lay.addWidget(self.audit_log, 1)
        return page

    def _init_tooltips(self):
        _tip(self.enabled, "MCP включён", "Главный переключатель MCP. Если выключен, инструменты MCP не передаются модели.")
        _tip(self.add_button, "Добавить сервер", "Добавить новый MCP-сервер в список настроек.")
        _tip(self.example_button, "Пример сервера", "Добавить готовый простой MCP-пример из папки examples/mcp.")
        _tip(self.delete_button, "Удалить сервер", "Удалить выбранный MCP-сервер из настроек (с подтверждением).")
        _tip(self.cancel_button, "Отмена", "Вернуть поля выбранного сервера к сохранённым значениям.")
        _tip(self.start_button, "Запустить сервер", "Запустить выбранный stdio MCP-сервер для текущей GUI-сессии.")
        _tip(self.stop_button, "Остановить сервер", "Остановить выбранный stdio MCP-сервер, если он был запущен из этой вкладки.")
        _tip(self.discover_button, "Проверить сервер", "Подключиться к серверу и обновить список tools, resources и prompts.")
        _tip(self.refresh_audit_button, "Обновить Audit", "Обновить статус сервера, последние вызовы tools и отказы доступа.")
        _tip(self.save_button, "Сохранить", "Сохранить MCP-настройки в config.json.")
        _tip(self.filter_input, "Фильтр серверов", "Быстрый фильтр по списку MCP-серверов: имя, статус, команда, доступ.")
        _tip(self.transport, "Транспорт", "Тип подключения MCP-сервера: stdio, SSE или streamable HTTP.")
        _tip(self.command, "Команда", "Команда запуска stdio MCP-сервера, например путь к node/python исполняемому файлу.")
        _tip(self.args, "Аргументы", "Аргументы запуска MCP-сервера. Один аргумент на строку.")
        _tip(self.cwd, "Рабочая папка", "Рабочая папка для stdio-сервера. Можно оставить пустой.")
        _tip(self.url, "URL", "URL MCP-сервера для transport sse или streamable_http.")
        _tip(self.env, "Переменные окружения", "Переменные окружения в JSON. Значения показываются как есть, не храните там лишних секретов.")
        _tip(self.server_enabled, "Сервер включён", "Разрешить использовать этот сервер при запросах к модели.")
        _tip(self.auto_start, "Автозапуск", "Пометка автозапуска сервера. Полноценный persistent pool ещё не включён.")
        _tip(self.access_admin, "Админ", "Разрешить tools этого сервера администраторам.")
        _tip(self.access_private, "Личные чаты", "Разрешить tools этого сервера в личных чатах.")
        _tip(self.access_group, "Группы", "Разрешить tools этого сервера в группах.")
        _tip(self.access_secretary, "Секретарь", "Разрешить tools этого сервера в secretary/Chat Automation сценариях.")
        _tip(self.access, "Access JSON", "Расширенный JSON доступа. Кнопки доступа выше обновляют основные поля автоматически.")
        _tip(self.description, "Описание", "Короткое описание сервера для себя и будущих проверок.")
        _tip(self.tools_preview, "Tools", "Последний discovery-результат tools для выбранного сервера.")
        _tip(self.resources_preview, "Resources", "Последний discovery-результат resources и resource templates.")
        _tip(self.prompts_preview, "Prompts", "Последний discovery-результат prompts.")
        _tip(self.preview_actor, "actor_telegram_id", "Telegram ID пользователя для проверки доступа.")
        _tip(self.preview_chat, "chat_id", "chat_id для проверки доступа.")
        _tip(self.preview_source, "Источник", "Источник запроса: обычный чат, bot-to-bot или secretary.")
        _tip(self.preview_chat_type, "Тип чата", "Тип чата для проверки доступа.")
        _tip(self.preview_admin, "is_admin", "Проверять доступ так, будто пользователь администратор.")
        _tip(self.preview_button, "Проверить доступ", "Показать tools, доступные для указанного контекста.")
        _tip(self.preview_result, "Результат", "Результат проверки доступа для указанного контекста.")
        _tip(self.audit_log, "Журнал вызовов", "Последние MCP tool calls и отказы доступа по выбранному серверу.")

    # ── Вспомогательные методы интерфейса ──

    def _notify(self, text: str) -> None:
        """Короткое уведомление (тост) главного окна; без окна — тихо."""
        toast = getattr(self.window(), "toast", None)
        if toast is not None:
            toast.show_message(text)

    def _servers(self):
        settings = settings_manager.get_settings()
        return settings.get("mcp", {}).get("servers", [])

    def load_settings(self, select_row: int | None = None, select_name: str | None = None, reload_fields: bool = False):
        settings = settings_manager.get_settings()
        self.enabled.setChecked(settings.get("mcp", {}).get("enabled", False))
        servers = preview_servers(settings)
        statuses = self._status_by_server()
        previous_name = self._selected_server_name()
        previous_row = self.current_row

        # Пересобираем список карточек
        for card_widget in self.cards:
            self.cards_layout.removeWidget(card_widget)
            card_widget.setParent(None)
            card_widget.deleteLater()
        self.cards = []
        self._card_haystack = []
        selected_row = -1
        for row, server in enumerate(servers):
            name = server.get("name", "")
            if select_name and name == select_name:
                selected_row = row
            access = server.get("access", {})
            access_text = ",".join(key for key, value in access.items() if value)
            status = statuses.get(name, {})
            status_text, kind = _status_view(status.get("status"))
            badge_text = CARD_BADGE.get(str(status.get("status") or ""), "Стоп")   # короткий текст: экономит место названию
            transport = server.get("transport", "stdio")
            command = str(server.get("command") or server.get("url") or "")
            tools_count = len(server.get("tools") or [])
            subtitle = f"{(command.split() or ['—'])[0].replace(chr(92), '/').split('/')[-1]} · {transport}"
            server_card = ServerCard(
                name, subtitle, badge_text, kind, tools_count,
                "mdi6.web" if transport != "stdio" else "mdi6.console",
            )
            # Длинное имя/команда не должны растягивать список — обрезаются, полный текст в подсказке
            info_col = server_card.layout().itemAt(1).layout()
            for idx, text, obj in ((0, name, "cardTitle"), (1, subtitle, "mono")):
                old = info_col.itemAt(idx).widget()
                new = ElidedLabel(text, obj)
                info_col.replaceWidget(old, new)
                old.deleteLater()
            _tip(server_card, name, f"{command or 'команда не задана'}\nСтатус: {status_text}. Доступ: {access_text or 'нет'}")
            server_card.clicked.connect(self._on_card_clicked)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, server_card)
            self.cards.append(server_card)
            self._card_haystack.append(" ".join([
                name, status_text, str(status.get("status") or ""), "да" if server.get("enabled") else "нет",
                access_text, transport, command,
            ]).lower())
        self.empty_label.setVisible(not servers)

        if selected_row < 0 and select_row is not None and 0 <= select_row < len(servers):
            selected_row = select_row
        if selected_row < 0 and servers:
            selected_row = 0
        self._update_metrics(servers, statuses)
        if selected_row >= 0:
            # Поля формы перечитываем только при смене сервера: несохранённый ввод не теряем
            same = (selected_row == previous_row and servers[selected_row].get("name") == previous_name)
            self._select_row(selected_row, reload_fields=reload_fields or not same)
        else:
            self.current_row = -1
            self._show_header(None, {})
        self._apply_filter()
        self.refresh_audit()

    def _update_metrics(self, servers, statuses):
        """Плитки метрик: реальные данные из реестра и аудита."""
        running = sum(1 for server in servers if (statuses.get(server.get("name", "")) or {}).get("status") == "started")
        tools_total = sum(len(server.get("tools") or []) for server in servers)
        for tile, value in (
            (self.tile_servers, len(servers)),
            (self.tile_running, running),
            (self.tile_tools, tools_total),
            (self.tile_denials, self._denials_last_day()),
        ):
            tile._target, tile._text = int(value), str(value)   # play() при показе страницы считает до актуального числа
            tile.num.setText(str(value))

    @staticmethod
    def _denials_last_day() -> int:
        """Отказы доступа за последние 24 часа (по журналу аудита)."""
        border = datetime.now(timezone.utc) - timedelta(days=1)
        db = DatabaseManager()
        try:
            items = db.mcp.list_access_denials(limit=500)
        finally:
            db.close()
        count = 0
        for item in items:
            try:
                created = datetime.fromisoformat(str(item.get("created_at")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)   # SQLite CURRENT_TIMESTAMP хранит UTC
            if created >= border:
                count += 1
        return count

    def _on_card_clicked(self, card_widget):
        if card_widget not in self.cards:
            return
        self._select_row(self.cards.index(card_widget), reload_fields=True)
        self.refresh_audit()

    def _select_row(self, row: int, reload_fields: bool = True):
        self.current_row = row
        for index, server_card in enumerate(self.cards):
            server_card.set_selected(index == row)
        if reload_fields:
            self._on_selection_changed()
        else:
            servers = self._servers()
            if 0 <= row < len(servers):
                self._show_header(normalize_server_config(servers[row]), self._status_by_server().get(
                    normalize_server_config(servers[row]).get("name", ""), {}))

    def _show_header(self, server, status):
        """Шапка деталей: иконка, имя, бейдж статуса и строка команды."""
        if not server:
            self.title_label.setText("Сервер не выбран")
            self.cmdline_label.setText("")
            self.status_badge.set("Нет данных", "idle")
            self.big_icon.icon_name, self.big_icon.kind = "mdi6.server-outline", "idle"
            self.big_icon.update()
            return
        text, kind = _status_view(status.get("status"))
        self.title_label.setText(server.get("name", ""))
        self.title_label.setToolTip(server.get("name", ""))
        line = " ".join([str(server.get("command") or server.get("url") or ""), *[str(a) for a in server.get("args") or []]]).strip()
        self.cmdline_label.setText(line)
        self.cmdline_label.setToolTip(line)
        self.status_badge.set(text, kind)
        self.big_icon.icon_name = "mdi6.web" if server.get("transport", "stdio") != "stdio" else "mdi6.console"
        self.big_icon.kind = kind
        self.big_icon.update()

    def _on_selection_changed(self):
        servers = self._servers()
        if self.current_row < 0 or self.current_row >= len(servers):
            return
        server = normalize_server_config(servers[self.current_row])
        self.transport.setCurrentText(server["transport"] if server["transport"] in {"stdio", "sse", "streamable_http"} else "stdio")
        self.command.setText(server["command"])
        self.args.setPlainText("\n".join(server["args"]))
        self.cwd.setText(server["cwd"])
        self.url.setText(server["url"])
        self.env.setPlainText(json.dumps(server["env"], ensure_ascii=False, indent=2))
        self.server_enabled.setChecked(server["enabled"])
        self.auto_start.setChecked(server["auto_start"])
        self._set_access_checks(server["access"])
        self.description.setPlainText(server["description"])
        tools = server.get("tools") or []
        self._set_tools(tools)
        resources = {
            "resources": server.get("resources") or [],
            "resource_templates": server.get("resource_templates") or [],
        }
        has_resources = resources["resources"] or resources["resource_templates"]
        self.resources_preview.setPlainText(json.dumps(resources, ensure_ascii=False, indent=2) if has_resources else "")
        prompts = server.get("prompts") or []
        self.prompts_preview.setPlainText(json.dumps(prompts, ensure_ascii=False, indent=2) if prompts else "")
        self._show_header(server, self._status_by_server().get(server.get("name", ""), {}))
        self.refresh_audit()

    def add_server(self):
        name, ok = prompt_text(self, "Добавить MCP-сервер", "Имя сервера:")
        if not ok or not name.strip():
            return
        servers = self._servers()
        servers.append({"name": name.strip(), "enabled": False, "command": "", "args": [], "env": {}, "access": {"admin": True}})
        settings_manager.settings.setdefault("mcp", {})["servers"] = servers
        self.load_settings(select_name=name.strip(), reload_fields=True)

    def add_example_server(self):
        project_root = Path(__file__).resolve().parents[2]
        example_path = project_root / "examples" / "mcp" / "simple_snapmatch_mcp.py"
        servers = self._servers()
        existing_index = next(
            (
                index
                for index, server in enumerate(servers)
                if isinstance(server, dict) and server.get("name") == "snapmatch-simple-example"
            ),
            -1,
        )
        config = {
            "name": "snapmatch-simple-example",
            "enabled": True,
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(example_path)],
            "cwd": str(project_root),
            "env": {},
            "access": {"admin": True, "private": False, "group": False, "secretary": False},
            "auto_start": False,
            "description": "Простой локальный MCP-пример: ping, current_time, format_note, summarize_numbers.",
        }
        if existing_index >= 0:
            if not ask(
                self,
                "Пример MCP-сервера",
                "Сервер «snapmatch-simple-example» уже есть. Перезаписать его настройки примером?",
                yes="Перезаписать",
                default="no",
            ):
                return
            servers[existing_index] = {**servers[existing_index], **config}
            select_row = existing_index
        else:
            servers.append(config)
            select_row = len(servers) - 1
        settings_manager.settings.setdefault("mcp", {})["servers"] = servers
        settings_manager.save_settings()
        self.load_settings(select_row=select_row, reload_fields=True)

    def delete_server(self):
        servers = self._servers()
        if self.current_row < 0 or self.current_row >= len(servers):
            return
        name = servers[self.current_row].get("name", "") if isinstance(servers[self.current_row], dict) else ""
        if not ask(
            self,
            "Удалить MCP-сервер",
            f"Удалить MCP-сервер «{name}» из настроек?",
            yes="Удалить",
            danger=True,
        ):
            return
        del servers[self.current_row]
        settings_manager.settings.setdefault("mcp", {})["servers"] = servers
        settings_manager.save_settings()
        self.current_row = -1
        self.load_settings()

    def save_settings(self):
        servers = self._servers()
        selected_name = self._selected_server_name()
        selected_row = self.current_row
        if 0 <= self.current_row < len(servers):
            try:
                env = json.loads(self.env.toPlainText() or "{}")
                access = json.loads(self.access.toPlainText() or "{}")
            except json.JSONDecodeError as e:
                warn(self, "Ошибка", f"Некорректный JSON: {e}")
                return
            existing = dict(servers[self.current_row])
            existing.update({
                "enabled": self.server_enabled.isChecked(),
                "transport": self.transport.currentText(),
                "command": self.command.text().strip(),
                "args": self.args.toPlainText().splitlines(),
                "cwd": self.cwd.text().strip(),
                "url": self.url.text().strip(),
                "env": env,
                "auto_start": self.auto_start.isChecked(),
                "access": self._access_from_checks(access),
                "description": self.description.toPlainText().strip(),
            })
            servers[self.current_row] = normalize_server_config(existing)
        current_mcp = dict(settings_manager.settings.get("mcp") or {})
        current_mcp.update({"enabled": self.enabled.isChecked(), "servers": servers})
        settings_manager.settings["mcp"] = current_mcp
        settings_manager.save_settings()
        self.load_settings(select_row=selected_row, select_name=selected_name)
        logger.info("MCP registry settings saved")

    def discover_tools(self):
        if not is_mcp_sdk_available():
            details = get_mcp_sdk_error()
            message = "MCP Python SDK не установлен или недоступен."
            if details:
                message = f"{message}\n\nДетали: {details}"
            warn(self, "MCP SDK", message)
            return
        self.save_settings()
        servers = self._servers()
        if self.current_row < 0 or self.current_row >= len(servers):
            inform(self, "MCP", "Выберите MCP-сервер.")
            return
        # Обращение к серверу (до 20 с) идёт в фоне — окно не замирает
        row = self.current_row
        server_cfg = servers[row]
        self._run_busy(
            lambda: discover_server_capabilities(server_cfg),
            lambda caps: self._on_discovered(caps, row),
            lambda msg: warn(self, "MCP discovery", f"Не удалось проверить сервер: {msg}"),
        )

    def _run_busy(self, fn, on_done, on_error):
        """Запускает fn в фоне, пока кнопки управления серверами заблокированы."""
        buttons = (self.start_button, self.stop_button, self.discover_button)
        for button in buttons:
            button.setEnabled(False)
        self.busy.show()

        def _restore():
            self.busy.hide()
            for button in buttons:
                button.setEnabled(True)

        def _done(result):
            _restore()
            on_done(result)

        def _failed(message):
            _restore()
            on_error(message)

        run_in_background(fn, on_done=_done, on_error=_failed)

    def _on_discovered(self, capabilities, row):
        servers = self._servers()
        if row < 0 or row >= len(servers):
            return
        self.current_row = row
        discovered_tools = capabilities.get("tools") or []
        existing_tools = {
            str(tool.get("name") or "").strip(): tool
            for tool in (servers[self.current_row].get("tools") or [])
            if isinstance(tool, dict) and str(tool.get("name") or "").strip()
        }
        for tool in discovered_tools:
            if not isinstance(tool, dict):
                continue
            previous = existing_tools.get(str(tool.get("name") or "").strip())
            if previous is not None and "requires_confirmation" in previous:
                tool["requires_confirmation"] = bool(previous.get("requires_confirmation"))
        servers[self.current_row]["tools"] = discovered_tools
        servers[self.current_row]["resources"] = capabilities.get("resources") or []
        servers[self.current_row]["resource_templates"] = capabilities.get("resource_templates") or []
        servers[self.current_row]["prompts"] = capabilities.get("prompts") or []
        settings_manager.settings.setdefault("mcp", {})["servers"] = servers
        settings_manager.save_settings()
        self._set_tools(servers[self.current_row]["tools"])
        self.resources_preview.setPlainText(json.dumps({
            "resources": servers[self.current_row]["resources"],
            "resource_templates": servers[self.current_row]["resource_templates"],
        }, ensure_ascii=False, indent=2))
        self.prompts_preview.setPlainText(json.dumps(servers[self.current_row]["prompts"], ensure_ascii=False, indent=2))
        self.refresh_audit()
        self.load_settings(select_name=servers[self.current_row].get("name"))
        self._notify(
            f"Найдено: tools={len(servers[self.current_row]['tools'])}, "
            f"resources={len(servers[self.current_row]['resources'])}, "
            f"resource_templates={len(servers[self.current_row]['resource_templates'])}, "
            f"prompts={len(servers[self.current_row]['prompts'])}"
        )

    def start_server(self):
        selected_name = self._selected_server_name()
        self.save_settings()
        servers = self._servers()
        if selected_name:
            for index, server in enumerate(servers):
                if normalize_server_config(server).get("name") == selected_name:
                    self.current_row = index
                    self._select_row(index, reload_fields=False)
                    break
        if self.current_row < 0 or self.current_row >= len(servers):
            inform(self, "MCP", "Выберите MCP-сервер.")
            return
        server_cfg = servers[self.current_row]

        def _failed(message):
            warn(self, "MCP start", f"Не удалось запустить сервер: {message}")
            self.load_settings(select_name=selected_name)

        def _started(result):
            self.load_settings(select_name=selected_name)
            self._notify(f"MCP start: {result.get('status')}. {result.get('details') or ''}".strip())

        self._run_busy(lambda: start_server_process(server_cfg), _started, _failed)

    def stop_server(self):
        selected_name = self._selected_server_name()
        servers = self._servers()
        if self.current_row < 0 or self.current_row >= len(servers):
            inform(self, "MCP", "Выберите MCP-сервер.")
            return
        server_cfg = servers[self.current_row]

        def _failed(message):
            warn(self, "MCP stop", f"Не удалось остановить сервер: {message}")
            self.load_settings(select_name=selected_name)

        def _stopped(result):
            self.load_settings(select_name=selected_name)
            self._notify(f"MCP stop: {result.get('status')}. {result.get('details') or ''}".strip())

        self._run_busy(lambda: stop_server_process(server_cfg), _stopped, _failed)

    def preview_access(self):
        try:
            actor_id = int(self.preview_actor.text().strip()) if self.preview_actor.text().strip() else None
            chat_id = int(self.preview_chat.text().strip()) if self.preview_chat.text().strip() else None
        except ValueError:
            warn(self, "MCP access", "actor_telegram_id и chat_id должны быть числами.")
            return
        request_context = {
            "source_mode": self.preview_source.currentText(),
            "actor_telegram_id": actor_id,
            "chat_id": chat_id,
            "chat_type": self.preview_chat_type.currentText(),
            "is_admin": self.preview_admin.isChecked(),
            "author_is_bot": False,
        }
        tools = allowed_tools_for_context(settings_manager.get_settings(), request_context)
        self.preview_result.setPlainText(json.dumps(tools, ensure_ascii=False, indent=2))

    def refresh_audit(self):
        server_name = self._selected_server_name()
        db = DatabaseManager()
        try:
            statuses = db.mcp.list_server_statuses()
            status = next((item for item in statuses if item.get("server_name") == server_name), None) if server_name else None
            if status:
                self.status_label.setText(
                    f"Статус: {status.get('status')} | tools={status.get('tools_count')} | {status.get('updated_at')}"
                )
            else:
                self.status_label.setText("Статус: нет данных")
            text, kind = _status_view(status.get("status") if status else None)
            self.status_badge.set(text, kind)
            self.big_icon.kind = kind
            self.big_icon.update()

            calls = db.mcp.list_tool_calls(limit=20, server_name=server_name)
            denials = db.mcp.list_access_denials(limit=20, server_name=server_name)
        finally:
            db.close()

        lines = ["Последние tool calls:"]
        for item in calls:
            lines.append(
                f"- {item.get('created_at')} {item.get('server_name')}.{item.get('tool_name')} "
                f"{item.get('status')} {item.get('duration_ms') or 0}ms"
            )
            if item.get("error"):
                lines.append(f"  error: {item.get('error')}")
        lines.append("")
        lines.append("Последние отказы доступа:")
        for item in denials:
            lines.append(
                f"- {item.get('created_at')} {item.get('server_name')}.{item.get('tool_name')} "
                f"actor={item.get('actor_telegram_id')} chat={item.get('chat_id')} reason={item.get('reason')}"
            )
        self.audit_log.setPlainText("\n".join(lines))
        self._update_warning()

    def _selected_server_name(self) -> str:
        servers = self._servers()
        if self.current_row < 0 or self.current_row >= len(servers):
            return ""
        return normalize_server_config(servers[self.current_row]).get("name", "")

    def _set_access_checks(self, access):
        self._loading_access = True
        self.access_admin.setChecked(bool(access.get("admin", True)))
        self.access_private.setChecked(bool(access.get("private", False)))
        self.access_group.setChecked(bool(access.get("group", False)))
        self.access_secretary.setChecked(bool(access.get("secretary", False)))
        self._loading_access = False
        self._sync_access_json_from_checks()

    def _access_from_checks(self, current=None):
        access = dict(current or {})
        access.update({
            "admin": self.access_admin.isChecked(),
            "private": self.access_private.isChecked(),
            "group": self.access_group.isChecked(),
            "secretary": self.access_secretary.isChecked(),
        })
        return access

    def _sync_access_json_from_checks(self):
        if self._loading_access:
            return
        try:
            current = json.loads(self.access.toPlainText() or "{}")
        except json.JSONDecodeError:
            # Не затираем ручной ввод: сначала нужно исправить JSON
            warn(self, "MCP access", "Access JSON содержит ошибку. Исправьте его — флажки не изменили текст.")
            return
        self.access.setPlainText(json.dumps(self._access_from_checks(current), ensure_ascii=False, indent=2))

    def _status_by_server(self):
        db = DatabaseManager()
        try:
            return {item.get("server_name"): item for item in db.mcp.list_server_statuses()}
        finally:
            db.close()

    def _update_warning(self):
        servers = [normalize_server_config(server) for server in self._servers() if isinstance(server, dict)]
        risky = []
        for server in servers:
            access = server.get("access", {})
            if server.get("enabled") and not any(access.get(scope) for scope in ("private", "group", "secretary")):
                risky.append(server.get("name", ""))
        if risky:
            self.warning_label.setText(
                "Предупреждение: включены MCP без non-admin доступа: " + ", ".join(risky)
            )
        else:
            self.warning_label.setText("")

    def _apply_filter(self):
        needle = self.filter_input.text().strip().lower()
        for server_card, haystack in zip(self.cards, self._card_haystack):
            server_card.setVisible(not needle or needle in haystack)
