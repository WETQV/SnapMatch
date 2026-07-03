# gui/admin_panel/user_management.py

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QPushButton,
    QGroupBox, QDialog, QFrame, QTableWidget, QTableWidgetItem, QTextEdit,
    QHeaderView, QAbstractItemView, QMessageBox,
    QScrollBar, QScrollArea, QCheckBox, QComboBox, QTabWidget, QApplication
)
from gui.widgets import UnicodeSpinBox
from PyQt6.QtCore import QTimer, pyqtSignal, Qt, QRegularExpression
from PyQt6.QtGui import QPixmap, QCursor, QFont, QTextCharFormat, QColor, QTextCursor, QTextOption, QPalette
from functools import partial
from utils.database.database_manager import DatabaseManager
from utils import server_state
from utils.logger import setup_logger
from config.settings import settings_manager
from utils import stats  # Импортируем модуль статистики
import datetime
import logging
import queue
from PyQt6.QtGui import QFontInfo

# Убран статический импорт для избежания циклического импорта
# Импорт делается внутри функции update_message_history()

# 🆕 Импорты из новых сервисов
from .handlers.log_handler import LogHandler  # Переиспользуемый обработчик логов
from .services.user_service import UserService  # Работа с пользователями и чатами
from .services.stats_service import StatsService  # Работа со статистикой

logger = setup_logger(__name__)

class ClickableWidget(QWidget):
    clicked = pyqtSignal()

    def __init__(self, text='', parent=None):
        super().__init__(parent)

        # Устанавливаем курсор по умолчанию для всего виджета
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        layout = QHBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)  # Добавляем отступы для рамки

        # Иконка-символ (заменяем картинку на Unicode символ)
        self.icon_label = QLabel()
        self.icon_label.setText("📊")  # Символ статистики
        self.icon_label.setFont(QFont("Segoe UI Emoji", 16))
        self.icon_label.setFixedSize(20, 20)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)

        # Устанавливаем tooltip на иконку
        self.icon_label.setToolTip("Наведитесь и нажмите на статистику, чтобы увидеть подробную информацию")

        # Текст
        self.label = QLabel(text)
        layout.addWidget(self.label)

        # Устанавливаем курсор указателя только на текст
        self.label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # Расширение, чтобы сжать элементы влево
        layout.addStretch()

        self.setLayout(layout)

        # Устанавливаем стиль для изменения фона и рамки только при наведении на текст
        self.label.setStyleSheet("""
            QLabel {
                background-color: transparent;
                color: white;
                border: 1px solid transparent;
                border-radius: 5px;
            }
            QLabel:hover {
                background-color: #808080;
                border: 1px solid #556977;
                color: white;
            }
        """)

        # Не устанавливаем tooltip на текст
        # self.label.setToolTip("")

    def mouseReleaseEvent(self, event):
        # Проверяем, было ли нажатие на метку (текст)
        if event.button() == Qt.MouseButton.LeftButton and self.label.underMouse():
            self.clicked.emit()
        super().mouseReleaseEvent(event)

# 🆕 LogHandler теперь импортируется из handlers.log_handler
# (оригинальное определение перенесено в gui/admin_panel/handlers/log_handler.py)

