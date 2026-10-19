# gui/admin_panel/admin_panel_base.py

from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)
from PyQt6.QtCore import QSize, QTimer
from gui.admin_panel.user_management import UserManagement
from gui.admin_panel.settings_panel import SettingsPanel  # Импортируем ваш реальный SettingsPanel
from gui.admin_panel.voice_settings_tab import VoiceSettingsTab
from gui.admin_panel.voice_history_tab import VoiceHistoryTab
from gui.admin_panel.extra_settings_tab import ExtraSettingsTab
from gui.admin_panel.mcp_tab import McpTab
from gui.admin_panel.secretary_tab import SecretaryTab
from gui.design import appearance, icons, motion
from gui.design.shell import FrameController, TitleBar, prepare_translucent
from gui.design.widgets import GlowRoot, label
from gui.splash_screen import APP_VERSION
from bot.handlers.services.mcp_runtime import stop_all_server_processes
from utils import server_state
from utils.logger import setup_logger
import datetime

logger = setup_logger(__name__)

SIDEBAR_WIDTH = 224


class AdminPanelBase(QMainWindow):
    def __init__(self, bot_thread):
        super().__init__()
        self.bot_thread = bot_thread
        self._closing = False
        self.init_ui()
        self.setup_bot_signals()

    def init_ui(self):
        self.setWindowTitle('SnapMatch')
        self.resize(1180, 900)
        self.setMinimumSize(960, 720)
        # Прозрачность окна включается ДО первого show() и остаётся всегда (иначе на Wayland не будет
        # альфа-канала и у скруглённой рамки останутся квадратные уголки). Без собственной рамки корень
        # рисует непрозрачный фон.
        prepare_translucent(self)

        # Корень рисует фон окна, полосу боковой панели и скругление; панель и заголовок прозрачные
        self.root = GlowRoot()
        self.root.setObjectName("root")
        self.root.sidebar_w = SIDEBAR_WIDTH
        self.setCentralWidget(self.root)
        outer = QVBoxLayout(self.root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.titlebar = TitleBar(self)
        outer.addWidget(self.titlebar)
        self.frame = FrameController(self, self.root, self.titlebar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # Боковая панель: бренд, навигация, версия
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(SIDEBAR_WIDTH)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 14)
        sl.addWidget(label("SnapMatch", "brand"))
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(20, 20))
        sl.addWidget(self.nav, 1)
        sl.addWidget(label(f"v{APP_VERSION}", "muted"))
        body.addWidget(side)

        self.pages = motion.FadeStack()
        body.addWidget(self.pages, 1)
        self.toast = motion.Toast(self.root)
        self._nav_icons: list[str] = []

        # Страницы — существующие вкладки (их внутренности переносятся на новый дизайн поэтапно)
        self.user_management = UserManagement(self.bot_thread)
        self.add_page("Пользователи", "mdi6.account-group-outline", self.user_management)

        # Панель настроек (передаем bot_thread)
        self.settings_panel = SettingsPanel(self.bot_thread)
        self.add_page("Настройки", "mdi6.tune-variant", self.settings_panel)

        self.voice_tab = VoiceSettingsTab(self)
        self.add_page("Голос", "mdi6.microphone-outline", self.voice_tab)

        # История расшифровок голосовых и кружочков
        self.voice_history_tab = VoiceHistoryTab(self)
        self.add_page("Расшифровки", "mdi6.text-recognition", self.voice_history_tab)

        self.extra_tab = ExtraSettingsTab(self)
        self.add_page("Доп. настройки", "mdi6.cog-outline", self.extra_tab)

        self.mcp_tab = McpTab(self)
        self.add_page("MCP", "mdi6.puzzle-outline", self.mcp_tab)

        self.secretary_tab = SecretaryTab(self)
        self.add_page("Секретарь", "mdi6.briefcase-outline", self.secretary_tab)

        # Подсветка-«пилюля» выбранного пункта навигации
        self.indicator = motion.NavIndicator(self.nav.viewport())
        self.nav.currentRowChanged.connect(self._on_nav)
        self.nav.setCurrentRow(0)
        QTimer.singleShot(0, lambda: self._move_indicator(animate=False))

        # Оформление: применяем до показа окна, дальше слушаем смену темы и рамки
        self.appearance = appearance.controller()
        self.appearance.changed.connect(self._on_appearance_changed)
        self.appearance.frameless_changed.connect(self.frame.set_frameless)
        self.apply_theme()
        self.frame.set_frameless(self.appearance.settings["ui_frameless"])

        # Инициализируем статус сервера
        self.initialize_server()
        # Старые вкладки: после показа подгоняем кнопки под текст (пока их не перенесли на FxButton)
        QTimer.singleShot(0, self._fit_buttons_to_text)

    def _fit_buttons_to_text(self):
        """Снимает жёсткие ограничения ширины, из-за которых текст кнопок обрезался."""
        for button in self.findChildren(QPushButton):
            if not button.text():
                continue  # стрелки спинбоксов и иконочные кнопки не трогаем
            needed = button.sizeHint().width() + 8
            if button.maximumWidth() < needed:
                button.setMaximumWidth(16777215)
            if button.minimumWidth() < needed:
                button.setMinimumWidth(needed)

    # ── навигация ──
    def add_page(self, title: str, icon_name: str, widget: QWidget) -> int:
        """Добавляет экран: пункт боковой навигации + страница в FadeStack. Возвращает индекс."""
        item = QListWidgetItem(icons.nav_icon(icon_name), title, self.nav)
        item.setToolTip(title)
        self._nav_icons.append(icon_name)
        return self.pages.addWidget(widget)

    def show_page(self, page) -> None:
        """Переключает экран по индексу или по виджету-странице."""
        index = page if isinstance(page, int) else self.pages.indexOf(page)
        if index >= 0:
            self.nav.setCurrentRow(index)

    def _on_nav(self, row: int) -> None:
        if row >= 0:
            self.pages.setCurrentIndex(row)
            self._move_indicator()

    def _move_indicator(self, animate: bool = True) -> None:
        item = self.nav.currentItem()
        if item is not None:
            self.indicator.move_to(self.nav.visualItemRect(item), animate)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.toast.hide()
        QTimer.singleShot(0, lambda: self._move_indicator(animate=False))

    # ── оформление ──
    def _on_appearance_changed(self, _tokens):
        for i, name in enumerate(self._nav_icons):
            self.nav.item(i).setIcon(icons.nav_icon(name))
        self.root.update()

    def apply_theme(self):
        """Тонкая обёртка над новой системой оформления: (пере)применяет тему из настроек ко всему приложению.
        Оставлена для обратной совместимости (её вызывают вкладки после сохранения настроек)."""
        self.appearance.settings = appearance.load_settings()
        self.appearance.apply()

    def setup_bot_signals(self):
        """Настройка сигналов от bot_thread"""
        self.bot_thread.restart_needed_signal.connect(self.handle_bot_restart)
        self.bot_thread.started_signal.connect(self.handle_bot_started)
        self.bot_thread.stopped_signal.connect(self.handle_bot_stopped)
        self.bot_thread.startup_failed_signal.connect(self.handle_bot_startup_failed)

    def handle_bot_restart(self):
        """Обработка перезапуска бота"""
        logger.info("Получен сигнал о необходимости перезапуска бота")
        
        # Сбрасываем флаг перезапуска
        self.bot_thread._should_restart = False
        
        # Ждем завершения потока
        if self.bot_thread.isRunning():
            self.bot_thread.wait(15000)
            if self.bot_thread.isRunning():
                logger.warning("Bot restart skipped because previous BotThread is still running.")
                return
        
        # Создаем НОВЫЙ поток вместо повторного использования старого
        if not self.bot_thread.isRunning():
            from bot.handlers.queue_manager import reset_runtime_state
             
            # Создаем новый поток
            new_bot_thread = self.bot_thread.__class__()
            reset_runtime_state()
            
            # Обновляем ссылки в панелях
            self.bot_thread = new_bot_thread
            self.user_management.bot_thread = new_bot_thread
            self.settings_panel.bot_thread = new_bot_thread
            
            # Переподключаем сигналы
            self.setup_bot_signals()
            
            # Запускаем новый поток
            self.bot_thread.start()
            logger.info("Бот успешно перезапущен с новым потоком")

    def handle_bot_started(self):
        """Обработка запуска бота - обновляем UI статус"""
        logger.info("Получен сигнал о запуске бота - обновляем UI")
        
        # Обновляем статус в UI
        self.user_management.show_status_message('Сервер запущен') 
        self.user_management.toggle_server_button.setText('Остановить сервер')
        self.user_management.toggle_server_button.setEnabled(True)
        
        # Устанавливаем время начала сеанса если его нет
        if self.user_management.session_start_time is None:
            self.user_management.session_start_time = datetime.datetime.now()
            logger.info(f"Сеанс начат в {self.user_management.session_start_time}")

    def handle_bot_stopped(self):
        """Обработка остановки бота - обновляем UI статус"""
        logger.info("Получен сигнал об остановке бота - обновляем UI")
        
        # Обновляем статус в UI
        self.user_management.show_status_message('Сервер остановлен')
        self.user_management.toggle_server_button.setText('Запустить сервер')
        self.user_management.toggle_server_button.setEnabled(True)

    def handle_bot_startup_failed(self, error_message):
        """Обработка ошибки запуска бота - сбрасываем UI из состояния ожидания."""
        logger.warning("Не удалось запустить бота: %s", error_message)

        details = (error_message or "").strip()
        if "api.telegram.org" in details:
            status_message = "Нет соединения с Telegram API"
        else:
            status_message = "Не удалось запустить сервер"

        self.user_management.show_status_message(status_message, timeout=10000)
        self.user_management.toggle_server_button.setText('Запустить сервер')
        self.user_management.toggle_server_button.setEnabled(True)

    def smart_restart_bot(self, reason="Изменение настроек"):
        """
        Умный перезапуск бота при изменении настроек.
        Проверяет валидность настроек перед запуском.
        """
        logger.info(f"Умный перезапуск бота: {reason}")
        
        # Импортируем settings_manager для проверки настроек
        from config.settings import settings_manager
        
        # Проверяем настройки ПЕРЕД перезапуском
        if not settings_manager.is_ready_for_bot():
            is_valid, errors = settings_manager.validate_settings()
            logger.warning(f"Настройки невалидны - перезапуск отменен. Ошибки: {', '.join(errors)}")
            
            # Показываем сообщение пользователю
            QMessageBox.warning(
                self,
                "Невалидные настройки",
                f"Не удается запустить бота:\n\n" + "\n".join(f"• {error}" for error in errors)
            )
            return False
        
        # Настройки валидны - выполняем перезапуск
        logger.info("Настройки валидны - выполняем перезапуск бота...")
        
        # Останавливаем текущий бот если запущен
        if self.bot_thread.isRunning():
            logger.info("Останавливаем текущий бот...")
            if not self.bot_thread.stop_and_wait(15000):
                logger.warning("Smart restart cancelled because previous BotThread is still running.")
                QMessageBox.warning(
                    self,
                    "Перезапуск отменен",
                    "Не удалось корректно остановить текущий сеанс бота. Попробуйте закрыть приложение и запустить его снова."
                )
                return False
        
        # Создаем новый поток
        from bot.handlers.queue_manager import reset_runtime_state
        new_bot_thread = self.bot_thread.__class__()
        reset_runtime_state()
        
        # Обновляем ссылки
        self.bot_thread = new_bot_thread
        self.user_management.bot_thread = new_bot_thread
        self.settings_panel.bot_thread = new_bot_thread
        
        # Переподключаем сигналы
        self.setup_bot_signals()
        
        # Запускаем новый поток
        self.bot_thread.start()
        
        logger.info(f"Умный перезапуск бота завершен успешно: {reason}")
        return True

    def initialize_server(self):
        if server_state.server_active:
            self.user_management.status_label.setText('Сервер запущен')
            self.user_management.toggle_server_button.setText('Остановить сервер')
            if self.user_management.session_start_time is None:
                self.user_management.session_start_time = datetime.datetime.now()
                logger.info(f"Сеанс начат в {self.user_management.session_start_time}")
        else:
            self.user_management.status_label.setText('Сервер остановлен')
            self.user_management.toggle_server_button.setText('Запустить сервер')

    def closeEvent(self, event):
        if self._closing:
            event.accept()
            return

        if server_state.server_active:
            reply = QMessageBox.question(
                self, 'Выход',
                'Сохранить статистику текущего сеанса перед выходом?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            self._closing = True
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    self.user_management.save_session_statistics()
                except Exception as e:
                    logger.error(f"Ошибка при сохранении статистики сеанса: {e}")
                    QMessageBox.warning(
                        self,
                        "Ошибка",
                        "Не удалось сохранить статистику сеанса."
                    )
        else:
            reply = QMessageBox.question(
                self, 'Выход',
                'Вы действительно хотите выйти?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                self._closing = False
                event.ignore()
                return
            self._closing = True

        if not self._shutdown_runtime():
            self._closing = False
            event.ignore()
            QMessageBox.warning(
                self,
                "Завершение работы",
                "Фоновые операции ещё завершаются. Подождите немного и закройте приложение повторно.",
            )
            return

        event.accept()
        app = QApplication.instance()
        if app:
            app.quit()

    def _shutdown_runtime(self):
        server_state.server_active = False

        try:
            stop_all_server_processes()
        except Exception as e:
            logger.warning(f"Ошибка при остановке MCP-процессов: {e}")

        if self.bot_thread and self.bot_thread.isRunning():
            if not self.bot_thread.stop_and_wait(30000):
                logger.warning("BotThread не завершился за 30 секунд; принудительная остановка не выполняется.")
                return False
        return True
