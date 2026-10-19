# gui/admin_panel/user_management.py

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QDialog, QTableWidgetItem,
    QTextEdit, QHeaderView, QAbstractItemView, QSpinBox, QSplitter,
    QStackedWidget, QApplication, QSizePolicy, QScrollArea, QFrame,
)
from PyQt6.QtCore import QTimer, Qt, QEvent
from PyQt6.QtGui import QFont, QTextCharFormat, QColor, QTextCursor, QTextOption, QFontDatabase
from functools import partial
from utils import server_state
from utils.logger import setup_logger
from utils import stats  # Импортируем модуль статистики
import collections
import datetime
import logging

from gui.design import (
    FxButton, FxComboBox, SegmentedControl, StatTile, StatusBadge, SwitchRow,
    card, current_tokens, icon_button, icons, label, make_table, page_header, primary,
)
from gui.design.dialogs import FxDialog, ask, inform, warn

# Убран статический импорт для избежания циклического импорта
# Импорт делается внутри функции update_message_history()

# Импорты из сервисов
from .handlers.log_handler import LogHandler  # Переиспользуемый обработчик логов
from .services.user_service import UserService  # Работа с пользователями и чатами
from .services.stats_service import StatsService  # Работа со статистикой

logger = setup_logger(__name__)

# Ширина области таблицы+истории, начиная с которой они стоят рядом (иначе — друг под другом)
SIDE_BY_SIDE_MIN_WIDTH = 890
# Минимальные ширины карточек в раскладке «рядом» (в сумме с ручкой сплиттера ~ порог выше)
SIDE_LEFT_MIN_W = 550
SIDE_RIGHT_MIN_W = 330
# Фиксированные ширины колонок с виджетами внутри ячеек (QHeaderView их содержимое не измеряет)
COL_PRIORITY_W = 92
COL_STATUS_W = 112
COL_ACTION_W = 124


class ServerButton(FxButton):
    """Кнопка запуска/остановки сервера. Вид (primary/danger) и иконка следуют за текстом,
    поэтому внешний код по-прежнему управляет ею через setText('Остановить сервер') и setEnabled()."""

    def __init__(self, text: str = "Запустить сервер") -> None:
        super().__init__(text)
        self._sync_variant()

    def setText(self, text: str) -> None:  # noqa: N802 (имя Qt)
        super().setText(text)
        self._sync_variant()

    def _sync_variant(self) -> None:
        text = self.text()
        stopping = text == "Остановить сервер" or text.startswith("Останавлива")
        variant = "danger" if stopping else "primary"
        icon_name = "mdi6.stop" if stopping else "mdi6.play"
        color = "danger" if stopping else "accent_text"
        self.setProperty("iconName", icon_name)
        self.setProperty("iconColor", color)
        self.setIcon(icons.icon(icon_name, color=color))
        if self.objectName() != variant:
            self.setObjectName(variant)
            # objectName влияет на QSS (цвет текста) — переприменяем стиль
            self.style().unpolish(self)
            self.style().polish(self)
        self.update()


class ServerStatusLabel(QWidget):
    """Бейдж статуса сервера с интерфейсом QLabel (setText/text/setVisible):
    admin_panel_base.py обращается к нему как к текстовой метке. Цвет бейджа выводится из текста."""

    def __init__(self, text: str = "Сервер остановлен") -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._badge = StatusBadge(text, "idle", pulse=False)
        lay.addWidget(self._badge)
        self.setText(text)

    @staticmethod
    def kind_for(text: str) -> str:
        low = text.lower()
        if any(word in low for word in ("не удалось", "нет соединения", "ошибк")):
            return "error"
        if "остановлен" in low:
            return "idle"
        if "запущен" in low:
            return "ok"
        if low.startswith("запуск") or low.startswith("останавлива"):
            return "warn"
        return "info"

    def setText(self, text: str) -> None:  # noqa: N802
        self.set_status(text, self.kind_for(text))

    def set_status(self, text: str, kind: str) -> None:
        self._badge.text, self._badge.kind = text, kind
        self._badge.updateGeometry()
        self._badge.update()

    def text(self) -> str:
        return self._badge.text


