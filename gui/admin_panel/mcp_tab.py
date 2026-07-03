import json
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt

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


class McpTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_row = -1
        self._loading_access = False
        self._init_ui()
        self._init_tooltips()
        self.load_settings()

    @staticmethod
    def _table_item(text, *, centered: bool = False):
        item = QTableWidgetItem(str(text))
        if centered:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _init_ui(self):
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.enabled = QCheckBox("Включить MCP")
        self.add_button = QPushButton("Добав.")
        self.example_button = QPushButton("Пример")
        self.delete_button = QPushButton("Удал.")
        self.start_button = QPushButton("Старт")
        self.stop_button = QPushButton("Стоп")
        self.discover_button = QPushButton("Disc.")
        self.save_button = QPushButton("Сохр.")
        self.refresh_audit_button = QPushButton("Audit")
        for button in (
            self.add_button,
            self.example_button,
            self.delete_button,
            self.start_button,
            self.stop_button,
            self.discover_button,
            self.refresh_audit_button,
            self.save_button,
        ):
            button.setMinimumWidth(0)
        toolbar.addWidget(self.enabled)
        toolbar.addStretch()
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.example_button)
        toolbar.addWidget(self.delete_button)
        toolbar.addWidget(self.start_button)
        toolbar.addWidget(self.stop_button)
        toolbar.addWidget(self.discover_button)
        toolbar.addWidget(self.refresh_audit_button)
        toolbar.addWidget(self.save_button)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left_widget = QWidget()
        left_widget.setMinimumWidth(420)
        left_panel = QVBoxLayout(left_widget)
        left_panel.setContentsMargins(0, 0, 0, 0)
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Фильтр по имени, статусу, команде или доступу")
        left_panel.addWidget(self.filter_input)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Сервер", "Статус", "Вкл", "Tools", "Доступ", "Transport"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        header = self.table.horizontalHeader()
        for column in (0, 1, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        left_panel.addWidget(self.table, 1)
        splitter.addWidget(left_widget)

        tabs = QTabWidget()
        tabs.setMinimumWidth(260)
        config_tab = QWidget()
        config_tab_layout = QVBoxLayout(config_tab)
        config_tab_layout.setContentsMargins(0, 0, 0, 0)
        config_scroll = QScrollArea()
        config_scroll.setWidgetResizable(True)
        config_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        config_content = QWidget()
        config_content.setMinimumWidth(0)
        config_layout = QVBoxLayout(config_content)
        config_layout.setContentsMargins(10, 10, 10, 10)
        config_layout.setSpacing(10)
        connection_group = QGroupBox("Подключение")
        connection_form = QFormLayout(connection_group)
        connection_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        connection_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        connection_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        connection_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        connection_form.setHorizontalSpacing(14)
        connection_form.setVerticalSpacing(10)
        self.command = QLineEdit()
        self.command.setPlaceholderText("Команда запуска MCP-сервера")
        self.transport = QComboBox()
        self.transport.addItems(["stdio", "sse", "streamable_http"])
        self.cwd = QLineEdit()
        self.cwd.setPlaceholderText("Рабочая папка для stdio-сервера")
        self.url = QLineEdit()
        self.url.setPlaceholderText("URL для sse/streamable_http")
        self.args = QTextEdit()
        self.args.setPlaceholderText("Аргументы, по одному на строку")
        self.args.setMinimumHeight(78)
        self.args.setMaximumHeight(110)
        self.env = QTextEdit()
        self.env.setPlaceholderText('Env JSON, например {"API_KEY":"..."}')
        self.env.setMinimumHeight(96)
        self.env.setMaximumHeight(140)
        self.access = QTextEdit()
        self.access.setPlaceholderText('Access JSON, например {"admin":true,"private":false,"group":false,"secretary":false}')
        self.access.setMinimumHeight(88)
        self.access.setMaximumHeight(120)
        self.description = QTextEdit()
        self.description.setPlaceholderText("Описание")
        self.description.setMinimumHeight(78)
        self.description.setMaximumHeight(120)
        self.server_enabled = QCheckBox("Сервер включен")
        self.auto_start = QCheckBox("Запускать автоматически")
        access_widget = QWidget()
        access_row = QHBoxLayout(access_widget)
        access_row.setContentsMargins(0, 0, 0, 0)
        self.access_admin = QCheckBox("Админ")
        self.access_private = QCheckBox("ЛС")
        self.access_group = QCheckBox("Группы")
        self.access_secretary = QCheckBox("Секретарь")
        access_row.addWidget(self.access_admin)
        access_row.addWidget(self.access_private)
        access_row.addWidget(self.access_group)
        access_row.addWidget(self.access_secretary)
        access_row.addStretch()
        state_widget = QWidget()
        state_row = QHBoxLayout(state_widget)
        state_row.setContentsMargins(0, 0, 0, 0)
        state_row.addWidget(self.server_enabled)
        state_row.addWidget(self.auto_start)
        state_row.addStretch()
        connection_form.addRow("Транспорт:", self.transport)
        connection_form.addRow("Команда:", self.command)
        connection_form.addRow("Аргументы:", self.args)
        connection_form.addRow("Рабочая папка:", self.cwd)
        connection_form.addRow("URL:", self.url)
        connection_form.addRow("Переменные env:", self.env)
        connection_form.addRow("Состояние:", state_widget)
        connection_form.addRow("Доступ:", access_widget)
        connection_form.addRow("Access JSON:", self.access)
        connection_form.addRow("Описание:", self.description)
        config_layout.addWidget(connection_group)

        discovery_group = QGroupBox("Discovery preview")
        discovery_layout = QVBoxLayout(discovery_group)
        self.tools_preview = QTextEdit()
        self.tools_preview.setReadOnly(True)
        self.tools_preview.setPlaceholderText("Tools discovery result")
        self.tools_preview.setMinimumHeight(110)
        self.resources_preview = QTextEdit()
        self.resources_preview.setReadOnly(True)
        self.resources_preview.setPlaceholderText("Resources and resource templates discovery result")
        self.resources_preview.setMinimumHeight(92)
        self.prompts_preview = QTextEdit()
        self.prompts_preview.setReadOnly(True)
        self.prompts_preview.setPlaceholderText("Prompts discovery result")
        self.prompts_preview.setMinimumHeight(92)
        discovery_layout.addWidget(QLabel("Tools"))
        discovery_layout.addWidget(self.tools_preview, 2)
        discovery_layout.addWidget(QLabel("Resources"))
        discovery_layout.addWidget(self.resources_preview, 1)
        discovery_layout.addWidget(QLabel("Prompts"))
        discovery_layout.addWidget(self.prompts_preview, 1)
        config_layout.addWidget(discovery_group, 1)
        config_scroll.setWidget(config_content)
        config_tab_layout.addWidget(config_scroll)
        tabs.addTab(config_tab, "Настройка")

        audit_tab = QWidget()
        audit_layout = QVBoxLayout(audit_tab)
        self.status_label = QLabel("Статус: нет данных")
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.preview_actor = QLineEdit()
        self.preview_actor.setPlaceholderText("actor_telegram_id")
        self.preview_chat = QLineEdit()
        self.preview_chat.setPlaceholderText("chat_id")
        self.preview_source = QComboBox()
        self.preview_source.addItems(["normal", "bot_to_bot", "secretary"])
        self.preview_chat_type = QComboBox()
        self.preview_chat_type.addItems(["private", "group", "supergroup"])
        self.preview_admin = QCheckBox("is_admin")
        self.preview_button = QPushButton("Проверить доступ")
        preview_group = QGroupBox("Access preview")
        preview_group_layout = QVBoxLayout(preview_group)
        preview_row = QHBoxLayout()
        preview_row.addWidget(self.preview_actor)
        preview_row.addWidget(self.preview_chat)
        preview_row.addWidget(self.preview_source)
        preview_row.addWidget(self.preview_chat_type)
        preview_row.addWidget(self.preview_admin)
        preview_row.addWidget(self.preview_button)
        self.preview_result = QTextEdit()
        self.preview_result.setReadOnly(True)
        self.preview_result.setMaximumHeight(120)
        self.audit_log = QTextEdit()
        self.audit_log.setReadOnly(True)
        self.audit_log.setMinimumHeight(220)
        audit_layout.addWidget(self.status_label)
        audit_layout.addWidget(self.warning_label)
        preview_group_layout.addLayout(preview_row)
        preview_group_layout.addWidget(self.preview_result)
        audit_layout.addWidget(preview_group)
        audit_layout.addWidget(self.audit_log, 1)
        tabs.addTab(audit_tab, "Status / Audit")

        splitter.addWidget(tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([500, 740])
        layout.addWidget(splitter, 1)

        self.add_button.clicked.connect(self.add_server)
        self.example_button.clicked.connect(self.add_example_server)
        self.delete_button.clicked.connect(self.delete_server)
        self.start_button.clicked.connect(self.start_server)
        self.stop_button.clicked.connect(self.stop_server)
        self.discover_button.clicked.connect(self.discover_tools)
        self.refresh_audit_button.clicked.connect(self.refresh_audit)
        self.preview_button.clicked.connect(self.preview_access)
        self.save_button.clicked.connect(self.save_settings)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.filter_input.textChanged.connect(self._apply_filter)
        for checkbox in (self.access_admin, self.access_private, self.access_group, self.access_secretary):
            checkbox.toggled.connect(self._sync_access_json_from_checks)

    def _init_tooltips(self):
        self.enabled.setToolTip("Главный переключатель MCP. Если выключен, инструменты MCP не передаются модели.")
        self.add_button.setToolTip("Добавить новый MCP-сервер в список настроек.")
        self.example_button.setToolTip("Добавить готовый простой MCP-пример из папки examples/mcp.")
        self.delete_button.setToolTip("Удалить выбранный MCP-сервер из настроек.")
        self.start_button.setToolTip("Запустить выбранный stdio MCP-сервер для текущей GUI-сессии.")
        self.stop_button.setToolTip("Остановить выбранный stdio MCP-сервер, если он был запущен из этой вкладки.")
        self.discover_button.setToolTip("Подключиться к серверу и обновить список tools, resources и prompts.")
        self.refresh_audit_button.setToolTip("Обновить статус сервера, последние вызовы tools и отказы доступа.")
        self.save_button.setToolTip("Сохранить MCP-настройки в config.json.")
        self.filter_input.setToolTip("Быстрый фильтр по таблице MCP-серверов.")
        self.table.setToolTip("Список настроенных MCP-серверов. Выберите строку, чтобы редактировать сервер справа.")
        self.transport.setToolTip("Тип подключения MCP-сервера: stdio, SSE или streamable HTTP.")
        self.command.setToolTip("Команда запуска stdio MCP-сервера, например путь к node/python исполняемому файлу.")
        self.args.setToolTip("Аргументы запуска MCP-сервера. Один аргумент на строку.")
        self.cwd.setToolTip("Рабочая папка для stdio-сервера. Можно оставить пустой.")
        self.url.setToolTip("URL MCP-сервера для transport sse или streamable_http.")
        self.env.setToolTip("Переменные окружения в JSON. Секреты маскируются в интерфейсе и логах.")
        self.server_enabled.setToolTip("Разрешить использовать этот сервер при запросах к модели.")
        self.auto_start.setToolTip("Пометка автозапуска сервера. Полноценный persistent pool ещё не включён.")
        self.access_admin.setToolTip("Разрешить tools этого сервера администраторам.")
        self.access_private.setToolTip("Разрешить tools этого сервера в личных чатах.")
        self.access_group.setToolTip("Разрешить tools этого сервера в группах.")
        self.access_secretary.setToolTip("Разрешить tools этого сервера в secretary/Chat Automation сценариях.")
        self.access.setToolTip("Расширенный JSON доступа. Чекбоксы выше обновляют основные поля автоматически.")
        self.description.setToolTip("Короткое описание сервера для себя и будущих проверок.")
        self.tools_preview.setToolTip("Последний discovery-результат tools для выбранного сервера.")
        self.resources_preview.setToolTip("Последний discovery-результат resources и resource templates.")
        self.prompts_preview.setToolTip("Последний discovery-результат prompts.")
        self.preview_actor.setToolTip("Telegram ID пользователя для проверки доступа.")
        self.preview_chat.setToolTip("chat_id для проверки доступа.")
        self.preview_source.setToolTip("Источник запроса: обычный чат, bot-to-bot или secretary.")
        self.preview_chat_type.setToolTip("Тип чата для проверки доступа.")
        self.preview_admin.setToolTip("Проверять доступ так, будто пользователь администратор.")
        self.preview_button.setToolTip("Показать tools, доступные для указанного контекста.")
        self.preview_result.setToolTip("Результат проверки доступа для указанного контекста.")
        self.audit_log.setToolTip("Последние MCP tool calls и отказы доступа по выбранному серверу.")

    def _servers(self):
        settings = settings_manager.get_settings()
        return settings.get("mcp", {}).get("servers", [])

    def load_settings(self, select_row: int | None = None, select_name: str | None = None):
        settings = settings_manager.get_settings()
        self.enabled.setChecked(settings.get("mcp", {}).get("enabled", False))
        servers = preview_servers(settings)
        statuses = self._status_by_server()
        self.table.setRowCount(len(servers))
        selected_row = -1
        for row, server in enumerate(servers):
            if select_name and server.get("name") == select_name:
                selected_row = row
            access = server.get("access", {})
            access_text = ",".join(key for key, value in access.items() if value)
            status = statuses.get(server.get("name", ""), {})
            self.table.setItem(row, 0, self._table_item(server.get("name", "")))
            self.table.setItem(row, 1, self._table_item(status.get("status", "нет данных"), centered=True))
            self.table.setItem(row, 2, self._table_item("да" if server.get("enabled") else "нет", centered=True))
            self.table.setItem(row, 3, self._table_item(len(server.get("tools") or []), centered=True))
            self.table.setItem(row, 4, self._table_item(access_text))
            self.table.setItem(row, 5, self._table_item(server.get("transport", "stdio"), centered=True))
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        elif select_row is not None and 0 <= select_row < len(servers):
            self.table.selectRow(select_row)
        elif servers:
            self.table.selectRow(0)
        self._apply_filter()
        self.refresh_audit()

    def _on_selection_changed(self):
        self.current_row = self.table.currentRow()
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
        self.tools_preview.setPlainText(json.dumps(tools, ensure_ascii=False, indent=2) if tools else "")
        resources = {
            "resources": server.get("resources") or [],
            "resource_templates": server.get("resource_templates") or [],
        }
        has_resources = resources["resources"] or resources["resource_templates"]
        self.resources_preview.setPlainText(json.dumps(resources, ensure_ascii=False, indent=2) if has_resources else "")
        prompts = server.get("prompts") or []
        self.prompts_preview.setPlainText(json.dumps(prompts, ensure_ascii=False, indent=2) if prompts else "")
        self.refresh_audit()

    def add_server(self):
        name, ok = QInputDialog.getText(self, "Добавить MCP-сервер", "Имя сервера:")
        if not ok or not name.strip():
            return
        servers = self._servers()
        servers.append({"name": name.strip(), "enabled": False, "command": "", "args": [], "env": {}, "access": {"admin": True}})
        settings_manager.settings.setdefault("mcp", {})["servers"] = servers
        self.load_settings()

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
            servers[existing_index] = {**servers[existing_index], **config}
            select_row = existing_index
        else:
            servers.append(config)
            select_row = len(servers) - 1
        settings_manager.settings.setdefault("mcp", {})["servers"] = servers
        settings_manager.save_settings()
        self.load_settings(select_row=select_row)

    def delete_server(self):
        servers = self._servers()
        if self.current_row < 0 or self.current_row >= len(servers):
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
                QMessageBox.warning(self, "Ошибка", f"Некорректный JSON: {e}")
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
            QMessageBox.warning(self, "MCP SDK", message)
            return
        self.save_settings()
        servers = self._servers()
        if self.current_row < 0 or self.current_row >= len(servers):
            QMessageBox.information(self, "MCP", "Выберите MCP-сервер.")
            return
        try:
            capabilities = discover_server_capabilities(servers[self.current_row])
        except McpRuntimeError as e:
            QMessageBox.warning(self, "MCP discovery", str(e))
            return
        except Exception as e:
            logger.error(f"MCP discovery failed: {e}")
            QMessageBox.warning(self, "MCP discovery", f"Не удалось проверить сервер: {e}")
            return

        servers[self.current_row]["tools"] = capabilities.get("tools") or []
        servers[self.current_row]["resources"] = capabilities.get("resources") or []
        servers[self.current_row]["resource_templates"] = capabilities.get("resource_templates") or []
        servers[self.current_row]["prompts"] = capabilities.get("prompts") or []
        settings_manager.settings.setdefault("mcp", {})["servers"] = servers
        settings_manager.save_settings()
        self.tools_preview.setPlainText(json.dumps(servers[self.current_row]["tools"], ensure_ascii=False, indent=2))
        self.resources_preview.setPlainText(json.dumps({
            "resources": servers[self.current_row]["resources"],
            "resource_templates": servers[self.current_row]["resource_templates"],
        }, ensure_ascii=False, indent=2))
        self.prompts_preview.setPlainText(json.dumps(servers[self.current_row]["prompts"], ensure_ascii=False, indent=2))
        self.refresh_audit()
        QMessageBox.information(
            self,
            "MCP discovery",
            (
                f"Найдено: tools={len(servers[self.current_row]['tools'])}, "
                f"resources={len(servers[self.current_row]['resources'])}, "
                f"resource_templates={len(servers[self.current_row]['resource_templates'])}, "
                f"prompts={len(servers[self.current_row]['prompts'])}"
            ),
        )

    def start_server(self):
        selected_name = self._selected_server_name()
        self.save_settings()
        servers = self._servers()
        if selected_name:
            for index, server in enumerate(servers):
                if normalize_server_config(server).get("name") == selected_name:
                    self.current_row = index
                    self.table.selectRow(index)
                    break
        if self.current_row < 0 or self.current_row >= len(servers):
            QMessageBox.information(self, "MCP", "Выберите MCP-сервер.")
            return
        try:
            result = start_server_process(servers[self.current_row])
        except McpRuntimeError as e:
            QMessageBox.warning(self, "MCP start", str(e))
            self.refresh_audit()
            self.load_settings(select_name=selected_name)
            return
        except Exception as e:
            logger.error(f"MCP start failed: {e}")
            QMessageBox.warning(self, "MCP start", f"Не удалось запустить сервер: {e}")
            self.refresh_audit()
            self.load_settings(select_name=selected_name)
            return

        self.refresh_audit()
        self.load_settings(select_name=selected_name)
        QMessageBox.information(
            self,
            "MCP start",
            f"Статус: {result.get('status')}\n{result.get('details') or ''}",
        )

    def stop_server(self):
        selected_name = self._selected_server_name()
        servers = self._servers()
        if self.current_row < 0 or self.current_row >= len(servers):
            QMessageBox.information(self, "MCP", "Выберите MCP-сервер.")
            return
        try:
            result = stop_server_process(servers[self.current_row])
        except Exception as e:
            logger.error(f"MCP stop failed: {e}")
            QMessageBox.warning(self, "MCP stop", f"Не удалось остановить сервер: {e}")
            self.refresh_audit()
            self.load_settings(select_name=selected_name)
            return

        self.refresh_audit()
        self.load_settings(select_name=selected_name)
        QMessageBox.information(
            self,
            "MCP stop",
            f"Статус: {result.get('status')}\n{result.get('details') or ''}",
        )

    def preview_access(self):
        try:
            actor_id = int(self.preview_actor.text().strip()) if self.preview_actor.text().strip() else None
            chat_id = int(self.preview_chat.text().strip()) if self.preview_chat.text().strip() else None
        except ValueError:
            QMessageBox.warning(self, "MCP access", "actor_telegram_id и chat_id должны быть числами.")
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
            current = {}
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
        for row in range(self.table.rowCount()):
            haystack = []
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                if item:
                    haystack.append(item.text().lower())
            self.table.setRowHidden(row, bool(needle) and needle not in " ".join(haystack))
