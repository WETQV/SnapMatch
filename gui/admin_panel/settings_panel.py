# gui/admin_panel/settings_panel.py
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, QComboBox, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QDialog, QTextEdit, QApplication, QFrame,
    QGridLayout, QListWidget, QListWidgetItem, QSplitter, QSizePolicy,
    QScrollArea, QSpinBox, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QTimer
from config.settings import settings_manager  # Импортируем существующий экземпляр
from PyQt6.QtGui import QDoubleValidator, QIntValidator, QFontDatabase
from bot.handlers.queue_manager import (
    get_model_usage_stats,
    get_available_placeholders,
    init_model_clients,
    validate_system_prompt,
)
from bot.handlers.services.prompt_manager import build_system_prompt_status
from gui.design.dialogs import FxDialog, SHADOW, ask, inform, warn, error, prompt_text
from gui.design import (
    Collapsible, FxButton, FxComboBox, StatusBadge, Switch, SwitchRow,
    card, icon_button, label, page_header, primary,
)
from .services.model_service import ModelService  # Сервис управления моделями
from utils.logger import setup_logger

logger = setup_logger(__name__)


def _caption_field(caption: str, widget: QWidget) -> QWidget:
    """Поле с подписью над ним (подписи сверху экономят ширину)."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(label(caption, "muted"))
    lay.addWidget(widget)
    return box


def _spin(minimum: int, maximum: int, value: int = 0, step: int = 1) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setValue(value)
    return spin


class ModelsTable(QTableWidget):
    """Таблица моделей: на узкой ширине скрывает колонки API Key и Base URL (они есть в подсказке ID и в форме
    редактирования), чтобы не появлялась горизонтальная прокрутка и не обрезались ID и переключатели."""

    COL_KEY, COL_URL = 2, 3
    WIDTH_FULL = 900          # ключ и URL видны
    WIDTH_WITH_URL_ONLY = 780  # виден только URL

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        width = self.viewport().width()
        self.setColumnHidden(self.COL_KEY, width < self.WIDTH_FULL)
        self.setColumnHidden(self.COL_URL, width < self.WIDTH_WITH_URL_ONLY)


class ModelDialog(FxDialog):
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
        super().__init__(parent, "Добавить/Редактировать модель")
        self.setMinimumSize(620 + 2 * SHADOW, 460 + 2 * SHADOW)
        self.resize_content(720, 680)
        self.existing_model = existing_model
        self.init_ui()
        
    def init_ui(self):
        outer = self.body
        outer.addLayout(page_header(
            "Редактирование модели" if self.existing_model else "Новая модель",
            "Подключение к API и поведение модели при распределении запросов",
        ))

        # Прокручиваемая область с секциями-карточками
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 8, 0)
        body_lay.setSpacing(14)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # ── Подключение ──
        connection, conn_lay = card()
        conn_lay.setSpacing(12)
        conn_lay.addWidget(label("Подключение", "h2"))

        # Тип API (первый элемент — определяет подсказки остальных полей)
        self.api_type_combo = FxComboBox()
        self.api_type_combo.addItems([
            "OpenAI-compatible (LM Studio, Ollama, OpenAI, OpenRouter, Chutes)",
            "Anthropic (Claude)",
        ])
        self.api_type_combo.setToolTip(
            "Тип API\n"
            "Определяет формат запросов к модели.\n\n"
            "OpenAI-compatible — универсальный формат.\n"
            "  Поддерживается: LM Studio, Ollama, OpenAI, OpenRouter, Chutes, Together AI и др.\n\n"
            "Anthropic (Claude) — формат для API Claude.\n"
            "  Используется: Anthropic Claude (api.anthropic.com)"
        )
        self.api_type_combo.currentIndexChanged.connect(self._on_api_type_changed)
        conn_lay.addWidget(_caption_field('Тип API', self.api_type_combo))

        self.model_id_input = QLineEdit()
        self.model_id_input.setPlaceholderText('Например: gemma-7b-it')
        self.model_id_input.setToolTip(
            "ID модели\n"
            "Уникальный идентификатор модели. Используется при запросах к API.\n\n"
            "LM Studio: название модели из списка загруженных\n"
            "Ollama: название модели (например: llama3.2)\n"
            "OpenAI: gpt-4o, gpt-4o-mini, gpt-3.5-turbo и т.д.\n"
            "OpenRouter: google/gemini-2.0-flash-exp:free и т.д.\n"
            "Chutes: ID модели/cord в формате провайдера.\n\n"
            "Если несколько экземпляров одной модели — добавьте суффикс (например: gemma-7b-it:1)"
        )
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText('API ключ для LM Studio')
        self.api_key_input.setToolTip(
            "API ключ\n"
            "Ключ для авторизации.\n\n"
            "LM Studio: используется то же значение, что и ID модели\n"
            "Ollama: не требуется, но можно продублировать название модели (например: llama3.2)\n"
            "OpenAI: ключ вида sk-... из dashboard.openai.com\n"
            "Anthropic (Claude): ключ вида sk-ant-... из console.anthropic.com\n"
            "OpenRouter: ключ вида sk-or-... из openrouter.ai/keys\n"
            "Chutes: API ключ провайдера, если доступ к модели требует авторизацию"
        )
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText('http://localhost:1234/v1')
        self.base_url_input.setToolTip(
            "URL API\n"
            "Адрес для API запросов.\n\n"
            "Локальные серверы:\n"
            "  LM Studio: http://localhost:1234/v1\n"
            "  Ollama: http://localhost:11434/v1\n\n"
            "Облачные провайдеры:\n"
            "  OpenAI: https://api.openai.com/v1\n"
            "  OpenRouter: https://openrouter.ai/api/v1\n"
            "  Chutes: https://llm.chutes.ai/v1\n\n"
            "Формат: http(s)://<адрес>:<порт>/v1"
        )
        ids = QGridLayout()
        ids.setHorizontalSpacing(14)
        ids.setColumnStretch(0, 1)
        ids.setColumnStretch(1, 1)
        ids.addWidget(_caption_field('ID модели', self.model_id_input), 0, 0)
        ids.addWidget(_caption_field('API ключ', self.api_key_input), 0, 1)
        conn_lay.addLayout(ids)
        conn_lay.addWidget(_caption_field('URL API', self.base_url_input))
        body_lay.addWidget(connection)

        # ── Поведение ──
        behavior, beh_lay = card()
        beh_lay.setSpacing(12)
        beh_lay.addWidget(label("Поведение", "h2"))

        self.weight_input = _spin(1, 100, 1)
        self.weight_input.setToolTip(
            "Вес для балансировки\n"
            "Вес модели для взвешенного распределения запросов.\n"
            "Чем больше значение, тем чаще модель будет выбираться при стратегии random_weighted"
        )
        self.max_concurrent_input = _spin(1, 100, 1)
        self.max_concurrent_input.setToolTip(
            "Макс. одновременных запросов\n"
            "Максимальное количество одновременных запросов для этой модели.\n\n"
            "LM Studio 0.4+: до 4 (настраивается в Advanced Settings → Max Concurrent Predictions)\n"
            "Ollama: 3-10 в зависимости от железа (если мощное, можно выше)\n"
            "Облачные API (OpenAI, Claude, OpenRouter): 5-50 в зависимости от тарифа\n\n"
            "Бот автоматически распределяет запросы с учётом этого лимита."
        )
        self.context_window_input = _spin(256, 131072, 4096, 512)
        self.context_window_input.setToolTip(
            "Размер окна контекста\n"
            "Размер окна контекста модели в токенах.\n"
            "LM Studio: посмотрите в Server settings → Context length (ctx_len)\n"
            "Ollama: запустите команду 'ollama show --json model_name' и ищите context_length\n"
            "Примеры: llama3=8192, mistral=32768, gemma=4096"
        )
        numbers = QGridLayout()
        numbers.setHorizontalSpacing(14)
        for column in range(3):
            numbers.setColumnStretch(column, 1)
        numbers.addWidget(_caption_field('Вес (для балансировки)', self.weight_input), 0, 0)
        numbers.addWidget(_caption_field('Макс. одновременных запросов', self.max_concurrent_input), 0, 1)
        numbers.addWidget(_caption_field('Окно контекста (токены)', self.context_window_input), 0, 2)
        beh_lay.addLayout(numbers)

        self.active_checkbox = SwitchRow("Активировать модель", True)
        self.active_checkbox.setToolTip("Активировать модель\nЕсли отключено, модель не будет использоваться для обработки запросов")
        beh_lay.addWidget(self.active_checkbox)

        self.vision_checkbox = SwitchRow("Поддерживает изображения (VLM)", False)
        self.vision_checkbox.setToolTip(
            "Поддержка изображений (VLM)\n"
            "Включите, если модель умеет обрабатывать изображения (Vision-Language Model).\n"
            "Такие модели получат доступ к изображениям из истории и запросов."
        )
        beh_lay.addWidget(self.vision_checkbox)
        body_lay.addWidget(behavior)

        # ── Думание модели (редко нужно — под раскрывающейся секцией) ──
        reasoning_box = QWidget()
        reasoning_grid = QGridLayout(reasoning_box)
        reasoning_grid.setContentsMargins(0, 0, 0, 0)
        reasoning_grid.setHorizontalSpacing(14)
        for column in range(3):
            reasoning_grid.setColumnStretch(column, 1)

        self.reasoning_mode_combo = FxComboBox()
        for text, value in self.REASONING_MODES:
            self.reasoning_mode_combo.addItem(text, value)
        self.reasoning_mode_combo.setToolTip(
            "Думание\n"
            "Не управлять — режим по умолчанию, без дополнительных reasoning-параметров.\n"
            "Thinking не выводится в Telegram."
        )
        self.reasoning_provider_combo = FxComboBox()
        for text, value in self.REASONING_PROVIDERS:
            self.reasoning_provider_combo.addItem(text, value)
        self.reasoning_provider_combo.setToolTip("Формат\nФормат reasoning/thinking payload для провайдера.")
        self.reasoning_budget_input = _spin(0, 200000, 0, 1024)
        self.reasoning_budget_input.setToolTip(
            "Бюджет токенов\n"
            "Бюджет thinking-токенов для Anthropic budget или OpenRouter budget. 0 — не передавать бюджет.\n"
            "Для Anthropic минимум 1024 и значение должно быть меньше max_tokens."
        )
        reasoning_grid.addWidget(_caption_field('Думание', self.reasoning_mode_combo), 0, 0)
        reasoning_grid.addWidget(_caption_field('Формат', self.reasoning_provider_combo), 0, 1)
        reasoning_grid.addWidget(_caption_field('Бюджет токенов', self.reasoning_budget_input), 0, 2)
        self.reasoning_mode_combo.currentIndexChanged.connect(self._update_reasoning_budget_state)
        self.reasoning_provider_combo.currentIndexChanged.connect(self._update_reasoning_budget_state)

        reasoning_card, reasoning_lay = card()
        self.reasoning_group = Collapsible(
            "Думание модели", reasoning_box,
            expanded=bool(self.existing_model) and self._existing_reasoning_mode() != 'default',
        )
        reasoning_lay.addWidget(self.reasoning_group)
        body_lay.addWidget(reasoning_card)
        body_lay.addStretch(1)

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
            self._set_combo_by_data(self.reasoning_mode_combo, self._existing_reasoning_mode())
            self._set_combo_by_data(self.reasoning_provider_combo, self.existing_model.get('reasoning_provider', 'auto'))
            self.reasoning_budget_input.setValue(self.existing_model.get('reasoning_budget_tokens', 0))
        self._update_reasoning_budget_state()
        
        # Кнопки
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        self.cancel_button = FxButton('Отмена')
        self.save_button = primary('Сохранить')
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.save_button)
        outer.addLayout(button_layout)
        
        # Привязка событий
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
    
    def _existing_reasoning_mode(self) -> str:
        """Режим думания редактируемой модели (с учётом старых полей reasoning_enabled/effort)."""
        model = self.existing_model or {}
        mode = model.get('reasoning_mode')
        if not mode:
            mode = model.get('reasoning_effort', 'medium') if model.get('reasoning_enabled') else 'default'
            if mode == 'none':
                mode = 'off'
        return mode

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



class PromptEditorDialog(FxDialog):
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
        super().__init__(parent, title)
        self.panel = panel_adapter or parent
        self.original_prompt = prompt_text or ""
        self.placeholder_defaults = dict(placeholder_defaults or {})
        self.history = list(history or [])
        # Мусор в файле шаблонов (не dict, text=null) пропускаем, значения приводим к строкам
        self.templates = [
            {**item, "name": str(item.get("name") or "Без имени"), "text": str(item.get("text") or "")}
            for item in (templates or [])
            if isinstance(item, dict)
        ]
        self._last_applied_prompt = self.original_prompt
        self.placeholder_provider = placeholder_provider or get_available_placeholders
        self.show_defaults = bool(show_defaults)

        self.setMinimumSize(900 + 2 * SHADOW, 660 + 2 * SHADOW)
        self.resize_content(1140, 700)
        self.init_ui()
        self._load_initial_state()

    def init_ui(self):
        main_layout = self.body
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── Слева: редактор ──
        editor_card, editor_layout = card()
        editor_layout.setSpacing(10)
        editor_layout.addWidget(label("Текст промпта", "h2"))
        self.prompt_editor = QTextEdit()
        self.prompt_editor.setPlaceholderText(
            "Введите System Prompt. Плейсхолдеры можно скопировать справа и вставить в текст."
        )
        editor_layout.addWidget(self.prompt_editor, 1)
        editor_card.setMinimumWidth(380)

        # ── Справа: карточки ──
        side_panel = QWidget()
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(12)
        side_panel.setMinimumWidth(300)
        side_panel.setMaximumWidth(380)

        # Дефолты плейсхолдеров
        self.defaults_group, defaults_layout = card()
        defaults_layout.setSpacing(8)
        defaults_layout.addWidget(label("Дефолты плейсхолдеров", "h2"))
        self.ph_model_name = QLineEdit()
        self.ph_model_name.setPlaceholderText("например: gemma-3-4b-it")
        self.ph_user_name = QLineEdit()
        self.ph_user_name.setPlaceholderText("например: Vetta")
        for edit in (self.ph_model_name, self.ph_user_name):
            edit.setMinimumHeight(34)
        defaults_layout.addWidget(_caption_field("model_name", self.ph_model_name))
        defaults_layout.addWidget(_caption_field("user_name", self.ph_user_name))
        # datetime не редактируется — подставляется автоматически
        self.ph_datetime = label("", "muted")
        defaults_layout.addWidget(self.ph_datetime)
        self.defaults_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        side_layout.addWidget(self.defaults_group)
        if not self.show_defaults:
            self.defaults_group.hide()

        # Плейсхолдеры (двойной клик копирует)
        self.placeholders_section, placeholders_layout = card()
        placeholders_layout.setSpacing(8)
        placeholders_layout.addWidget(label("Плейсхолдеры", "h2"))
        self.placeholders_hint = label("Двойной клик по элементу копирует плейсхолдер.", "muted")
        self.placeholders_hint.setWordWrap(True)
        placeholders_layout.addWidget(self.placeholders_hint)
        self.placeholders_list = QListWidget()
        self.placeholders_list.setAlternatingRowColors(True)
        self.placeholders_list.setMinimumHeight(120)
        self.placeholders_list.setToolTip(
            "Плейсхолдеры\nДвойной клик по элементу копирует плейсхолдер. Описание доступно в подсказке при наведении."
        )
        self.placeholders_list.itemDoubleClicked.connect(self.copy_placeholder_item)
        placeholders_layout.addWidget(self.placeholders_list, 1)
        side_layout.addWidget(self.placeholders_section, 1)

        # Шаблоны
        templates_group, templates_layout = card()
        templates_layout.setSpacing(8)
        templates_layout.addWidget(label("Шаблоны", "h2"))
        self.templates_list = QListWidget()
        self.templates_list.setMinimumHeight(64)
        templates_layout.addWidget(self.templates_list, 1)
        templates_buttons = QHBoxLayout()
        templates_buttons.setSpacing(6)
        self.save_template_button = FxButton("Сохранить")
        self.load_template_button = FxButton("Загрузить")
        self.delete_template_button = FxButton("Удалить")
        self.delete_template_button.setObjectName("danger")
        self.save_template_button.setToolTip("Сохранить шаблон\nСохраняет текущий текст промпта под выбранным названием.")
        self.load_template_button.setToolTip("Загрузить шаблон\nЗаменяет текст в редакторе выбранным шаблоном.")
        self.delete_template_button.setToolTip("Удалить шаблон\nУдаляет выбранный шаблон после подтверждения.")
        for button in (self.save_template_button, self.load_template_button, self.delete_template_button):
            templates_buttons.addWidget(button, 1)
        templates_layout.addLayout(templates_buttons)
        side_layout.addWidget(templates_group, 1)

        splitter.addWidget(editor_card)
        splitter.addWidget(side_panel)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 0)
        main_layout.addWidget(splitter, 1)

        actions_layout = QHBoxLayout()
        self.check_prompt_button = icon_button("Проверить промпт", "mdi6.check-decagram-outline")
        self.check_prompt_button.setToolTip("Проверить промпт\nИщет ошибки в тексте и оценивает размер в токенах.")
        self.apply_button = primary("Сохранить и применить")
        self.cancel_button = FxButton("Отмена")
        actions_layout.addWidget(self.check_prompt_button)
        actions_layout.addStretch()
        actions_layout.addWidget(self.cancel_button)
        actions_layout.addWidget(self.apply_button)
        main_layout.addLayout(actions_layout)

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
        self.ph_datetime.setText("datetime подставляется автоматически")
        self.ph_datetime.setToolTip("datetime\nТекущая дата и время: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self._refresh_placeholders()
        self._refresh_templates()

    def _refresh_placeholders(self):
        placeholders = self.placeholder_provider()
        self.placeholders_list.clear()
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(9)
        for placeholder, description in placeholders.items():
            item = QListWidgetItem(placeholder)
            item.setToolTip(description)
            item.setFont(mono)
            self.placeholders_list.addItem(item)

    def _refresh_templates(self):
        self.templates_list.clear()
        for template in self.templates:
            name = template.get("name", "Без имени")
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, template)
            item.setToolTip(template.get("text", "")[:400])
            self.templates_list.addItem(item)

    def _confirm_discard_changes(self, action_text):
        if self.prompt_editor.toPlainText().rstrip() == (self._last_applied_prompt or "").rstrip():
            return True
        return ask(
            self,
            "Подтверждение",
            f"В редакторе есть несохранённые изменения. {action_text}?",
            default="no",
        )


    def copy_placeholder_item(self, item):
        if item:
            QApplication.clipboard().setText(item.text())
            # Короткое подтверждение прямо в подсказке карточки
            self.placeholders_hint.setText(f"Скопировано: {item.text()}")
            QTimer.singleShot(2000, self._reset_placeholders_hint)

    def _reset_placeholders_hint(self):
        try:
            self.placeholders_hint.setText("Двойной клик по элементу копирует плейсхолдер.")
        except RuntimeError:
            pass  # диалог уже закрыт и удалён

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
        name, ok = prompt_text(self, "Новый шаблон", "Название шаблона:")
        if not ok:
            return
        name = name.strip()
        if not name:
            warn(self, "Шаблоны", "Название шаблона не может быть пустым.")
            return

        text = self.prompt_editor.toPlainText()
        for template in self.templates:
            if template.get("name") == name:
                if not ask(
                    self,
                    "Шаблоны",
                    "Шаблон с таким названием уже существует. Перезаписать?",
                    yes="Перезаписать",
                    danger=True,
                ):
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
            inform(self, "Шаблоны", "Выберите шаблон для загрузки.")
            return
        if not self._confirm_discard_changes("Загрузить шаблон поверх текущего текста"):
            return
        template = current_item.data(Qt.ItemDataRole.UserRole) or {}
        self.prompt_editor.setPlainText(template.get("text", ""))

    def delete_selected_template(self):
        current_item = self.templates_list.currentItem()
        if not current_item:
            inform(self, "Шаблоны", "Выберите шаблон для удаления.")
            return
        template = current_item.data(Qt.ItemDataRole.UserRole) or {}
        if not ask(
            self,
            "Шаблоны",
            f"Удалить шаблон '{template.get('name', 'Без имени')}'?",
            yes="Удалить",
            danger=True,
        ):
            return
        # Удаляем только выбранный шаблон, а не все с таким же именем
        row = self.templates_list.row(current_item)
        if 0 <= row < len(self.templates):
            del self.templates[row]
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
        self._models_snapshot = None
        self.init_ui()
        
        # Создаем таймер для автоматического обновления статистики
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(
            lambda: self.isVisible() and self.load_models_table()
        )
        self.stats_timer.start(5000)  # Обновляем каждые 5 секунд

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        self.save_button = primary('Сохранить настройки', "mdi6.content-save-outline")
        self.save_button.setToolTip("Сохранить настройки\nЗаписывает токен, промпт и параметры генерации. При смене токена бот перезапускается.")
        root.addLayout(page_header("Настройки", "Токен, системный промпт, генерация и модели", self.save_button))

        # Длинная форма: прокручиваем вертикально, горизонтальной прокрутки нет
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 10, 0)
        content_layout.setSpacing(16)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        content_layout.addWidget(self._build_basic_card())
        content_layout.addWidget(self._build_generation_card())
        content_layout.addWidget(self._build_models_card(), 1)

        # Загрузка текущих настроек
        self.load_settings()

        # Привязка событий
        self.save_button.clicked.connect(self.save_settings)
        self.add_model_button.clicked.connect(self.add_model)
        self.edit_model_button.clicked.connect(self.edit_model)
        self.delete_model_button.clicked.connect(self.delete_model)

    # ───────────────────────── карточки экрана ─────────────────────────
    def _build_basic_card(self) -> QFrame:
        frame, lay = card()
        lay.setSpacing(12)
        lay.addWidget(label("Основное", "h2"))

        # Telegram Token (умное скрытие) и администраторы — в две колонки
        self.telegram_token_input = QLineEdit()
        self.telegram_token_input.setPlaceholderText('Токен из BotFather')
        self.telegram_token_input.setToolTip("Токен Telegram\nТокен бота из BotFather. Скрыт, пока поле не в фокусе.")
        self.telegram_token_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.token_hide_timer = QTimer(self)
        self.token_hide_timer.setSingleShot(True)
        self.token_hide_timer.timeout.connect(self.hide_token)

        self.telegram_token_input.focusInEvent = self.token_focus_in
        self.telegram_token_input.focusOutEvent = self.token_focus_out
        self.telegram_token_input.textChanged.connect(self.token_text_changed)

        self.admin_telegram_ids_input = QLineEdit()
        self.admin_telegram_ids_input.setPlaceholderText("123456789, 987654321")
        self.admin_telegram_ids_input.setToolTip(
            "Администраторы Telegram\n"
            "Telegram ID администраторов через запятую. "
            "Эти ID получают админские права; priority >= 100 остаётся совместимостью."
        )

        self.token_label = label("Telegram Token", "muted")
        self.token_container = QWidget()
        token_lay = QVBoxLayout(self.token_container)
        token_lay.setContentsMargins(0, 0, 0, 0)
        token_lay.setSpacing(4)
        token_lay.addWidget(self.token_label)
        token_lay.addWidget(self.telegram_token_input)
        self.admin_telegram_ids_container = _caption_field("Администраторы Telegram", self.admin_telegram_ids_input)

        credentials = QGridLayout()
        credentials.setHorizontalSpacing(14)
        credentials.setColumnStretch(0, 1)
        credentials.setColumnStretch(1, 1)
        credentials.addWidget(self.token_container, 0, 0)
        credentials.addWidget(self.admin_telegram_ids_container, 0, 1)
        lay.addLayout(credentials)

        lay.addWidget(self._divider())

        # Системный промпт: заголовок с кнопками, предпросмотр, статус
        prompt_head = QHBoxLayout()
        prompt_head.setSpacing(8)
        prompt_head.addWidget(label("Системный промпт", "h2"))
        prompt_head.addStretch()
        self.validate_prompt_btn = icon_button("Проверить промпт", "mdi6.check-decagram-outline")
        self.validate_prompt_btn.setToolTip("Проверить промпт\nИщет ошибки в системном промпте и оценивает размер в токенах.")
        self.validate_prompt_btn.clicked.connect(self.validate_system_prompt)
        self.edit_prompt_btn = icon_button("Редактировать", "mdi6.pencil-outline")
        self.edit_prompt_btn.setToolTip("Редактировать промпт\nОткрывает отдельный редактор с плейсхолдерами и шаблонами.")
        self.edit_prompt_btn.clicked.connect(self.open_system_prompt_editor)
        prompt_head.addWidget(self.validate_prompt_btn)
        prompt_head.addWidget(self.edit_prompt_btn)
        lay.addLayout(prompt_head)

        self.system_prompt_input = QTextEdit()
        self.system_prompt_input.setReadOnly(True)
        self.system_prompt_input.setPlaceholderText('Системный промпт (пустой = без промпта). Поддерживает плейсхолдеры.')
        self.system_prompt_input.setToolTip("Текущий System Prompt\nДля редактирования откройте отдельный редактор.")
        self.system_prompt_input.setFixedHeight(96)
        lay.addWidget(self.system_prompt_input)

        self.prompt_status_label = label("", "muted")
        self.prompt_status_label.setWordWrap(True)
        lay.addWidget(self.prompt_status_label)
        self.refresh_system_prompt_status()
        return frame

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setObjectName("divider")
        line.setFrameShape(QFrame.Shape.HLine)
        return line

    def _build_generation_card(self) -> QFrame:
        frame, lay = card()
        lay.setSpacing(12)
        lay.addWidget(label("Генерация", "h2"))

        self.temperature_input = QLineEdit()
        self.temperature_input.setPlaceholderText('0.7')
        self.temperature_input.setValidator(QDoubleValidator(0.0, 2.0, 2))
        self.temperature_input.setToolTip("Temperature\nУправляет случайностью генерации.\nБолее высокие значения делают вывод более разнообразным, низкие — более детерминированным")

        self.top_p_input = QLineEdit()
        self.top_p_input.setPlaceholderText('0.95')
        self.top_p_input.setValidator(QDoubleValidator(0.0, 1.0, 2))
        self.top_p_input.setToolTip("Top P\nSampling с nucleus (top-p). Альтернатива temperature.")

        self.top_k_input = QLineEdit()
        self.top_k_input.setPlaceholderText('40')
        self.top_k_input.setValidator(QIntValidator(0, 100))
        self.top_k_input.setToolTip("Top K\nКоличество токенов с наивысшей вероятностью для выбора следующего токена.")

        self.max_tokens_input = QLineEdit()
        self.max_tokens_input.setPlaceholderText('1024')
        self.max_tokens_input.setValidator(QIntValidator(100, 10000))
        self.max_tokens_input.setToolTip("Max Tokens\nМаксимальное количество токенов в ответе.")

        self.repeat_penalty_input = QLineEdit()
        self.repeat_penalty_input.setPlaceholderText('1.1')
        self.repeat_penalty_input.setValidator(QDoubleValidator(0.0, 2.0, 2))
        self.repeat_penalty_input.setToolTip("Repeat Penalty\nШтраф за повторение слов и фраз.")

        self.presence_penalty_input = QLineEdit()
        self.presence_penalty_input.setPlaceholderText('0.0')
        self.presence_penalty_input.setValidator(QDoubleValidator(-2.0, 2.0, 2))
        self.presence_penalty_input.setToolTip("Presence Penalty\nШтраф за повторение одной и той же темы.")

        self.frequency_penalty_input = QLineEdit()
        self.frequency_penalty_input.setPlaceholderText('0.0')
        self.frequency_penalty_input.setValidator(QDoubleValidator(-2.0, 2.0, 2))
        self.frequency_penalty_input.setToolTip("Frequency Penalty\nШтраф за частое повторение одних и тех же фраз.")

        self.seed_input = QLineEdit()
        self.seed_input.setPlaceholderText('-1')
        self.seed_input.setValidator(QIntValidator(-1, 999999))
        self.seed_input.setToolTip("Seed\nФиксированный seed делает одинаковые запросы воспроизводимыми. -1 означает случайный seed.")

        self.balancing_strategy_combo = FxComboBox()
        self.balancing_strategy_combo.addItems([
            "round_robin", "random_weighted", "least_used"
        ])
        self.balancing_strategy_combo.setToolTip(
            "Стратегия балансировки\nСтратегия распределения запросов между моделями:\n"
            "round_robin — по кругу, random_weighted — случайно с учётом веса, least_used — наименее загруженная."
        )

        main_grid = QGridLayout()
        main_grid.setHorizontalSpacing(14)
        main_grid.setVerticalSpacing(10)
        for column in range(3):
            main_grid.setColumnStretch(column, 1)
        main_fields = [
            ("Temperature", self.temperature_input),
            ("Top P", self.top_p_input),
            ("Top K", self.top_k_input),
            ("Max Tokens", self.max_tokens_input),
            ("Стратегия балансировки", self.balancing_strategy_combo),
        ]
        for index, (caption, widget) in enumerate(main_fields):
            main_grid.addWidget(self.create_compact_setting(caption, widget, 0), index // 3, index % 3)
        lay.addLayout(main_grid)

        # Редко нужные параметры — под раскрывающейся секцией
        extra_box = QWidget()
        extra_grid = QGridLayout(extra_box)
        extra_grid.setContentsMargins(0, 0, 0, 0)
        extra_grid.setHorizontalSpacing(14)
        extra_grid.setVerticalSpacing(10)
        for column in range(3):
            extra_grid.setColumnStretch(column, 1)
        extra_fields = [
            ("Repeat Penalty", self.repeat_penalty_input),
            ("Presence Penalty", self.presence_penalty_input),
            ("Frequency Penalty", self.frequency_penalty_input),
            ("Seed", self.seed_input),
        ]
        for index, (caption, widget) in enumerate(extra_fields):
            extra_grid.addWidget(self.create_compact_setting(caption, widget, 0), index // 3, index % 3)
        self.extra_generation = Collapsible("Дополнительно", extra_box, expanded=False)
        lay.addWidget(self.extra_generation)
        return frame

    def _build_models_card(self) -> QFrame:
        frame, lay = card()
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("LM Модели", "h2"))
        self.models_summary_label = label("", "muted")
        self.models_summary_label.setWordWrap(True)  # длинная сводка не должна раздвигать карточку
        titles.addWidget(self.models_summary_label)
        head.addLayout(titles)
        head.addStretch()
        self.add_model_button = icon_button("Добавить", "mdi6.plus")
        self.edit_model_button = icon_button("Редактировать", "mdi6.pencil-outline")
        self.delete_model_button = icon_button("Удалить", "mdi6.delete-outline", "danger")
        self.add_model_button.setToolTip("Добавить модель\nОткрывает форму подключения новой модели.")
        self.edit_model_button.setToolTip("Редактировать модель\nИзменяет выбранную в таблице модель.")
        self.delete_model_button.setToolTip("Удалить модель\nУдаляет выбранную модель после подтверждения.")
        head.addWidget(self.add_model_button)
        head.addWidget(self.edit_model_button)
        head.addWidget(self.delete_model_button)
        lay.addLayout(head)

        # Таблица моделей
        self.models_table = ModelsTable()
        self.models_table.setColumnCount(10)
        self.models_table.setHorizontalHeaderLabels([
            "ID", "Тип", "API Key", "Base URL", "Вес", "Запросы", "Ошибки", "VLM", "Думание", "Активна"
        ])
        self.models_table.verticalHeader().setVisible(False)
        self.models_table.verticalHeader().setDefaultSectionSize(50)  # QSS даёт ячейке отступ 6px сверху/снизу
        self.models_table.setShowGrid(False)
        self.models_table.setAlternatingRowColors(True)
        self.models_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.models_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.models_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.models_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.models_table.setMinimumHeight(240)
        self.models_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.models_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.models_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Размеры столбцов: ID/ключ/URL тянутся, остальные — компактные (колонки с виджетами — фиксированной ширины)
        header = self.models_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column in (0, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        for column in (1, 4, 5, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column, width in ((7, 68), (8, 100), (9, 76)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.models_table.setColumnWidth(column, width)

        lay.addWidget(self.models_table, 1)
        return frame

    def apply_theme(self, is_oled: bool = False, accent_color: str = ""):
        """Оставлен для совместимости: внешний вид задаёт глобальный QSS дизайн-системы, ничего делать не нужно."""

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

    def create_compact_setting(self, label_text, widget, max_width=0):
        """Поле с подписью над ним. max_width оставлен для совместимости (ширину задаёт сетка)."""
        if not label_text:
            return widget
        return _caption_field(label_text, widget)

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
            warn(self, "Ошибка", "Не удалось открыть редактор System Prompt.")

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
                inform(parent_widget, "Проверка", message)
            else:
                warn(parent_widget, "Проверка", message)
        except Exception as e:
            logger.error(f"Ошибка при проверке промпта: {e}")
            warn(parent_widget, "Ошибка", "Не удалось проверить промпт")

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


    @staticmethod
    def _cell_holder(widget, align=Qt.AlignmentFlag.AlignCenter):
        """Ячейка таблицы с виджетом внутри (по центру/левому краю строки)."""
        holder = QWidget()
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(widget, 0, align | Qt.AlignmentFlag.AlignVCenter)
        return holder

    @staticmethod
    def _model_reasoning_mode(model):
        reasoning_mode = model.get('reasoning_mode')
        if not reasoning_mode:
            reasoning_mode = model.get('reasoning_effort', 'medium') if model.get('reasoning_enabled') else 'default'
            if reasoning_mode == 'none':
                reasoning_mode = 'off'
        return reasoning_mode

    def load_models_table(self):
        settings = self.settings_manager.get_settings()
        models = settings.get('models', [])
        stats = get_model_usage_stats()

        # Данные не менялись — таблицу не пересоздаём (сохраняем выделение и фокус)
        snapshot = repr((models, {m.get('id', ''): stats.get(m.get('id', ''), {}) for m in models}))
        if snapshot == self._models_snapshot:
            return
        self._models_snapshot = snapshot

        selected_row = self.models_table.currentRow()
        self.models_table.setUpdatesEnabled(False)
        try:
            self.models_table.setRowCount(0)
            self.models_table.setRowCount(len(models))
            self._fill_models_table(models, stats)
            if 0 <= selected_row < len(models):
                self.models_table.selectRow(selected_row)
        finally:
            self.models_table.setUpdatesEnabled(True)

        total_requests = sum(stats.get(m.get('id', ''), {}).get('requests', 0) for m in models)
        total_errors = sum(stats.get(m.get('id', ''), {}).get('errors', 0) for m in models)
        active = sum(1 for m in models if m.get('active', True))
        self.models_summary_label.setText(
            f"Моделей: {len(models)} · активных: {active} · запросов: {total_requests} · ошибок: {total_errors}"
        )

    def _fill_models_table(self, models, stats):
        # Короткие обозначения типов API для таблицы
        api_type_labels = {
            'openai': 'OAI',
            'anthropic': 'Claude',
        }

        def centered(text, tooltip=""):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if tooltip:
                item.setToolTip(tooltip)
            return item

        for row, model in enumerate(models):
            model_id = model.get('id', '')
            model_stats = stats.get(model_id, {"requests": 0, "errors": 0})

            # ID
            id_item = QTableWidgetItem(model_id)
            id_item.setToolTip(f"{model_id}\n{model.get('base_url', '')}".rstrip())
            self.models_table.setItem(row, 0, id_item)

            # Тип API
            api_type = model.get('api_type', 'openai')
            self.models_table.setItem(row, 1, centered(api_type_labels.get(api_type, api_type)))

            # API Key (маска: видны только последние 4 символа)
            api_key = model.get('api_key', '')
            masked_key = '*' * (len(api_key) - 4) + api_key[-4:] if len(api_key) > 4 else api_key
            self.models_table.setItem(row, 2, QTableWidgetItem(masked_key))

            # Base URL
            base_url = model.get('base_url', '')
            url_item = QTableWidgetItem(base_url)
            url_item.setToolTip(base_url)
            self.models_table.setItem(row, 3, url_item)

            # Вес, запросы, ошибки
            self.models_table.setItem(row, 4, centered(str(model.get('weight', 1))))
            self.models_table.setItem(row, 5, centered(str(model_stats["requests"])))
            self.models_table.setItem(row, 6, centered(str(model_stats["errors"])))

            # VLM: бейдж, если модель понимает изображения
            if model.get('supports_vision'):
                vlm = StatusBadge("VLM", "info", pulse=False)
                vlm.setToolTip("Поддержка изображений\nМодель получает картинки из истории и запросов.")
                self.models_table.setCellWidget(row, 7, self._cell_holder(vlm))
            else:
                self.models_table.setItem(row, 7, centered("—"))

            # Думание: бейдж с режимом, если он задан
            reasoning_mode = self._model_reasoning_mode(model)
            if reasoning_mode and reasoning_mode != 'default':
                badge = StatusBadge(reasoning_mode, "warn" if reasoning_mode != 'off' else "idle", pulse=False)
                badge.setToolTip(f"Думание модели\nРежим: {reasoning_mode}")
                self.models_table.setCellWidget(row, 8, self._cell_holder(badge))
            else:
                self.models_table.setItem(row, 8, centered("—"))

            # Активность: переключатель в ячейке (подписка после установки значения, чтобы не было ложного сигнала)
            switch = Switch(bool(model.get('active', True)))
            switch.setToolTip("Активна\nЕсли выключено, модель не используется для обработки запросов.")
            switch.toggled.connect(lambda on, r=row: self.toggle_model_active(r, on))
            self.models_table.setCellWidget(row, 9, self._cell_holder(switch))

    def toggle_model_active(self, row, active):
        """Переключить активность модели"""
        try:
            # Используем ModelService
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
        if dialog.exec() == QDialog.DialogCode.Accepted:
            model_data = dialog.get_model_data()
            
            # Используем ModelService для добавления
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
            
            # Используем ModelService для редактирования
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
        if ask(
            self,
            'Подтверждение удаления',
            f"Вы уверены, что хотите удалить модель '{model_id}'?",
            yes="Удалить",
            danger=True,
        ):
            # Используем ModelService для удаления
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
        error(self, "Ошибка", message)

    def show_message(self, message):
        """Сообщение об успехе: всплывающее уведомление окна (если оно есть), иначе обычный диалог."""
        window = self.window()
        toast = getattr(window, "toast", None)
        if toast is not None and window.isVisible():
            toast.show_message(message, hold_ms=3500)
        else:
            inform(self, "Информация", message)
