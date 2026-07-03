# main.py

import sys
import os
import atexit
from concurrent.futures import TimeoutError as FutureTimeoutError

# ИСПРАВЛЕНИЕ ДЛЯ PYINSTALLER (NOCONSOLE MODE)
# Перенаправляем stdout/stderr в null, если они отсутствуют
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from gui.admin_panel.admin_panel_base import AdminPanelBase
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from PyQt6.QtCore import QThread, pyqtSignal
from utils.logger import setup_logger
from utils.resource_manager import get_resource_path, load_app_icon
from config.settings import settings_manager
from bot.handlers.command_handlers import start_command, clear_history_command, reload_models_command, reset_context_command, my_chat_member_handler
from bot.handlers.menu_handlers import open_menu, handle_menu_callback
from bot.handlers.message_handlers import message_handler, edited_message_handler, deleted_message_handler
from bot.handlers.secretary_handlers import (
    business_connection_handler,
    business_message_handler,
    secretary_callback_handler,
    close_secretary_handlers,
)
from bot.handlers.queue_manager import process_queue, close_all_clients, wait_for_active_tasks, reset_runtime_state
from bot.handlers.services.mcp_runtime import stop_all_server_processes
from utils.database.backlog_writer import backlog_message_writer
from utils import stats  # Импортируем модуль статистики
from utils import server_state
from utils.session_stats_storage import SESSION_STATS_FILE, migrate_legacy_session_stats
from utils.single_instance import acquire_single_instance_lock, release_single_instance_lock
import datetime

# Отключаем Qt font warnings (не критичные, только шум)
import logging
logging.getLogger('PyQt6').setLevel(logging.ERROR)

logger = setup_logger(__name__)