class UserManagement(QWidget):
    def __init__(self, bot_thread):
        super().__init__()
        self.bot_thread = bot_thread
        # 🆕 Используем сервисы вместо прямого DatabaseManager
        self.user_service = UserService()
        self.stats_service = StatsService()
        self.db = self.user_service.db  # Для совместимости, если что-то ещё нужно напрямую
        self.current_user_id = None  # Хранит Telegram ID выбранного пользователя
        self.current_chat_id = None  # Хранит ID выбранного чата (для групп)
        self.current_chat_title = None  # Заголовок выбранного чата
        self.current_chat_type = None  # Тип выбранного чата
        self.session_start_time = None  # Время начала сеанса
        self.auto_scroll_enabled = True  # Флаг для автоматической прокрутки чата
        self.message_formats = {
            "user": QTextCharFormat(),
            "assistant": QTextCharFormat(),
            "system": QTextCharFormat(),
            "error": QTextCharFormat(),
            "header": QTextCharFormat(),
            "snapshot": QTextCharFormat(),
            "snapshot_header": QTextCharFormat(),
            "separator": QTextCharFormat(),
            "image_indicator": QTextCharFormat(),
            "user_content": QTextCharFormat(),
            "assistant_content": QTextCharFormat(),
        }
        self.init_message_formats()
        
        # Настройка логгера для отображения в GUI
        self.log_handler = LogHandler()
        root_logger = logging.getLogger()
        root_logger.addHandler(self.log_handler)
        
        self.init_ui()

        # Кэш состояния истории: используем подпись, чтобы отслеживать изменения
        self._last_message_count = -1
        self._last_filter_index = -1
        self._last_history_signature = None

        self.setup_timers()
        self.initialize_server_state()

    def initialize_server_state(self):
        if server_state.server_active:
            if self.session_start_time is None:
                self.session_start_time = datetime.datetime.now()
                logger.info(f"Сеанс начат в {self.session_start_time}")
        else:
            self.session_start_time = None

    def init_message_formats(self):
        # Формат для заголовков чата (например, "Пользователь: WETQV") — светло-серый, чуть крупнее
        self.message_formats["header"].setForeground(QColor("#CFD8DC"))
        self.message_formats["header"].setFontWeight(QFont.Weight.Bold)
        self.message_formats["header"].setFontPointSize(10)

        # Формат для заголовка "Краткий контекст последних сообщений:" — голубоватый, жирный
        self.message_formats["snapshot_header"].setForeground(QColor("#90CAF9"))
        
        # Формат для краткого контекста — приглушённый серый, курсив
        self.message_formats["snapshot"].setForeground(QColor("#90A4AE"))
        self.message_formats["snapshot"].setFontItalic(True)
        
        # Формат для меток пользователя "USER:" — голубой, жирный
        self.message_formats["user"].setForeground(QColor("#64B5F6"))
        self.message_formats["user"].setFontWeight(QFont.Weight.Bold)
        
        # Формат для меток ассистента "ASSISTANT:" — мягкий зелёный, жирный
        self.message_formats["assistant"].setForeground(QColor("#81C784"))
        self.message_formats["assistant"].setFontWeight(QFont.Weight.Bold)
        
        # Формат для контента пользователя — светло-голубоватый
        self.message_formats["user_content"].setForeground(QColor("#B3E5FC"))
        
        # Формат для контента ассистента — светло-зелёный
        self.message_formats["assistant_content"].setForeground(QColor("#C8E6C9"))
        
        # Формат для системных сообщений — нейтральный серый
        self.message_formats["system"].setForeground(QColor("#78909C"))
        self.message_formats["system"].setFontItalic(True)
        
        # Формат для ошибок — приглушённый красный
        self.message_formats["error"].setForeground(QColor("#E57373"))
        self.message_formats["error"].setFontWeight(QFont.Weight.Bold)
        
        # Формат для индикаторов изображений — жёлтый
        self.message_formats["image_indicator"].setForeground(QColor("#FFD54F"))
        self.message_formats["image_indicator"].setFontWeight(QFont.Weight.Bold)

    def init_ui(self):
        main_layout = QVBoxLayout()

        # Верхняя панель с кнопкой управления сервером
        top_layout = QHBoxLayout()
        
        # Кнопка управления (теперь первая слева)
        self.toggle_server_button = QPushButton('Запустить сервер')
        
        # 🆕 Метка для отображения прогресса наверстывания сообщений
        self.backlog_label = QLabel('⏳')
        self.backlog_label.setStyleSheet("""
            QLabel {
                color: #FFB300; 
                font-weight: bold; 
                margin-left: 10px;
                padding: 2px 5px;
                border: 1px solid #FFB300;
                border-radius: 4px;
            }
        """)
        self.backlog_label.setVisible(False)
        
        # Статус-сообщение (теперь справа от кнопки, скрыто по умолчанию)
        self.status_label = QLabel('')
        self.status_label.setStyleSheet("color: #90A4AE; font-style: italic; margin-left: 10px;")
        self.status_label.setVisible(False)
        
        # Инициализация таймера для скрытия статуса
        self.status_timer = QTimer()
        self.status_timer.setSingleShot(True)
        self.status_timer.timeout.connect(lambda: self.status_label.setVisible(False))

        top_layout.addWidget(self.toggle_server_button)
        top_layout.addWidget(self.backlog_label)
        top_layout.addWidget(self.status_label)
        top_layout.addStretch()

        # Основной макет с таблицей пользователей и правой частью
        content_layout = QHBoxLayout()

        # Левая часть: Таблица пользователей
        self.users_table = QTableWidget()
        self.users_table.setColumnCount(5)
        self.users_table.setHorizontalHeaderLabels(['Имя пользователя', 'Telegram ID', 'Приоритет', 'Забанен', 'Действия'])
        self.users_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.users_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.users_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.users_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Добавление горизонтальной прокрутки, если необходимо
        self.users_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Таблица групповых чатов
        self.groups_table = QTableWidget()
        self.groups_table.setColumnCount(5)
        self.groups_table.setHorizontalHeaderLabels(['Название чата', 'Chat ID', 'Сообщений', 'Забанен', 'Действия'])
        self.groups_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.groups_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.groups_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.groups_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.groups_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.entities_tab = QTabWidget()
        self.entities_tab.addTab(self.users_table, "Пользователи")
        self.entities_tab.addTab(self.groups_table, "Группы")
        self.entities_tab.currentChanged.connect(self._refresh_visible_entity_list)

        # Правая часть: Статистика и история сообщений
        right_layout = QVBoxLayout()
        
        # Компактная статистика
        self.stats_widget = ClickableWidget()
        self.stats_widget.clicked.connect(self.show_full_stats)
        right_layout.addWidget(self.stats_widget)

        # Создаем вкладки для чата и логов
        self.tab_widget = QTabWidget()
        
        # Вкладка истории чата
        chat_tab = QWidget()
        chat_layout = QVBoxLayout(chat_tab)
        
        # Панель управления чатом
        chat_control_layout = QHBoxLayout()
        
        # Переключатель автопрокрутки
        self.auto_scroll_checkbox = QCheckBox("Автопрокрутка")
        self.auto_scroll_checkbox.setChecked(True)
        self.auto_scroll_checkbox.stateChanged.connect(self.toggle_auto_scroll)
        chat_control_layout.addWidget(self.auto_scroll_checkbox)

        self.group_addressed_only_checkbox = QCheckBox("Только обращения")
        self.group_addressed_only_checkbox.setChecked(True)
        self.group_addressed_only_checkbox.setToolTip(
            "Показывать только обращения к боту, его ответы и сводки. "
            "Снимите галочку, чтобы увидеть все сохранённые сообщения группы."
        )
        self.group_addressed_only_checkbox.setVisible(False)
        self.group_addressed_only_checkbox.stateChanged.connect(self.update_message_history)
        chat_control_layout.addWidget(self.group_addressed_only_checkbox)
        
        # Добавляем распорку, чтобы отделить автопрокрутку от фильтра
        chat_control_layout.addStretch(1)
        
        # Создаем отдельный контейнер для фильтра, чтобы метка и комбобокс были всегда рядом
        filter_container = QWidget()
        filter_layout = QHBoxLayout(filter_container)
        filter_layout.setContentsMargins(0, 0, 0, 0)  # Убираем отступы
        
        # Фильтр типов сообщений
        filter_label = QLabel("Фильтр:")
        self.message_filter_combo = QComboBox()
        self.message_filter_combo.addItems(["Обычные", "Секретарь", "Сводки", "Контекст", "Всё"])
        self.message_filter_combo.currentIndexChanged.connect(self.filter_messages)
        
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.message_filter_combo)
        
        chat_control_layout.addWidget(filter_container)

        chat_layout.addLayout(chat_control_layout)
        
        # Текстовое поле для истории
        self.history_text = QTextEdit()
        self.history_text.setReadOnly(True)
        chat_layout.addWidget(self.history_text)
        
        # Вкладка системных логов
        logs_tab = QWidget()
        logs_layout = QVBoxLayout(logs_tab)
        
        # Панель управления логами
        logs_control_layout = QHBoxLayout()
        
        # Переключатель автопрокрутки для логов
        self.logs_auto_scroll = QCheckBox("Автопрокрутка")
        self.logs_auto_scroll.setChecked(True)
        logs_control_layout.addWidget(self.logs_auto_scroll)
        
        logs_layout.addLayout(logs_control_layout)
        
        # Текстовое поле для логов
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        # Отключаем горизонтальный скролл и включаем перенос по ширине
        self.logs_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.logs_text.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.logs_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Моноширинный шрифт для ровного выравнивания
        mono_font = QFont("Consolas")
        mono_font.setStyleHint(QFont.StyleHint.Monospace)
        # Если Consolas недоступен, используем fallback
        if not QFontInfo(mono_font).exactMatch():
            mono_font = QFont()
            mono_font.setStyleHint(QFont.StyleHint.Monospace)
            mono_font.setFamily("Courier New")
        self.logs_text.setFont(mono_font)
        logs_layout.addWidget(self.logs_text)
        
        # Добавляем вкладки
        self.tab_widget.addTab(chat_tab, "История чата")
        self.tab_widget.addTab(logs_tab, "Системные логи")
        self.tab_widget.currentChanged.connect(self._handle_right_tab_changed)
        
        right_layout.addWidget(self.tab_widget)

        # Добавляем таблицу и правую часть в основной контентный макет
        content_layout.addWidget(self.entities_tab, 8)  # Таблица/вкладки занимают большую часть
        content_layout.addLayout(right_layout, 4)       # Правая панель компактнее

        # Собираем весь макет
        main_layout.addLayout(top_layout)
        main_layout.addLayout(content_layout)
        self.setLayout(main_layout)

        # Привязка событий
        self.groups_table.cellClicked.connect(self.display_group_history)
        self.users_table.cellClicked.connect(self.display_user_history)
        self.toggle_server_button.clicked.connect(self.toggle_server)

        # Загрузка пользователей и обновление статистики при инициализации
        self.load_users()
        self.load_group_chats()
        self.update_stats()

    def setup_timers(self):
        # Таймер для обновления пользователей и статистики каждые 5 секунд
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._refresh_visible_entity_list)
        self.update_timer.timeout.connect(self.update_stats)
        self.update_timer.start(5000)  # 5000 мс = 5 секунд

        # Таймер для обновления истории сообщений каждые 5 секунд
        self.history_timer = QTimer()
        self.history_timer.timeout.connect(self.update_message_history)
        self.history_timer.start(5000)
        
        # Таймер для обновления логов каждую секунду
        self.logs_timer = QTimer()
        self.logs_timer.timeout.connect(self.update_logs)
        self.logs_timer.start(1000)  # 1000 мс = 1 секунд

        # Останавливаем таймеры при закрытии приложения
        app = QApplication.instance()
        if app is not None:
            try:
                app.aboutToQuit.connect(self.stop_timers)
            except Exception:
                pass

        self._sync_refresh_intervals()

    def stop_timers(self):
        try:
            if hasattr(self, 'update_timer') and self.update_timer.isActive():
                self.update_timer.stop()
            if hasattr(self, 'history_timer') and self.history_timer.isActive():
                self.history_timer.stop()
            if hasattr(self, 'logs_timer') and self.logs_timer.isActive():
                self.logs_timer.stop()
        except Exception:
            pass

    def _sync_refresh_intervals(self):
        backlog_mode = server_state.is_catching_up
        update_interval = 15000 if backlog_mode else 5000
        history_interval = 15000 if backlog_mode else 5000

        if hasattr(self, 'update_timer') and self.update_timer.interval() != update_interval:
            self.update_timer.setInterval(update_interval)

        if hasattr(self, 'history_timer') and self.history_timer.interval() != history_interval:
            self.history_timer.setInterval(history_interval)

    def _refresh_visible_entity_list(self):
        if self.entities_tab.currentIndex() == 0:
            self.load_users()
        else:
            self.load_group_chats()

    def _handle_right_tab_changed(self, index):
        if index == 0 and (self.current_user_id is not None or self.current_chat_id is not None):
            self.update_message_history()

    def load_users(self):
        try:
            # 🆕 Используем UserService
            users = self.user_service.get_all_users()
            self.users_table.setRowCount(0)
            for row_number, user in enumerate(users):
                self.users_table.insertRow(row_number)
                username = user.get('username') or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                self.users_table.setItem(row_number, 0, QTableWidgetItem(username))
                self.users_table.setItem(row_number, 1, QTableWidgetItem(str(user['telegram_id'])))

                # SpinBox для приоритета (кастомный с Unicode-стрелочками)
                priority_spinbox = UnicodeSpinBox(min=0, max=10, value=user['priority'])
                priority_spinbox.valueChanged.connect(partial(self.change_user_priority, user['id']))
                self.users_table.setCellWidget(row_number, 2, priority_spinbox)

                # Статус бана
                ban_status = 'Да' if user['is_banned'] else 'Нет'
                ban_item = QTableWidgetItem(ban_status)
                ban_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.users_table.setItem(row_number, 3, ban_item)

                # Кнопки действий (Бан/Разбан)
                action_button_text = 'Бан' if not user['is_banned'] else 'Разбан'
                action_button = QPushButton(action_button_text)
                # Используем partial для корректной передачи объекта user
                action_button.clicked.connect(partial(self.toggle_ban_user, user))
                self.users_table.setCellWidget(row_number, 4, action_button)

            if self.current_user_id is not None:
                target = str(self.current_user_id)
                for row in range(self.users_table.rowCount()):
                    if self.users_table.item(row, 1) and self.users_table.item(row, 1).text() == target:
                        self.users_table.selectRow(row)
                        break
        except Exception as e:
            logger.error(f"Ошибка загрузки пользователей: {e}")

    def load_group_chats(self):
        try:
            # 🆕 Используем UserService
            chats = self.user_service.get_group_chats()
            self.groups_table.setRowCount(0)
            for row_number, chat in enumerate(chats):
                self.groups_table.insertRow(row_number)
                chat_id = chat.get('chat_id')
                chat_title = chat.get('chat_title') or f"Чат {chat_id}"
                messages_count = chat.get('messages_count', 0)
                chat_type = chat.get('chat_type', 'group')

                title_item = QTableWidgetItem(chat_title)
                chat_id_item = QTableWidgetItem(str(chat_id))
                chat_id_item.setData(Qt.ItemDataRole.UserRole, chat_type)
                messages_item = QTableWidgetItem(str(messages_count))

                self.groups_table.setItem(row_number, 0, title_item)
                self.groups_table.setItem(row_number, 1, chat_id_item)
                self.groups_table.setItem(row_number, 2, messages_item)

                # Статус бана
                ban_status = 'Да' if chat['is_banned'] else 'Нет'
                ban_item = QTableWidgetItem(ban_status)
                ban_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.groups_table.setItem(row_number, 3, ban_item)

                # Кнопка действий (Бан/Разбан)
                action_button_text = 'Бан' if not chat['is_banned'] else 'Разбан'
                action_button = QPushButton(action_button_text)
                # Используем partial для корректной передачи объекта chat
                action_button.clicked.connect(partial(self.toggle_ban_group, chat))
                self.groups_table.setCellWidget(row_number, 4, action_button)

            if self.current_chat_id is not None:
                target = str(self.current_chat_id)
                for row in range(self.groups_table.rowCount()):
                    if self.groups_table.item(row, 1) and self.groups_table.item(row, 1).text() == target:
                        self.groups_table.selectRow(row)
                        break

        except Exception as e:
            logger.error(f"Ошибка загрузки групповых чатов: {e}")

    def display_user_history(self, row, column):
        user_id_item = self.users_table.item(row, 1)  # Используем Telegram ID
        if user_id_item:
            telegram_id = int(user_id_item.text())
            self.current_user_id = telegram_id
            self.current_chat_id = None
            self.current_chat_title = None
            self.current_chat_type = 'private'
            # 🔧 ИСПРАВЛЕНО: Сбрасываем счётчики при выборе нового пользователя
            self._last_message_count = -1
            self._last_filter_index = -1
            self._last_history_signature = None
            self.groups_table.clearSelection()
            self.users_table.selectRow(row)
            self.group_addressed_only_checkbox.setVisible(False)
            self.update_message_history()

    def display_group_history(self, row, column):
        chat_id_item = self.groups_table.item(row, 1)
        if chat_id_item:
            chat_id_text = chat_id_item.text()
            try:
                chat_id = int(chat_id_text)
            except ValueError:
                chat_id = chat_id_text
            chat_type = chat_id_item.data(Qt.ItemDataRole.UserRole) or 'group'
            chat_title_item = self.groups_table.item(row, 0)
            chat_title = chat_title_item.text() if chat_title_item else str(chat_id)

            self.current_user_id = None
            self.current_chat_id = chat_id
            self.current_chat_title = chat_title
            self.current_chat_type = chat_type
            # 🔧 ИСПРАВЛЕНО: Сбрасываем счётчики при выборе нового чата
            self._last_message_count = -1
            self._last_filter_index = -1
            self._last_history_signature = None

            self.users_table.clearSelection()
            self.groups_table.selectRow(row)
            self.group_addressed_only_checkbox.setVisible(True)
            self.update_message_history()

    def toggle_server(self):
        # 🔧 ИСПРАВЛЕНО: Проверяем по тексту кнопки или состоянию, а не по лейблу, который теперь скрывается
        if self.toggle_server_button.text() == 'Остановить сервер':
            # Начало процесса остановки
            logger.info("Инициирована остановка сервера через GUI...")
            server_state.server_active = False
            
            # Меняем состояние кнопки на переходное
            self.show_status_message('Останавливается...')
            self.toggle_server_button.setText('Останавливается...')
            self.toggle_server_button.setEnabled(False)
            
            # Сохранение статистики сеанса
            self.save_session_statistics()
            
            # Останавливаем bot_thread если он запущен
            if self.bot_thread and self.bot_thread.isRunning():
                self.bot_thread.stop_bot()
            else:
                # Если поток не запущен, сразу переключаем UI
                self.show_status_message('Сервер остановлен')
                self.toggle_server_button.setText('Запустить сервер')
                self.toggle_server_button.setEnabled(True)
                
        else:
            # УМНЫЙ ЗАПУСК СЕРВЕРА
            logger.info("Попытка запуска сервера...")
            
            # 🆕 МГНОВЕННЫЙ ФИДБЕК: Меняем состояние кнопки сразу
            self.show_status_message('Запуск сервера...')
            self.toggle_server_button.setText('Запуск...')
            self.toggle_server_button.setEnabled(False)
            
            # Принудительно обновляем UI, чтобы кнопка изменилась до начала проверок
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()
            
            # Импортируем settings_manager для проверки
            from config.settings import settings_manager
            
            # Проверяем настройки перед запуском
            if not settings_manager.is_ready_for_bot():
                is_valid, errors = settings_manager.validate_settings()
                error_msg = "Не удается запустить сервер. Проблемы с настройками:\n\n" + "\n".join(f"• {error}" for error in errors)
                error_msg += "\n\nПерейдите на вкладку 'Настройки' для исправления проблем."
                
                QMessageBox.warning(self, "Невалидные настройки", error_msg)
                logger.warning(f"Запуск сервера отменен - невалидные настройки: {', '.join(errors)}")
                
                # Возвращаем кнопку в исходное состояние
                self.toggle_server_button.setText('Запустить сервер')
                self.toggle_server_button.setEnabled(True)
                self.status_label.setVisible(False)
                return
            
            # Настройки валидны - пытаемся запустить
            logger.info("Настройки валидны - выполняем умный запуск сервера...")
            
            # Получаем родительское окно для вызова умного перезапуска
            parent_window = self.parent()
            while parent_window and not hasattr(parent_window, 'smart_restart_bot'):
                parent_window = parent_window.parent()
            
            if parent_window and hasattr(parent_window, 'smart_restart_bot'):
                # Используем умный перезапуск
                success = parent_window.smart_restart_bot("Ручной запуск сервера")
                if not success:
                    # Если запуск не удался (например, ошибка валидации), возвращаем кнопку в исходное состояние
                    self.toggle_server_button.setText('Запустить сервер')
                    self.toggle_server_button.setEnabled(True)
                    self.status_label.setVisible(False)
                else:
                    # UI обновится через сигналы от bot_thread (handle_bot_started)
                    logger.info("Умный запуск сервера успешен")
                    
                    # Обновляем статистику сеанса
                    # 🔧 ИСПРАВЛЕНО: Используем правильный метод для сброса статистики
                    if hasattr(stats, 'stats'):
                        stats.stats.reset()
                    self.session_start_time = datetime.datetime.now()
                    logger.info(f"Сеанс начат в {self.session_start_time}")
            else:
                # Fallback: старый способ
                logger.warning("Не найден parent с smart_restart_bot, используем простой запуск")
                
                # Запуск bot_thread если он не запущен
                if self.bot_thread and not self.bot_thread.isRunning():
                    self.bot_thread.start()
                
                # Активируем сервер
                server_state.server_active = True
                self.show_status_message('Сервер запущен')
                self.toggle_server_button.setText('Остановить сервер')
                
                # Сброс статистики сеанса
                # 🔧 ИСПРАВЛЕНО: Используем правильный метод для сброса статистики
                if hasattr(stats, 'stats'):
                    stats.stats.reset()
                self.session_start_time = datetime.datetime.now()
                logger.info(f"Сеанс начат в {self.session_start_time}")

    def toggle_ban_user(self, user):
        try:
            # 🆕 Используем UserService
            self.user_service.toggle_user_ban(user)
            self.load_users()  # Обновляем список после изменения
        except Exception as e:
            logger.error(f"Ошибка при изменении статуса бана пользователя: {e}")

    def toggle_ban_group(self, chat):
        try:
            # 🆕 Используем UserService
            self.user_service.toggle_group_ban(chat)
            self.load_group_chats() # Обновляем список после изменения
        except Exception as e:
            logger.error(f"Ошибка при изменении статуса бана группы: {e}")

    def change_user_priority(self, user_id, new_priority):
        try:
            # 🆕 Используем UserService
            self.user_service.change_user_priority(user_id, new_priority)
        except Exception as e:
            logger.error(f"Ошибка при изменении приоритета пользователя {user_id}: {e}")

    def update_stats(self):
        try:
            self._sync_refresh_intervals()
            # 🆕 Используем UserService и StatsService
            total_users = self.user_service.count_total_users()
            online_users = self.user_service.count_online_users()
            stats_text = self.stats_service.get_compact_stats_string(total_users, online_users)
            self.stats_widget.label.setText(stats_text)

            # 🆕 Обновляем статус наверстывания истории
            if server_state.is_catching_up:
                self.backlog_label.setToolTip(f"Навёрстывание истории: обработано {server_state.backlog_processed_count} пропущенных сообщений.\nБот догоняет текущее время.")
                self.backlog_label.setVisible(True)
            else:
                self.backlog_label.setVisible(False)

        except Exception as e:
            logger.error(f"Ошибка обновления статистики: {e}")

    def _format_stat_value(self, value, compact=True):
        """Форматирует числа. compact=True (1.5k), compact=False (1 500)."""
        if not isinstance(value, (int, float)):
            try:
                value = int(value)
            except:
                return str(value)
        
        if compact:
            if value >= 1000000:
                return f"{value/1000000:.1f}M".replace(".0M", "M")
            if value >= 1000:
                return f"{value/1000:.1f}k".replace(".0k", "k")
            return f"{value:,}".replace(",", " ")
        
        # Полный формат с разделителем тысяч (пробел)
        return f"{value:,}".replace(",", " ")

    def show_full_stats(self):
        """Показывает компактный горизонтальный диалог со статистикой и историей сеансов."""
        try:
            total_users = self.user_service.count_total_users()
            online_users = self.user_service.count_online_users()
            data = self.stats_service.get_all_current_stats()

            dialog = QDialog(self)
            dialog.setWindowTitle("Статистика")
            # Увеличенная высота для предотвращения сплюснутости
            dialog.setMinimumSize(750, 420)
            dialog.setMaximumSize(950, 500)
            dialog.resize(800, 420)

            # Применяем тему
            self._apply_stats_dialog_theme(dialog)

            main_layout = QVBoxLayout()
            main_layout.setContentsMargins(8, 8, 8, 8)
            main_layout.setSpacing(6)

            # Заголовок
            title_label = QLabel("📊 Статистика текущего сеанса")
            system_accent = QApplication.palette().color(QPalette.ColorRole.Highlight)
            accent_color = system_accent.name()
            title_label.setStyleSheet(
                f"font-size: 14px; font-weight: bold; padding: 6px; "
                f"color: {accent_color};"
            )
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            main_layout.addWidget(title_label)

            # ━━━ ГОРИЗОНТАЛЬНЫЙ КОНТЕЙНЕР С СЕКЦИЯМИ ━━━
            sections_container = QWidget()
            sections_layout = QHBoxLayout(sections_container)
            sections_layout.setSpacing(12)
            sections_layout.setContentsMargins(0, 0, 0, 0)

            avg_wait_str = self.stats_service._format_time(data["avg_wait_time"])
            avg_resp_str = self.stats_service._format_time(data["avg_response_time"])

            # Секция 1: Пользователи (левая колонка)
            users_section = self._create_stats_section("Пользователи", [
                self._create_stat_row("👤", "Онлайн", f"{online_users}/{total_users}", "#81C784"),
                self._create_stat_row("📝", "Запросов", str(data["request_count"])),
                self._create_stat_row("⏳", "В очереди", str(data["pending_requests"]), "#FFB74D"),
            ])
            sections_layout.addWidget(users_section, 1)

            # Секция 2: Производительность (средняя колонка)
            perf_section = self._create_stats_section("Производительность", [
                self._create_stat_row("⏱️", "Ожидание", avg_wait_str, "#64B5F6"),
                self._create_stat_row("⚡", "Ответ", avg_resp_str, "#64B5F6"),
            ])
            sections_layout.addWidget(perf_section, 1)

            # Секция 3: Токены (правая колонка)
            tokens_section = self._create_stats_section("Токены", [
                self._create_stat_row("📥", "Входные", self._format_stat_value(data['input_tokens'], compact=False)),
                self._create_stat_row("📤", "Выходные", self._format_stat_value(data['output_tokens'], compact=False)),
                self._create_stat_row("📊", "Всего", self._format_stat_value(data['total_tokens'], compact=False), "#90CAF9"),
            ])
            sections_layout.addWidget(tokens_section, 1)

            main_layout.addWidget(sections_container)

            # ━━━ ИСТОРИЯ СЕАНСОВ (компактная горизонтальная) ━━━
            history_group = QGroupBox("История сеансов")
            history_group.setStyleSheet("""
                QGroupBox {
                    font-weight: bold;
                }
            """)
            history_layout = QHBoxLayout()
            history_layout.setSpacing(8)

            past_sessions = self.stats_service.get_past_sessions(limit=5)
            total_sessions = self.stats_service.get_total_sessions_count()

            if past_sessions:
                history_table = QTableWidget()
                history_table.setColumnCount(4)
                history_table.setHorizontalHeaderLabels(["Дата", "Длит.", "Запросы", "Ср. отв."])
                history_table.setRowCount(len(past_sessions))
                history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
                history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
                history_table.verticalHeader().setVisible(False)
                # Растягиваемая высота
                history_table.setMinimumHeight(150)
                # history_table.setMaximumHeight(110) # Убрано ограничение

                # Растягиваем колонки
                history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
                history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
                history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
                history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

                for row, session in enumerate(past_sessions):
                    start = session.get("start", "—")
                    # Обрезаем дату до часа:минуты
                    if len(start) > 16:
                        start = start[:16]
                    date_item = QTableWidgetItem(start)
                    date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    history_table.setItem(row, 0, date_item)

                    duration = session.get("duration", "—")
                    if "." in duration:
                        duration = duration.split(".")[0]
                    dur_item = QTableWidgetItem(duration)
                    dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    history_table.setItem(row, 1, dur_item)

                    req_item = QTableWidgetItem(str(session.get("requests", 0)))
                    req_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    history_table.setItem(row, 2, req_item)

                    avg_resp = session.get("avg_response", "—")
                    resp_item = QTableWidgetItem(avg_resp)
                    resp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    history_table.setItem(row, 3, resp_item)

                history_layout.addWidget(history_table, 3)
                
                # ━━━ ПАНЕЛЬ УПРАВЛЕНИЯ ИСТОРИЕЙ (ПРАВАЯ) ━━━
                file_column = QVBoxLayout()
                file_column.setContentsMargins(12, 0, 12, 0)
                file_column.setSpacing(10)
                file_column.addStretch(1)

                # Информация о количестве сеансов (теперь сверху и более заметна)
                sessions_header = QLabel("СЕАНСЫ")
                sessions_header.setStyleSheet("color: #B0BEC5; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
                sessions_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
                file_column.addWidget(sessions_header)

                sessions_count = QLabel(f"<b>{total_sessions}</b> сеансов")
                sessions_count.setStyleSheet("color: #FFFFFF; font-size: 12px;")
                sessions_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
                file_column.addWidget(sessions_count)

                # Разделитель
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setStyleSheet("background-color: #333333; max-height: 1px; margin: 4px 0;")
                file_column.addWidget(line)
                
                # Кнопки (фиксированная ширина для симметрии)
                btn_width = 110
                
                open_file_btn = QPushButton("📄 Открыть")
                open_file_btn.setFixedWidth(btn_width)
                open_file_btn.setToolTip("Открыть session_stats.txt")
                open_file_btn.clicked.connect(self._open_session_stats_file)
                open_file_btn.setEnabled(self.stats_service.session_stats_exist())
                file_column.addWidget(open_file_btn, 0, Qt.AlignmentFlag.AlignCenter)

                reset_btn = QPushButton("🔄 Сбросить")
                reset_btn.setFixedWidth(btn_width)
                reset_btn.setToolTip("Сбросить счётчики текущего сеанса")
                reset_btn.clicked.connect(lambda: self._reset_session_stats(dialog))
                file_column.addWidget(reset_btn, 0, Qt.AlignmentFlag.AlignCenter)
                
                file_column.addStretch(1)
                history_layout.addLayout(file_column, 1)
            else:
                no_data_label = QLabel("Нет сохранённых сеансов")
                no_data_label.setStyleSheet("color: #78909C; padding: 10px;")
                no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                history_layout.addWidget(no_data_label)

            history_group.setLayout(history_layout)
            main_layout.addWidget(history_group, 1) # Добавлен stretch фактор 1

            dialog.setLayout(main_layout)
            dialog.exec()

        except Exception as e:
            logger.error(f"Ошибка отображения полной статистики: {e}")
            QMessageBox.warning(self, "Ошибка", f"Не удалось показать статистику: {e}")

    def _apply_stats_dialog_theme(self, dialog: QDialog):
        """Применяет текущую тему OLED/стандартную к диалогу статистики."""
        try:
            from config.settings import settings_manager
            settings = settings_manager.get_settings()
            is_oled = settings.get('oled_mode', False)
            
            # 🎨 ПОЛУЧАЕМ СИСТЕМНЫЙ АКЦЕНТНЫЙ ЦВЕТ
            from PyQt6.QtGui import QPalette
            from PyQt6.QtWidgets import QApplication
            system_accent = QApplication.palette().color(QPalette.ColorRole.Highlight)
            accent_color = system_accent.name()
            
            if is_oled:
                border_color = "#333333"
                bg_color = "#000000"
                panel_bg = "#000000"
                header_bg = "#000000"
            else:
                border_color = "#444444"
                bg_color = "#1e1e1e"
                panel_bg = "#252526"
                header_bg = "#252526"
            
            # Применяем стили к диалогу и его содержимому
            dialog_style = f"""
                QDialog {{
                    background-color: {bg_color};
                }}
                QScrollArea {{
                    border: none;
                    background-color: transparent;
                }}
                QScrollArea > QWidget > QWidget {{
                    background-color: transparent;
                }}
                QGroupBox {{
                    border: 2px solid {border_color};
                    border-radius: 8px;
                    margin-top: 1.1em;
                    padding-top: 0.8em;
                    color: #FFFFFF;
                    font-weight: bold;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px;
                    color: {accent_color};
                }}
                QLabel {{
                    color: #FFFFFF;
                    background-color: transparent;
                }}
                QTableWidget {{
                    gridline-color: {border_color};
                    background-color: {bg_color};
                    border: 1px solid {border_color};
                    color: #FFFFFF;
                }}
                QHeaderView::section {{
                    background-color: {header_bg};
                    color: #FFFFFF;
                    padding: 6px;
                    border: 1px solid {border_color};
                }}
                QPushButton {{
                    padding: 6px 12px;
                    border-radius: 4px;
                    border: 1px solid {border_color};
                    background-color: {header_bg};
                    color: #FFFFFF;
                }}
                QPushButton:hover {{
                    background-color: {border_color};
                }}
            """
            dialog.setStyleSheet(dialog_style)
        except Exception as e:
            logger.debug(f"Ошибка при применении темы к диалогу статистики: {e}")

    def _create_stat_row(self, icon: str, label: str, value: str, value_color: str = "#FFFFFF") -> QWidget:
        """Создаёт компактную строку статистики с иконкой."""
        row = QFrame()
        row.setMinimumHeight(38) # Предотвращаем сплюснутость
        row.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.03);
                border-radius: 6px;
                padding: 6px 12px;
            }
        """)
        
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)
        
        # Иконка
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("border: none; background: transparent;")
        icon_label.setFixedWidth(24)
        row_layout.addWidget(icon_label)
        
        # Название метрики
        label_widget = QLabel(label)
        label_widget.setStyleSheet("color: #90A4AE; font-size: 12px; border: none; background: transparent;")
        row_layout.addWidget(label_widget)
        
        # Значение (растягивается)
        row_layout.addStretch()
        
        # Значение
        value_widget = QLabel(value)
        value_widget.setStyleSheet(f"color: {value_color}; font-size: 13px; font-weight: bold; border: none; background: transparent;")
        row_layout.addWidget(value_widget)
        
        row.setLayout(row_layout)
        return row

    def show_status_message(self, message: str, timeout: int = 5000):
        """Показывает временное статусное сообщение справа от кнопки."""
        self.status_label.setText(message)
        self.status_label.setVisible(True)
        self.status_timer.start(timeout)

    def _create_stats_section(self, title: str, rows: list) -> QWidget:
        """Создаёт секцию статистики с заголовком и строками."""
        section = QFrame()
        section.setStyleSheet("border: none; background: transparent;")
        
        section_layout = QVBoxLayout()
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(4)
        
        # Заголовок секции
        title_label = QLabel(title)
        title_label.setStyleSheet("""
            color: #B0BEC5;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 1px;
            padding: 8px 12px 4px;
            border: none;
            background: transparent;
        """)
        section_layout.addWidget(title_label)
        
        # Строки метрик
        for row in rows:
            section_layout.addWidget(row)
        
        # Добавляем распорку в конец, чтобы заголовки всегда были сверху
        section_layout.addStretch()
        
        section.setLayout(section_layout)
        return section

    def _open_session_stats_file(self):
        """Открывает файл session_stats.txt в системном редакторе."""
        try:
            import os
            import subprocess
            
            file_path = self.stats_service.get_session_stats_path()
            
            if not file_path.exists():
                QMessageBox.information(
                    self,
                    "Файл не найден",
                    "Файл session_stats.txt ещё не создан.\n"
                    "Он появится после первого завершения сеанса.\n\n"
                    f"Ожидаемый путь:\n{file_path}",
                )
                return
            
            # Открываем в системном редакторе (Windows)
            os.startfile(str(file_path.resolve()))
        except Exception as e:
            logger.error(f"Ошибка при открытии файла статистики: {e}")
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть файл: {e}")

    def _reset_session_stats(self, dialog: QDialog):
        """Сбрасывает статистику текущего сеанса (с подтверждением)."""
        reply = QMessageBox.question(
            dialog,
            "Сброс статистики",
            "Сбросить счётчики текущего сеанса?\n\nИстория предыдущих сеансов не будет затронута.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.stats_service.reset()
            dialog.close()
            self.update_stats()
            logger.info("Статистика сеанса сброшена пользователем")

    def save_session_statistics(self):
        """
        Сбрасывает UI-состояние сеанса.
        
        Примечание: Запись статистики в session_stats.txt выполняется
        в BotThread.save_session_statistics() (main.py) — он всегда
        вызывается при остановке бота через finally-блок.
        Здесь мы только сбрасываем состояние UI.
        """
        try:
            if self.session_start_time is not None:
                logger.info("Сеанс завершён (UI). Статистика будет сохранена потоком бота.")
                self.session_start_time = None
            else:
                logger.info("Сервер не был запущен. Статистика сеанса не сохранена.")
        except Exception as e:
            logger.error(f"Ошибка при завершении сеанса (UI): {e}")

    def toggle_auto_scroll(self, state):
        self.auto_scroll_enabled = bool(state)
        
    def filter_messages(self, index):
        # Запоминаем выбранный фильтр и обновляем историю сообщений
        if self.current_user_id is not None or self.current_chat_id is not None:
            self.update_message_history()

    def _apply_message_filter(self, messages, selected_filter, is_group_context):
        """Применяет фильтр к сообщениям."""
        if selected_filter == "Всё":
            return list(messages)
        
        filtered = []
        for msg in messages:
            role = (msg.get('role') or '').lower()
            is_summary = bool(msg.get('is_summary'))
            is_secretary = (msg.get('source_mode') or 'normal') == 'secretary'
            
            if selected_filter == "Обычные":
                # Только user и assistant без сводок
                if not is_secretary and not is_summary and role in {'user', 'assistant'}:
                    filtered.append(msg)
            elif selected_filter == "Секретарь":
                if is_secretary:
                    filtered.append(msg)
            elif selected_filter == "Сводки":
                # Только сводки
                if is_summary:
                    filtered.append(msg)
            elif selected_filter == "Контекст":
                # Системные сообщения и сводки (для групп)
                if is_summary or (not is_summary and role not in {'user', 'assistant'}):
                    filtered.append(msg)
        
        return filtered

    def _build_history_signature(self, messages):
        """Возвращает компактную подпись истории для отслеживания изменений."""
        if not messages:
            return (0, (), '', False)

        last_ids = tuple(msg.get('id') for msg in messages[-3:])
        last_edit_marker = ''
        try:
            last_edit_marker = max(
                (msg.get('edited_at') or msg.get('timestamp') or '')
                for msg in messages
            )
        except ValueError:
            last_edit_marker = ''
        has_deleted = any(bool(msg.get('is_deleted')) for msg in messages)

        return (len(messages), last_ids, last_edit_marker, has_deleted)

    def update_message_history(self):
        if hasattr(self, 'tab_widget') and self.tab_widget.currentIndex() != 0:
            return

        if self.current_user_id is None and self.current_chat_id is None:
            self.history_text.clear()
            return

        context_kind = None
        messages = []
        header_text = ""
        is_group_context = False
        snapshot_text = ""

        try:
            filter_index = self.message_filter_combo.currentIndex()
            selected_filter = self.message_filter_combo.currentText()

            scrollbar = self.history_text.verticalScrollBar()
            current_value = scrollbar.value()
            near_top = (current_value - scrollbar.minimum()) <= 50

            # 🔧 ИСПРАВЛЕНО + 🆕: Используем UserService для получения сообщений
            if self.current_user_id is not None:
                context_kind = "user"
                # 🆕 Используем UserService
                user = self.user_service.get_user_by_telegram_id(self.current_user_id)
                if user:
                    username = user.get('username') or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                    # 🆕 Используем UserService для получения истории
                    if selected_filter == "Секретарь":
                        messages = self.user_service.get_secretary_history(self.current_user_id, limit=500)
                    elif selected_filter == "Всё":
                        regular_messages = self.user_service.get_user_history(self.current_user_id, limit=500)
                        secretary_messages = self.user_service.get_secretary_history(self.current_user_id, limit=500)
                        messages = sorted(
                            [*regular_messages, *secretary_messages],
                            key=lambda msg: msg.get('timestamp') or '',
                        )
                    else:
                        messages = self.user_service.get_user_history(self.current_user_id, limit=500)
                else:
                    username = str(self.current_user_id)
                    messages = []
                header_text = f"Пользователь: {username} (ID: {self.current_user_id})"
            elif self.current_chat_id is not None:
                context_kind = "chat"
                # 🆕 Используем UserService для получения активных сообщений группы
                addressed_only = self.group_addressed_only_checkbox.isChecked()
                messages = self.user_service.get_group_history(self.current_chat_id, limit=500, addressed_only=addressed_only)
                chat_name = self.current_chat_title or str(self.current_chat_id)
                header_text = f"Чат: {chat_name}"
                is_group_context = True
                try:
                    # Lazy import для избежания циклического импорта
                    from bot.handlers.services.context_snapshot import build_group_context_snapshot
                    snapshot_text = build_group_context_snapshot(self.current_chat_id, limit=30)
                except Exception as snapshot_err:
                    logger.debug(f"Не удалось построить снапшот истории: {snapshot_err}")
            else:
                return

            # Применяем фильтр к сообщениям
            filtered_messages = self._apply_message_filter(messages, selected_filter, is_group_context)

            # 🔧 ИСПРАВЛЕНО: Проверяем нужно ли перезаписывать историю
            # Перезаписываем если: первый раз, количество сообщений изменилось, или изменился фильтр
            current_text = self.history_text.toPlainText()
            history_signature = self._build_history_signature(filtered_messages)
            need_refresh = (
                not current_text
                or filter_index != self._last_filter_index
                or history_signature != self._last_history_signature
            )
            
            if need_refresh:
                self.history_text.clear()
                cursor = self.history_text.textCursor()
                
                if header_text:
                    cursor.insertText(header_text + "\n", self.message_formats["header"])
                snapshot_clean = snapshot_text.strip() if snapshot_text else ""
                if snapshot_clean and selected_filter in ["Контекст", "Всё"]:
                    # Разделяем заголовок "Краткий контекст..." и сам контекст
                    if snapshot_clean.startswith("Краткий контекст"):
                        lines = snapshot_clean.split('\n', 1)
                        cursor.insertText(lines[0] + "\n", self.message_formats["snapshot_header"])
                        if len(lines) > 1:
                            cursor.insertText(lines[1] + "\n", self.message_formats["snapshot"])
                    else:
                        cursor.insertText(snapshot_clean + "\n", self.message_formats["snapshot"])
                if header_text or (snapshot_clean and selected_filter in ["Контекст", "Всё"]):
                    cursor.insertText("\n", self.message_formats["system"])

                # 🔧 ИСПРАВЛЕНО: Ограничиваем длину контента для очень длинных сообщений
                MAX_CONTENT_LENGTH = 5000  # Максимум символов на сообщение
                
                for msg in reversed(filtered_messages):
                    role = msg['role']
                    content = msg.get('content', '') or ""
                    content_type = (msg.get('content_type') or 'text').lower()

                    format_key = role if role in self.message_formats else "system"
                    lower_content = content.lower()
                    if "ошибка" in lower_content or "error" in lower_content:
                        format_key = "error"

                    # 🔧 ИСПРАВЛЕНО: Обработка сводок (is_summary)
                    is_summary = msg.get('is_summary', 0)
                    if is_summary:
                        format_key = "system"
                        label = "📋 СВОДКА ИСТОРИИ"
                    else:
                        label = role.upper()
                        if (msg.get('source_mode') or 'normal') == 'secretary':
                            label = f"СЕКРЕТАРЬ {label}"
                    
                    if is_group_context:
                        author = msg.get('author_username') or msg.get('author_full_name')
                        if not author and msg.get('author_telegram_id'):
                            author = str(msg.get('author_telegram_id'))
                        if author and not is_summary:
                            label = f"{label} ({author})"
                        if role == 'user' and not msg.get('is_addressed'):
                            label += " [без @]"

                    # 🆕 Добавляем индикаторы для отредактированных и удалённых сообщений
                    is_deleted = msg.get('is_deleted', 0)
                    edited_at = msg.get('edited_at')
                    
                    if is_deleted:
                        label += " 🗑️ [УДАЛЕНО]"
                        content = "[Это сообщение было удалено]"
                        format_key = "error"
                    elif edited_at:
                        label += " ✏️ [ОТРЕДАКТИРОВАНО]"

                    # Обработка изображений с отдельным форматом
                    image_prefix = ""
                    if content_type in {'image', 'image_ref'}:
                        prefix = "📷"
                        if msg.get('image_path'):
                            image_prefix = f"[{prefix} {msg.get('image_mime') or 'image'}] "
                        else:
                            image_prefix = f"[{prefix}] "
                            if not content:
                                content = "Изображение недоступно"
                    elif content_type == 'voice':
                        image_prefix = "[🎤] "
                    elif content_type == 'video_note':
                        image_prefix = "[⭕] "

                    # 🔧 ИСПРАВЛЕНО: Обрезаем очень длинные сообщения
                    if len(content) > MAX_CONTENT_LENGTH:
                        content = content[:MAX_CONTENT_LENGTH] + f"\n\n[... обрезано, показано {MAX_CONTENT_LENGTH} из {len(content)} символов ...]"

                    # Метка (User/Assistant/System) — с форматом роли
                    label_format = self.message_formats.get(format_key, self.message_formats["system"])
                    cursor.insertText(f"{label}: ", label_format)
                    
                    # Индикатор изображения (если есть)
                    if image_prefix:
                        cursor.insertText(image_prefix, self.message_formats["image_indicator"])
                    
                    # Контент — разные цвета для юзера и ассистента
                    if role == 'user':
                        content_format = self.message_formats["user_content"]
                    elif role == 'assistant':
                        content_format = self.message_formats["assistant_content"]
                    else:
                        content_format = self.message_formats["system"]
                    
                    cursor.insertText(content, content_format)
                    cursor.insertText("\n\n", self.message_formats["system"])
                
                # Сохраняем количество сообщений и фильтр для сравнения
                self._last_message_count = len(filtered_messages)
                self._last_filter_index = filter_index
                self._last_history_signature = history_signature

            # 🔧 ИСПРАВЛЕНО: Автопрокрутка только если включена и пользователь не прокрутил вверх
            if self.auto_scroll_enabled or near_top:
                scrollbar.setValue(scrollbar.minimum())
            else:
                scrollbar.setValue(current_value)

        except Exception as e:
            logger.error(f"Ошибка обновления истории сообщений: {e}")
            cursor = self.history_text.textCursor()
            cursor.insertText(f"ОШИБКА: {str(e)}\n\n", self.message_formats["error"])

    def clear_logs(self):
        self.logs_text.clear()
    
    def update_logs(self):
        try:
            logs = self.log_handler.get_logs()
            if not logs:
                return
                
            # Сохраняем текущую позицию скролла и близость к верху
            scrollbar = self.logs_text.verticalScrollBar()
            current_position = scrollbar.value()
            near_top = (current_position - scrollbar.minimum()) <= 50
            
            # Доступ к текстовому курсору
            cursor = self.logs_text.textCursor()
            
            # Добавляем все новые логи
            for level, message in logs:
                # Парсим сообщение формата: ts - LEVEL - logger - msg
                ts, lvl, name, msg = None, None, None, None
                try:
                    parts = message.split(" - ", 3)
                    if len(parts) == 4:
                        ts, lvl, name, msg = parts
                    else:
                        msg = message
                except Exception:
                    msg = message

                # Форматы для частей
                time_fmt = QTextCharFormat()
                time_fmt.setForeground(QColor("#9E9E9E"))

                level_fmt = self.log_handler.log_formats.get(level, QTextCharFormat())
                level_fmt.setFontWeight(QFont.Weight.Bold)

                name_fmt = QTextCharFormat()
                name_fmt.setForeground(QColor("#1565C0"))
                name_fmt.setFontItalic(True)

                msg_fmt = QTextCharFormat()
                if level >= logging.ERROR:
                    msg_fmt.setForeground(QColor("#D32F2F"))

                # Вставка с подсветкой и отступами ВВЕРХ (новые сверху)
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                if ts is not None:
                    cursor.insertText(ts, time_fmt)
                    cursor.insertText("  ")
                if lvl is not None:
                    cursor.insertText(lvl, level_fmt)
                    cursor.insertText("  ")
                if name is not None:
                    cursor.insertText(name, name_fmt)
                    cursor.insertText("  ")
                if msg is not None:
                    cursor.insertText(msg, msg_fmt)
                cursor.insertText("\n\n")  # дополнительный отступ между сообщениями
            
            # Логика автопрокрутки: новые логи сверху
            if self.logs_auto_scroll.isChecked() or near_top:
                scrollbar.setValue(scrollbar.minimum())
            else:
                scrollbar.setValue(current_position)
        except KeyboardInterrupt:
            logger.info("Остановка обновления логов (KeyboardInterrupt)")
        except Exception as e:
            logger.error(f"Ошибка обновления логов: {e}")
