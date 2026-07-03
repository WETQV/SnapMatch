from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from utils.database.database_manager import DatabaseManager


class MessageHistory(QWidget):
    def __init__(self):
        super().__init__()
        self.current_messages = []
        self.current_chat_id = None
        self.empty_history_message = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите Telegram ID пользователя")
        self.search_button = QPushButton("Просмотреть историю")
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_button)

        filter_layout = QHBoxLayout()
        filter_label = QLabel("Фильтр:")
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["Обычные", "Секретарь", "Сводки", "Контекст", "Всё"])
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.filter_combo)
        filter_layout.addStretch()

        self.history_text = QTextEdit()
        self.history_text.setReadOnly(True)

        layout.addLayout(search_layout)
        layout.addLayout(filter_layout)
        layout.addWidget(self.history_text)
        self.setLayout(layout)

        self.search_button.clicked.connect(self.load_history)
        self.filter_combo.currentIndexChanged.connect(self.render_history)

    def _load_user_history(self, telegram_id: int):
        db = DatabaseManager()
        try:
            user = db.users.get_user_by_telegram_id(telegram_id)
            if not user:
                return None, [], None, False

            messages = db.messages.get_user_messages_active(
                user["id"],
                limit=500,
                chat_type="private",
                chat_id=telegram_id,
            )
            secretary_messages = db.messages.get_secretary_owner_messages_active(
                telegram_id,
                limit=500,
            )
            messages = sorted(
                [*messages, *secretary_messages],
                key=lambda msg: msg.get("timestamp") or "",
            )
            has_group_history = False
            if not messages:
                has_group_history = bool(db.messages.get_user_messages_active(user["id"], limit=1))

            current_chat_id = messages[-1].get("chat_id") if messages else None
            return user, messages, current_chat_id, has_group_history
        finally:
            db.close()

    def _get_archived_messages_summary(self, chat_id: int) -> int:
        db = DatabaseManager()
        try:
            return db.messages.get_archived_messages_summary(chat_id)
        finally:
            db.close()

    def load_history(self):
        telegram_id_text = self.search_input.text().strip()
        if not telegram_id_text.isdigit():
            self.history_text.setText("Ошибка: введите корректный Telegram ID.")
            self.current_messages = []
            self.current_chat_id = None
            self.empty_history_message = None
            return

        telegram_id = int(telegram_id_text)
        user, messages, current_chat_id, has_group_history = self._load_user_history(telegram_id)
        if not user:
            self.history_text.setText("Пользователь не найден.")
            self.current_messages = []
            self.current_chat_id = None
            self.empty_history_message = None
            return

        self.current_messages = messages
        self.current_chat_id = current_chat_id

        if not messages:
            if has_group_history:
                self.empty_history_message = "В личных сообщениях с ботом истории нет. Для этого пользователя есть только сообщения из групп."
            else:
                self.empty_history_message = "История пуста. Сообщения появятся после новых реплик."
            self.history_text.setText(self.empty_history_message)
            return

        self.empty_history_message = None
        self.filter_combo.blockSignals(True)
        self.filter_combo.setCurrentIndex(0)
        self.filter_combo.blockSignals(False)
        self.render_history()

    def render_history(self, *_):
        if not self.current_messages:
            if self.empty_history_message is not None:
                self.history_text.setText(self.empty_history_message)
            return

        selected_filter = self.filter_combo.currentText()
        filtered_messages = self._apply_filter(self.current_messages, selected_filter)

        if not filtered_messages:
            self.history_text.setText("Сообщений для выбранного фильтра нет.")
            return

        history_lines = []
        for msg in filtered_messages:
            role = (msg.get("role") or "").upper()
            content = msg.get("content", "") or ""
            content_type = msg.get("content_type") or "text"

            if msg.get("source_mode") == "secretary":
                prefix = "[Секретарь] "
            elif msg.get("is_summary"):
                prefix = "[Сводка] "
            elif role == "SYSTEM":
                prefix = "[Контекст] "
            else:
                prefix = ""

            if content_type == "image":
                display_content = f"[Фото] {content}".strip()
            elif content_type == "image_ref":
                display_content = f"[Фото*] {content}".strip()
            elif content_type == "voice":
                display_content = f"[Голосовое] {content}".strip()
            elif content_type == "video_note":
                display_content = f"[Кружочек] {content}".strip()
            else:
                display_content = content

            history_lines.append(f"{prefix}{role}: {display_content}")

        if self.current_chat_id is not None:
            archived_count = self._get_archived_messages_summary(self.current_chat_id)
            if archived_count > 0:
                history_lines.insert(0, f"[Архивировано {archived_count} старых сообщений]\n")

        self.history_text.setText("\n".join(history_lines))

    def _apply_filter(self, messages, selected_filter):
        if selected_filter == "Всё":
            return list(messages)

        filtered = []
        for msg in messages:
            role = (msg.get("role") or "").lower()
            is_summary = bool(msg.get("is_summary"))
            is_secretary = (msg.get("source_mode") or "normal") == "secretary"

            if selected_filter == "Обычные":
                if not is_secretary and not is_summary and role in {"user", "assistant"}:
                    filtered.append(msg)
            elif selected_filter == "Секретарь":
                if is_secretary:
                    filtered.append(msg)
            elif selected_filter == "Сводки":
                if is_summary:
                    filtered.append(msg)
            elif selected_filter == "Контекст":
                if not is_summary and role not in {"user", "assistant"}:
                    filtered.append(msg)

        return filtered