class BotThread(QThread):
    started_signal = pyqtSignal()
    stopped_signal = pyqtSignal()
    restart_needed_signal = pyqtSignal()
    startup_failed_signal = pyqtSignal(str)
    backlog_signal = pyqtSignal(int)  # Передает количество обработанных сообщений из очереди

    def __init__(self):
        super().__init__()
        self._is_running = False
        self._should_restart = False
        self.loop = None
        self.dp = None  # Инициализируем self.dp
        self.bot = None  # Инициализируем self.bot
        self.queue_task = None  # Для задачи process_queue
        self.session_start_time = None  # Время начала сеанса
        self._current_token = None  # Текущий токен
        self._shutdown_requested = False
        self._stop_future = None

    def run(self):
        try:
            self._is_running = True
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.session_start_time = datetime.datetime.now()  # Зафиксировать время начала сеанса
            self.loop.run_until_complete(self.start_bot())
        except Exception as e:
            logger.error(f"Ошибка в потоке бота: {e}")
            server_state.server_active = False
            error_text = str(e).strip() or e.__class__.__name__
            self.startup_failed_signal.emit(error_text)
        finally:
            try:
                if self.bot and self.loop and not self.loop.is_closed():
                    self.loop.run_until_complete(self.bot.session.close())
            except Exception as close_error:
                logger.warning(f"Ошибка при закрытии сессии Telegram бота: {close_error}")
            finally:
                self.bot = None
                self.dp = None
                self.queue_task = None
                self._stop_future = None
                self._is_running = False

            if self.loop and not self.loop.is_closed():
                try:
                    self.loop.run_until_complete(self._cancel_remaining_tasks())
                except Exception as task_error:
                    logger.warning(f"Error while cancelling pending bot loop tasks: {task_error}")
                try:
                    self.loop.run_until_complete(self.loop.shutdown_asyncgens())
                except Exception as asyncgen_error:
                    logger.warning(f"Error while shutting down bot async generators: {asyncgen_error}")
                try:
                    self.loop.run_until_complete(self.loop.shutdown_default_executor())
                except Exception as executor_error:
                    logger.warning(f"Error while shutting down bot executor: {executor_error}")
                try:
                    self.loop.close()
                except Exception as loop_error:
                    logger.warning(f"Ошибка при закрытии event loop бота: {loop_error}")
            self.loop = None

    async def _cancel_remaining_tasks(self):
        current_task = asyncio.current_task()
        pending = [
            task
            for task in asyncio.all_tasks(self.loop)
            if task is not current_task and not task.done()
        ]
        if not pending:
            return
        logger.warning("Cancelling %s pending bot loop task(s) before loop close", len(pending))
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def start_bot(self):
        reset_runtime_state()
        settings = settings_manager.get_settings()
        telegram_token = settings.get('telegram_token')
        
        # Сбрасываем счетчики наверстывания
        server_state.backlog_processed_count = 0
        server_state.is_catching_up = False
        server_state.last_backlog_message_at = 0.0
        
        # Сохраняем текущий токен
        self._current_token = telegram_token
        
        if not telegram_token:
            logger.warning("Telegram токен не установлен. Бот не может быть запущен.")
            return
            
        self.bot = Bot(token=telegram_token)
        me = await self.bot.get_me()
        server_state.bot_id = me.id
        server_state.bot_username = me.username or ""
        full_name_parts = [me.first_name or "", me.last_name or ""]
        server_state.bot_full_name = " ".join(part for part in full_name_parts if part).strip() or me.username or "Bot"
        server_state.bot_started_at_utc = datetime.datetime.now(datetime.timezone.utc)
        logger.info(
            "Бот авторизован: id=%s, username=%s, name=%s",
            server_state.bot_id,
            server_state.bot_username,
            server_state.bot_full_name,
        )
        self.dp = Dispatcher()
        # Регистрируем хэндлеры
        self.dp.message.register(start_command, Command(commands=["start"]))
        self.dp.message.register(clear_history_command, Command(commands=["clear_history"]))
        self.dp.message.register(reload_models_command, Command(commands=["reload_models"]))
        self.dp.message.register(reset_context_command, Command(commands=["reset_context"]))
        self.dp.message.register(open_menu, Command(commands=["menu"]))
        self.dp.callback_query.register(handle_menu_callback, F.data.startswith("menu:"))
        self.dp.callback_query.register(secretary_callback_handler, F.data.startswith("secretary:"))
        
        # Регистрация обработчика событий добавления в чат
        self.dp.my_chat_member.register(my_chat_member_handler)
        self.dp.business_connection.register(business_connection_handler)
        self.dp.business_message.register(business_message_handler)
        
        self.dp.message.register(message_handler)
        self.dp.message.register(edited_message_handler)
        self.dp.message.register(deleted_message_handler)
        # Запускаем process_queue в отдельной задаче
        self.queue_task = asyncio.create_task(process_queue())
        
        try:
            # АВТОМАТИЧЕСКИ АКТИВИРУЕМ СЕРВЕР при успешном запуске бота
            server_state.server_active = True
            logger.info("Сервер автоматически активирован при запуске бота")
            
            # ТЕПЕРЬ испускаем сигнал ПОСЛЕ активации сервера
            self.started_signal.emit()

            try:
                await self.bot.delete_webhook(drop_pending_updates=True)
                logger.info("Pending Telegram updates dropped before polling start")
            except Exception as exc:
                logger.warning("Не удалось сбросить pending updates перед polling: %s", exc)

            await self.dp.start_polling(
                self.bot,
                handle_signals=False,
                close_bot_session=False,
            )
        finally:
            # Останавливаем сервер
            server_state.server_active = False
            logger.info("Сервер деактивирован при остановке бота")
            
            # Останавливаем задачу process_queue при остановке polling
            if self.queue_task:
                self.queue_task.cancel()
                try:
                    await self.queue_task
                except asyncio.CancelledError:
                    pass

            try:
                await backlog_message_writer.stop()
            except Exception as e:
                logger.warning(f"Error while stopping backlog writer: {e}")

            await close_secretary_handlers()
            
            # ПЛАВНОЕ ЗАВЕРШЕНИЕ: Ждем выполнения активных запросов (макс 10с)
            try:
                await wait_for_active_tasks(timeout=10.0)
            except Exception as e:
                logger.warning(f"Ошибка при ожидании завершения задач: {e}")

            # Закрываем HTTP-сессии клиентов моделей
            try:
                await close_all_clients()
            except Exception as e:
                logger.warning(f"Ошибка при закрытии HTTP-сессий клиентов: {e}")
            
            # Зафиксировать время окончания сеанса
            session_end_time = datetime.datetime.now()
            # Сохранить статистику сеанса
            self.save_session_statistics(session_end_time)
            
            # Если нужен перезапуск, уведомляем об этом
            if self._should_restart:
                self.restart_needed_signal.emit()
            else:
                self.stopped_signal.emit()

    def stop_bot(self):
        if not self._is_running or not self.loop or self.loop.is_closed():
            return None

        if self._stop_future and not self._stop_future.done():
            return self._stop_future

        self._shutdown_requested = True

        async def _request_stop():
            if self.dp:
                try:
                    await self.dp.stop_polling()
                except RuntimeError as exc:
                    logger.debug(f"Dispatcher stop_polling skipped: {exc}")
            elif self.bot:
                await self.bot.session.close()

        try:
            self._stop_future = asyncio.run_coroutine_threadsafe(_request_stop(), self.loop)
            return self._stop_future
        except RuntimeError as exc:
            logger.warning(f"Could not schedule bot shutdown: {exc}")
            return None

    def stop_and_wait(self, timeout_ms: int = 15000) -> bool:
        future = self.stop_bot()
        if future:
            try:
                future.result(timeout=min(max(timeout_ms / 1000, 0.1), 5.0))
            except FutureTimeoutError:
                logger.warning("Bot stop request did not complete within the short wait window")
            except Exception as exc:
                logger.warning(f"Bot stop request failed: {exc}")

        return self.wait(timeout_ms)

    def restart_bot(self):
        """Перезапуск бота с новыми настройками"""
        logger.info("Запрошен перезапуск бота...")
        self._should_restart = True
        self.stop_bot()

    def check_token_changed(self):
        """Проверяет, изменился ли токен в настройках"""
        settings = settings_manager.get_settings()
        new_token = settings.get('telegram_token')
        return new_token != self._current_token

    def get_current_token(self):
        """Возвращает текущий токен бота"""
        return self._current_token

    def save_session_statistics(self, session_end_time):
        """Сохраняет статистику завершённого сеанса в session_stats.txt."""
        try:
            if self.session_start_time is None:
                logger.warning("Пропускаем сохранение статистики: время начала сессии не задано.")
                return

            session_duration = session_end_time - self.session_start_time

            wait_times = stats.stats.get_wait_times()
            response_times = stats.stats.get_response_times()
            request_count = stats.stats.get_request_count()
            input_tokens = stats.stats.get_input_tokens_total()
            output_tokens = stats.stats.get_output_tokens_total()
            
            avg_wait_time = sum(wait_times) / len(wait_times) if wait_times else 0
            avg_response_time = sum(response_times) / len(response_times) if response_times else 0
            has_meaningful_activity = any([
                request_count > 0,
                input_tokens > 0,
                output_tokens > 0,
                avg_wait_time > 0,
                avg_response_time > 0,
                bool(wait_times),
                bool(response_times),
            ])
            if not has_meaningful_activity:
                logger.info(
                    "Пропускаем сохранение пустого технического сеанса: duration=%s, requests=%s, tokens=%s+%s",
                    str(session_duration).split('.')[0],
                    request_count,
                    input_tokens,
                    output_tokens,
                )
                return

            # Убираем микросекунды из длительности для чистоты
            duration_clean = str(session_duration).split('.')[0]

            stats_text = (
                f"\nСеанс с {self.session_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
                f" по {session_end_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Продолжительность сеанса: {duration_clean}\n"
                f"Количество запросов за сеанс: {request_count}\n"
                f"Среднее ожидание: {avg_wait_time:.2f} сек\n"
                f"Среднее время ответа: {avg_response_time:.2f} сек\n"
                f"Токены: {input_tokens} вход / {output_tokens} выход\n"
            )

            session_stats_path = migrate_legacy_session_stats()
            session_stats_path.parent.mkdir(parents=True, exist_ok=True)
            with session_stats_path.open('a', encoding='utf-8') as f:
                f.write(stats_text + '\n')
            
            logger.info(
                "Статистика сеанса сохранена в %s: %s запросов, %s+%s токенов, wait=%s, response=%s",
                session_stats_path,
                request_count,
                input_tokens,
                output_tokens,
                len(wait_times),
                len(response_times),
            )
        except Exception as e:
            logger.error(f"Ошибка при сохранении статистики сеанса: {e}")

