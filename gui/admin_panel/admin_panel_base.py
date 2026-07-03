# gui/admin_panel/admin_panel_base.py

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QWidget, QVBoxLayout, QTabWidget, QLabel
)
from gui.admin_panel.user_management import UserManagement
from gui.admin_panel.settings_panel import SettingsPanel  # Импортируем ваш реальный SettingsPanel
from gui.admin_panel.voice_settings_tab import VoiceSettingsTab
from gui.admin_panel.extra_settings_tab import ExtraSettingsTab
from gui.admin_panel.mcp_tab import McpTab
from gui.admin_panel.secretary_tab import SecretaryTab
from bot.handlers.services.mcp_runtime import stop_all_server_processes
from utils import server_state
from utils.logger import setup_logger
import datetime

logger = setup_logger(__name__)

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

        # Создаем центральный виджет и устанавливаем макет
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # Создаем вкладки
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # Панель управления пользователями
        self.user_management = UserManagement(self.bot_thread)
        self.tab_widget.addTab(self.user_management, "Управление пользователями")

        # Панель настроек (передаем bot_thread)
        self.settings_panel = SettingsPanel(self.bot_thread)
        self.tab_widget.addTab(self.settings_panel, "Настройки")

        # Настройки голоса
        self.voice_tab = VoiceSettingsTab(self)
        self.tab_widget.addTab(self.voice_tab, "Голос")

        # Дополнительные настройки
        self.extra_tab = ExtraSettingsTab(self)
        self.tab_widget.addTab(self.extra_tab, "Доп настройки")

        self.mcp_tab = McpTab(self)
        self.tab_widget.addTab(self.mcp_tab, "MCP")

        self.secretary_tab = SecretaryTab(self)
        self.tab_widget.addTab(self.secretary_tab, "Секретарь")

        # Инициализируем статус сервера
        self.initialize_server()
        
        # Применяем тему (OLED или обычную)
        self.apply_theme()

    def apply_theme(self):
        """Применяет тему оформления (OLED или стандартную)"""
        from PyQt6.QtGui import QPalette, QColor
        from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
        from config.settings import settings_manager
        settings = settings_manager.get_settings()
        is_oled = settings.get('oled_mode', False)
        
        # 🎨 ПОЛУЧАЕМ СИСТЕМНЫЙ АКЦЕНТНЫЙ ЦВЕТ
        # Вытягиваем тот самый цвет, который пользователь выбрал в Windows
        system_accent = QApplication.palette().color(QPalette.ColorRole.Highlight)
        accent_color = system_accent.name()
        
        # Определяем цвета для палитры
        if is_oled:
            tooltip_bg = QColor("#050505")
            tooltip_fg = QColor("#FFFFFF")
            border_color = "#333333"
            header_bg = "#000000"
            window_bg = "#000000"
            panel_bg = "#000000"
        else:
            tooltip_bg = QColor("#2d2d2d")
            tooltip_fg = QColor("#FFFFFF")
            border_color = "#444444"
            header_bg = "#252526"
            window_bg = "#1e1e1e"
            panel_bg = "#252526"

        # Устанавливаем палитру для подсказок
        palette = QApplication.palette()
        palette.setColor(QPalette.ColorRole.ToolTipBase, tooltip_bg)
        palette.setColor(QPalette.ColorRole.ToolTipText, tooltip_fg)
        QApplication.setPalette(palette)
        
        # Общие стили для обоих режимов
        common_style = f"""
            QTabWidget::pane {{ 
                border: 1px solid {border_color}; 
                top: -1px; 
                background-color: {window_bg};
            }}
            QTabWidget::tab-bar {{ alignment: left; }}
            QTabBar::tab {{
                padding: 10px 15px;
                margin-right: 2px;
                border: 1px solid {border_color};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                background-color: {header_bg};
                color: #888888;
            }}
            QTabBar::tab:selected {{
                background-color: {window_bg};
                color: #FFFFFF;
                border-bottom: 2px solid {accent_color}; /* Системный акцент! */
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
            QLineEdit, QSpinBox, QComboBox, QTextEdit {{
                padding: 5px;
                border-radius: 4px;
                border: 1px solid {border_color};
                background-color: {panel_bg};
                color: #FFFFFF;
            }}
            
            /* Стили для кастомных кнопок UnicodeSpinBox */
            QPushButton[accessibleName="spinbox_up"], 
            QPushButton[accessibleName="spinbox_down"] {{
                padding: 2px 4px;
                border-radius: 2px;
                border: 1px solid {border_color};
                background-color: {header_bg};
                color: #FFFFFF;
                min-width: 20px;
            }}
            QPushButton[accessibleName="spinbox_up"]:hover, 
            QPushButton[accessibleName="spinbox_down"]:hover {{
                background-color: {border_color};
            }}
            QGroupBox {{
                font-weight: bold;
                border: 2px solid {border_color}; /* Сделали границу чуть толще для видимости */
                border-radius: 8px;
                margin-top: 1.1em;
                padding-top: 0.8em;
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: {accent_color}; /* Заголовок группы тоже в акцент */
            }}
            QToolTip {{
                background-color: {tooltip_bg.name()};
                color: {tooltip_fg.name()};
                border: 1px solid {accent_color};
                border-radius: 6px;
                padding: 0px;
            }}
            QHeaderView::section {{
                background-color: {header_bg};
                color: #FFFFFF;
                padding: 6px;
                border: 1px solid {border_color};
            }}
            QHeaderView {{
                background-color: {window_bg};
            }}
            QTableCornerButton::section {{
                background-color: {window_bg};
                border: 1px solid {border_color};
            }}
            QHeaderView::section:vertical {{
                background-color: {window_bg};
                border: 1px solid {border_color};
            }}
            QTableWidget {{
                gridline-color: {border_color};
                background-color: {window_bg};
                border: 1px solid {border_color};
            }}
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            /* Это важно для того, чтобы контент внутри скролла не терял стили */
            QScrollArea > QWidget > QWidget {{
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                width: 10px;
                background: transparent;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {border_color};
                min-height: 30px;
                border-radius: 5px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {accent_color};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}

            QScrollBar:horizontal {{
                height: 10px;
                background: transparent;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {border_color};
                min-width: 30px;
                border-radius: 5px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {accent_color};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
                background: none;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
            QLabel {{
                color: #FFFFFF;
                background: transparent;
            }}
            /* Стили для всех диалоговых окон и сообщений */
            QDialog, QMessageBox {{
                background-color: {window_bg};
                color: #FFFFFF;
            }}
            QDialog QLabel, QMessageBox QLabel {{
                color: #FFFFFF;
            }}
        """

        # Применяем финальный стиль к главному окну
        self.setStyleSheet(f"QMainWindow, QWidget#centralWidget {{ background-color: {window_bg}; }} " + common_style)
        logger.info(f"Применена тема (OLED: {is_oled}) с системным акцентом {accent_color}")

        # Обновляем все дочерние элементы
        self.style().unpolish(self)
        self.style().polish(self)
        
        # Специальный вызов для панели настроек (с передачей акцента)
        if hasattr(self.settings_panel, "apply_theme"):
            self.settings_panel.apply_theme(is_oled, accent_color)

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

        self._shutdown_runtime()

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
                logger.warning("BotThread не завершился за 30 секунд, принудительно завершаем поток.")
                self.bot_thread.terminate()
                self.bot_thread.wait(3000)
