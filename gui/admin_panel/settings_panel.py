# gui/admin_panel/settings_panel.py
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QFormLayout,
    QComboBox, QGroupBox, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QDialog, QTextEdit,
    QCheckBox, QWidget, QApplication, QFrame, QGridLayout, QListWidget,
    QListWidgetItem, QSplitter, QInputDialog, QSizePolicy)
from PyQt6.QtCore import Qt, QTimer
from gui.widgets import UnicodeSpinBox, UnicodeDoubleSpinBox
from config.settings import settings_manager  # Импортируем существующий экземпляр
from PyQt6.QtGui import QDoubleValidator, QIntValidator, QPalette, QFont
from bot.handlers.queue_manager import (
    get_model_usage_stats,
    get_available_placeholders,
    init_model_clients,
    validate_system_prompt,
)
from bot.handlers.services.prompt_manager import build_system_prompt_status
from .services.model_service import ModelService  # 🆕 Новый сервис для управления моделями
from utils.logger import setup_logger

logger = setup_logger(__name__)

class ModelDialog(QDialog):
    REASONING_MODES = [
        ("Не управлять", "default"),
        ("Авто / adaptive", "auto"),
        ("Выключено", "off"),
        ("Минимум", "minimal"),
        ("Низкий", "low"),
        ("Средний", "medium"),
        ("Высокий", "high"),
        ("Максимальный", "xhigh"),
    ]
    REASONING_PROVIDERS = [
        ("Определить автоматически", "auto"),
        ("OpenRouter", "openrouter"),
        ("OpenAI-compatible", "openai_compatible"),
        ("Anthropic adaptive", "anthropic_adaptive"),
        ("Anthropic budget", "anthropic_budget"),
    ]

    def __init__(self, parent=None, existing_model=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить/Редактировать модель")
        self.resize(400, 250)
        self.existing_model = existing_model
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()
        
        # Тип API (первый элемент — определяет подсказки остальных полей)
        self.api_type_combo = QComboBox()
        self.api_type_combo.addItems([
            "OpenAI-compatible (LM Studio, Ollama, OpenAI, OpenRouter, Chutes)",
            "Anthropic (Claude)",
        ])
        self.api_type_combo.setToolTip(
            "Тип API определяет формат запросов к модели.\n\n"
            "OpenAI-compatible — универсальный формат.\n"
            "  Поддерживается: LM Studio, Ollama, OpenAI, OpenRouter, Chutes, Together AI и др.\n\n"
            "Anthropic (Claude) — формат для API Claude.\n"
            "  Используется: Anthropic Claude (api.anthropic.com)"
        )
        self.api_type_combo.currentIndexChanged.connect(self._on_api_type_changed)
        form_layout.addRow('Тип API:', self.api_type_combo)
        
        # ID модели
        self.model_id_input = QLineEdit()
        self.model_id_input.setPlaceholderText('Например: gemma-7b-it')
        self.model_id_input.setToolTip(
            "Уникальный идентификатор модели. Используется при запросах к API.\n\n"
            "LM Studio: название модели из списка загруженных\n"
            "Ollama: название модели (например: llama3.2)\n"
            "OpenAI: gpt-4o, gpt-4o-mini, gpt-3.5-turbo и т.д.\n"
            "OpenRouter: google/gemini-2.0-flash-exp:free и т.д.\n"
            "Chutes: ID модели/cord в формате провайдера.\n\n"
            "Если несколько экземпляров одной модели — добавьте суффикс (например: gemma-7b-it:1)"
        )
        form_layout.addRow('ID модели:', self.model_id_input)
        
        # API Key
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText('API ключ для LM Studio')
        self.api_key_input.setToolTip(
            "Ключ API для авторизации.\n\n"
            "LM Studio: используется то же значение, что и ID модели\n"
            "Ollama: не требуется, но можно продублировать название модели (например: llama3.2)\n"
            "OpenAI: ключ вида sk-... из dashboard.openai.com\n"
            "Anthropic (Claude): ключ вида sk-ant-... из console.anthropic.com\n"
            "OpenRouter: ключ вида sk-or-... из openrouter.ai/keys\n"
            "Chutes: API ключ провайдера, если доступ к модели требует авторизацию"
        )
        form_layout.addRow('API ключ:', self.api_key_input)
        
        # Base URL
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText('http://localhost:1234/v1')
        self.base_url_input.setToolTip(
            "URL для API запросов.\n\n"
            "Локальные серверы:\n"
            "  LM Studio: http://localhost:1234/v1\n"
            "  Ollama: http://localhost:11434/v1\n\n"
            "Облачные провайдеры:\n"
            "  OpenAI: https://api.openai.com/v1\n"
            "  OpenRouter: https://openrouter.ai/api/v1\n"
            "  Chutes: https://llm.chutes.ai/v1\n\n"
            "Формат: http(s)://<адрес>:<порт>/v1"
        )
        form_layout.addRow('URL API:', self.base_url_input)
        
        # Weight (кастомный UnicodeSpinBox)
        self.weight_input = UnicodeSpinBox(min=1, max=100, value=1)
        self.weight_input.setToolTip("Вес модели для взвешенного распределения запросов.\nЧем больше значение, тем чаще модель будет выбираться при стратегии random_weighted")
        form_layout.addRow('Вес (для балансировки):', self.weight_input)
        
        # Активная модель
        self.active_checkbox = QCheckBox("Активировать модель")
        self.active_checkbox.setChecked(True)
        self.active_checkbox.setToolTip("Если отключено, модель не будет использоваться для обработки запросов")
        form_layout.addRow('', self.active_checkbox)

        # Поддержка изображений (VLM)
        self.vision_checkbox = QCheckBox("Поддерживает изображение (VLM)")
        self.vision_checkbox.setChecked(False)
        self.vision_checkbox.setToolTip(
            "Включите, если модель умеет обрабатывать изображения (Vision-Language Model).\n"
            "Такие модели получат доступ к изображениями из истории и запросов."
        )
        form_layout.addRow('', self.vision_checkbox)

        reasoning_group = QGroupBox("Думание модели")
        reasoning_layout = QFormLayout(reasoning_group)

        self.reasoning_mode_combo = QComboBox()
        for label, value in self.REASONING_MODES:
            self.reasoning_mode_combo.addItem(label, value)
        self.reasoning_mode_combo.setToolTip(
            "Не управлять — режим по умолчанию, без дополнительных reasoning-параметров.\n"
            "Thinking не выводится в Telegram."
        )
        reasoning_layout.addRow('Думание:', self.reasoning_mode_combo)

        self.reasoning_provider_combo = QComboBox()
        for label, value in self.REASONING_PROVIDERS:
            self.reasoning_provider_combo.addItem(label, value)
        self.reasoning_provider_combo.setToolTip("Формат reasoning/thinking payload для провайдера.")
        reasoning_layout.addRow('Формат:', self.reasoning_provider_combo)

        self.reasoning_budget_input = UnicodeSpinBox(min=0, max=200000, value=0, step=1024)
        self.reasoning_budget_input.setToolTip(
            "Бюджет thinking-токенов для Anthropic budget или OpenRouter budget. 0 — не передавать бюджет.\n"
            "Для Anthropic минимум 1024 и значение должно быть меньше max_tokens."
        )
        reasoning_layout.addRow('Бюджет токенов:', self.reasoning_budget_input)
        self.reasoning_mode_combo.currentIndexChanged.connect(self._update_reasoning_budget_state)
        self.reasoning_provider_combo.currentIndexChanged.connect(self._update_reasoning_budget_state)
        form_layout.addRow(reasoning_group)
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 🔧 ДОПОЛНИТЕЛЬНЫЕ НАСТРОЙКИ МОДЕЛИ
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        # Макс. одновременных запросов (кастомный UnicodeSpinBox)
        self.max_concurrent_input = UnicodeSpinBox(min=1, max=100, value=1)
        self.max_concurrent_input.setToolTip(
            "Максимальное количество одновременных запросов для этой модели.\n\n"
            "LM Studio 0.4+: до 4 (настраивается в Advanced Settings → Max Concurrent Predictions)\n"
            "Ollama: 3-10 в зависимости от железа (если мощное, можно выше)\n"
            "Облачные API (OpenAI, Claude, OpenRouter): 5-50 в зависимости от тарифа\n\n"
            "Бот автоматически распределяет запросы с учётом этого лимита."
        )
        form_layout.addRow('Макс. одновременных запросов:', self.max_concurrent_input)
        
        # Размер окна контекста (кастомный UnicodeSpinBox)
        self.context_window_input = UnicodeSpinBox(min=256, max=131072, value=4096, step=512)
        self.context_window_input.setToolTip(
            "Размер окна контекста модели в токенах.\n"
            "LM Studio: посмотрите в Server settings → Context length (ctx_len)\n"
            "Ollama: запустите команду 'ollama show --json model_name' и ищите context_length\n"
            "Примеры: llama3=8192, mistral=32768, gemma=4096"
        )
        form_layout.addRow('Размер окна контекста (токены):', self.context_window_input)
        
        # Если редактируем существующую модель
        if self.existing_model:
            # Устанавливаем тип API
            api_type = self.existing_model.get('api_type', 'openai')
            if api_type == 'anthropic':
                self.api_type_combo.setCurrentIndex(1)
            else:
                self.api_type_combo.setCurrentIndex(0)
            
            self.model_id_input.setText(self.existing_model.get('id', ''))
            self.api_key_input.setText(self.existing_model.get('api_key', ''))
            self.base_url_input.setText(self.existing_model.get('base_url', ''))
            self.weight_input.setValue(self.existing_model.get('weight', 1))
            self.active_checkbox.setChecked(self.existing_model.get('active', True))
            self.max_concurrent_input.setValue(self.existing_model.get('max_concurrent_requests', 1))
            self.context_window_input.setValue(self.existing_model.get('context_window_size', 4096))
            self.vision_checkbox.setChecked(self.existing_model.get('supports_vision', False))
            reasoning_mode = self.existing_model.get('reasoning_mode')
            if not reasoning_mode:
                reasoning_mode = self.existing_model.get('reasoning_effort', 'medium') if self.existing_model.get('reasoning_enabled') else 'default'
                if reasoning_mode == 'none':
                    reasoning_mode = 'off'
            self._set_combo_by_data(self.reasoning_mode_combo, reasoning_mode)
            self._set_combo_by_data(self.reasoning_provider_combo, self.existing_model.get('reasoning_provider', 'auto'))
            self.reasoning_budget_input.setValue(self.existing_model.get('reasoning_budget_tokens', 0))
        self._update_reasoning_budget_state()
        
        # Кнопки
        button_layout = QHBoxLayout()
        self.save_button = QPushButton('Сохранить')
        self.cancel_button = QPushButton('Отмена')
        
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(form_layout)
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
        # Привязка событий
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
    
    def _on_api_type_changed(self, index: int):
        """Обновляет плейсхолдеры полей при смене типа API."""
        if index == 1:  # Anthropic
            self.model_id_input.setPlaceholderText('Например: claude-sonnet-4-20250514')
            self.api_key_input.setPlaceholderText('Ключ вида sk-ant-...')
            self.base_url_input.setPlaceholderText('https://api.anthropic.com')
        else:  # OpenAI-compatible
            self.model_id_input.setPlaceholderText('Например: gemma-7b-it')
            self.api_key_input.setPlaceholderText('API ключ для LM Studio')
            self.base_url_input.setPlaceholderText('http://localhost:1234/v1')

    def _set_combo_by_data(self, combo: QComboBox, value: str):
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _update_reasoning_budget_state(self):
        provider = self.reasoning_provider_combo.currentData()
        mode = self.reasoning_mode_combo.currentData()
        self.reasoning_budget_input.setEnabled(provider in {'anthropic_budget', 'openrouter'} and mode != 'default')

    def get_model_data(self):
        # Определяем api_type из ComboBox
        api_type_index = self.api_type_combo.currentIndex()
        api_type = 'anthropic' if api_type_index == 1 else 'openai'
        
        return {
            'id': self.model_id_input.text().strip(),
            'api_key': self.api_key_input.text().strip(),
            'base_url': self.base_url_input.text().strip(),
            'weight': self.weight_input.value(),
            'active': self.active_checkbox.isChecked(),
            'api_type': api_type,
            'max_concurrent_requests': self.max_concurrent_input.value(),
            'context_window_size': self.context_window_input.value(),
            'supports_vision': self.vision_checkbox.isChecked(),
            'reasoning_mode': self.reasoning_mode_combo.currentData(),
            'reasoning_provider': self.reasoning_provider_combo.currentData(),
            'reasoning_budget_tokens': self.reasoning_budget_input.value(),
            'reasoning_hide_internal': True,
            'disable_sampling_for_reasoning': True,
        }


class PromptEditorDialog(QDialog):
    HISTORY_LIMIT = 15

    def __init__(
        self,
        parent,
        prompt_text,
        placeholder_defaults=None,
        history=None,
        templates=None,
        *,
        panel_adapter=None,
        placeholder_provider=None,
        title="Редактор System Prompt",
        show_defaults=True,
    ):
        super().__init__(parent)
        self.panel = panel_adapter or parent
        self.original_prompt = prompt_text or ""
        self.placeholder_defaults = dict(placeholder_defaults or {})
        self.history = list(history or [])
        self.templates = list(templates or [])
        self._last_applied_prompt = self.original_prompt
        self.placeholder_provider = placeholder_provider or get_available_placeholders
        self.show_defaults = bool(show_defaults)

        self.setWindowTitle(title)
        self.resize(1180, 720)
        self.init_ui()
        self._load_initial_state()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        accent_color = QApplication.palette().color(QPalette.ColorRole.Highlight).name()
        border_color = QApplication.palette().color(QPalette.ColorRole.Mid).name()
        is_oled = settings_manager.get_settings().get('oled_mode', False)
        panel_bg = "#000000" if is_oled else "#252526"

        editor_panel = QWidget()
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)

        self.prompt_editor = QTextEdit()
        self.prompt_editor.setPlaceholderText(
            "Введите System Prompt. Плейсхолдеры можно скопировать справа и вставить в текст."
        )
        editor_layout.addWidget(self.prompt_editor, 1)

        side_panel = QWidget()
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(10)
        side_panel.setMinimumWidth(280)
        side_panel.setMaximumWidth(320)

        defaults_group = QGroupBox("Дефолты плейсхолдеров")
        self.defaults_group = defaults_group
        defaults_form = QFormLayout()
        defaults_form.setContentsMargins(10, 8, 10, 10)
        defaults_form.setSpacing(8)
        self.ph_model_name = QLineEdit()
        self.ph_model_name.setPlaceholderText("например: gemma-3-4b-it")
        self.ph_user_name = QLineEdit()
        self.ph_user_name.setPlaceholderText("например: Vetta")
        self.ph_datetime = QLineEdit()
        self.ph_datetime.setReadOnly(True)
        defaults_form.addRow("model_name:", self.ph_model_name)
        defaults_form.addRow("user_name:", self.ph_user_name)
        defaults_form.addRow("datetime:", self.ph_datetime)
        defaults_group.setLayout(defaults_form)
        defaults_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        side_layout.addWidget(defaults_group)
        if not self.show_defaults:
            defaults_group.hide()

        placeholders_section = QGroupBox("Плейсхолдеры")
        placeholders_section_layout = QVBoxLayout(placeholders_section)
        self.placeholders_section = placeholders_section
        placeholders_section_layout.setContentsMargins(10, 8, 10, 10)
        placeholders_section_layout.setSpacing(6)

        placeholders_tooltip = "Двойной клик по элементу копирует плейсхолдер. Описание доступно в подсказке при наведении."

        placeholders_title_row = QHBoxLayout()
        placeholders_title_row.setContentsMargins(10, 0, 10, 0)
        placeholders_title_row.setSpacing(6)
        self.placeholders_title = QLabel("Плейсхолдеры")
        self.placeholders_title.setObjectName("placeholdersTitle")
        self.placeholders_title.setStyleSheet("font-weight: 700;")
        self.placeholders_title.setToolTip("")
        self.placeholders_section.setToolTip(placeholders_tooltip)
        self.placeholders_title.hide()
        self.placeholders_help = QLabel("")
        self.placeholders_help.setObjectName("placeholdersHelp")
        self.placeholders_help.setToolTip("")
        self.placeholders_help.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholders_help.setFixedSize(0, 0)
        self.placeholders_help.hide()
        self.placeholders_help.setStyleSheet(
            "font-weight: 700;"
        )
        self.placeholders_title.setStyleSheet(
            "font-weight: 700;"
        )
        placeholders_title_row.addWidget(self.placeholders_title)
        placeholders_title_row.addWidget(self.placeholders_help)
        placeholders_title_row.addStretch()

        self.placeholders_group = QFrame()
        self.placeholders_group.setObjectName("promptPlaceholdersCard")
        self.placeholders_group.setFrameShape(QFrame.Shape.NoFrame)
        self.placeholders_group.setStyleSheet(
            "#promptPlaceholdersCard { background-color: transparent; border: none; }"
        )
        placeholders_layout = QVBoxLayout()
        placeholders_layout.setContentsMargins(10, 8, 10, 10)
        placeholders_layout.setSpacing(6)
        self.placeholders_list = QListWidget()
        self.placeholders_list.setAlternatingRowColors(True)
        self.placeholders_list.setMinimumHeight(248)
        self.placeholders_list.setStyleSheet(
            f"QListWidget {{ background-color: {panel_bg}; border: 1px solid {border_color}; color: #FFFFFF; }}"
        )
        self.placeholders_list.itemDoubleClicked.connect(self.copy_placeholder_item)
        placeholders_layout.addWidget(self.placeholders_list)
        self.placeholders_group.setLayout(placeholders_layout)
        placeholders_section_layout.addWidget(self.placeholders_group, 1)
        side_layout.addWidget(placeholders_section, 1)

        templates_group = QGroupBox("Шаблоны")
        templates_layout = QVBoxLayout()
        templates_layout.setContentsMargins(10, 8, 10, 10)
        templates_layout.setSpacing(8)
        self.templates_list = QListWidget()
        self.templates_list.setStyleSheet(
            f"QListWidget {{ background-color: {panel_bg}; border: 1px solid {border_color}; color: #FFFFFF; }}"
        )
        templates_layout.addWidget(self.templates_list)
        templates_buttons = QHBoxLayout()
        self.save_template_button = QPushButton("Сохранить")
        self.load_template_button = QPushButton("Загрузить")
        self.delete_template_button = QPushButton("Удалить")
        templates_buttons.addWidget(self.save_template_button)
        templates_buttons.addWidget(self.load_template_button)
        templates_buttons.addWidget(self.delete_template_button)
        templates_layout.addLayout(templates_buttons)
        templates_group.setLayout(templates_layout)
        templates_group.setMinimumHeight(130)
        side_layout.addWidget(templates_group, 1)

        splitter.addWidget(editor_panel)
        splitter.addWidget(side_panel)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 0)
        main_layout.addWidget(splitter, 1)

        actions_layout = QHBoxLayout()
        self.check_prompt_button = QPushButton("Проверить промпт")
        self.apply_button = QPushButton("Сохранить и применить")
        self.cancel_button = QPushButton("Отмена")
        actions_layout.addWidget(self.check_prompt_button)
        actions_layout.addStretch()
        actions_layout.addWidget(self.apply_button)
        actions_layout.addWidget(self.cancel_button)
        main_layout.addLayout(actions_layout)

        self.prompt_editor.textChanged.connect(self._mark_dirty)
        self.ph_model_name.editingFinished.connect(self.save_defaults_immediately)
        self.ph_user_name.editingFinished.connect(self.save_defaults_immediately)
        self.save_template_button.clicked.connect(self.save_template)
        self.load_template_button.clicked.connect(self.load_selected_template)
        self.delete_template_button.clicked.connect(self.delete_selected_template)
        self.check_prompt_button.clicked.connect(self.validate_current_prompt)
        self.apply_button.clicked.connect(self.apply_changes)
        self.cancel_button.clicked.connect(self.reject)

    def _load_initial_state(self):
        self.prompt_editor.setPlainText(self.original_prompt)
        self.ph_model_name.setText(self.placeholder_defaults.get("model_name", ""))
        self.ph_user_name.setText(self.placeholder_defaults.get("user_name", ""))
        self.ph_datetime.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self._refresh_placeholders()
        self._refresh_templates()
        self._mark_dirty()

    def _refresh_placeholders(self):
        placeholders = self.placeholder_provider()
        self.placeholders_list.clear()
        for placeholder, description in placeholders.items():
            item = QListWidgetItem(placeholder)
            item.setToolTip(description)
            item.setFont(QFont("Courier", 9))
            self.placeholders_list.addItem(item)

    def _refresh_templates(self):
        self.templates_list.clear()
        for template in self.templates:
            name = template.get("name", "Без имени")
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, template)
            item.setToolTip(template.get("text", "")[:400])
            self.templates_list.addItem(item)

    def _mark_dirty(self):
        pass

    def _confirm_discard_changes(self, action_text):
        if self.prompt_editor.toPlainText() == self._last_applied_prompt:
            return True
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"В редакторе есть несохранённые изменения. {action_text}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def copy_placeholder_item(self, item):
        if item:
            QApplication.clipboard().setText(item.text())

    def save_defaults_immediately(self):
        self.placeholder_defaults["model_name"] = self.ph_model_name.text().strip()
        self.placeholder_defaults["user_name"] = self.ph_user_name.text().strip()
        self.panel.persist_prompt_editor_state(
            placeholder_defaults=self.placeholder_defaults,
            history=self.history,
            templates=self.templates,
        )

    def validate_current_prompt(self):
        self.panel.show_prompt_validation_result(self.prompt_editor.toPlainText(), parent_widget=self)

    def save_template(self):
        name, ok = QInputDialog.getText(self, "Новый шаблон", "Название шаблона:")
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "Шаблоны", "Название шаблона не может быть пустым.")
            return

        text = self.prompt_editor.toPlainText()
        for template in self.templates:
            if template.get("name") == name:
                reply = QMessageBox.question(
                    self,
                    "Шаблоны",
                    "Шаблон с таким названием уже существует. Перезаписать?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                template["text"] = text
                self._refresh_templates()
                self.panel.persist_prompt_editor_state(
                    placeholder_defaults=self.placeholder_defaults,
                    history=self.history,
                    templates=self.templates,
                )
                return

        self.templates.append({"name": name, "text": text})
        self._refresh_templates()
        self.panel.persist_prompt_editor_state(
            placeholder_defaults=self.placeholder_defaults,
            history=self.history,
            templates=self.templates,
        )

    def load_selected_template(self):
        current_item = self.templates_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "Шаблоны", "Выберите шаблон для загрузки.")
            return
        if not self._confirm_discard_changes("Загрузить шаблон поверх текущего текста"):
            return
        template = current_item.data(Qt.ItemDataRole.UserRole) or {}
        self.prompt_editor.setPlainText(template.get("text", ""))

    def delete_selected_template(self):
        current_item = self.templates_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "Шаблоны", "Выберите шаблон для удаления.")
            return
        template = current_item.data(Qt.ItemDataRole.UserRole) or {}
        reply = QMessageBox.question(
            self,
            "Шаблоны",
            f"Удалить шаблон '{template.get('name', 'Без имени')}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.templates = [item for item in self.templates if item.get("name") != template.get("name")]
        self._refresh_templates()
        self.panel.persist_prompt_editor_state(
            placeholder_defaults=self.placeholder_defaults,
            history=self.history,
            templates=self.templates,
        )

    def apply_changes(self):
        prompt_text = self.prompt_editor.toPlainText().rstrip()
        previous_text = self.panel.system_prompt_input.toPlainText()
        if prompt_text != previous_text:
            self.history = self.panel.append_prompt_history(self.history, previous_text)

        self.placeholder_defaults["model_name"] = self.ph_model_name.text().strip()
        self.placeholder_defaults["user_name"] = self.ph_user_name.text().strip()

        self._last_applied_prompt = prompt_text
        self.panel.apply_prompt_editor_state(prompt_text, self.placeholder_defaults, self.history, self.templates)
        self.panel.persist_prompt_editor_state(
            prompt_text=prompt_text,
            placeholder_defaults=self.placeholder_defaults,
            history=self.history,
            templates=self.templates,
        )
        self.accept()

    def reject(self):
        if not self._confirm_discard_changes("Закрыть редактор без применения"):
            return
        super().reject()


class SettingsPanel(QWidget):
    def __init__(self, bot_thread=None):
        super().__init__()
        self.bot_thread = bot_thread  # Сохраняем ссылку на поток бота
        self.settings_manager = settings_manager  # Используем существующий экземпляр
        self.placeholder_defaults = {}
        self.system_prompt_history = []
        self.system_prompt_templates = []
        self.init_ui()
        
        # Создаем таймер для автоматического обновления статистики
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.load_models_table)
        self.stats_timer.start(5000)  # Обновляем каждые 5 секунд


    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(0)
        self.save_button = QPushButton('Сохранить настройки')
        top_bar.addStretch()
        top_bar.addWidget(self.save_button)
        main_layout.addLayout(top_bar)

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)
        
        # Основные настройки
        basic_settings_group = QGroupBox("Основные настройки")
        basic_settings_layout = QVBoxLayout()
        basic_settings_layout.setContentsMargins(8, 12, 8, 8)
        basic_settings_layout.setSpacing(4)

        # Telegram Token (умное скрытие)
        self.token_label = QLabel("Telegram Token")
        self.token_label.setObjectName("settingsAccentLabel")
        self.token_label.setStyleSheet("font-weight: 700;")
        self.token_label.setContentsMargins(8, 0, 0, 0)
        basic_settings_layout.addWidget(self.token_label)

        self.telegram_token_input = QLineEdit()
        self.telegram_token_input.setPlaceholderText('Введите ваш Telegram Token. Получить его можно в BotFather.')
        self.telegram_token_input.setToolTip("Токен бота Telegram.")
        self.telegram_token_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.token_hide_timer = QTimer(self)
        self.token_hide_timer.setSingleShot(True)
        self.token_hide_timer.timeout.connect(self.hide_token)

        self.telegram_token_input.focusInEvent = self.token_focus_in
        self.telegram_token_input.focusOutEvent = self.token_focus_out
        self.telegram_token_input.textChanged.connect(self.token_text_changed)
        self.token_container = QWidget()
        token_layout = QHBoxLayout()
        token_layout.setContentsMargins(8, 0, 0, 0)
        token_layout.setSpacing(0)
        token_layout.addWidget(self.telegram_token_input, 1)
        self.token_container.setLayout(token_layout)
        basic_settings_layout.addWidget(self.token_container)

        admin_ids_label = QLabel("Администраторы Telegram")
        admin_ids_label.setObjectName("settingsAccentLabel")
        admin_ids_label.setStyleSheet("font-weight: 700;")
        admin_ids_label.setContentsMargins(8, 0, 0, 0)
        basic_settings_layout.addWidget(admin_ids_label)

        self.admin_telegram_ids_input = QLineEdit()
        self.admin_telegram_ids_input.setPlaceholderText("123456789, 987654321")
        self.admin_telegram_ids_input.setToolTip(
            "Telegram ID администраторов через запятую. "
            "Эти ID получают админские права; priority >= 100 остаётся совместимостью."
        )
        self.admin_telegram_ids_container = QWidget()
        admin_ids_layout = QHBoxLayout()
        admin_ids_layout.setContentsMargins(8, 0, 0, 0)
        admin_ids_layout.setSpacing(0)
        admin_ids_layout.addWidget(self.admin_telegram_ids_input, 1)
        self.admin_telegram_ids_container.setLayout(admin_ids_layout)
        basic_settings_layout.addWidget(self.admin_telegram_ids_container)

        prompt_label = QLabel("Системный промпт")
        prompt_label.setObjectName("settingsAccentLabel")
        prompt_label.setStyleSheet("font-weight: 700;")
        prompt_label.setContentsMargins(8, 0, 0, 0)
        basic_settings_layout.addWidget(prompt_label)

        self.system_prompt_input = QTextEdit()
        self.system_prompt_input.setReadOnly(True)
        self.system_prompt_input.setPlaceholderText('Системный промпт (пустой = без промпта). Поддерживает плейсхолдеры.')
        self.system_prompt_input.setToolTip("Текущий System Prompt. Для редактирования откройте отдельный редактор.")
        self.system_prompt_input.setFixedHeight(68)

        self.prompt_container = QWidget()
        prompt_layout = QHBoxLayout()
        prompt_layout.setContentsMargins(8, 0, 0, 0)
        prompt_layout.setSpacing(6)
        prompt_layout.addWidget(self.system_prompt_input, 1)
        prompt_actions_layout = QVBoxLayout()
        prompt_actions_layout.setSpacing(6)
        prompt_actions_layout.addStretch()
        self.edit_prompt_btn = QPushButton("Редактировать")
        self.edit_prompt_btn.setMaximumWidth(140)
        self.edit_prompt_btn.setFixedHeight(28)
        self.edit_prompt_btn.clicked.connect(self.open_system_prompt_editor)
        self.validate_prompt_btn = QPushButton("Проверить промпт")
        self.validate_prompt_btn.setMaximumWidth(140)
        self.validate_prompt_btn.setFixedHeight(28)
        self.validate_prompt_btn.setToolTip("Проверить текущий System Prompt на ошибки")
        self.validate_prompt_btn.clicked.connect(self.validate_system_prompt)
        prompt_actions_layout.addWidget(self.edit_prompt_btn)
        prompt_actions_layout.addWidget(self.validate_prompt_btn)
        prompt_actions_layout.addStretch()
        prompt_layout.addLayout(prompt_actions_layout)
        self.prompt_container.setLayout(prompt_layout)
        basic_settings_layout.addWidget(self.prompt_container)

        self.prompt_status_label = QLabel()
        self.prompt_status_label.setWordWrap(True)
        self.prompt_status_label.setStyleSheet("color: #9AA6B2; font-size: 11px;")
        self.prompt_status_label.setContentsMargins(8, 0, 8, 0)
        basic_settings_layout.addWidget(self.prompt_status_label)
        self.refresh_system_prompt_status()

        self.temperature_input = QLineEdit()
        self.temperature_input.setPlaceholderText('0.7')
        self.temperature_input.setValidator(QDoubleValidator(0.0, 2.0, 2))
        self.temperature_input.setToolTip("Управляет случайностью генерации.\nБолее высокие значения делают вывод более разнообразным, низкие — более детерминированным")

        self.top_p_input = QLineEdit()
        self.top_p_input.setPlaceholderText('0.95')
        self.top_p_input.setValidator(QDoubleValidator(0.0, 1.0, 2))
        self.top_p_input.setToolTip("Sampling с nucleus (top-p). Альтернатива temperature.")

        self.top_k_input = QLineEdit()
        self.top_k_input.setPlaceholderText('40')
        self.top_k_input.setValidator(QIntValidator(0, 100))
        self.top_k_input.setToolTip("Количество токенов с наивысшей вероятностью для выбора следующего токена.")

        self.max_tokens_input = QLineEdit()
        self.max_tokens_input.setPlaceholderText('1024')
        self.max_tokens_input.setValidator(QIntValidator(100, 10000))
        self.max_tokens_input.setToolTip("Максимальное количество токенов в ответе.")

        self.repeat_penalty_input = QLineEdit()
        self.repeat_penalty_input.setPlaceholderText('1.1')
        self.repeat_penalty_input.setValidator(QDoubleValidator(0.0, 2.0, 2))
        self.repeat_penalty_input.setToolTip("Штраф за повторение слов и фраз.")

        self.presence_penalty_input = QLineEdit()
        self.presence_penalty_input.setPlaceholderText('0.0')
        self.presence_penalty_input.setValidator(QDoubleValidator(-2.0, 2.0, 2))
        self.presence_penalty_input.setToolTip("Штраф за повторение одной и той же темы.")

        self.frequency_penalty_input = QLineEdit()
        self.frequency_penalty_input.setPlaceholderText('0.0')
        self.frequency_penalty_input.setValidator(QDoubleValidator(-2.0, 2.0, 2))
        self.frequency_penalty_input.setToolTip("Штраф за частое повторение одних и тех же фраз.")

        self.seed_input = QLineEdit()
        self.seed_input.setPlaceholderText('-1')
        self.seed_input.setValidator(QIntValidator(-1, 999999))
        self.seed_input.setToolTip("Фиксированный seed делает одинаковые запросы воспроизводимыми. -1 означает случайный seed.")

        self.balancing_strategy_combo = QComboBox()
        self.balancing_strategy_combo.addItems([
            "round_robin", "random_weighted", "least_used"
        ])
        self.balancing_strategy_combo.setToolTip("Стратегия распределения запросов между моделями.")

        self.generation_frame = QFrame()
        self.generation_frame.setObjectName("generationCard")
        self.generation_frame.setFrameShape(QFrame.Shape.NoFrame)
        generation_layout = QVBoxLayout(self.generation_frame)
        generation_layout.setContentsMargins(12, 12, 12, 10)
        generation_layout.setSpacing(6)

        top_generation_grid = QGridLayout()
        top_generation_grid.setHorizontalSpacing(10)
        top_generation_grid.setVerticalSpacing(6)

        top_fields = [
            ("Temperature", self.temperature_input, 132),
            ("Top P", self.top_p_input, 132),
            ("Top K", self.top_k_input, 132),
            ("Repeat Penalty", self.repeat_penalty_input, 132),
            ("Presence Penalty", self.presence_penalty_input, 132),
            ("Frequency Penalty", self.frequency_penalty_input, 132),
        ]

        for index, (label_text, widget, width) in enumerate(top_fields):
            row = index // 2
            column = index % 2
            top_generation_grid.addWidget(self.create_compact_setting(label_text, widget, width), row, column)
            top_generation_grid.setColumnStretch(column, 1)

        generation_layout.addLayout(top_generation_grid)

        self.generation_divider = QFrame()
        self.generation_divider.setObjectName("generationDivider")
        generation_layout.addWidget(self.generation_divider)

        bottom_generation_grid = QGridLayout()
        bottom_generation_grid.setHorizontalSpacing(10)
        bottom_generation_grid.setVerticalSpacing(6)

        bottom_fields = [
            ("Max Tokens", self.max_tokens_input, 132),
            ("Seed", self.seed_input, 132),
            ("Стратегия балансировки", self.balancing_strategy_combo, 132),
        ]

        for index, (label_text, widget, width) in enumerate(bottom_fields):
            bottom_generation_grid.addWidget(self.create_compact_setting(label_text, widget, width), 0, index)
            bottom_generation_grid.setColumnStretch(index, 1)

        generation_layout.addLayout(bottom_generation_grid)
        basic_settings_layout.addWidget(self.generation_frame)
        basic_settings_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        basic_settings_group.setLayout(basic_settings_layout)
        content_layout.addWidget(basic_settings_group)

        # Секция управления моделями
        models_group = QGroupBox("LM Модели")
        models_layout = QVBoxLayout()
        models_layout.setContentsMargins(10, 12, 10, 8)
        models_layout.setSpacing(8)
        
        # Таблица моделей
        self.models_table = QTableWidget()
        self.models_table.setColumnCount(10)
        self.models_table.setHorizontalHeaderLabels([
            "ID", "Тип", "API Key", "Base URL", "Вес", "Запросы", "Ошибки", "VLM", "Думание", "Активна"
        ])
        self.models_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.models_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.models_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.models_table.setMinimumHeight(84)
        self.models_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.models_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Настройка размеров столбцов
        self.models_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # ID
        self.models_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Тип
        self.models_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # API Key
        self.models_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)  # Base URL
        self.models_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Вес
        self.models_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Запросы
        self.models_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Ошибки
        self.models_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)  # VLM
        self.models_table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)  # Думание
        self.models_table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeMode.ResizeToContents)  # Активна
        
        self.models_table.setColumnWidth(0, 120)
        
        models_layout.addWidget(self.models_table, 1)
        
        # Кнопки управления моделями
        models_buttons_layout = QHBoxLayout()
        self.add_model_button = QPushButton("Добавить модель")
        self.edit_model_button = QPushButton("Редактировать")
        self.delete_model_button = QPushButton("Удалить")
        for button in (self.add_model_button, self.edit_model_button, self.delete_model_button):
            button.setFixedHeight(28)
        models_buttons_layout.setContentsMargins(0, 0, 0, 0)
        models_buttons_layout.setSpacing(6)
        
        models_buttons_layout.addWidget(self.add_model_button)
        models_buttons_layout.addWidget(self.edit_model_button)
        models_buttons_layout.addWidget(self.delete_model_button)
        models_buttons_layout.addStretch()
        models_layout.addLayout(models_buttons_layout)
        
        models_group.setLayout(models_layout)
        models_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        models_group.setMinimumHeight(130)
        content_layout.addWidget(models_group, 1)
        main_layout.addLayout(content_layout, 1)

        self.setLayout(main_layout)
        
        # Загрузка текущих настроек
        self.load_settings()
        
        # Привязка событий
        self.save_button.clicked.connect(self.save_settings)
        self.add_model_button.clicked.connect(self.add_model)
        self.edit_model_button.clicked.connect(self.edit_model)
        self.delete_model_button.clicked.connect(self.delete_model)

    def apply_theme(self, is_oled: bool, accent_color: str):
        """Обновляет проблемные зоны при смене темы."""
        # Стили теперь наследуются от главного окна AdminPanelBase.
        # Мы больше не устанавливаем жесткие стили на scroll_area и scroll_content,
        # чтобы не блокировать отображение границ QGroupBox.
        
        if is_oled:
            border_color = "#333333"
            header_bg = "#111111"
            bg_color = "#000000"
        else:
            border_color = "#444444"
            header_bg = "#252526"
            bg_color = "#1e1e1e"
            
        # Обновляем таблицу моделей отдельно для применения акцентов и заголовков
        self.models_table.setStyleSheet(f"""
            QHeaderView::section {{
                background-color: {header_bg};
                color: #FFFFFF;
                border: 1px solid {border_color};
                font-weight: bold;
            }}
            QHeaderView {{
                background-color: {bg_color};
            }}
            QTableCornerButton::section {{
                background-color: {bg_color};
                border: 1px solid {border_color};
            }}
            QHeaderView::section:vertical {{
                background-color: {bg_color};
                border: 1px solid {border_color};
            }}
            QTableWidget {{
                gridline-color: {border_color};
                background-color: {bg_color};
                color: #FFFFFF;
                border: 1px solid {border_color};
            }}
        """)

        self.generation_frame.setStyleSheet("")
        self.generation_divider.setStyleSheet(
            f"background-color: {border_color}; min-height: 1px; max-height: 1px; border: none;"
        )
        for label in self.findChildren(QLabel, "settingsAccentLabel"):
            label.setStyleSheet(f"font-weight: 700; color: {accent_color};")


    # Методы для умного скрытия токена
    def token_focus_in(self, event):
        """Показываем токен при получении фокуса"""
        self.telegram_token_input.setEchoMode(QLineEdit.EchoMode.Normal)
        self.token_hide_timer.stop()  # Останавливаем таймер
        # Вызываем оригинальный обработчик
        QLineEdit.focusInEvent(self.telegram_token_input, event)
        
    def token_focus_out(self, event):
        """Скрываем токен при потере фокуса"""
        self.hide_token()
        # Вызываем оригинальный обработчик
        QLineEdit.focusOutEvent(self.telegram_token_input, event)
        
    def token_text_changed(self):
        """Перезапускаем таймер при изменении текста"""
        if self.telegram_token_input.hasFocus():
            self.token_hide_timer.start(8000)  # 8 секунд
            
    def hide_token(self):
        """Скрываем токен"""
        self.telegram_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_hide_timer.stop()

    def create_compact_setting(self, label_text, widget, max_width):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        if label_text:
            label = QLabel(label_text)
            label.setWordWrap(False)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            label.setStyleSheet("font-size: 12px; color: #AAAAAA;")
            label.setMinimumHeight(18)
            layout.addWidget(label)
        else:
            layout.addSpacing(18)

        widget.setMinimumWidth(max_width)
        widget.setFixedHeight(28)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(widget)
        container.setMinimumHeight(48)
        return container

    def set_system_prompt_preview(self, prompt_text):
        self.system_prompt_input.setPlainText(prompt_text or "")
        self.refresh_system_prompt_status()

    def refresh_system_prompt_status(self):
        if not hasattr(self, "prompt_status_label"):
            return
        updated_at = self.settings_manager.settings.get("system_prompt_updated_at", "")
        self.prompt_status_label.setText(
            build_system_prompt_status(
                self.system_prompt_input.toPlainText(),
                updated_at,
            )
        )

    def append_prompt_history(self, history, prompt_text):
        text = (prompt_text or "").rstrip()
        if not text:
            return list(history or [])

        updated_history = list(history or [])
        if updated_history and updated_history[-1].get("text", "") == text:
            return updated_history

        updated_history.append({
            "text": text,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        return updated_history[-PromptEditorDialog.HISTORY_LIMIT:]

    def apply_prompt_editor_state(self, prompt_text, placeholder_defaults, history, templates):
        self.placeholder_defaults = dict(placeholder_defaults or {})
        self.system_prompt_history = list(history or [])
        self.system_prompt_templates = list(templates or [])
        self.set_system_prompt_preview(prompt_text)

    def persist_prompt_editor_state(self, prompt_text=None, placeholder_defaults=None, history=None, templates=None):
        previous_prompt = self.settings_manager.settings.get('system_prompt', '')
        if prompt_text is not None:
            self.set_system_prompt_preview(prompt_text)
        if placeholder_defaults is not None:
            self.placeholder_defaults = dict(placeholder_defaults or {})
        if history is not None:
            self.system_prompt_history = list(history or [])
        if templates is not None:
            self.system_prompt_templates = list(templates or [])

        active_prompt = self.system_prompt_input.toPlainText().strip()
        self.settings_manager.settings['system_prompt'] = active_prompt
        if active_prompt != previous_prompt:
            self.settings_manager.settings['system_prompt_updated_at'] = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        self.settings_manager.settings['placeholder_defaults'] = self.placeholder_defaults
        self.settings_manager.save_system_prompt_history(
            self.system_prompt_history[-PromptEditorDialog.HISTORY_LIMIT:]
        )
        self.settings_manager.save_system_prompt_templates(self.system_prompt_templates)
        self.settings_manager.save_settings()
        self.refresh_system_prompt_status()

    def open_system_prompt_editor(self):
        try:
            dialog = PromptEditorDialog(
                self,
                self.system_prompt_input.toPlainText(),
                self.placeholder_defaults,
                self.system_prompt_history,
                self.system_prompt_templates,
            )
            dialog.exec()
        except Exception as e:
            logger.error(f"Ошибка открытия редактора промпта: {e}")
            QMessageBox.warning(self, "Ошибка", "Не удалось открыть редактор System Prompt.")

    def open_placeholders_dialog(self):
        self.open_system_prompt_editor()

    def build_prompt_validation_result(self, prompt):
        is_valid, warnings, recommendations = validate_system_prompt(prompt)

        token_info = ""
        if prompt.strip():
            try:
                from utils.tokenizer import count_tokens

                settings = self.settings_manager.get_settings()
                model_id = settings.get('model_id') or (settings.get('models', [{}])[0].get('id') if settings.get('models') else None)
                n_tokens = count_tokens(
                    prompt,
                    model_id=model_id,
                    allow_hf_tokenizer=False,
                )
                token_info = f"\n\nОценка токенов системного промпта: ~{n_tokens} токенов"
            except Exception:
                pass

        if is_valid and not warnings:
            if not prompt.strip():
                return True, "✅ Модель будет работать без системного промпта"
            return True, "✅ Промпт выглядит хорошо!" + token_info

        message = "Результат проверки:\n\n"
        if warnings:
            message += "Предупреждения:\n"
            for warning in warnings:
                message += f"• {warning}\n"
            message += "\n"

        if recommendations:
            message += "Рекомендации:\n"
            for rec in recommendations:
                message += f"• {rec}\n"

        return is_valid, message + token_info

    def show_prompt_validation_result(self, prompt, parent_widget=None):
        parent_widget = parent_widget or self
        try:
            is_valid, message = self.build_prompt_validation_result(prompt)
            if is_valid:
                QMessageBox.information(parent_widget, "Проверка", message)
            else:
                QMessageBox.warning(parent_widget, "Проверка", message)
        except Exception as e:
            logger.error(f"Ошибка при проверке промпта: {e}")
            QMessageBox.warning(parent_widget, "Ошибка", "Не удалось проверить промпт")

    def validate_system_prompt(self):
        """Проверить системный промпт на ошибки и оценить токены"""
        self.show_prompt_validation_result(self.system_prompt_input.toPlainText())

    def _reload_models_sync(self):
        """Вспомогательная функция для синхронной перезагрузки моделей"""
        try:
            init_model_clients()
            logger.info("Модели успешно перезагружены через GUI")
        except Exception as e:
            logger.error(f"Ошибка при перезагрузке моделей: {e}")

    def load_settings(self):
        settings = self.settings_manager.get_settings()
        self.telegram_token_input.setText(settings.get('telegram_token', ''))
        admin_ids = settings.get('admin_telegram_ids', []) or []
        self.admin_telegram_ids_input.setText(", ".join(str(item) for item in admin_ids))
        self.placeholder_defaults = dict(settings.get('placeholder_defaults', {}) or {})
        self.system_prompt_history = list(self.settings_manager.load_system_prompt_history() or [])
        self.system_prompt_templates = list(self.settings_manager.load_system_prompt_templates() or [])
        self.set_system_prompt_preview(settings.get('system_prompt', ''))
        self.temperature_input.setText(str(settings.get('temperature', '0.7')))
        self.max_tokens_input.setText(str(settings.get('max_tokens', '1024')))
        self.presence_penalty_input.setText(str(settings.get('presence_penalty', '0.0')))
        self.frequency_penalty_input.setText(str(settings.get('frequency_penalty', '0.0')))
        self.top_p_input.setText(str(settings.get('top_p', '0.95')))
        self.top_k_input.setText(str(settings.get('top_k', '40')))
        self.repeat_penalty_input.setText(str(settings.get('repeat_penalty', '1.1')))
        self.seed_input.setText(str(settings.get('seed', '-1')))
        
        # Загружаем стратегию балансировки
        strategy = settings.get('load_balancing_strategy', 'round_robin')
        index = self.balancing_strategy_combo.findText(strategy)
        if index >= 0:
            self.balancing_strategy_combo.setCurrentIndex(index)
        
        # Загружаем таблицу моделей
        self.load_models_table()

    def load_models_table(self):
        settings = self.settings_manager.get_settings()
        models = settings.get('models', [])
        stats = get_model_usage_stats()
        
        self.models_table.setRowCount(len(models))
        
        # Короткие обозначения типов API для таблицы
        api_type_labels = {
            'openai': 'OAI',
            'anthropic': 'Claude',
        }
        
        for row, model in enumerate(models):
            model_id = model.get('id', '')
            model_stats = stats.get(model_id, {"requests": 0, "errors": 0})
            
            # ID
            self.models_table.setItem(row, 0, QTableWidgetItem(model_id))
            
            # Тип API
            api_type = model.get('api_type', 'openai')
            type_item = QTableWidgetItem(api_type_labels.get(api_type, api_type))
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.models_table.setItem(row, 1, type_item)
            
            # API Key
            api_key = model.get('api_key', '')
            masked_key = '*' * (len(api_key) - 4) + api_key[-4:] if len(api_key) > 4 else api_key
            self.models_table.setItem(row, 2, QTableWidgetItem(masked_key))
            
            # Base URL
            self.models_table.setItem(row, 3, QTableWidgetItem(model.get('base_url', '')))
            
            # Weight
            weight_item = QTableWidgetItem(str(model.get('weight', 1)))
            weight_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.models_table.setItem(row, 4, weight_item)
            
            # Requests
            requests_item = QTableWidgetItem(str(model_stats["requests"]))
            requests_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.models_table.setItem(row, 5, requests_item)
            
            # Errors
            errors_item = QTableWidgetItem(str(model_stats["errors"]))
            errors_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.models_table.setItem(row, 6, errors_item)

            # VLM support
            vlm_item = QTableWidgetItem("✓" if model.get('supports_vision') else "—")
            vlm_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.models_table.setItem(row, 7, vlm_item)

            # Reasoning
            reasoning_mode = model.get('reasoning_mode')
            if not reasoning_mode:
                reasoning_mode = model.get('reasoning_effort', 'medium') if model.get('reasoning_enabled') else 'default'
                if reasoning_mode == 'none':
                    reasoning_mode = 'off'
            reasoning_item = QTableWidgetItem(reasoning_mode)
            reasoning_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.models_table.setItem(row, 8, reasoning_item)

            # Active status
            active = model.get('active', True)
            checkbox = QCheckBox()
            checkbox.setChecked(active)
            checkbox.stateChanged.connect(lambda state, r=row: self.toggle_model_active(r, state == 2))

            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            
            self.models_table.setCellWidget(row, 9, checkbox_widget)

    def toggle_model_active(self, row, active):
        """Переключить активность модели"""
        try:
            # 🆕 Используем ModelService
            success, message = ModelService.toggle_model_active(row, active)
            
            if not success:
                self.show_error(message)
                return
            
            # Перезагружаем модели для применения изменений
            self._reload_models_sync()
                
        except Exception as e:
            logger.error(f"Ошибка при изменении статуса модели: {e}")
            self.show_error(f"Ошибка при изменении статуса модели: {e}")

    def add_model(self):
        dialog = ModelDialog(self)
        # Применяем тему OLED/стандартную
        parent_base = self.parent()
        while parent_base and not hasattr(parent_base, 'apply_theme'):
            parent_base = parent_base.parent()
        if parent_base and hasattr(parent_base, 'apply_theme'):
            # Мы можем использовать ту же логику стилизации, что и для других диалогов
            # Но так как ModelDialog это QDialog, общие стили из AdminPanelBase уже подхватятся
            # если мы правильно прописали их в apply_theme родителя.
            pass
            
        if dialog.exec() == QDialog.DialogCode.Accepted:
            model_data = dialog.get_model_data()
            
            # 🆕 Используем ModelService для добавления
            success, message = ModelService.add_model(model_data)
            
            if not success:
                self.show_error(message)
                return
            
            # Перезагружаем модели
            self._reload_models_sync()
            
            self.load_models_table()
            self.show_message(message)

    def edit_model(self):
        current_row = self.models_table.currentRow()
        if current_row == -1:
            self.show_error("Выберите модель для редактирования")
            return
        
        models = ModelService.get_all_models()
        
        if current_row >= len(models):
            self.show_error("Выбранная модель не найдена")
            return
        
        existing_model = models[current_row]
        dialog = ModelDialog(self, existing_model)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            model_data = dialog.get_model_data()
            
            # 🆕 Используем ModelService для редактирования
            success, message = ModelService.edit_model(current_row, model_data)
            
            if not success:
                self.show_error(message)
                return
            
            # Перезагружаем модели
            self._reload_models_sync()
            
            self.load_models_table()
            self.show_message(message)

    def delete_model(self):
        current_row = self.models_table.currentRow()
        if current_row == -1:
            self.show_error("Выберите модель для удаления")
            return
        
        models = ModelService.get_all_models()
        
        if current_row >= len(models):
            self.show_error("Выбранная модель не найдена")
            return
        
        model_to_delete = models[current_row]
        model_id = model_to_delete.get('id', 'Unknown')
        
        # Подтверждение удаления
        reply = QMessageBox.question(
            self, 
            'Подтверждение удаления', 
            f"Вы уверены, что хотите удалить модель '{model_id}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 🆕 Используем ModelService для удаления
            success, message = ModelService.delete_model(current_row)
            
            if not success:
                self.show_error(message)
                return
            
            # Перезагружаем модели
            self._reload_models_sync()
            
            self.load_models_table()
            self.show_message(message)

    def save_settings(self):
        try:
            # Сохраняем старые настройки для сравнения
            old_settings = self.settings_manager.get_settings()
            old_token = old_settings.get('telegram_token', '')
            old_models = old_settings.get('models', [])
            
            new_settings = {
                'telegram_token': self.telegram_token_input.text().strip(),
                'admin_telegram_ids': self.settings_manager._normalize_telegram_id_list(
                    self.admin_telegram_ids_input.text()
                ),
                'system_prompt': self.system_prompt_input.toPlainText().strip(),
                'placeholder_defaults': self.placeholder_defaults,
                'temperature': float(self.temperature_input.text() or 0.7),
                'max_tokens': int(self.max_tokens_input.text() or 1024),
                'presence_penalty': float(self.presence_penalty_input.text() or 0.0),
                'frequency_penalty': float(self.frequency_penalty_input.text() or 0.0),
                'top_p': float(self.top_p_input.text() or 0.95),
                'top_k': int(self.top_k_input.text() or 40),
                'repeat_penalty': float(self.repeat_penalty_input.text() or 1.1),
                'seed': int(self.seed_input.text() or -1),
                'load_balancing_strategy': self.balancing_strategy_combo.currentText(),
            }
            
            # Проверяем критические изменения
            new_token = new_settings['telegram_token']
            token_changed = old_token != new_token
            
            # Обновляем настройки в менеджере и сохраняем
            self.settings_manager.settings.update(new_settings)
            self.settings_manager.save_system_prompt_history(
                self.system_prompt_history[-PromptEditorDialog.HISTORY_LIMIT:]
            )
            self.settings_manager.save_system_prompt_templates(self.system_prompt_templates)
            self.settings_manager.save_settings()
            
            # Перезагружаем модели для применения новых настроек
            self._reload_models_sync()
            
            # УМНЫЙ ПЕРЕЗАПУСК: если изменились критические настройки
            should_restart = token_changed  # Пока только токен требует перезапуска
            
            if should_restart and self.bot_thread is not None:
                logger.info("Критические настройки изменились - выполняем умный перезапуск...")
                
                # Получаем родительское окно (AdminPanelBase) для вызова умного перезапуска
                parent_window = self.parent()
                while parent_window and not hasattr(parent_window, 'smart_restart_bot'):
                    parent_window = parent_window.parent()
                
                if parent_window and hasattr(parent_window, 'smart_restart_bot'):
                    # Используем умный перезапуск из админ-панели
                    success = parent_window.smart_restart_bot("Изменение критических настроек")
                    if success:
                        self.show_message("Настройки сохранены успешно. Бот перезапущен с новыми настройками!")
                    else:
                        # Ошибка валидации показана в smart_restart_bot()
                        logger.warning("Умный перезапуск не удался - настройки невалидны")
                else:
                    # Fallback: используем старый метод перезапуска
                    logger.warning("Не найден parent с smart_restart_bot, используем старый метод")
                    if new_token:
                        self.bot_thread.restart_bot()
                        self.show_message("Настройки сохранены успешно. Бот перезапускается...")
                    else:
                        self.show_message("Настройки сохранены. Внимание: пустой токен, бот остановлен.")
            else:
                # Обычное сохранение без перезапуска
                self.show_message("Настройки сохранены успешно")
            
            logger.info("Настройки сохранены через GUI")
            
        except ValueError as e:
            self.show_error(f"Ошибка в формате данных: {e}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении настроек: {e}")
            self.show_error(f"Ошибка при сохранении настроек: {e}")

    def show_error(self, message):
        QMessageBox.critical(self, "Ошибка", message)

    def show_message(self, message):
        QMessageBox.information(self, "Информация", message) 