if __name__ == '__main__':
    single_instance_lock = acquire_single_instance_lock()
    if single_instance_lock is None:
        logger.warning("SnapMatch is already running; second instance exits.")
        sys.exit(0)

    app = QApplication(sys.argv)
    atexit.register(release_single_instance_lock, single_instance_lock)
    
    # Устанавливаем иконку приложения
    try:
        app_icon = load_app_icon()
        if app_icon:
            app.setWindowIcon(app_icon)
            logger.info("Иконка установлена для приложения")
    except Exception as e:
        logger.warning(f"Не удалось загрузить иконку приложения: {e}")

    try:
        # Импортируем и показываем сплеш-скрин
        from gui.splash_screen import SplashScreen
        splash = SplashScreen(app)
        splash.show()
        
        # Обрабатываем события, чтобы отобразить заставку
        app.processEvents()
        
        # СОЗДАЕМ BotThread, но НЕ ЗАПУСКАЕМ его автоматически
        bot_thread = BotThread()
        
        # Проверяем настройки ПЕРЕД запуском бота
        logger.info("Проверка настроек перед запуском бота...")
        
        if settings_manager.is_ready_for_bot():
            logger.info("Настройки валидны - запускаем бота автоматически")
            bot_thread.start()
        else:
            is_valid, errors = settings_manager.validate_settings()
            logger.warning(f"Настройки невалидны - бот не запущен. Ошибки: {', '.join(errors)}")

        # Ждем, пока анимация заставки закончится
        while splash.isVisible():
            app.processEvents()

        # Показываем главное окно после завершения анимации
        panel = AdminPanelBase(bot_thread)
        
        # Устанавливаем иконку и для главного окна
        try:
            app_icon = load_app_icon()
            if app_icon:
                panel.setWindowIcon(app_icon)
                logger.info("Иконка установлена для главного окна")
        except Exception as e:
            logger.warning(f"Не удалось установить иконку для главного окна: {e}")
        
        panel.show()

        try:
            exit_code = app.exec()
            try:
                stop_all_server_processes()
            except Exception as e:
                logger.warning(f"Ошибка при финальной остановке MCP-процессов: {e}")
            if bot_thread and bot_thread.isRunning():
                if not bot_thread.stop_and_wait(30000):
                    logger.warning("BotThread не завершился за 30 секунд после выхода GUI, принудительно завершаем поток.")
                    bot_thread.terminate()
                    bot_thread.wait(3000)
            sys.exit(exit_code)
        except KeyboardInterrupt:
            logger.info("Получен KeyboardInterrupt. Корректное завершение приложения...")
            try:
                stop_all_server_processes()
                if bot_thread and bot_thread.isRunning():
                    # Создаем событийный цикл если он ещё не запущен (для вызова асинхронных функций)
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(wait_for_active_tasks(2.0), loop)
                        asyncio.run_coroutine_threadsafe(close_all_clients(), loop)
                    else:
                        loop.run_until_complete(wait_for_active_tasks(2.0))
                        loop.run_until_complete(close_all_clients())
                    
                    bot_thread.stop_and_wait(10000)
            except Exception as e:
                logger.error(f"Ошибка при KeyboardInterrupt: {e}")
            sys.exit(0)
    except Exception as e:
        logger.error(f"Ошибка приложения: {e}")