class UserManagement(QWidget):
    def __init__(self, bot_thread):
        super().__init__()
        self.bot_thread = bot_thread
        # Сервисы вместо прямого DatabaseManager
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
        self._formats_theme_key = None
        self._splitter_sized = False
        self._log_theme_key = None
        self._log_entries = collections.deque(maxlen=self.MAX_LOG_ENTRIES)  # (level, ts, lvl, name, msg)
        self.init_message_formats()
        
        # Настройка логгера для отображения в GUI
        self.log_handler = LogHandler()
        root_logger = logging.getLogger()
        root_logger.addHandler(self.log_handler)
        
        self.init_ui()
        try:  # перекраска журнала при смене темы
            from gui.design import appearance
            appearance.controller().changed.connect(self._rerender_logs_for_theme)
        except Exception as e:
            logger.warning(f"Не удалось подписаться на смену темы: {e}")

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

    @staticmethod
    def _theme_key():
        """Подпись текущей темы: по ней понимаем, что форматы текста надо пересоздать."""
        t = current_tokens()
        return (t.get("bg"), t.get("accent")) if t else None

    def init_message_formats(self):
        """Форматы текста истории из токенов темы — читаются в тёмной, светлой и OLED-темах."""
        t = current_tokens()
        if not t:
            return
        self._formats_theme_key = self._theme_key()

        def setup(key, role, bold=False, italic=False, size=None):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(t[role]))
            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            if italic:
                fmt.setFontItalic(True)
            if size:
                fmt.setFontPointSize(size)
            self.message_formats[key] = fmt

        setup("header", "text", bold=True, size=10)                # заголовок чата
        setup("snapshot_header", "info")                           # «Краткий контекст последних сообщений:»
        setup("snapshot", "text_muted", italic=True)               # краткий контекст
        setup("user", "info", bold=True)                           # метка «USER:»
        setup("assistant", "accent", bold=True)                    # метка «ASSISTANT:»
        setup("user_content", "text")                              # текст пользователя
        setup("assistant_content", "text")                         # текст ассистента
        setup("system", "text_muted", italic=True)                 # системные сообщения
        setup("error", "danger", bold=True)                        # ошибки
        setup("image_indicator", "warning", bold=True)             # индикаторы изображений
        setup("separator", "text_muted")

    def _refresh_theme_formats(self):
        """Если тема сменилась — пересоздаём форматы и просим перерисовать историю."""
        if self._theme_key() != self._formats_theme_key:
            self.init_message_formats()
            self._last_history_signature = None

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # ── Шапка: заголовок, статус сервера, кнопка запуска/остановки ──
        self.toggle_server_button = ServerButton('Запустить сервер')
        self.toggle_server_button.setToolTip(
            "Запуск и остановка сервера\n"
            "Запускает или останавливает приём сообщений Telegram. Перед запуском проверяются настройки."
        )

        # Индикатор наверстывания пропущенных сообщений (виден только пока бот догоняет)
        self.backlog_label = StatusBadge('Наверстывание', 'warn', pulse=False)
        self.backlog_label.setVisible(False)

        # Статус сервера: бейдж с интерфейсом метки (его обновляет admin_panel_base)
        self.status_label = ServerStatusLabel('Сервер остановлен')

        # Таймер возврата бейджа к «постоянному» состоянию после временного сообщения
        self.status_timer = QTimer(self)
        self.status_timer.setSingleShot(True)
        self.status_timer.timeout.connect(self._show_steady_status)

        self.stats_button = icon_button("", "mdi6.chart-box-outline")
        self.stats_button.setToolTip("Подробная статистика\nТокены, время ожидания и ответа, история прошлых сеансов.")
        self.stats_button.clicked.connect(self.show_full_stats)

        root.addLayout(page_header(
            "Пользователи", "Кто общается с ботом и нагрузка",
            self.backlog_label, self.status_label, self.stats_button, self.toggle_server_button,
        ))

        # ── Плитки метрик ──
        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(14)
        self.tile_online = StatTile("0", "Онлайн", "mdi6.account-check-outline", "ok")
        self.tile_requests = StatTile("0", "Запросов", "mdi6.message-processing-outline", "idle")
        self.tile_pending = StatTile("0", "В очереди", "mdi6.timer-sand", "warn")
        self.tile_tokens = StatTile("0", "Токенов", "mdi6.counter", "info")
        self._tiles = (self.tile_online, self.tile_requests, self.tile_pending, self.tile_tokens)
        for tile in self._tiles:
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setToolTip("Статистика сеанса\nОнлайн — пользователи на связи из всех известных. Нажмите, чтобы открыть подробную статистику.")
            tile.installEventFilter(self)
            tiles_row.addWidget(tile, 1)
        root.addLayout(tiles_row)

        # ── Основная часть: слева таблицы, справа история и логи ──
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)

        # Левая карточка: переключатель «Пользователи / Группы» и таблицы
        left, left_lay = card()
        left_lay.setSpacing(10)
        self.entities_switch = SegmentedControl(["Пользователи", "Группы"])
        left_lay.addWidget(self.entities_switch)

        self.users_table = self._make_entity_table(
            ['Пользователь', 'Telegram ID', 'Приоритет', 'Статус', 'Действия'])
        self.groups_table = self._make_entity_table(
            ['Название чата', 'Chat ID', 'Сообщений', 'Статус', 'Действия'])

        self.entities_stack = QStackedWidget()
        self.entities_stack.addWidget(self.users_table)
        self.entities_stack.addWidget(self.groups_table)
        left_lay.addWidget(self.entities_stack, 1)
        self.entities_tab = self.entities_stack  # совместимость: прежнее имя (есть currentIndex)
        self.entities_switch.changed.connect(self._on_entities_switched)

        # Правая карточка: переключатель «История чата / Системные логи»
        right, right_lay = card()
        right_lay.setSpacing(10)
        self.right_switch = SegmentedControl(["История чата", "Системные логи"])
        right_lay.addWidget(self.right_switch)

        self.right_stack = QStackedWidget()
        self.tab_widget = self.right_stack  # совместимость: прежнее имя (есть currentIndex)

        # Страница истории чата
        chat_page = QWidget()
        chat_layout = QVBoxLayout(chat_page)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(8)

        chat_control_layout = QHBoxLayout()
        chat_control_layout.setSpacing(12)
        self.auto_scroll_checkbox = SwitchRow("Автопрокрутка", True, compact=True)
        self.auto_scroll_checkbox.setToolTip("Автопрокрутка\nПоказывать самые новые сообщения сверху при обновлении истории.")
        self.auto_scroll_checkbox.toggled.connect(self.toggle_auto_scroll)
        chat_control_layout.addWidget(self.auto_scroll_checkbox)
        chat_control_layout.addStretch(1)

        self.message_filter_combo = FxComboBox()
        self.message_filter_combo.addItems(["Обычные", "Секретарь", "Сводки", "Контекст", "Всё"])
        self.message_filter_combo.setToolTip("Фильтр сообщений\nОбычные, переписка секретаря, сводки истории, контекст или всё сразу.")
        self.message_filter_combo.currentIndexChanged.connect(self.filter_messages)
        chat_control_layout.addWidget(self.message_filter_combo)
        chat_layout.addLayout(chat_control_layout)

        self.group_addressed_only_checkbox = SwitchRow("Только обращения", True, compact=True)
        self.group_addressed_only_checkbox.setToolTip(
            "Только обращения\n"
            "Показывать только обращения к боту, его ответы и сводки. "
            "Выключите, чтобы увидеть все сохранённые сообщения группы."
        )
        self.group_addressed_only_checkbox.setVisible(False)
        self.group_addressed_only_checkbox.toggled.connect(lambda _on: self.update_message_history())
        chat_layout.addWidget(self.group_addressed_only_checkbox)

        self.history_text = QTextEdit()
        self.history_text.setReadOnly(True)
        self.history_text.setPlaceholderText("Выберите пользователя или группу слева, чтобы увидеть историю чата.")
        chat_layout.addWidget(self.history_text, 1)

        # Страница системных логов
        logs_page = QWidget()
        logs_layout = QVBoxLayout(logs_page)
        logs_layout.setContentsMargins(0, 0, 0, 0)
        logs_layout.setSpacing(8)

        logs_control_layout = QHBoxLayout()
        logs_control_layout.setSpacing(12)
        self.logs_auto_scroll = SwitchRow("Автопрокрутка", True, compact=True)
        self.logs_auto_scroll.setToolTip("Автопрокрутка\nПоказывать самые новые записи журнала сверху.")
        logs_control_layout.addWidget(self.logs_auto_scroll)
        logs_control_layout.addStretch(1)
        self.clear_logs_button = FxButton("Очистить")
        self.clear_logs_button.setToolTip("Очистить журнал\nУбирает записи из окна. Файлы логов на диске не затрагиваются.")
        self.clear_logs_button.clicked.connect(self.clear_logs)
        logs_control_layout.addWidget(self.clear_logs_button)
        logs_layout.addLayout(logs_control_layout)

        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        # Без горизонтального скролла: перенос по ширине
        self.logs_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.logs_text.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.logs_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Системный моноширинный шрифт (Consolas/Cascadia на Windows, DejaVu Sans Mono на Linux)
        self.logs_text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        logs_layout.addWidget(self.logs_text, 1)

        self.right_stack.addWidget(chat_page)
        self.right_stack.addWidget(logs_page)
        right_lay.addWidget(self.right_stack, 1)
        self.right_switch.changed.connect(self._on_right_switched)

        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self._left_card, self._right_card = left, right
        root.addWidget(self.splitter, 1)

        # Привязка событий
        self.groups_table.cellClicked.connect(self.display_group_history)
        self.users_table.cellClicked.connect(self.display_user_history)
        self.toggle_server_button.clicked.connect(self.toggle_server)

        # Загрузка пользователей и обновление статистики при инициализации
        self.load_users()
        self.load_group_chats()
        self.update_stats()

    # ───────────────────────── вспомогательное для оформления ─────────────────────────
    def _make_entity_table(self, headers):
        """Таблица пользователей/групп: имя тянется, остальные колонки — по содержимому/фиксированно."""
        table = make_table(headers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.verticalHeader().setDefaultSectionSize(50)  # QSS даёт ячейке отступ 6px сверху/снизу
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for column, width in ((2, COL_PRIORITY_W), (3, COL_STATUS_W), (4, COL_ACTION_W)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(column, width)
        return table

    @staticmethod
    def _cell_holder(widget, align=Qt.AlignmentFlag.AlignLeft):
        """Оборачивает виджет в ячейку таблицы с отступами и выравниванием по центру строки."""
        holder = QWidget()
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(widget, 0, align | Qt.AlignmentFlag.AlignVCenter)
        return holder

    def _ban_badge_cell(self, banned):
        badge = StatusBadge('Забанен' if banned else 'Активен', 'error' if banned else 'ok', pulse=False)
        return self._cell_holder(badge)

    def _ban_button_cell(self, banned, handler):
        button = FxButton('Разбан' if banned else 'Бан')
        if not banned:
            button.setObjectName("danger")
        button.setToolTip(
            ("Разбанить\nСнова разрешить доступ к боту." if banned
             else "Забанить\nБот перестанет отвечать, пока доступ не вернут.")
        )
        button.clicked.connect(handler)
        return self._cell_holder(button)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        # На узком окне таблица и история встают друг под другом — иначе колонки не помещаются
        wide = self.splitter.width() >= SIDE_BY_SIDE_MIN_WIDTH
        wanted = Qt.Orientation.Horizontal if wide else Qt.Orientation.Vertical
        if self.splitter.orientation() != wanted or not self._splitter_sized:
            self._splitter_sized = True
            self.splitter.setOrientation(wanted)
            if wide:
                self._left_card.setMinimumSize(SIDE_LEFT_MIN_W, 0)
                self._right_card.setMinimumSize(SIDE_RIGHT_MIN_W, 0)
                total = max(self.splitter.width(), 1)
                self.splitter.setSizes([total * 6 // 10, total * 4 // 10])
            else:
                self._left_card.setMinimumSize(0, 232)
                self._right_card.setMinimumSize(0, 200)
                total = max(self.splitter.height(), 1)
                self.splitter.setSizes([total // 2, total // 2])

    def eventFilter(self, obj, event):  # noqa: N802
        # Клик по плитке метрики открывает окно статистики
        if (obj in getattr(self, "_tiles", ()) and event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton):
            QTimer.singleShot(0, self.show_full_stats)
        return super().eventFilter(obj, event)

    def _on_entities_switched(self, index):
        self.entities_stack.setCurrentIndex(index)
        self._refresh_visible_entity_list()

    def _on_right_switched(self, index):
        self.right_stack.setCurrentIndex(index)
        self._handle_right_tab_changed(index)

    def _refresh_if_visible(self):
        if not self.isVisible():
            return
        self._refresh_visible_entity_list()
        self.update_stats()

    def setup_timers(self):
        # Таймер для обновления пользователей и статистики каждые 5 секунд
        self.update_timer = QTimer()
        # Не дёргаем БД и не перерисовываем таблицы, пока вкладка скрыта
        self.update_timer.timeout.connect(self._refresh_if_visible)
        self.update_timer.start(5000)  # 5000 мс = 5 секунд

        # Таймер для обновления истории сообщений каждые 5 секунд
        self.history_timer = QTimer()
        self.history_timer.timeout.connect(
            lambda: self.isVisible() and self.update_message_history()
        )
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
        if self.entities_stack.currentIndex() == 0:
            self.load_users()
        else:
            self.load_group_chats()

    def _handle_right_tab_changed(self, index):
        if index == 0 and (self.current_user_id is not None or self.current_chat_id is not None):
            self.update_message_history()

    def load_users(self):
        try:
            users = self.user_service.get_all_users()
            # Данные не менялись — не пересоздаём таблицу (сохраняем фокус/выделение)
            snapshot = repr(users)
            if snapshot == getattr(self, '_users_snapshot', None):
                return
            self._users_snapshot = snapshot
            self.users_table.setUpdatesEnabled(False)
            self.users_table.setRowCount(0)
            for row_number, user in enumerate(users):
                self.users_table.insertRow(row_number)
                username = user.get('username') or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                self.users_table.setItem(row_number, 0, QTableWidgetItem(username))
                self.users_table.setItem(row_number, 1, QTableWidgetItem(str(user['telegram_id'])))

                # Приоритет: обычный QSpinBox, значение сохраняется сразу при изменении
                priority_spinbox = QSpinBox()
                priority_spinbox.setRange(0, 10)
                priority_spinbox.setValue(user['priority'])
                priority_spinbox.setToolTip("Приоритет\nЧем больше число, тем раньше бот обрабатывает запросы пользователя. Сохраняется сразу.")
                priority_spinbox.valueChanged.connect(partial(self.change_user_priority, user['id']))
                self.users_table.setCellWidget(row_number, 2, self._cell_holder(priority_spinbox))

                # Статус бана и кнопка действия (Бан/Разбан)
                banned = bool(user['is_banned'])
                self.users_table.setCellWidget(row_number, 3, self._ban_badge_cell(banned))
                self.users_table.setCellWidget(
                    row_number, 4, self._ban_button_cell(banned, partial(self.toggle_ban_user, user)))

            if self.current_user_id is not None:
                target = str(self.current_user_id)
                for row in range(self.users_table.rowCount()):
                    if self.users_table.item(row, 1) and self.users_table.item(row, 1).text() == target:
                        self.users_table.selectRow(row)
                        break
        except Exception as e:
            self._users_snapshot = None
            logger.error(f"Ошибка загрузки пользователей: {e}")
        finally:
            self.users_table.setUpdatesEnabled(True)

    def load_group_chats(self):
        try:
            chats = self.user_service.get_group_chats()
            snapshot = repr(chats)
            if snapshot == getattr(self, '_chats_snapshot', None):
                return
            self._chats_snapshot = snapshot
            self.groups_table.setUpdatesEnabled(False)
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

                banned = bool(chat['is_banned'])
                self.groups_table.setCellWidget(row_number, 3, self._ban_badge_cell(banned))
                self.groups_table.setCellWidget(
                    row_number, 4, self._ban_button_cell(banned, partial(self.toggle_ban_group, chat)))

            if self.current_chat_id is not None:
                target = str(self.current_chat_id)
                for row in range(self.groups_table.rowCount()):
                    if self.groups_table.item(row, 1) and self.groups_table.item(row, 1).text() == target:
                        self.groups_table.selectRow(row)
                        break

        except Exception as e:
            self._chats_snapshot = None
            logger.error(f"Ошибка загрузки групповых чатов: {e}")
        finally:
            self.groups_table.setUpdatesEnabled(True)

    def display_user_history(self, row, column):
        user_id_item = self.users_table.item(row, 1)  # Используем Telegram ID
        if user_id_item:
            telegram_id = int(user_id_item.text())
            self.current_user_id = telegram_id
            self.current_chat_id = None
            self.current_chat_title = None
            self.current_chat_type = 'private'
            # Сбрасываем счётчики при выборе нового пользователя
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
            # Сбрасываем счётчики при выборе нового чата
            self._last_message_count = -1
            self._last_filter_index = -1
            self._last_history_signature = None

            self.users_table.clearSelection()
            self.groups_table.selectRow(row)
            self.group_addressed_only_checkbox.setVisible(True)
            self.update_message_history()


    def toggle_server(self):
        # Проверяем по тексту кнопки (её переключают и сигналы bot_thread через admin_panel_base)
        if self.toggle_server_button.text() == 'Остановить сервер':
            # Начало процесса остановки
            logger.info("Инициирована остановка сервера через GUI...")
            server_state.server_active = False
            
            # Меняем состояние кнопки на переходное
            self.show_status_message('Останавливается…')
            self.toggle_server_button.setText('Останавливается…')
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
            
            # Мгновенный фидбек: Меняем состояние кнопки сразу
            self.show_status_message('Запуск сервера…')
            self.toggle_server_button.setText('Запуск…')
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
                
                warn(self, "Невалидные настройки", error_msg)
                logger.warning(f"Запуск сервера отменен - невалидные настройки: {', '.join(errors)}")
                
                # Возвращаем кнопку в исходное состояние
                self.toggle_server_button.setText('Запустить сервер')
                self.toggle_server_button.setEnabled(True)
                self._show_steady_status()
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
                    self._show_steady_status()
                else:
                    # UI обновится через сигналы от bot_thread (handle_bot_started)
                    logger.info("Умный запуск сервера успешен")
                    
                    # Обновляем статистику сеанса
                    # Используем правильный метод для сброса статистики
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
                # Используем правильный метод для сброса статистики
                if hasattr(stats, 'stats'):
                    stats.stats.reset()
                self.session_start_time = datetime.datetime.now()
                logger.info(f"Сеанс начат в {self.session_start_time}")

    def toggle_ban_user(self, user):
        try:
            # Используем UserService
            self.user_service.toggle_user_ban(user)
            self.load_users()  # Обновляем список после изменения
        except Exception as e:
            logger.error(f"Ошибка при изменении статуса бана пользователя: {e}")

    def toggle_ban_group(self, chat):
        try:
            # Используем UserService
            self.user_service.toggle_group_ban(chat)
            self.load_group_chats() # Обновляем список после изменения
        except Exception as e:
            logger.error(f"Ошибка при изменении статуса бана группы: {e}")

    def change_user_priority(self, user_id, new_priority):
        try:
            # Используем UserService
            self.user_service.change_user_priority(user_id, new_priority)
        except Exception as e:
            logger.error(f"Ошибка при изменении приоритета пользователя {user_id}: {e}")

    def update_stats(self):
        try:
            self._sync_refresh_intervals()
            total_users = self.user_service.count_total_users()
            online_users = self.user_service.count_online_users()
            input_tokens = self.stats_service.get_input_tokens_total()
            output_tokens = self.stats_service.get_output_tokens_total()

            self._set_tile(self.tile_online, f"{online_users}/{total_users}")
            self._set_tile(self.tile_requests, str(self.stats_service.get_request_count()))
            self._set_tile(self.tile_pending, str(self.stats_service.get_pending_requests()))
            self._set_tile(self.tile_tokens, self._format_stat_value(input_tokens + output_tokens, compact=True))

            # Статус наверстывания истории
            if server_state.is_catching_up:
                self.backlog_label.text = f"Наверстывание: {server_state.backlog_processed_count}"
                self.backlog_label.updateGeometry()
                self.backlog_label.update()
                self.backlog_label.setToolTip(
                    "Наверстывание истории\n"
                    f"Обработано {server_state.backlog_processed_count} пропущенных сообщений. Бот догоняет текущее время."
                )
                self.backlog_label.setVisible(True)
            else:
                self.backlog_label.setVisible(False)

        except Exception as e:
            logger.error(f"Ошибка обновления статистики: {e}")

    @staticmethod
    def _set_tile(tile, value: str):
        """Обновляет число в плитке без повторной анимации «набегания»."""
        if tile.num.text() == value:
            return
        tile._count.stop()
        tile._text = value
        tile._target = int(value) if value.isdigit() else None
        tile.num.setText(value)

    def _format_stat_value(self, value, compact=True):
        """Форматирует числа. compact=True (1.5k), compact=False (1 500)."""
        if not isinstance(value, (int, float)):
            try:
                value = int(value)
            except (TypeError, ValueError):
                return str(value)
        
        if compact:
            if value >= 1000000:
                return f"{value/1000000:.1f}M".replace(".0M", "M")
            if value >= 1000:
                return f"{value/1000:.1f}k".replace(".0k", "k")
            return f"{value:,}".replace(",", " ")
        
        # Полный формат с разделителем тысяч (пробел)
        return f"{value:,}".replace(",", " ")

    # ───────────────────────── окно статистики ─────────────────────────
    def _create_stat_row(self, caption: str, value: str) -> QWidget:
        """Строка статистики: приглушённая подпись слева, значение справа."""
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 3, 0, 3)
        lay.addWidget(label(caption, "muted"))
        lay.addStretch()
        lay.addWidget(label(value, "h2"))
        return row

    def _create_stats_section(self, title: str, rows: list) -> QWidget:
        """Секция-карточка статистики с заголовком и строками."""
        section, lay = card()
        lay.setSpacing(6)
        lay.addWidget(label(title.upper(), "sectionLabel"))
        for row in rows:
            lay.addWidget(row)
        lay.addStretch()
        return section

    @staticmethod
    def _fmt_hms(seconds) -> str:
        total = int(round(seconds or 0))
        return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"

    def _build_voice_stats_card(self, v: dict) -> QWidget:
        """Карточка «Звук»: распознанные голосовые/кружки, пустые, ошибки, длительность, движки."""
        if not v or not v.get("total"):
            return self._create_stats_section("Звук", [label("Нет данных", "muted")])
        fmt = lambda n: self._format_stat_value(n, compact=False)
        rows = [
            self._create_stat_row("Голосовых", fmt(v["voice"])),
            self._create_stat_row("Кружков", fmt(v["video_note"])),
            self._create_stat_row("Пустых / ошибок", f'{fmt(v["empty"])} / {fmt(v["error"])}'),
            self._create_stat_row("Длительность", self._fmt_hms(v["duration_sec"])),
        ]
        engines = v.get("engines") or {}
        if engines:
            rows.append(self._create_stat_row("Движки", ", ".join(f"{k} {n}" for k, n in engines.items())))
        since = str(v.get("since") or "")[:10]
        note = label(f"За последние {v['total']} записей" + (f" (с {since})" if since else ""), "muted")
        rows.append(note)
        return self._create_stats_section("Звук", rows)

    def _build_usage_stats_card(self, u: dict) -> QWidget:
        """Карточка «Чем пользовались»: топ MCP, события секретаря, режимы сообщений."""
        u = u or {}
        rows = []
        mcp = u.get("mcp_top") or []
        sec = u.get("secretary_events") or {}
        modes = u.get("message_modes") or {}
        if not (mcp or sec or modes):
            return self._create_stats_section("Чем пользовались", [label("Нет данных", "muted")])
        fmt = lambda n: self._format_stat_value(n, compact=False)
        if mcp:
            table = make_table(["MCP-инструмент", "Вызовов", "Ошибок"], [
                [f"{m['server']}/{m['tool']}", fmt(m["calls"]), f"{round(100 * m['errors'] / m['calls'])}%"]
                for m in mcp
            ])
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            table.verticalHeader().setDefaultSectionSize(26)
            table.horizontalHeader().setFixedHeight(30)
            table.setFixedHeight(30 + 26 * len(mcp) + 4)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            rows.append(table)
        else:
            rows.append(self._create_stat_row("MCP-вызовы", "Нет данных"))
        rows.append(self._create_stat_row(
            "Секретарь", ", ".join(f"{k} {n}" for k, n in sec.items()) if sec else "Нет данных"))
        rows.append(self._create_stat_row(
            "Сообщения", ", ".join(f"{k} {n}" for k, n in modes.items()) if modes else "Нет данных"))
        return self._create_stats_section("Чем пользовались", rows)

    def _build_model_usage_card(self, m: dict) -> QWidget:
        """Карточка «Токены по моделям»: запросы, входные и выходные токены (старые записи — «не указана»)."""
        models = (m or {}).get("models") or []
        if not models:
            return self._create_stats_section("Токены по моделям", [label("Нет данных", "muted")])
        fmt = lambda n: self._format_stat_value(n, compact=False)
        table = make_table(["Модель", "Запросов", "Вход", "Выход"], [
            [r["model"] or "не указана", fmt(r["requests"]), fmt(r["input"]), fmt(r["output"])]
            for r in models
        ])
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.verticalHeader().setDefaultSectionSize(26)
        table.horizontalHeader().setFixedHeight(30)
        table.setFixedHeight(30 + 26 * len(models) + 4)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rows = [table]
        if m.get("more"):
            rows.append(label(f"И ещё моделей: {m['more']}", "muted"))
        return self._create_stats_section("Токены по моделям", rows)

    def show_full_stats(self):
        """Показывает окно со статистикой сеанса и историей прошлых сеансов."""
        try:
            total_users = self.user_service.count_total_users()
            online_users = self.user_service.count_online_users()
            data = self.stats_service.get_all_current_stats()

            dialog = FxDialog(self, "Статистика")
            dialog.setMinimumSize(760 + 40, 480 + 40)
            dialog.resize_content(880, 640)

            # Контент в прокручиваемой области: блоков стало больше, окно не должно выходить за экран
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
            inner = QWidget()
            scroll.setWidget(inner)
            dialog.body.addWidget(scroll, 1)
            main_layout = QVBoxLayout(inner)
            main_layout.setContentsMargins(0, 0, 6, 0)
            main_layout.setSpacing(14)
            main_layout.addLayout(page_header("Статистика", "Счётчики текущего сеанса и история прошлых запусков"))

            avg_wait_str = self.stats_service._format_time(data["avg_wait_time"])
            avg_resp_str = self.stats_service._format_time(data["avg_response_time"])

            sections = QHBoxLayout()
            sections.setSpacing(14)
            sections.addWidget(self._create_stats_section("Пользователи", [
                self._create_stat_row("Онлайн", f"{online_users}/{total_users}"),
                self._create_stat_row("Запросов", str(data["request_count"])),
                self._create_stat_row("В очереди", str(data["pending_requests"])),
            ]), 1)
            sections.addWidget(self._create_stats_section("Производительность", [
                self._create_stat_row("Ожидание", avg_wait_str),
                self._create_stat_row("Ответ", avg_resp_str),
            ]), 1)
            sections.addWidget(self._create_stats_section("Токены", [
                self._create_stat_row("Входные", self._format_stat_value(data['input_tokens'], compact=False)),
                self._create_stat_row("Выходные", self._format_stat_value(data['output_tokens'], compact=False)),
                self._create_stat_row("Всего", self._format_stat_value(data['total_tokens'], compact=False)),
            ]), 1)
            main_layout.addLayout(sections)

            # Звук и «чем пользовались» — данные из БД, грузим при открытии окна
            extra = QHBoxLayout()
            extra.setSpacing(14)
            extra.addWidget(self._build_voice_stats_card(self.stats_service.get_voice_stats()), 1)
            extra.addWidget(self._build_usage_stats_card(self.stats_service.get_usage_stats()), 1)
            main_layout.addLayout(extra)
            main_layout.addWidget(self._build_model_usage_card(self.stats_service.get_usage_by_model()))

            # История сеансов
            history_card, history_layout = card()
            history_layout.addWidget(label("История сеансов", "h2"))

            past_sessions = self.stats_service.get_past_sessions(limit=5)
            total_sessions = self.stats_service.get_total_sessions_count()

            if past_sessions:
                body = QHBoxLayout()
                body.setSpacing(14)
                rows = []
                for session in past_sessions:
                    start = session.get("start", "—")
                    if len(start) > 16:
                        start = start[:16]  # обрезаем дату до часа:минуты
                    duration = session.get("duration", "—")
                    if "." in duration:
                        duration = duration.split(".")[0]
                    rows.append([start, duration, str(session.get("requests", 0)), session.get("avg_response", "—")])
                history_table = make_table(["Дата", "Длит.", "Запросы", "Ср. отв."], rows)
                history_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
                history_table.verticalHeader().setDefaultSectionSize(36)
                history_table.setMinimumHeight(150)
                body.addWidget(history_table, 3)

                # Панель управления историей
                file_column = QVBoxLayout()
                file_column.setSpacing(8)
                file_column.addWidget(label("СЕАНСЫ", "sectionLabel"))
                file_column.addWidget(label(f"Всего сохранено: {total_sessions}", "muted"))
                file_column.addSpacing(6)

                open_file_btn = icon_button("Открыть", "mdi6.file-document-outline")
                open_file_btn.setToolTip("Открыть session_stats.txt\nФайл со статистикой завершённых сеансов откроется в редакторе по умолчанию.")
                open_file_btn.clicked.connect(self._open_session_stats_file)
                open_file_btn.setEnabled(self.stats_service.session_stats_exist())
                file_column.addWidget(open_file_btn)

                reset_btn = icon_button("Сбросить", "mdi6.restore", "danger")
                reset_btn.setToolTip("Сбросить счётчики\nОбнуляет статистику текущего сеанса. История прошлых сеансов не затрагивается.")
                reset_btn.clicked.connect(lambda: self._reset_session_stats(dialog))
                file_column.addWidget(reset_btn)
                file_column.addStretch(1)
                body.addLayout(file_column, 1)
                history_layout.addLayout(body, 1)
            else:
                history_layout.addStretch(1)
                empty = label("Нет сохранённых сеансов", "muted")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                history_layout.addWidget(empty)
                history_layout.addStretch(1)
                reset_btn = icon_button("Сбросить текущий сеанс", "mdi6.restore", "danger")
                reset_btn.clicked.connect(lambda: self._reset_session_stats(dialog))
                history_layout.addWidget(reset_btn, 0, Qt.AlignmentFlag.AlignRight)

            history_card.setMinimumHeight(230)
            main_layout.addWidget(history_card, 1)
            dialog.exec()

        except Exception as e:
            logger.error(f"Ошибка отображения полной статистики: {e}")
            warn(self, "Ошибка", f"Не удалось показать статистику: {e}")

    # ───────────────────────── статус сервера ─────────────────────────
    def _steady_status_text(self) -> str:
        """«Постоянный» статус по состоянию кнопки сервера."""
        text = self.toggle_server_button.text()
        if text == 'Остановить сервер':
            return 'Сервер запущен'
        if text.startswith('Запуск'):
            return 'Запуск сервера…'
        if text.startswith('Останавлива'):
            return 'Останавливается…'
        return 'Сервер остановлен'

    def _show_steady_status(self):
        self.status_label.setText(self._steady_status_text())
        self.status_label.setVisible(True)

    def show_status_message(self, message: str, timeout: int = 5000):
        """Показывает временное сообщение в бейдже статуса; по таймеру он возвращается к состоянию сервера."""
        self.status_label.setText(message)
        self.status_label.setVisible(True)
        self.status_timer.start(timeout)

    def _open_session_stats_file(self):
        """Открывает файл session_stats.txt в системном редакторе."""
        try:
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl

            file_path = self.stats_service.get_session_stats_path()
            
            if not file_path.exists():
                inform(
                    self,
                    "Файл не найден",
                    "Файл session_stats.txt ещё не создан.\n"
                    "Он появится после первого завершения сеанса.\n\n"
                    f"Ожидаемый путь:\n{file_path}",
                )
                return
            
            # Системный редактор по умолчанию: Windows, Linux (xdg-open) и macOS
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path.resolve()))):
                warn(
                    self,
                    "Не удалось открыть файл",
                    f"В системе не найдено приложение для .txt.\n\nФайл лежит здесь:\n{file_path}",
                )
        except Exception as e:
            logger.error(f"Ошибка при открытии файла статистики: {e}")
            warn(self, "Ошибка", f"Не удалось открыть файл: {e}")

    def _reset_session_stats(self, dialog: QDialog):
        """Сбрасывает статистику текущего сеанса (с подтверждением)."""
        if ask(
            dialog,
            "Сброс статистики",
            "Сбросить счётчики текущего сеанса?\n\nИстория предыдущих сеансов не будет затронута.",
            yes="Сбросить",
            danger=True,
        ):
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
        self._refresh_theme_formats()
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

            # Используем UserService для получения сообщений
            if self.current_user_id is not None:
                context_kind = "user"
                # Используем UserService
                user = self.user_service.get_user_by_telegram_id(self.current_user_id)
                if user:
                    username = user.get('username') or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                    # Используем UserService для получения истории
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
                # Используем UserService для получения активных сообщений группы
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

            # Проверяем нужно ли перезаписывать историю
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

                # Ограничиваем длину контента для очень длинных сообщений
                MAX_CONTENT_LENGTH = 5000  # Максимум символов на сообщение
                
                for msg in reversed(filtered_messages):
                    role = msg['role']
                    content = msg.get('content', '') or ""
                    content_type = (msg.get('content_type') or 'text').lower()

                    format_key = role if role in self.message_formats else "system"
                    lower_content = content.lower()
                    if "ошибка" in lower_content or "error" in lower_content:
                        format_key = "error"

                    # Обработка сводок (is_summary)
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

                    # Добавляем индикаторы для отредактированных и удалённых сообщений
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

                    # Обрезаем очень длинные сообщения
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

            # Автопрокрутка только если включена и пользователь не прокрутил вверх
            if self.auto_scroll_enabled or near_top:
                scrollbar.setValue(scrollbar.minimum())
            else:
                scrollbar.setValue(current_value)

        except Exception as e:
            logger.error(f"Ошибка обновления истории сообщений: {e}")
            cursor = self.history_text.textCursor()
            cursor.insertText(f"ОШИБКА: {str(e)}\n\n", self.message_formats["error"])

    MAX_LOG_ENTRIES = 2000
    MAX_LOG_BLOCKS = 2 * MAX_LOG_ENTRIES + 2  # запас: запись = блок текста + пустой блок

    def clear_logs(self):
        self._log_entries.clear()
        self.logs_text.clear()

    @staticmethod
    def _split_log_message(message):
        """Разбор строки формата «ts - LEVEL - logger - msg» на части (None, если формат иной)."""
        parts = message.split(" - ", 3)
        if len(parts) == 4:
            return tuple(parts)
        return None, None, None, message

    def _insert_log_entry(self, cursor, entry):
        """Вставляет одну запись в начало документа; цвета берутся из токенов текущей темы."""
        level, ts, lvl, name, msg = entry
        t = current_tokens()
        time_fmt = QTextCharFormat()
        time_fmt.setForeground(QColor(t["text_muted"]))

        level_fmt = QTextCharFormat(self.log_handler.log_formats.get(level, QTextCharFormat()))
        level_fmt.setFontWeight(QFont.Weight.Bold)

        name_fmt = QTextCharFormat()
        name_fmt.setForeground(QColor(t["info"]))
        name_fmt.setFontItalic(True)

        msg_fmt = QTextCharFormat()
        if level >= logging.ERROR:
            msg_fmt.setForeground(QColor(t["danger"]))

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

    def _rerender_logs_for_theme(self, *_args):
        """Смена темы: пересоздаём форматы и перерисовываем весь накопленный буфер новыми цветами."""
        try:
            key = self._theme_key()
            if key == self._log_theme_key:
                return
            self._log_theme_key = key
            self.log_handler.init_formats()
            self.logs_text.setUpdatesEnabled(False)
            try:
                scrollbar = self.logs_text.verticalScrollBar()
                position = scrollbar.value()
                self.logs_text.clear()
                cursor = self.logs_text.textCursor()
                # Буфер хранится от старых к новым; вставка в начало даёт «новые сверху»
                for entry in self._log_entries:
                    self._insert_log_entry(cursor, entry)
                scrollbar.setValue(position)
            finally:
                self.logs_text.setUpdatesEnabled(True)
        except Exception as e:
            logger.error(f"Ошибка перекраски журнала: {e}")

    def update_logs(self):
        try:
            # Цвета могли устареть после смены темы (если сигнал не дошёл)
            if self._theme_key() != self._log_theme_key:
                self._rerender_logs_for_theme()

            logs = self.log_handler.get_logs()
            if not logs:
                return

            # Сохраняем текущую позицию скролла и близость к верху
            scrollbar = self.logs_text.verticalScrollBar()
            current_position = scrollbar.value()
            near_top = (current_position - scrollbar.minimum()) <= 50

            cursor = self.logs_text.textCursor()
            for level, message in logs:
                ts, lvl, name, msg = self._split_log_message(message)
                entry = (level, ts, lvl, name, msg)
                self._log_entries.append(entry)  # deque(maxlen) сам отбрасывает самые старые
                self._insert_log_entry(cursor, entry)

            # Ограничиваем размер журнала: новые записи сверху, старые отрезаем снизу
            # (setMaximumBlockCount тут не подходит — он удаляет с начала документа)
            doc = self.logs_text.document()
            if doc.blockCount() > self.MAX_LOG_BLOCKS:
                tail = QTextCursor(doc.findBlockByNumber(self.MAX_LOG_BLOCKS))
                tail.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
                tail.removeSelectedText()

            # Логика автопрокрутки: новые логи сверху
            if self.logs_auto_scroll.isChecked() or near_top:
                scrollbar.setValue(scrollbar.minimum())
            else:
                scrollbar.setValue(current_position)
        except KeyboardInterrupt:
            logger.info("Остановка обновления логов (KeyboardInterrupt)")
        except Exception as e:
            logger.error(f"Ошибка обновления логов: {e}")
