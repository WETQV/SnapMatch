# gui/admin_panel/extra_settings_tab.py

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGroupBox, QFormLayout, QCheckBox, QComboBox, QLineEdit, QMessageBox
)

from config.settings import settings_manager
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ExtraSettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()

        # Верхняя панель с кнопкой сохранения (чтобы не тянуться далеко)
        top_bar = QHBoxLayout()
        save_btn_top = QPushButton("Сохранить")
        save_btn_top.clicked.connect(self.save_settings)
        top_bar.addStretch()
        top_bar.addWidget(save_btn_top)
        layout.addLayout(top_bar)

        settings = settings_manager.get_settings()

        group = QGroupBox("Дополнительные настройки")
        form = QFormLayout()

        # Системные уведомления в чате
        self.cb_sys_notify = QCheckBox("Показывать системные уведомления в чате")
        self.cb_sys_notify.setChecked(settings.get('chat_system_notifications', True))
        self.cb_sys_notify.setToolTip(
            "Показывать пользователю служебные уведомления (например, предупреждения о переполнении контекста).\n"
            "Отключите для чистого UX."
        )
        form.addRow("Системные уведомления:", self.cb_sys_notify)

        # Форматирование текста
        self.cb_md = QCheckBox("Включить MarkdownV2")
        self.cb_md.setChecked(settings.get('format_markdown', True))
        self.cb_md.setToolTip(
            "Разрешить отправку ответов с форматированием MarkdownV2."
            "При ошибках форматирования будет выполнена авто-конвертация в HTML или обычный текст."
        )
        self.cb_html = QCheckBox("Включить HTML")
        self.cb_html.setChecked(settings.get('format_html', True))
        self.cb_html.setToolTip(
            "Разрешить HTML-форматирование ответов."
            "Если отключено, сообщения будут отправляться как обычный текст."
        )
        form.addRow("Форматирование:", self.cb_md)
        form.addRow(" ", self.cb_html)

        rich_settings = settings.get('rich_messages') or {}
        self.cb_rich_messages = QCheckBox("Включить Telegram Rich Messages")
        self.cb_rich_messages.setChecked(bool(rich_settings.get('enabled', False)))
        self.cb_rich_messages.setToolTip(
            "Отправлять финальные ответы через Bot API sendRichMessage.\n"
            "Даёт расширенное форматирование и лимит до 32768 UTF-8 символов.\n\n"
            "Если выключено, бот использует старый путь sendMessage с MarkdownV2/HTML."
        )
        form.addRow("Rich Messages:", self.cb_rich_messages)

        self.rich_format_combo = QComboBox()
        self.rich_format_combo.addItems(["markdown", "html"])
        rich_format = str(rich_settings.get('format', 'markdown') or 'markdown')
        index = self.rich_format_combo.findText(rich_format)
        self.rich_format_combo.setCurrentIndex(index if index >= 0 else 0)
        self.rich_format_combo.setToolTip(
            "Формат Rich Message.\n"
            "markdown лучше подходит для ответов LLM.\n"
            "html можно использовать, если промпты стабильно возвращают rich HTML."
        )
        form.addRow(" ", self.rich_format_combo)

        self.cb_rich_fallback = QCheckBox("При ошибке Rich Messages отправлять старым способом")
        self.cb_rich_fallback.setChecked(bool(rich_settings.get('fallback_to_legacy', True)))
        self.cb_rich_fallback.setToolTip(
            "Если Telegram отклонит sendRichMessage или ответ превысит rich-лимит,\n"
            "бот отправит сообщение через старый sendMessage с разбиением по 4096 символов."
        )
        form.addRow(" ", self.cb_rich_fallback)

        self.cb_rich_streaming = QCheckBox("Использовать Rich Draft для плавного стриминга")
        self.cb_rich_streaming.setChecked(bool(rich_settings.get('streaming_enabled', True)))
        self.cb_rich_streaming.setToolTip(
            "Когда включены Rich Messages и общий стриминг, бот использует Bot API sendRichMessageDraft:\n"
            "частичный rich-preview во время генерации + финальный sendRichMessage.\n\n"
            "Работает только в личных чатах с ботом. В группах и режиме секретаря используется fallback."
        )
        form.addRow(" ", self.cb_rich_streaming)

        # Окно контекста (токенов) по умолчанию
        self.le_ctx_len = QLineEdit()
        self.le_ctx_len.setPlaceholderText("4096")
        self.le_ctx_len.setToolTip(
            "Размер окна контекста по умолчанию (в токенах). Используется как fallback для моделей, если не указан context_window_size.\n"
            "Каждая модель может иметь свой размер контекста — смотрите настройки при добавлении модели.\n"
            "Примеры: 4096, 8192, 16384. Убедитесь, что система достаточно мощна для работы с большими значениями."
        )
        ctx = settings.get('default_context_length', 4096)
        self.le_ctx_len.setText(str(ctx))
        form.addRow("Окно контекста по умолчанию (токены):", self.le_ctx_len)

        # 🆕 Режим обработки группы
        self.cb_group_parallel = QCheckBox("Отвечать на все запросы одновременно")
        self.cb_group_parallel.setChecked(settings.get('group_parallel_mode', False))
        # 🆕 Режим обработки обращений в группах
        self.cb_mention_only = QCheckBox("Реагировать только на @упоминания")
        self.cb_mention_only.setChecked(settings.get('respond_only_on_mention', False))
        self.cb_mention_only.setToolTip(
            "Если включено, бот в группах реагирует только на сообщения с прямым упоминанием (@бот).\n"
            "Ответы на собственные сообщения бота игнорируются, чтобы не плодить случайные триггеры."
        )
        form.addRow("Фильтр обращений:", self.cb_mention_only)

        self.cb_reject_empty_mentions = QCheckBox("Требовать текст при упоминании")
        self.cb_reject_empty_mentions.setChecked(settings.get('reject_empty_mentions', True))
        self.cb_reject_empty_mentions.setToolTip(
            "Когда включено, бот просит добавить текст, если сообщение содержит лишь пустое упоминание.\n"
            "Полезно, чтобы пользователи не спамили пустыми тегами."
        )
        form.addRow(" ", self.cb_reject_empty_mentions)

        self.cb_accept_bot_messages = QCheckBox("Принимать сообщения от Telegram-ботов")
        self.cb_accept_bot_messages.setChecked(settings.get('accept_bot_messages', True))
        self.cb_accept_bot_messages.setToolTip(
            "Если включено, сообщения от других Telegram-ботов обрабатываются как сообщения обычных пользователей:\n"
            "сохраняются в историю и могут получить ответ, если проходят текущие правила чата.\n"
            "Если выключено, такие сообщения полностью игнорируются."
        )
        form.addRow("Сообщения от ботов:", self.cb_accept_bot_messages)

        bot_policy = settings.get('bot_access_policy') or {}
        self.combo_bot_policy_mode = QComboBox()
        self.combo_bot_policy_mode.addItems(["all", "off", "allowlist", "denylist"])
        current_mode = str(bot_policy.get('mode', 'all')).strip().lower()
        self.combo_bot_policy_mode.setCurrentText(current_mode if current_mode in {"all", "off", "allowlist", "denylist"} else "all")
        self.combo_bot_policy_mode.setToolTip(
            "Дополнительная политика для сообщений от Telegram-ботов:\n"
            "all - принимать всех, если общий переключатель включен;\n"
            "off - не принимать ботов;\n"
            "allowlist - принимать только ID из списка;\n"
            "denylist - принимать всех, кроме ID из списка."
        )
        form.addRow("Bot policy:", self.combo_bot_policy_mode)

        self.le_bot_allow_ids = QLineEdit()
        self.le_bot_allow_ids.setPlaceholderText("12345, 67890")
        self.le_bot_allow_ids.setText(", ".join(str(item) for item in bot_policy.get('allow_bot_ids', []) or []))
        self.le_bot_allow_ids.setToolTip("Telegram ID ботов для режима allowlist. Разделители: запятая, точка с запятой или новая строка.")
        form.addRow("Разрешенные bot ID:", self.le_bot_allow_ids)

        self.le_bot_deny_ids = QLineEdit()
        self.le_bot_deny_ids.setPlaceholderText("12345, 67890")
        self.le_bot_deny_ids.setText(", ".join(str(item) for item in bot_policy.get('deny_bot_ids', []) or []))
        self.le_bot_deny_ids.setToolTip("Telegram ID ботов для режима denylist. Разделители: запятая, точка с запятой или новая строка.")
        form.addRow("Запрещенные bot ID:", self.le_bot_deny_ids)

        self.cb_bot_policy_private = QCheckBox("Применять в личных чатах")
        self.cb_bot_policy_private.setChecked(bool(bot_policy.get('apply_in_private', True)))
        self.cb_bot_policy_private.setToolTip(
            "Применять Bot policy к личным чатам с обычными пользователями."
        )
        self.cb_bot_policy_groups = QCheckBox("Применять в группах")
        self.cb_bot_policy_groups.setChecked(bool(bot_policy.get('apply_in_groups', True)))
        self.cb_bot_policy_groups.setToolTip(
            "Применять Bot policy к группам и супергруппам."
        )
        self.cb_bot_policy_secretary = QCheckBox("Применять в режиме Личный секретарь")
        self.cb_bot_policy_secretary.setChecked(bool(bot_policy.get('apply_in_secretary', False)))
        self.cb_bot_policy_secretary.setToolTip(
            "Применять Bot policy к входящим сообщениям Telegram-ботов в режиме личного секретаря.\n"
            "Обычно выключено, чтобы не ломать business-чаты без явной необходимости."
        )
        form.addRow("Bot policy scope:", self.cb_bot_policy_private)
        form.addRow(" ", self.cb_bot_policy_groups)
        form.addRow(" ", self.cb_bot_policy_secretary)

        self.cb_group_parallel.setToolTip(
            "Поведение бота в групповых чатах:\n\n"
            "✅ ВКЛЮЧЕНО (параллельно):\n"
            "Бот отвечает на несколько запросов из одной группы одновременно (если модель это поддерживает по max_concurrent_requests).\n"
            "Быстро, но может быть беспорядочно.\n\n"
            "❌ ВЫКЛЮЧЕНО (последовательно):\n"
            "Бот отвечает на запросы из одной группы по одному — ждёт полного ответа перед обработкой следующего.\n"
            "Медленнее, но более упорядочено и предсказуемо."
        )
        form.addRow("Режим обработки в группах:", self.cb_group_parallel)

        # 🆕 OLED режим (перенесён в самый низ)
        self.cb_oled = QCheckBox("OLED режим (True Black)")
        self.cb_oled.setChecked(settings.get('oled_mode', False))
        self.cb_oled.setToolTip(
            "Заменяет тёмно-серый фон на абсолютно чёрный (#000000).\n"
            "Помогает экономить заряд на OLED-дисплеях и уменьшает нагрузку на глаза ночью."
        )
        form.addRow("Внешний вид:", self.cb_oled)

        # 🆕 Пометка голосовых сообщений
        self.cb_stt_annotate = QCheckBox("Акцентировать внимание на голосовых и кружочках")
        self.cb_stt_annotate.setChecked(settings.get('stt_annotate', False))
        self.cb_stt_annotate.setToolTip(
            "Добавлять метки '[Голосовое]' и '[Кружочек]' перед распознанным текстом в истории.\n"
            "Помогает понять, что сообщение пришло из аудио, а не было набрано текстом."
        )
        form.addRow("Аудио:", self.cb_stt_annotate)

        # Анимация генерации ответа
        self.cb_stream_draft = QCheckBox("Плавная генерация текста (стриминг)")
        self.cb_stream_draft.setChecked(settings.get('stream_mode', False))
        self.cb_stream_draft.setToolTip(
            "Показывать ответ ИИ по мере генерации.\n"
            "Если Rich Messages включены, используется sendRichMessageDraft + финальный sendRichMessage.\n"
            "Если Rich Messages выключены, используется старый режим edit_text.\n\n"
            "⚠ Работает ТОЛЬКО в личных сообщениях с ботом.\n"
            "В группах и режиме секретаря бот автоматически переключается на обычный режим/fallback."
        )
        form.addRow("Стриминг:", self.cb_stream_draft)

        group.setLayout(form)
        layout.addWidget(group)
        layout.addStretch()

        self.setLayout(layout)

    def save_settings(self):
        settings = settings_manager.get_settings()
        settings['chat_system_notifications'] = self.cb_sys_notify.isChecked()
        settings['format_markdown'] = self.cb_md.isChecked()
        settings['format_html'] = self.cb_html.isChecked()
        settings['rich_messages'] = {
            **(settings.get('rich_messages') or {}),
            'enabled': self.cb_rich_messages.isChecked(),
            'format': self.rich_format_combo.currentText(),
            'fallback_to_legacy': self.cb_rich_fallback.isChecked(),
            'streaming_enabled': self.cb_rich_streaming.isChecked(),
        }

        ctx_txt = self.le_ctx_len.text().strip()
        try:
            settings['default_context_length'] = max(1024, int(ctx_txt)) if ctx_txt else 4096
        except ValueError:
            settings['default_context_length'] = 4096

        settings['group_parallel_mode'] = self.cb_group_parallel.isChecked()
        settings['respond_only_on_mention'] = self.cb_mention_only.isChecked()
        settings['reject_empty_mentions'] = self.cb_reject_empty_mentions.isChecked()
        settings['accept_bot_messages'] = self.cb_accept_bot_messages.isChecked()
        settings['bot_access_policy'] = {
            "mode": self.combo_bot_policy_mode.currentText(),
            "allow_bot_ids": self.le_bot_allow_ids.text(),
            "deny_bot_ids": self.le_bot_deny_ids.text(),
            "apply_in_private": self.cb_bot_policy_private.isChecked(),
            "apply_in_groups": self.cb_bot_policy_groups.isChecked(),
            "apply_in_secretary": self.cb_bot_policy_secretary.isChecked(),
        }
        settings['oled_mode'] = self.cb_oled.isChecked()
        settings['stt_annotate'] = self.cb_stt_annotate.isChecked()
        settings['stream_mode'] = self.cb_stream_draft.isChecked()

        settings_manager.update_settings(**settings)
        logger.info("Дополнительные настройки сохранены")

        # Применяем тему OLED если нужно
        parent_window = self.window()
        if hasattr(parent_window, 'apply_theme'):
            parent_window.apply_theme()

        QMessageBox.information(self, "Сохранено", "Настройки сохранены и применены. Текущие процессы не прерваны.")
