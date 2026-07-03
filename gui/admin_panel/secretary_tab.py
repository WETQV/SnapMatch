from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
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
from utils.database.database_manager import DatabaseManager
from utils.logger import setup_logger

logger = setup_logger(__name__)


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
        self._init_ui()
        self._init_tooltips()
        self.load_profiles()

    @staticmethod
    def _table_item(text, *, centered: bool = False):
        item = QTableWidgetItem(str(text))
        if centered:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _init_ui(self):
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.add_button = QPushButton("Добавить владельца")
        self.delete_button = QPushButton("Удалить владельца")
        self.save_button = QPushButton("Сохранить")
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.delete_button)
        toolbar.addWidget(self.save_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Telegram ID", "Имя", "Включен", "Режим"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        left_layout.addWidget(self.table)
        splitter.addWidget(left_widget)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        right_content = QWidget()
        right_content.setMinimumWidth(640)
        right_layout = QVBoxLayout(right_content)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(10)
        status_group = QGroupBox("Статус владельца")
        status_form = QFormLayout(status_group)
        status_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.enabled = QCheckBox("Включить секретаря для владельца")
        self.mode = QComboBox()
        self.mode.addItems(self.MODES)
        status_form.addRow("Секретарь:", self.enabled)
        status_form.addRow("Режим ответа:", self.mode)
        right_layout.addWidget(status_group)

        prompt_group = QGroupBox("Prompt")
        prompt_layout = QVBoxLayout(prompt_group)
        prompt_row = QHBoxLayout()
        self.prompt = QTextEdit()
        self.prompt.setReadOnly(True)
        self.prompt.setPlaceholderText("System Prompt секретаря (пусто = без дополнительного prompt)")
        self.prompt.setMinimumHeight(82)
        self.prompt.setMaximumHeight(110)
        self.system_prompt_input = self.prompt
        prompt_actions = QVBoxLayout()
        self.edit_prompt_button = QPushButton("Редактировать")
        self.validate_prompt_button = QPushButton("Проверить промпт")
        prompt_actions.addStretch(1)
        prompt_actions.addWidget(self.edit_prompt_button)
        prompt_actions.addWidget(self.validate_prompt_button)
        prompt_actions.addStretch(1)
        prompt_row.addWidget(self.prompt, 1)
        prompt_row.addLayout(prompt_actions)
        prompt_layout.addLayout(prompt_row)
        self.prompt_status_label = QLabel()
        self.prompt_status_label.setWordWrap(True)
        self.prompt_status_label.setStyleSheet("color: #9AA6B2; font-size: 11px;")
        prompt_layout.addWidget(self.prompt_status_label)
        right_layout.addWidget(prompt_group)

        behavior_group = QGroupBox("Поведение")
        behavior_form = QFormLayout(behavior_group)
        behavior_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.save_history = QCheckBox("Сохранять secretary-историю")
        self.ignore_bots = QCheckBox("Игнорировать сообщения от ботов")
        self.media_stt = QCheckBox("Обрабатывать голосовые и кружки")
        self.media_images = QCheckBox("Обрабатывать фото и картинки")
        self.default_delay = QLineEdit()
        self.default_delay.setPlaceholderText("2.0")
        self.burst_window = QLineEdit()
        self.burst_window.setPlaceholderText("2.0")
        self.max_batch_messages = QLineEdit()
        self.max_batch_messages.setPlaceholderText("10")
        self.default_session_ttl = QLineEdit()
        self.default_session_ttl.setPlaceholderText("3600")
        self.close_after_reply = QCheckBox("Закрывать сессию после auto-ответа")
        self.turn_based_replies = QCheckBox("Ждать новое входящее после ответа")
        self.owner_behavior = QComboBox()
        self.owner_behavior.addItems(self.OWNER_BEHAVIORS)
        self.allowed_chats = QTextEdit()
        self.allowed_chats.setPlaceholderText("Разрешенные chat_id, по одному на строку")
        self.allowed_chats.setMinimumHeight(52)
        self.allowed_chats.setMaximumHeight(70)
        self.blocked_chats = QTextEdit()
        self.blocked_chats.setPlaceholderText("Запрещенные chat_id, по одному на строку")
        self.blocked_chats.setMinimumHeight(52)
        self.blocked_chats.setMaximumHeight(70)
        behavior_flags = QWidget()
        behavior_flags_layout = QGridLayout(behavior_flags)
        behavior_flags_layout.setContentsMargins(0, 0, 0, 0)
        behavior_flags_layout.setHorizontalSpacing(18)
        behavior_flags_layout.setVerticalSpacing(6)
        behavior_flags_layout.addWidget(self.save_history, 0, 0)
        behavior_flags_layout.addWidget(self.ignore_bots, 0, 1)
        behavior_flags_layout.addWidget(self.media_stt, 1, 0)
        behavior_flags_layout.addWidget(self.media_images, 1, 1)
        behavior_form.addRow("", behavior_flags)
        behavior_form.addRow("Задержка ответа, сек:", self.default_delay)
        behavior_form.addRow("Окно объединения, сек:", self.burst_window)
        behavior_form.addRow("Макс. сообщений в пачке:", self.max_batch_messages)
        behavior_form.addRow("TTL сессии, сек:", self.default_session_ttl)
        behavior_form.addRow("", self.close_after_reply)
        behavior_form.addRow("", self.turn_based_replies)
        behavior_form.addRow("Поведение владельца:", self.owner_behavior)
        behavior_form.addRow("Разрешенные чаты:", self.allowed_chats)
        behavior_form.addRow("Запрещенные чаты:", self.blocked_chats)
        right_layout.addWidget(behavior_group)

        chat_group = QGroupBox("Настройки отдельных чатов")
        chat_form = QFormLayout(chat_group)
        chat_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        chat_toolbar_widget = QWidget()
        chat_toolbar = QVBoxLayout(chat_toolbar_widget)
        chat_toolbar.setContentsMargins(0, 0, 0, 0)
        chat_toolbar.setSpacing(8)
        chat_buttons_row = QHBoxLayout()
        chat_buttons_row.setContentsMargins(0, 0, 0, 0)
        chat_buttons_row.setSpacing(8)
        chat_id_row = QHBoxLayout()
        chat_id_row.setContentsMargins(0, 0, 0, 0)
        chat_id_row.setSpacing(8)
        self.chat_override_id = QComboBox()
        self.chat_override_id.setEditable(True)
        self.chat_override_id.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        if self.chat_override_id.lineEdit():
            self.chat_override_id.lineEdit().setPlaceholderText("chat_id")
        self.chat_override_id.setFixedWidth(105)
        self.load_chat_button = QPushButton("Загрузить чат")
        self.save_chat_button = QPushButton("Сохранить чат")
        self.clear_chat_button = QPushButton("Сбросить поля")
        self.clear_history_button = QPushButton("Очистить историю")
        chat_buttons_row.addWidget(self.load_chat_button)
        chat_buttons_row.addWidget(self.save_chat_button)
        chat_buttons_row.addWidget(self.clear_chat_button)
        chat_buttons_row.addWidget(self.clear_history_button)
        chat_buttons_row.addStretch(1)
        chat_id_row.addWidget(self.chat_override_id)
        self.chat_history_count_label = QLabel("История: 0 сообщений")
        self.chat_history_count_label.setStyleSheet("color: #9AA6B2;")
        chat_id_row.addWidget(self.chat_history_count_label)
        chat_id_row.addStretch(1)
        chat_toolbar.addLayout(chat_buttons_row)
        chat_toolbar.addLayout(chat_id_row)
        chat_form.addRow("Чат:", chat_toolbar_widget)
        self.chat_response_mode = QComboBox()
        self.chat_response_mode.addItems(["inherit", *self.MODES])
        self.chat_prompt = QTextEdit()
        self.chat_prompt.setPlaceholderText("Пусто = наследовать prompt владельца")
        self.chat_prompt.setMinimumHeight(70)
        self.chat_prompt.setMaximumHeight(80)
        self.chat_history = QComboBox()
        self.chat_history.addItems(["inherit", "on", "off"])
        self.chat_ttl = QLineEdit()
        self.chat_ttl.setPlaceholderText("Пусто = наследовать")
        self.chat_close_after_reply = QComboBox()
        self.chat_close_after_reply.addItems(["inherit", "on", "off"])
        self.chat_turn_based_replies = QComboBox()
        self.chat_turn_based_replies.addItems(["inherit", "on", "off"])
        self.chat_owner_behavior = QComboBox()
        self.chat_owner_behavior.addItems(["inherit", *self.OWNER_BEHAVIORS])
        self.chat_allowed_mcp = QTextEdit()
        self.chat_allowed_mcp.setPlaceholderText("Имена MCP серверов/инструментов, по одному на строку")
        self.chat_allowed_mcp.setMinimumHeight(54)
        self.chat_allowed_mcp.setMaximumHeight(60)
        self.chat_media_stt = QComboBox()
        self.chat_media_stt.addItems(["inherit", "on", "off"])
        self.chat_media_images = QComboBox()
        self.chat_media_images.addItems(["inherit", "on", "off"])
        chat_form.addRow("Режим:", self.chat_response_mode)
        chat_form.addRow("Prompt чата:", self.chat_prompt)
        chat_form.addRow("История:", self.chat_history)
        chat_form.addRow("TTL сессии, сек:", self.chat_ttl)
        chat_form.addRow("Закрывать после ответа:", self.chat_close_after_reply)
        chat_form.addRow("Очередность как в ЛС:", self.chat_turn_based_replies)
        chat_form.addRow("Поведение владельца:", self.chat_owner_behavior)
        chat_form.addRow("Разрешенные MCP:", self.chat_allowed_mcp)
        chat_form.addRow("Голос/STT:", self.chat_media_stt)
        chat_form.addRow("Фото/VLM:", self.chat_media_images)
        right_layout.addWidget(chat_group)

        events_group = QGroupBox("Журнал")
        events_layout = QVBoxLayout(events_group)
        self.events = QTextEdit()
        self.events.setReadOnly(True)
        self.events.setPlaceholderText("Последние события выбранного владельца")
        self.events.setMinimumHeight(140)
        events_layout.addWidget(self.events)
        right_layout.addWidget(events_group)
        right_layout.addStretch(1)

        right_scroll.setWidget(right_content)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([460, 720])
        layout.addWidget(splitter, 1)

        self.add_button.clicked.connect(self.add_profile)
        self.delete_button.clicked.connect(self.delete_profile)
        self.save_button.clicked.connect(self.save_profile)
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

    def _init_tooltips(self):
        self.add_button.setToolTip("Добавить владельца, который сможет использовать бота как личного секретаря.")
        self.delete_button.setToolTip("Удалить выбранный secretary-профиль.")
        self.save_button.setToolTip("Сохранить настройки выбранного владельца.")
        self.table.setToolTip("Список владельцев secretary-профилей. Выберите строку, чтобы редактировать настройки справа.")
        self.enabled.setToolTip("Включить или выключить ответы секретаря для выбранного владельца.")
        self.mode.setToolTip("Режим ответа: off - выключено, draft - черновик, confirm - с подтверждением, auto - автоответ.")
        self.prompt.setToolTip("System Prompt секретаря. Он задаёт стиль и правила ответа за владельца.")
        self.edit_prompt_button.setToolTip("Открыть расширенный редактор System Prompt секретаря с плейсхолдерами и шаблонами.")
        self.validate_prompt_button.setToolTip("Проверить текущий secretary prompt на неизвестные плейсхолдеры и типичные проблемы.")
        self.prompt_status_label.setToolTip("Статус текущего secretary prompt выбранного владельца.")
        self.save_history.setToolTip("Сохранять отдельную историю secretary-диалогов для контекста.")
        self.ignore_bots.setToolTip("Не отвечать на сообщения, отправленные Telegram-ботами.")
        self.media_stt.setToolTip("Разрешить секретарю распознавать голосовые сообщения и кружочки через общие STT-настройки.")
        self.media_images.setToolTip("Разрешить секретарю скачивать фото/картинки и передавать их VLM-модели, если такая модель активна.")
        self.default_delay.setToolTip("Минимальная задержка перед постановкой запроса секретаря в очередь.")
        self.burst_window.setToolTip("Период тишины, в течение которого быстрые сообщения объединяются в один запрос.")
        self.max_batch_messages.setToolTip("Максимальное число последних сообщений, которые можно объединить в один запрос.")
        self.default_session_ttl.setToolTip("Время жизни сессии в секундах. 0 означает бесконечную сессию.")
        self.close_after_reply.setToolTip("Если включено, auto-ответ закрывает текущую сессию после отправки.")
        self.turn_based_replies.setToolTip(
            "Если включено, секретарь игнорирует исходящие business-сообщения владельца/бота "
            "и ждёт новое входящее сообщение собеседника перед следующим ответом."
        )
        self.owner_behavior.setToolTip("Что делать, если владелец пишет в secretary-чате: ignore, takeover, add_to_context или close_session.")
        self.allowed_chats.setToolTip("Если заполнено, секретарь отвечает только в этих chat_id. Один ID на строку.")
        self.blocked_chats.setToolTip("Секретарь не отвечает в этих chat_id. Один ID на строку.")
        self.chat_override_id.setToolTip("chat_id, для которого нужно загрузить или сохранить override.")
        self.chat_history_count_label.setToolTip("Количество сохранённых secretary-сообщений для выбранного chat_id.")
        self.load_chat_button.setToolTip("Загрузить per-chat override выбранного владельца.")
        self.save_chat_button.setToolTip("Сохранить override для указанного chat_id.")
        self.clear_chat_button.setToolTip("Сбросить поля редактора. Существующую запись в базе не удаляет.")
        self.clear_history_button.setToolTip("Удалить secretary-историю выбранного chat_id и закрыть активную сессию этого чата.")
        self.chat_response_mode.setToolTip(
            "Режим ответа для конкретного чата:\n"
            "inherit - использовать режим владельца;\n"
            "off - не отвечать;\n"
            "draft - только сохранять черновик;\n"
            "confirm - спрашивать подтверждение;\n"
            "auto - отправлять автоматически."
        )
        self.chat_prompt.setToolTip("System Prompt только для указанного chat_id. Пустое поле означает наследование prompt владельца.")
        self.chat_history.setToolTip("inherit - наследовать настройку истории владельца, on - сохранять историю, off - не сохранять.")
        self.chat_ttl.setToolTip("TTL сессии для этого chat_id в секундах. Пустое поле означает наследование значения владельца.")
        self.chat_close_after_reply.setToolTip("inherit - наследовать, on - закрывать сессию после auto-ответа, off - не закрывать.")
        self.chat_turn_based_replies.setToolTip(
            "inherit - наследовать, on - отвечать только после нового входящего собеседника, "
            "off - разрешить старое поведение."
        )
        self.chat_owner_behavior.setToolTip(
            "Поведение при сообщении владельца в этом чате:\n"
            "inherit - наследовать;\n"
            "ignore - игнорировать;\n"
            "takeover - считать, что владелец перехватил диалог;\n"
            "add_to_context - добавить к контексту;\n"
            "close_session - закрыть текущую сессию."
        )
        self.chat_allowed_mcp.setToolTip(
            "Ограничение MCP для этого чата. По одному значению на строку:\n"
            "server_name - разрешить весь сервер;\n"
            "tool_name - разрешить tool с таким именем;\n"
            "server_name__tool_name - разрешить конкретный tool конкретного сервера.\n"
            "Пусто = наследовать общий доступ."
        )
        self.chat_media_stt.setToolTip("inherit - использовать настройку владельца, on/off - переопределить STT для этого чата.")
        self.chat_media_images.setToolTip("inherit - использовать настройку владельца, on/off - переопределить обработку фото для этого чата.")
        self.events.setToolTip("Последние события secretary-flow для выбранного владельца.")

    def load_profiles(self, select_owner_id: int | None = None):
        db = DatabaseManager()
        try:
            profiles = db.secretary.list_profiles()
        finally:
            db.close()
        self.table.setRowCount(len(profiles))
        selected_row = -1
        for row, profile in enumerate(profiles):
            owner_id = int(profile.get("owner_telegram_id"))
            if select_owner_id is not None and owner_id == select_owner_id:
                selected_row = row
            self.table.setItem(row, 0, self._table_item(owner_id))
            self.table.setItem(row, 1, self._table_item(self._profile_display_name(profile)))
            self.table.setItem(row, 2, self._table_item("да" if profile.get("enabled") else "нет", centered=True))
            self.table.setItem(row, 3, self._table_item(profile.get("response_mode") or "draft", centered=True))
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        elif profiles:
            self.table.selectRow(0)

    def _on_selection_changed(self):
        row = self.table.currentRow()
        if row < 0:
            return
        owner_item = self.table.item(row, 0)
        if not owner_item:
            return
        self.current_owner_id = int(owner_item.text())
        db = DatabaseManager()
        try:
            profile = db.secretary.get_profile(self.current_owner_id) or {}
            events = db.secretary.list_events(self.current_owner_id)
            recent_chats = db.secretary.list_recent_chats(self.current_owner_id)
            prompt_history = db.secretary.list_prompt_history(self.current_owner_id)
            prompt_templates = db.secretary.list_prompt_templates(self.current_owner_id)
        finally:
            db.close()
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
        self._refresh_chat_options(recent_chats)
        self._reset_chat_override_form()
        self.events.setPlainText(self._format_events(events))

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
            self.prompt.setPlainText(prompt_text or "")

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

    def save_profile(self):
        if self.current_owner_id is None:
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
        self.load_profiles(select_owner_id=self.current_owner_id)

    def delete_profile(self):
        if self.current_owner_id is None:
            return
        db = DatabaseManager()
        try:
            db.secretary.delete_profile(self.current_owner_id)
        finally:
            db.close()
        self.current_owner_id = None
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

    def _profile_display_name(self, profile):
        display_name = profile.get("owner_display_name") or ""
        if display_name:
            return display_name
        try:
            db = DatabaseManager()
            try:
                user = db.users.get_user_by_telegram_id(int(profile.get("owner_telegram_id")))
            finally:
                db.close()
            return self._user_display_name(user)
        except Exception:
            return ""
