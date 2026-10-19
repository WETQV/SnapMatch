from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt
from datetime import datetime

from bot.handlers.services.prompt_manager import (
    build_system_prompt_status,
    get_available_placeholders,
    validate_system_prompt,
)
from gui.admin_panel.settings_panel import PromptEditorDialog
from gui.design import (
    Collapsible,
    FxButton,
    FxComboBox,
    Reveal,
    SwitchRow,
    card,
    icon_button,
    label,
    make_table,
    page_header,
    primary,
)
from utils.database.database_manager import DatabaseManager
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Ширина страницы, начиная с которой таблица владельцев стоит слева; уже — сверху на всю ширину
SIDE_LAYOUT_MIN_WIDTH = 980
OWNERS_SIDE_WIDTH = 340


def _tip(widget, title: str, text: str = "") -> None:
    """Подсказка: первая строка — заголовок, остальное — пояснение."""
    widget.setToolTip(f"{title}\n{text}" if text else title)


def _mono_line(placeholder: str) -> QLineEdit:
    line = QLineEdit()
    line.setObjectName("mono")
    line.setPlaceholderText(placeholder)
    return line


def _text_area(placeholder: str, min_h: int, max_h: int, read_only: bool = False) -> QPlainTextEdit:
    edit = QPlainTextEdit()
    edit.setPlaceholderText(placeholder)
    edit.setMinimumHeight(min_h)
    edit.setMaximumHeight(max_h)
    edit.setReadOnly(read_only)
    return edit


class SecretaryTab(QWidget):
    MODES = ["off", "draft", "confirm", "auto"]
    OWNER_BEHAVIORS = ["ignore", "takeover", "add_to_context", "close_session"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_owner_id = None
        self.current_chat_override_id = None
        self.secretary_prompt_history = []
        self.secretary_prompt_templates = []
        self.placeholder_defaults = {}
        self._chat_message_counts = {}
        self._loading = False       # идёт заполнение полей из БД: правки не считаются изменениями пользователя
        self._dirty = False
        self._side_layout = None
        self._init_ui()
        self._init_tooltips()
        self._connect_dirty_tracking()
        self.load_profiles()

    @staticmethod
    def _table_item(text, *, centered: bool = False):
        item = QTableWidgetItem(str(text))
        if centered:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    @staticmethod
    def _caption_field(grid: QGridLayout, row: int, col: int, caption: str, widget: QWidget, span: int = 1) -> None:
        """Поле сетки: подпись над полем."""
        grid.addWidget(label(caption, "sectionLabel"), row * 2, col, 1, span)
        grid.addWidget(widget, row * 2 + 1, col, 1, span)

    @staticmethod
    def _two_columns() -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 120)
        grid.setColumnMinimumWidth(1, 120)
        return grid

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 0)
        root.setSpacing(0)

        # ── Шапка ──
        self.add_button = icon_button("Добавить владельца", "mdi6.account-plus-outline")
        self.delete_button = icon_button("Удалить владельца", "mdi6.account-remove-outline", "danger")
        root.addLayout(page_header("Секретарь", "Автоответы от имени владельца", self.add_button, self.delete_button))
        root.addSpacing(16)

        # ── Таблица владельцев ──
        self.owners_card, owners_lay = card()
        owners_lay.addWidget(label("ВЛАДЕЛЬЦЫ", "sectionLabel"))
        self.table = make_table(["Telegram ID", "Имя", "Вкл", "Режим"])
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(150)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        owners_lay.addWidget(self.table, 1)

        # ── Правая колонка: секции-карточки ──
        self.details = QWidget()
        col = QVBoxLayout(self.details)
        col.setContentsMargins(0, 0, 0, 12)
        col.setSpacing(14)

        # Статус владельца
        status_box, status_lay = card()
        status_lay.addWidget(label("Статус владельца", "h2"))
        self.owner_label = label("Владелец не выбран", "mono")
        self.owner_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        status_lay.addWidget(self.owner_label)
        self.enabled = SwitchRow("Включить секретаря для владельца", False)
        status_lay.addWidget(self.enabled)
        self.mode = FxComboBox()
        self.mode.addItems(self.MODES)
        status_lay.addWidget(label("РЕЖИМ ОТВЕТА", "sectionLabel"))
        status_lay.addWidget(self.mode)
        col.addWidget(status_box)

        # Prompt
        prompt_box, prompt_lay = card()
        prompt_lay.addWidget(label("Prompt", "h2"))
        self.prompt = _text_area("System Prompt секретаря (пусто = без дополнительного prompt)", 82, 130, True)
        self.system_prompt_input = self.prompt
        prompt_lay.addWidget(self.prompt)
        prompt_actions = QHBoxLayout()
        prompt_actions.setSpacing(8)
        self.edit_prompt_button = icon_button("Редактировать", "mdi6.pencil-outline")
        self.validate_prompt_button = icon_button("Проверить промпт", "mdi6.check-decagram-outline")
        for button in (self.edit_prompt_button, self.validate_prompt_button):
            button.setMinimumWidth(0)
            prompt_actions.addWidget(button)
        prompt_actions.addStretch()
        prompt_lay.addLayout(prompt_actions)
        self.prompt_status_label = label("", "muted")
        self.prompt_status_label.setWordWrap(True)
        self.prompt_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        prompt_lay.addWidget(self.prompt_status_label)
        col.addWidget(prompt_box)

        # Поведение
        behavior_box, behavior_lay = card()
        behavior_lay.addWidget(label("Поведение", "h2"))
        self.save_history = SwitchRow("Сохранять secretary-историю", True)
        self.ignore_bots = SwitchRow("Игнорировать сообщения от ботов", True)
        self.media_stt = SwitchRow("Обрабатывать голосовые и кружки", False)
        self.media_images = SwitchRow("Обрабатывать фото и картинки", False)
        self.close_after_reply = SwitchRow("Закрывать сессию после auto-ответа", False)
        self.turn_based_replies = SwitchRow("Ждать новое входящее после ответа", True)
        switches = self._two_columns()
        for index, switch in enumerate((
            self.save_history, self.ignore_bots, self.media_stt, self.media_images,
            self.close_after_reply, self.turn_based_replies,
        )):
            switches.addWidget(switch, index // 2, index % 2)
        behavior_lay.addLayout(switches)

        self.default_delay = _mono_line("2.0")
        self.burst_window = _mono_line("2.0")
        self.max_batch_messages = _mono_line("10")
        self.default_session_ttl = _mono_line("3600")
        self.owner_behavior = FxComboBox()
        self.owner_behavior.addItems(self.OWNER_BEHAVIORS)
        self.allowed_chats = _text_area("Разрешенные chat_id, по одному на строку", 56, 90)
        self.blocked_chats = _text_area("Запрещенные chat_id, по одному на строку", 56, 90)
        fields = self._two_columns()
        self._caption_field(fields, 0, 0, "ЗАДЕРЖКА ОТВЕТА, СЕК", self.default_delay)
        self._caption_field(fields, 0, 1, "ОКНО ОБЪЕДИНЕНИЯ, СЕК", self.burst_window)
        self._caption_field(fields, 1, 0, "МАКС. СООБЩЕНИЙ В ПАЧКЕ", self.max_batch_messages)
        self._caption_field(fields, 1, 1, "TTL СЕССИИ, СЕК", self.default_session_ttl)
        self._caption_field(fields, 2, 0, "ПОВЕДЕНИЕ ВЛАДЕЛЬЦА", self.owner_behavior, 2)
        self._caption_field(fields, 3, 0, "РАЗРЕШЕННЫЕ ЧАТЫ", self.allowed_chats)
        self._caption_field(fields, 3, 1, "ЗАПРЕЩЕННЫЕ ЧАТЫ", self.blocked_chats)
        behavior_lay.addLayout(fields)
        col.addWidget(behavior_box)

        # Настройки отдельных чатов — раскрывающаяся секция (нужна редко)
        overrides = QWidget()
        over_lay = QVBoxLayout(overrides)
        over_lay.setContentsMargins(0, 8, 0, 0)
        over_lay.setSpacing(10)
        self.chat_override_id = QComboBox()
        self.chat_override_id.setEditable(True)
        self.chat_override_id.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        if self.chat_override_id.lineEdit():
            self.chat_override_id.lineEdit().setPlaceholderText("chat_id")
        self.chat_override_id.setMinimumWidth(120)
        self.chat_override_id.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.chat_history_count_label = label("История: 0 сообщений", "muted")
        chat_id_row = QHBoxLayout()
        chat_id_row.setSpacing(12)
        chat_id_row.addWidget(self.chat_override_id, 1)
        chat_id_row.addWidget(self.chat_history_count_label)
        over_lay.addWidget(label("ЧАТ (ID ИЛИ «ID | НАЗВАНИЕ»)", "sectionLabel"))
        over_lay.addLayout(chat_id_row)

        self.load_chat_button = icon_button("Загрузить чат", "mdi6.download-outline")
        self.save_chat_button = icon_button("Сохранить чат", "mdi6.content-save-outline")
        self.clear_chat_button = icon_button("Сбросить поля", "mdi6.eraser")
        self.clear_history_button = icon_button("Очистить историю", "mdi6.delete-sweep-outline", "danger")
        chat_buttons = self._two_columns()
        for index, button in enumerate((
            self.load_chat_button, self.save_chat_button, self.clear_chat_button, self.clear_history_button,
        )):
            button.setMinimumWidth(0)
            chat_buttons.addWidget(button, index // 2, index % 2)
        over_lay.addLayout(chat_buttons)

        self.chat_response_mode = FxComboBox()
        self.chat_response_mode.addItems(["inherit", *self.MODES])
        self.chat_prompt = _text_area("Пусто = наследовать prompt владельца", 70, 100)
        self.chat_history = FxComboBox()
        self.chat_history.addItems(["inherit", "on", "off"])
        self.chat_ttl = _mono_line("Пусто = наследовать")
        self.chat_close_after_reply = FxComboBox()
        self.chat_close_after_reply.addItems(["inherit", "on", "off"])
        self.chat_turn_based_replies = FxComboBox()
        self.chat_turn_based_replies.addItems(["inherit", "on", "off"])
        self.chat_owner_behavior = FxComboBox()
        self.chat_owner_behavior.addItems(["inherit", *self.OWNER_BEHAVIORS])
        self.chat_allowed_mcp = _text_area("Имена MCP серверов/инструментов, по одному на строку", 54, 90)
        self.chat_media_stt = FxComboBox()
        self.chat_media_stt.addItems(["inherit", "on", "off"])
        self.chat_media_images = FxComboBox()
        self.chat_media_images.addItems(["inherit", "on", "off"])
        overrides_grid = self._two_columns()
        self._caption_field(overrides_grid, 0, 0, "РЕЖИМ", self.chat_response_mode)
        self._caption_field(overrides_grid, 0, 1, "ИСТОРИЯ", self.chat_history)
        self._caption_field(overrides_grid, 1, 0, "TTL СЕССИИ, СЕК", self.chat_ttl)
        self._caption_field(overrides_grid, 1, 1, "ЗАКРЫВАТЬ ПОСЛЕ ОТВЕТА", self.chat_close_after_reply)
        self._caption_field(overrides_grid, 2, 0, "ОЧЕРЕДНОСТЬ КАК В ЛС", self.chat_turn_based_replies)
        self._caption_field(overrides_grid, 2, 1, "ПОВЕДЕНИЕ ВЛАДЕЛЬЦА", self.chat_owner_behavior)
        self._caption_field(overrides_grid, 3, 0, "ГОЛОС / STT", self.chat_media_stt)
        self._caption_field(overrides_grid, 3, 1, "ФОТО / VLM", self.chat_media_images)
        self._caption_field(overrides_grid, 4, 0, "PROMPT ЧАТА", self.chat_prompt, 2)
        self._caption_field(overrides_grid, 5, 0, "РАЗРЕШЕННЫЕ MCP", self.chat_allowed_mcp, 2)
        over_lay.addLayout(overrides_grid)
        chat_box, chat_lay = card()
        self.chat_section = Collapsible("Настройки отдельных чатов (по умолчанию наследуются)", overrides)
        chat_lay.addWidget(self.chat_section)
        col.addWidget(chat_box)

        # Журнал
        events_box, events_lay = card()
        events_lay.addWidget(label("Журнал", "h2"))
        self.events = _text_area("Последние события выбранного владельца", 120, 100000, True)
        events_lay.addWidget(self.events)
        col.addWidget(events_box)
        col.addStretch(1)

        # ── Прокрутка только по вертикали: на узком окне горизонтальной полосы нет ──
        self.scroll_content = QWidget()
        self.grid = QGridLayout(self.scroll_content)
        self.grid.setContentsMargins(0, 0, 8, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(14)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.scroll_content)
        root.addWidget(self.scroll, 1)
        self._arrange(side=False)

        # ── Панель несохранённых изменений (Reveal) ──
        self.savebar = QFrame()
        self.savebar.setObjectName("savebar")
        bar = QHBoxLayout(self.savebar)
        bar.setContentsMargins(18, 10, 18, 10)
        bar.addWidget(label("Есть несохранённые изменения", "h2"))
        bar.addStretch()
        self.discard_button = FxButton("Отменить")
        self.save_button = primary("Сохранить")
        bar.addWidget(self.discard_button)
        bar.addWidget(self.save_button)
        self.save_reveal = Reveal(self.savebar)
        root.addWidget(self.save_reveal)
        root.addSpacing(18)

        self.add_button.clicked.connect(self.add_profile)
        self.delete_button.clicked.connect(self.delete_profile)
        self.save_button.clicked.connect(self.save_profile)
        self.discard_button.clicked.connect(self.discard_changes)
        self.load_chat_button.clicked.connect(self.load_chat_override)
        self.save_chat_button.clicked.connect(self.save_chat_override)
        self.clear_chat_button.clicked.connect(self.clear_chat_override)
        self.clear_history_button.clicked.connect(self.clear_chat_history)
        self.chat_override_id.activated.connect(self._on_chat_option_selected)
        if self.chat_override_id.lineEdit():
            self.chat_override_id.lineEdit().editingFinished.connect(self._update_chat_history_count_from_input)
        self.edit_prompt_button.clicked.connect(self.open_secretary_prompt_editor)
        self.validate_prompt_button.clicked.connect(self.validate_secretary_prompt)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

    # ── Раскладка: таблица владельцев слева (широкое окно) или сверху (узкое) ──

    def _arrange(self, side: bool) -> None:
        if self._side_layout is side:
            return
        self._side_layout = side
        for widget in (self.owners_card, self.details):
            self.grid.removeWidget(widget)
        for column in range(2):
            self.grid.setColumnStretch(column, 0)
            self.grid.setColumnMinimumWidth(column, 0)
        if side:
            self.owners_card.setMinimumWidth(OWNERS_SIDE_WIDTH)
            self.owners_card.setMaximumWidth(OWNERS_SIDE_WIDTH)
            self.owners_card.setMinimumHeight(0)
            self.owners_card.setMaximumHeight(16777215)
            self.grid.addWidget(self.owners_card, 0, 0, Qt.AlignmentFlag.AlignTop)
            self.grid.addWidget(self.details, 0, 1)
            self.grid.setColumnStretch(1, 1)
        else:
            self.owners_card.setMinimumWidth(0)
            self.owners_card.setMaximumWidth(16777215)
            self.owners_card.setMinimumHeight(215)
            self.owners_card.setMaximumHeight(215)
            self.grid.addWidget(self.owners_card, 0, 0)
            self.grid.addWidget(self.details, 1, 0)
            self.grid.setColumnStretch(0, 1)
        self.owners_card.show()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._arrange(side=self.width() >= SIDE_LAYOUT_MIN_WIDTH)

    # ── Панель «есть несохранённые изменения» ──

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = bool(dirty)
        self.save_reveal.set_open(self._dirty)

    def _mark_dirty(self, *_args) -> None:
        if self._loading:
            return
        self._set_dirty(True)

    def _connect_dirty_tracking(self) -> None:
        """Любая правка поля владельца показывает панель «Сохранить / Отменить» (stateChanged у SwitchRow нет — toggled)."""
        for switch in (
            self.enabled, self.save_history, self.ignore_bots, self.media_stt, self.media_images,
            self.close_after_reply, self.turn_based_replies,
        ):
            switch.toggled.connect(self._mark_dirty)
        for combo in (self.mode, self.owner_behavior):
            combo.currentIndexChanged.connect(self._mark_dirty)
        for line in (self.default_delay, self.burst_window, self.max_batch_messages, self.default_session_ttl):
            line.textChanged.connect(self._mark_dirty)
        for edit in (self.prompt, self.allowed_chats, self.blocked_chats):
            edit.textChanged.connect(self._mark_dirty)

    def discard_changes(self) -> None:
        """Возвращает поля владельца к сохранённым значениям; несохранённая форма чата остаётся."""
        if self.current_owner_id is None:
            self._set_dirty(False)
            return
        chat_state = self._capture_chat_form()
        self._on_selection_changed()
        self._restore_chat_form(chat_state)

    def _init_tooltips(self):
        _tip(self.add_button, "Добавить владельца", "Добавить владельца, который сможет использовать бота как личного секретаря.")
        _tip(self.delete_button, "Удалить владельца", "Удалить выбранный secretary-профиль (с подтверждением).")
        _tip(self.save_button, "Сохранить", "Сохранить настройки выбранного владельца.")
        _tip(self.discard_button, "Отменить", "Вернуть поля владельца к сохранённым значениям.")
        _tip(self.table, "Владельцы", "Список владельцев secretary-профилей. Выберите строку, чтобы редактировать настройки.")
        _tip(self.enabled, "Секретарь", "Включить или выключить ответы секретаря для выбранного владельца.")
        _tip(self.mode, "Режим ответа", "off - выключено, draft - черновик, confirm - с подтверждением, auto - автоответ.")
        _tip(self.prompt, "System Prompt", "System Prompt секретаря. Он задаёт стиль и правила ответа за владельца.")
        _tip(self.edit_prompt_button, "Редактировать", "Открыть расширенный редактор System Prompt секретаря с плейсхолдерами и шаблонами.")
        _tip(self.validate_prompt_button, "Проверить промпт", "Проверить текущий secretary prompt на неизвестные плейсхолдеры и типичные проблемы.")
        _tip(self.prompt_status_label, "Статус промпта", "Статус текущего secretary prompt выбранного владельца.")
        _tip(self.save_history, "История", "Сохранять отдельную историю secretary-диалогов для контекста.")
        _tip(self.ignore_bots, "Сообщения ботов", "Не отвечать на сообщения, отправленные Telegram-ботами.")
        _tip(self.media_stt, "Голосовые", "Разрешить секретарю распознавать голосовые сообщения и кружочки через общие STT-настройки.")
        _tip(self.media_images, "Фото", "Разрешить секретарю скачивать фото/картинки и передавать их VLM-модели, если такая модель активна.")
        _tip(self.default_delay, "Задержка ответа", "Минимальная задержка перед постановкой запроса секретаря в очередь.")
        _tip(self.burst_window, "Окно объединения", "Период тишины, в течение которого быстрые сообщения объединяются в один запрос.")
        _tip(self.max_batch_messages, "Сообщений в пачке", "Максимальное число последних сообщений, которые можно объединить в один запрос.")
        _tip(self.default_session_ttl, "TTL сессии", "Время жизни сессии в секундах. 0 означает бесконечную сессию.")
        _tip(self.close_after_reply, "Закрывать сессию", "Если включено, auto-ответ закрывает текущую сессию после отправки.")
        _tip(
            self.turn_based_replies, "Очередность ответов",
            "Если включено, секретарь игнорирует исходящие business-сообщения владельца/бота "
            "и ждёт новое входящее сообщение собеседника перед следующим ответом.",
        )
        _tip(self.owner_behavior, "Поведение владельца", "Что делать, если владелец пишет в secretary-чате: ignore, takeover, add_to_context или close_session.")
        _tip(self.allowed_chats, "Разрешённые чаты", "Если заполнено, секретарь отвечает только в этих chat_id. Один ID на строку.")
        _tip(self.blocked_chats, "Запрещённые чаты", "Секретарь не отвечает в этих chat_id. Один ID на строку.")
        _tip(self.chat_override_id, "chat_id", "chat_id, для которого нужно загрузить или сохранить override.")
        _tip(self.chat_history_count_label, "История чата", "Количество сохранённых secretary-сообщений для выбранного chat_id.")
        _tip(self.load_chat_button, "Загрузить чат", "Загрузить per-chat override выбранного владельца.")
        _tip(self.save_chat_button, "Сохранить чат", "Сохранить override для указанного chat_id.")
        _tip(self.clear_chat_button, "Сбросить поля", "Сбросить поля редактора. Существующую запись в базе не удаляет.")
        _tip(self.clear_history_button, "Очистить историю", "Удалить secretary-историю выбранного chat_id и закрыть активную сессию этого чата.")
        _tip(
            self.chat_response_mode, "Режим чата",
            "Режим ответа для конкретного чата:\n"
            "inherit - использовать режим владельца;\n"
            "off - не отвечать;\n"
            "draft - только сохранять черновик;\n"
            "confirm - спрашивать подтверждение;\n"
            "auto - отправлять автоматически.",
        )
        _tip(self.chat_prompt, "Prompt чата", "System Prompt только для указанного chat_id. Пустое поле означает наследование prompt владельца.")
        _tip(self.chat_history, "История чата", "inherit - наследовать настройку истории владельца, on - сохранять историю, off - не сохранять.")
        _tip(self.chat_ttl, "TTL чата", "TTL сессии для этого chat_id в секундах. Пустое поле означает наследование значения владельца.")
        _tip(self.chat_close_after_reply, "Закрывать после ответа", "inherit - наследовать, on - закрывать сессию после auto-ответа, off - не закрывать.")
        _tip(
            self.chat_turn_based_replies, "Очередность как в ЛС",
            "inherit - наследовать, on - отвечать только после нового входящего собеседника, "
            "off - разрешить старое поведение.",
        )
        _tip(
            self.chat_owner_behavior, "Поведение владельца в чате",
            "Поведение при сообщении владельца в этом чате:\n"
            "inherit - наследовать;\n"
            "ignore - игнорировать;\n"
            "takeover - считать, что владелец перехватил диалог;\n"
            "add_to_context - добавить к контексту;\n"
            "close_session - закрыть текущую сессию.",
        )
        _tip(
            self.chat_allowed_mcp, "Разрешённые MCP",
            "Ограничение MCP для этого чата. По одному значению на строку:\n"
            "server_name - разрешить весь сервер;\n"
            "tool_name - разрешить tool с таким именем;\n"
            "server_name__tool_name - разрешить конкретный tool конкретного сервера.\n"
            "Пусто = наследовать общий доступ.",
        )
        _tip(self.chat_media_stt, "Голос/STT в чате", "inherit - использовать настройку владельца, on/off - переопределить STT для этого чата.")
        _tip(self.chat_media_images, "Фото/VLM в чате", "inherit - использовать настройку владельца, on/off - переопределить обработку фото для этого чата.")
        _tip(self.events, "Журнал", "Последние события secretary-flow для выбранного владельца.")

    def load_profiles(self, select_owner_id: int | None = None):
        db = DatabaseManager()
        try:
            profiles = db.secretary.list_profiles()
            # Имена владельцев берём через уже открытое соединение (раньше — новое на каждую строку)
            display_names = [self._profile_display_name(p, db) for p in profiles]
        finally:
            db.close()
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(profiles))
        selected_row = -1
        for row, profile in enumerate(profiles):
            owner_id = int(profile.get("owner_telegram_id"))
            if select_owner_id is not None and owner_id == select_owner_id:
                selected_row = row
            self.table.setItem(row, 0, self._table_item(owner_id))
            self.table.setItem(row, 1, self._table_item(display_names[row]))
            self.table.setItem(row, 2, self._table_item("да" if profile.get("enabled") else "нет", centered=True))
            self.table.setItem(row, 3, self._table_item(profile.get("response_mode") or "draft", centered=True))
        self.table.setUpdatesEnabled(True)
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        elif profiles:
            self.table.selectRow(0)
        else:
            self.owner_label.setText("Владелец не выбран")
            self._set_dirty(False)

    def _on_selection_changed(self):
        row = self.table.currentRow()
        if row < 0:
            return
        owner_item = self.table.item(row, 0)
        if not owner_item:
            return
        self.current_owner_id = int(owner_item.text())
        name_item = self.table.item(row, 1)
        owner_name = name_item.text() if name_item else ""
        self.owner_label.setText(f"{self.current_owner_id}" + (f" · {owner_name}" if owner_name else ""))
        db = DatabaseManager()
        try:
            profile = db.secretary.get_profile(self.current_owner_id) or {}
            events = db.secretary.list_events(self.current_owner_id)
            recent_chats = db.secretary.list_recent_chats(self.current_owner_id)
            prompt_history = db.secretary.list_prompt_history(self.current_owner_id)
            prompt_templates = db.secretary.list_prompt_templates(self.current_owner_id)
        finally:
            db.close()
        self._loading = True
        try:
            self._fill_profile_fields(profile, prompt_history, prompt_templates)
        finally:
            self._loading = False
        self._refresh_chat_options(recent_chats)
        self._reset_chat_override_form()
        self.events.setPlainText(self._format_events(events))
        self._set_dirty(False)

    def _fill_profile_fields(self, profile, prompt_history, prompt_templates):
        self.enabled.setChecked(bool(profile.get("enabled")))
        self.mode.setCurrentText(profile.get("response_mode") or "draft")
        self.prompt.setPlainText(profile.get("system_prompt") or "")
        self.secretary_prompt_history = list(prompt_history or [])
        self.secretary_prompt_templates = list(prompt_templates or [])
        self.refresh_secretary_prompt_status(profile.get("updated_at") or "")
        self.save_history.setChecked(bool(profile.get("save_history", 1)))
        self.ignore_bots.setChecked(bool(profile.get("ignore_bot_messages", 1)))
        self.media_stt.setChecked(bool(profile.get("media_stt_enabled", 0)))
        self.media_images.setChecked(bool(profile.get("media_images_enabled", 0)))
        self.default_delay.setText(str(profile.get("default_delay_seconds", 2.0)))
        self.burst_window.setText(str(profile.get("burst_window_seconds", 2.0)))
        self.max_batch_messages.setText(str(profile.get("max_batch_messages", 10)))
        ttl_value = profile.get("default_session_ttl_seconds")
        self.default_session_ttl.setText(str(3600 if ttl_value is None else ttl_value))
        self.close_after_reply.setChecked(bool(profile.get("close_after_reply", 0)))
        self.turn_based_replies.setChecked(bool(profile.get("turn_based_replies", 1)))
        owner_behavior = profile.get("owner_message_behavior") or "takeover"
        self.owner_behavior.setCurrentText(owner_behavior if owner_behavior in self.OWNER_BEHAVIORS else "takeover")
        self.allowed_chats.setPlainText(profile.get("allowed_chats") or "")
        self.blocked_chats.setPlainText(profile.get("blocked_chats") or "")

    def add_profile(self):
        owner_id, ok = QInputDialog.getText(self, "Добавить владельца", "Telegram ID владельца:")
        if not ok:
            return
        try:
            owner_id_int = int(owner_id.strip())
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Telegram ID должен быть числом.")
            return
        db = DatabaseManager()
        try:
            user = db.users.get_user_by_telegram_id(owner_id_int)
            display_name = self._user_display_name(user) if user else ""
            db.secretary.upsert_profile(
                owner_id_int,
                owner_display_name=display_name,
                response_mode="draft",
                save_history=1,
                ignore_bot_messages=1,
            )
        finally:
            db.close()
        self.load_profiles(select_owner_id=owner_id_int)

    @staticmethod
    def _format_events(events):
        lines = []
        for event in events:
            created_at = event.get("created_at") or ""
            status = event.get("status") or ""
            chat_id = event.get("chat_id")
            details = event.get("details") or ""
            chat_part = f" chat={chat_id}" if chat_id is not None else ""
            lines.append(f"{created_at} [{status}]{chat_part} {details}".strip())
        return "\n".join(lines)

    def refresh_secretary_prompt_status(self, updated_at: str = ""):
        self.prompt_status_label.setText(
            build_system_prompt_status(self.prompt.toPlainText(), updated_at)
        )

    def open_secretary_prompt_editor(self):
        if self.current_owner_id is None:
            QMessageBox.warning(self, "Ошибка", "Сначала выберите владельца.")
            return
        try:
            dialog = PromptEditorDialog(
                self,
                self.prompt.toPlainText(),
                self.placeholder_defaults,
                self.secretary_prompt_history,
                self.secretary_prompt_templates,
                panel_adapter=self,
                placeholder_provider=lambda: get_available_placeholders(include_secretary=True),
                title="Редактор System Prompt секретаря",
                show_defaults=False,
            )
            dialog.exec()
        except Exception as exc:
            logger.error("Не удалось открыть редактор secretary prompt: %s", exc)
            QMessageBox.warning(self, "Ошибка", "Не удалось открыть редактор secretary prompt.")

    def validate_secretary_prompt(self):
        self.show_prompt_validation_result(self.prompt.toPlainText())

    def show_prompt_validation_result(self, prompt, parent_widget=None):
        is_valid, warnings, recommendations = validate_system_prompt(prompt, include_secretary=True)
        if is_valid and not warnings:
            message = "Промпт выглядит корректно."
            if recommendations:
                message += "\n\nРекомендации:\n- " + "\n- ".join(recommendations)
            QMessageBox.information(parent_widget or self, "Проверка", message)
            return

        parts = []
        if warnings:
            parts.append("Предупреждения:\n- " + "\n- ".join(warnings))
        if recommendations:
            parts.append("Рекомендации:\n- " + "\n- ".join(recommendations))
        QMessageBox.warning(parent_widget or self, "Проверка", "\n\n".join(parts) or "Промпт требует внимания.")

    def append_prompt_history(self, history, prompt_text):
        text = (prompt_text or "").rstrip()
        if not text.strip():
            return list(history or [])
        updated_history = list(history or [])
        if updated_history and updated_history[-1].get("text", "") == text:
            return updated_history
        updated_history.append({
            "text": text,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        return updated_history[-PromptEditorDialog.HISTORY_LIMIT:]

    def apply_prompt_editor_state(self, prompt_text, placeholder_defaults, history, templates):
        self.secretary_prompt_history = list(history or [])
        self.secretary_prompt_templates = list(templates or [])
        self.placeholder_defaults = dict(placeholder_defaults or {})
        self.prompt.setPlainText(prompt_text or "")
        self.refresh_secretary_prompt_status()

    def persist_prompt_editor_state(self, prompt_text=None, placeholder_defaults=None, history=None, templates=None):
        if self.current_owner_id is None:
            return
        if placeholder_defaults is not None:
            self.placeholder_defaults = dict(placeholder_defaults or {})
        if history is not None:
            self.secretary_prompt_history = list(history or [])
        if templates is not None:
            self.secretary_prompt_templates = list(templates or [])
        if prompt_text is not None:
            # Текст уже записывается в БД ниже: само по себе это не «несохранённая правка»
            was_loading = self._loading
            self._loading = True
            try:
                self.prompt.setPlainText(prompt_text or "")
            finally:
                self._loading = was_loading

        active_prompt = self.prompt.toPlainText().strip()
        db = DatabaseManager()
        try:
            if prompt_text is not None:
                db.secretary.upsert_profile(self.current_owner_id, system_prompt=active_prompt)
            db.secretary.save_prompt_history(
                self.current_owner_id,
                self.secretary_prompt_history[-PromptEditorDialog.HISTORY_LIMIT:],
            )
            db.secretary.save_prompt_templates(self.current_owner_id, self.secretary_prompt_templates)
        finally:
            db.close()
        if prompt_text is not None:
            self.refresh_secretary_prompt_status(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def _validate_profile_numbers(self) -> bool:
        """Некорректные числа не подменяются молча значением по умолчанию — показываем предупреждение."""
        checks = (
            ("Задержка по умолчанию", self.default_delay.text(), float),
            ("Окно серии сообщений", self.burst_window.text(), float),
            ("Макс. сообщений в пачке", self.max_batch_messages.text(), int),
            ("TTL сессии по умолчанию", self.default_session_ttl.text(), int),
        )
        for label, text, kind in checks:
            try:
                kind(str(text).strip().replace(",", ".") if kind is float else str(text).strip())
            except (TypeError, ValueError):
                QMessageBox.warning(self, "Некорректное значение", f"Поле «{label}»: «{text}» не является числом. Профиль не сохранён.")
                return False
        return True

    def _capture_chat_form(self):
        return {
            "id": self.current_chat_override_id,
            "chat_id_text": self.chat_override_id.currentText(),
            "history_label": self.chat_history_count_label.text(),
            "mode": self.chat_response_mode.currentText(),
            "prompt": self.chat_prompt.toPlainText(),
            "history": self.chat_history.currentText(),
            "ttl": self.chat_ttl.text(),
            "close": self.chat_close_after_reply.currentText(),
            "turn": self.chat_turn_based_replies.currentText(),
            "owner": self.chat_owner_behavior.currentText(),
            "mcp": self.chat_allowed_mcp.toPlainText(),
            "stt": self.chat_media_stt.currentText(),
            "images": self.chat_media_images.currentText(),
        }

    def _restore_chat_form(self, state):
        self.current_chat_override_id = state["id"]
        self.chat_override_id.setCurrentText(state["chat_id_text"])
        self.chat_history_count_label.setText(state["history_label"])
        self.chat_response_mode.setCurrentText(state["mode"])
        self.chat_prompt.setPlainText(state["prompt"])
        self.chat_history.setCurrentText(state["history"])
        self.chat_ttl.setText(state["ttl"])
        self.chat_close_after_reply.setCurrentText(state["close"])
        self.chat_turn_based_replies.setCurrentText(state["turn"])
        self.chat_owner_behavior.setCurrentText(state["owner"])
        self.chat_allowed_mcp.setPlainText(state["mcp"])
        self.chat_media_stt.setCurrentText(state["stt"])
        self.chat_media_images.setCurrentText(state["images"])

    def save_profile(self):
        if self.current_owner_id is None:
            return
        if not self._validate_profile_numbers():
            return
        db = DatabaseManager()
        try:
            db.secretary.upsert_profile(
                self.current_owner_id,
                enabled=int(self.enabled.isChecked()),
                response_mode=self.mode.currentText(),
                system_prompt=self.prompt.toPlainText().strip(),
                save_history=int(self.save_history.isChecked()),
                ignore_bot_messages=int(self.ignore_bots.isChecked()),
                media_stt_enabled=int(self.media_stt.isChecked()),
                media_images_enabled=int(self.media_images.isChecked()),
                default_delay_seconds=self._parse_nonnegative_float(self.default_delay.text(), default=2.0),
                burst_window_seconds=self._parse_nonnegative_float(self.burst_window.text(), default=2.0),
                max_batch_messages=self._parse_positive_int(self.max_batch_messages.text(), default=10, minimum=1),
                default_session_ttl_seconds=self._parse_positive_int(self.default_session_ttl.text(), default=3600, minimum=0),
                close_after_reply=int(self.close_after_reply.isChecked()),
                turn_based_replies=int(self.turn_based_replies.isChecked()),
                owner_message_behavior=self.owner_behavior.currentText(),
                allowed_chats=self.allowed_chats.toPlainText().strip(),
                blocked_chats=self.blocked_chats.toPlainText().strip(),
            )
        finally:
            db.close()
        # Перезагрузка таблицы пере-выбирает строку и сбрасывает форму чата — сохраняем несохранённый ввод
        chat_state = self._capture_chat_form()
        owner_id = self.current_owner_id
        self.load_profiles(select_owner_id=owner_id)
        if self.current_owner_id == owner_id:
            self._restore_chat_form(chat_state)
        self._set_dirty(False)

    def delete_profile(self):
        if self.current_owner_id is None:
            return
        reply = QMessageBox.question(
            self,
            "Удалить владельца",
            f"Удалить secretary-профиль владельца {self.current_owner_id}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        db = DatabaseManager()
        try:
            db.secretary.delete_profile(self.current_owner_id)
        finally:
            db.close()
        self.current_owner_id = None
        self._set_dirty(False)
        self.load_profiles()

    @staticmethod
    def _parse_positive_int(text: str, *, default: int, minimum: int = 1) -> int:
        try:
            return max(minimum, int(str(text).strip()))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_nonnegative_float(text: str, *, default: float) -> float:
        try:
            return max(0.0, float(str(text).strip().replace(",", ".")))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _nullable_combo_value(combo: QComboBox):
        value = combo.currentText()
        return None if value == "inherit" else value

    @staticmethod
    def _nullable_bool_combo_value(combo: QComboBox):
        value = combo.currentText()
        if value == "inherit":
            return None
        return 1 if value == "on" else 0

    def _reset_chat_override_form(self):
        self.current_chat_override_id = None
        self.chat_override_id.setCurrentText("")
        self._set_chat_history_count(None)
        self.chat_response_mode.setCurrentText("inherit")
        self.chat_prompt.clear()
        self.chat_history.setCurrentText("inherit")
        self.chat_ttl.clear()
        self.chat_close_after_reply.setCurrentText("inherit")
        self.chat_turn_based_replies.setCurrentText("inherit")
        self.chat_owner_behavior.setCurrentText("inherit")
        self.chat_allowed_mcp.clear()
        self.chat_media_stt.setCurrentText("inherit")
        self.chat_media_images.setCurrentText("inherit")

    def _refresh_chat_options(self, chats):
        current_text = self.chat_override_id.currentText().strip()
        self._chat_message_counts = {}
        self.chat_override_id.blockSignals(True)
        self.chat_override_id.clear()
        for chat in chats:
            chat_id = chat.get("chat_id")
            if chat_id is None:
                continue
            title = chat.get("chat_title") or ""
            count = int(chat.get("message_count") or 0)
            self._chat_message_counts[int(chat_id)] = count
            marker = "override" if chat.get("has_override") else "история"
            label_parts = [str(chat_id)]
            if title:
                label_parts.append(title)
            label_parts.append(f"{marker}, {count} сообщ.")
            self.chat_override_id.addItem(" | ".join(label_parts), str(chat_id))
        self.chat_override_id.setCurrentText(current_text)
        self.chat_override_id.blockSignals(False)
        self._update_chat_history_count_from_input()

    def _on_chat_option_selected(self, index: int):
        data = self.chat_override_id.itemData(index)
        if data is not None:
            self.chat_override_id.setCurrentText(str(data))
        self._update_chat_history_count_from_input()

    def _set_chat_history_count(self, count):
        if count is None:
            self.chat_history_count_label.setText("История: -")
            return
        self.chat_history_count_label.setText(f"История: {int(count)} сообщений")

    def _lookup_chat_message_count(self, chat_id: int) -> int:
        if chat_id in self._chat_message_counts:
            return int(self._chat_message_counts.get(chat_id) or 0)
        if self.current_owner_id is None:
            return 0
        db = DatabaseManager()
        try:
            count = db.secretary.count_chat_messages(self.current_owner_id, chat_id)
        finally:
            db.close()
        self._chat_message_counts[chat_id] = count
        return count

    def _update_chat_history_count_from_input(self):
        text = self._chat_id_text()
        if not text:
            self._set_chat_history_count(None)
            return
        try:
            chat_id = int(text)
        except ValueError:
            self._set_chat_history_count(None)
            return
        self._set_chat_history_count(self._lookup_chat_message_count(chat_id))

    def _chat_id_text(self) -> str:
        text = self.chat_override_id.currentText().strip()
        if "|" in text:
            text = text.split("|", 1)[0].strip()
        if not text:
            data = self.chat_override_id.currentData()
            text = str(data or "").strip()
        return text

    def _read_chat_id(self):
        if self.current_owner_id is None:
            QMessageBox.warning(self, "Ошибка", "Сначала выберите владельца.")
            return None
        try:
            return int(self._chat_id_text())
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "chat_id должен быть числом.")
            return None

    def load_chat_override(self):
        chat_id = self._read_chat_id()
        if chat_id is None:
            return
        db = DatabaseManager()
        try:
            settings = db.secretary.get_chat_settings(self.current_owner_id, chat_id) or {}
        finally:
            db.close()
        self.current_chat_override_id = chat_id
        self.chat_override_id.setCurrentText(str(chat_id))
        self._set_chat_history_count(self._lookup_chat_message_count(chat_id))
        self.chat_response_mode.setCurrentText(settings.get("response_mode") or "inherit")
        self.chat_prompt.setPlainText(settings.get("system_prompt") or "")
        history_enabled = settings.get("history_enabled")
        self.chat_history.setCurrentText("inherit" if history_enabled is None else ("on" if history_enabled else "off"))
        self.chat_ttl.setText("" if settings.get("session_ttl_seconds") is None else str(settings.get("session_ttl_seconds")))
        close_after_reply = settings.get("close_after_reply")
        self.chat_close_after_reply.setCurrentText("inherit" if close_after_reply is None else ("on" if close_after_reply else "off"))
        turn_based_replies = settings.get("turn_based_replies")
        self.chat_turn_based_replies.setCurrentText("inherit" if turn_based_replies is None else ("on" if turn_based_replies else "off"))
        behavior = settings.get("owner_message_behavior") or "inherit"
        self.chat_owner_behavior.setCurrentText(behavior if behavior in ["inherit", *self.OWNER_BEHAVIORS] else "inherit")
        self.chat_allowed_mcp.setPlainText(settings.get("allowed_mcp") or "")
        media_stt = settings.get("media_stt_enabled")
        self.chat_media_stt.setCurrentText("inherit" if media_stt is None else ("on" if media_stt else "off"))
        media_images = settings.get("media_images_enabled")
        self.chat_media_images.setCurrentText("inherit" if media_images is None else ("on" if media_images else "off"))
        QMessageBox.information(self, "Готово", "Настройки чата загружены.")

    def save_chat_override(self):
        chat_id = self._read_chat_id()
        if chat_id is None:
            return
        ttl_text = self.chat_ttl.text().strip()
        if ttl_text:
            try:
                int(ttl_text)
            except ValueError:
                QMessageBox.warning(self, "Некорректное значение", f"TTL чата: «{ttl_text}» не является целым числом. Настройки чата не сохранены.")
                return
        ttl_value = self._parse_positive_int(ttl_text, default=3600, minimum=0) if ttl_text else None
        prompt_text = self.chat_prompt.toPlainText().strip()
        db = DatabaseManager()
        try:
            db.secretary.upsert_chat_settings(
                self.current_owner_id,
                chat_id,
                response_mode=self._nullable_combo_value(self.chat_response_mode),
                system_prompt=prompt_text if prompt_text else None,
                history_enabled=self._nullable_bool_combo_value(self.chat_history),
                session_ttl_seconds=ttl_value,
                close_after_reply=self._nullable_bool_combo_value(self.chat_close_after_reply),
                turn_based_replies=self._nullable_bool_combo_value(self.chat_turn_based_replies),
                owner_message_behavior=self._nullable_combo_value(self.chat_owner_behavior),
                allowed_mcp=self.chat_allowed_mcp.toPlainText().strip() or None,
                media_stt_enabled=self._nullable_bool_combo_value(self.chat_media_stt),
                media_images_enabled=self._nullable_bool_combo_value(self.chat_media_images),
            )
            db.secretary.add_event(self.current_owner_id, "updated", f"chat override saved chat_id={chat_id}", chat_id=chat_id)
        finally:
            db.close()
        QMessageBox.information(self, "Сохранено", "Настройки чата сохранены.")

    def clear_chat_override(self):
        self._reset_chat_override_form()

    def clear_chat_history(self):
        chat_id = self._read_chat_id()
        if chat_id is None:
            return
        reply = QMessageBox.question(
            self,
            "Очистить историю",
            f"Удалить secretary-историю chat_id={chat_id} и закрыть активную сессию этого чата?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        db = DatabaseManager()
        try:
            deleted_count = db.messages.delete_secretary_context(self.current_owner_id, chat_id=chat_id)
            session = db.secretary.get_active_session(self.current_owner_id, chat_id)
            if session and session.get("id"):
                db.secretary.close_session(int(session["id"]), reason="gui_chat_history_clear")
            db.secretary.add_event(
                self.current_owner_id,
                "context_reset",
                f"chat history cleared from GUI deleted={deleted_count}",
                chat_id=chat_id,
            )
            recent_chats = db.secretary.list_recent_chats(self.current_owner_id)
            events = db.secretary.list_events(self.current_owner_id)
        finally:
            db.close()

        try:
            from utils.history_manager import reset_history_cache

            reset_history_cache()
        except Exception as exc:
            logger.warning("Не удалось сбросить history cache после очистки secretary-чата: %s", exc)

        self._refresh_chat_options(recent_chats)
        self._reset_chat_override_form()
        self.chat_override_id.setCurrentText(str(chat_id))
        self._chat_message_counts[chat_id] = 0
        self._set_chat_history_count(0)
        self.events.setPlainText(self._format_events(events))
        QMessageBox.information(self, "Готово", f"Удалено сообщений: {deleted_count}.")

    @staticmethod
    def _user_display_name(user):
        if not user:
            return ""
        full_name = " ".join(part for part in [user.get("first_name") or "", user.get("last_name") or ""] if part).strip()
        return full_name or user.get("username") or ""

    def _profile_display_name(self, profile, db=None):
        display_name = profile.get("owner_display_name") or ""
        if display_name:
            return display_name
        try:
            owner_db = db or DatabaseManager()
            try:
                user = owner_db.users.get_user_by_telegram_id(int(profile.get("owner_telegram_id")))
            finally:
                if db is None:
                    owner_db.close()
            return self._user_display_name(user)
        except Exception:
            return ""
