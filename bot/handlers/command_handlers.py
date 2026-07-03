# bot/handlers/command_handlers.py

from aiogram import types
from utils.logger import setup_logger
from utils.database.database_manager import DatabaseManager
from bot.handlers.queue_manager import reload_models
from utils.markdown_formatter import telegram_formatter
from utils.history_manager import reset_history_cache
from utils import stats
from utils import server_state
from config.settings import settings_manager
from bot.handlers.services.access_control import is_admin_user
from bot.handlers.services.telegram_utils import send_ephemeral_reply

logger = setup_logger(__name__)

async def start_command(message: types.Message):
    telegram_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    db = DatabaseManager()
    try:
        db.users.add_user(telegram_id, username, first_name, last_name)
        welcome_message = "Привет! Я ваш AI-ассистент."
        formatted_text, parse_mode = telegram_formatter.process_text(welcome_message)
        await message.reply(formatted_text, parse_mode=parse_mode)
        logger.info(f"Пользователь {telegram_id} начал диалог.")
    except Exception as e:
        logger.error(f"Ошибка в команде /start для пользователя {telegram_id}: {e}")
        error_message = "Произошла ошибка при запуске бота."
        formatted_text, parse_mode = telegram_formatter.process_text(error_message)
        await message.reply(formatted_text, parse_mode=parse_mode)
    finally:
        db.close()

async def clear_history_command(message: types.Message):
    telegram_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    chat_id = message.chat.id
    chat_type = message.chat.type
    
    db = DatabaseManager()
    try:
        # Сначала добавляем пользователя, если его нет
        db.users.add_user(telegram_id, username, first_name, last_name)
        
        # Теперь получаем пользователя (он точно должен быть)
        user = db.users.get_user_by_telegram_id(telegram_id)

        if user is not None:
            if chat_type in {'group', 'supergroup'}:
                # В группе удаляем только обращения к боту и ответы ассистента
                deleted_count = db.messages.delete_group_conversation(chat_id)
                success_message = (
                    "✅ Очищены обращения к боту и ответы в этой группе.\n"
                    f"Удалено сообщений: {deleted_count}."
                )
                logger.info(
                    "Адресованная история чата %s очищена по команде пользователя %s (%s сообщений)",
                    chat_id,
                    telegram_id,
                    deleted_count,
                )
            else:
                # В личном чате очищаем сообщения только в рамках текущего диалога
                deleted_count = db.messages.delete_messages_by_chat_and_user(chat_id, user['id'])
                success_message = (
                    "✅ Ваша история сообщений очищена.\n"
                    f"Удалено сообщений: {deleted_count}."
                )
                logger.info("История пользователя %s очищена (%s сообщений)", telegram_id, deleted_count)

            formatted_text, parse_mode = telegram_formatter.process_text(success_message)
            await send_ephemeral_reply(message, formatted_text, parse_mode=parse_mode)
            reset_history_cache()
        else:
            # Это не должно произойти, но на всякий случай
            error_message = "❌ Произошла ошибка при очистке истории сообщений."
            formatted_text, parse_mode = telegram_formatter.process_text(error_message)
            await send_ephemeral_reply(message, formatted_text, parse_mode=parse_mode)
            logger.error(f"Не удалось найти/создать пользователя {telegram_id}")
    except Exception as e:
        logger.error(f"Ошибка при очистке истории сообщений пользователя {telegram_id}: {e}")
        error_message = "❌ Произошла ошибка при очистке вашей истории сообщений."
        formatted_text, parse_mode = telegram_formatter.process_text(error_message)
        await send_ephemeral_reply(message, formatted_text, parse_mode=parse_mode)
    finally:
        db.close()

async def reload_models_command(message: types.Message):
    """Команда для перезагрузки списка моделей"""
    telegram_id = message.from_user.id
    db = DatabaseManager()
    try:
        user = db.users.get_user_by_telegram_id(telegram_id)
        if is_admin_user(settings_manager.get_settings(), user, telegram_id):
            # Вызываем функцию перезагрузки моделей
            result = reload_models()
            
            if result["status"] == "success":
                success_message = f"✅ Модели успешно перезагружены.\nАктивных моделей: {result['models_count']}\nСписок: {', '.join(result['active_models'])}"
                formatted_text, parse_mode = telegram_formatter.process_text(success_message)
                await send_ephemeral_reply(message, formatted_text, parse_mode=parse_mode)
            else:
                error_message = "❌ Ошибка при перезагрузке моделей."
                formatted_text, parse_mode = telegram_formatter.process_text(error_message)
                await send_ephemeral_reply(message, formatted_text, parse_mode=parse_mode)
        else:
            error_message = "⛔ У вас нет прав для выполнения этой команды."
            formatted_text, parse_mode = telegram_formatter.process_text(error_message)
            await send_ephemeral_reply(message, formatted_text, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Ошибка при перезагрузке моделей: {e}")
        error_message = "❌ Произошла ошибка при перезагрузке моделей."
        formatted_text, parse_mode = telegram_formatter.process_text(error_message)
        await message.reply(formatted_text, parse_mode=parse_mode)
    finally:
        db.close()

async def reset_context_command(message: types.Message):
    """Полный сброс диалога для текущего чата: история, кэш суммаризации, статистика."""
    telegram_id = message.from_user.id
    chat_id = message.chat.id
    chat_type = message.chat.type

    if chat_type not in {'group', 'supergroup'}:
        info_message = (
            "ℹ️ Команда /reset_context доступна только в групповых чатах. "
            "Пожалуйста, используйте /clear_history в личном диалоге."
        )
        formatted_text, parse_mode = telegram_formatter.process_text(info_message)
        await message.reply(formatted_text, parse_mode=parse_mode)
        return

    db = DatabaseManager()
    try:
        db.users.add_user(
            telegram_id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
        )

        user = db.users.get_user_by_telegram_id(telegram_id)
        if not is_admin_user(settings_manager.get_settings(), user, telegram_id):
            error_message = "⛔ У вас нет прав для выполнения этой команды."
            formatted_text, parse_mode = telegram_formatter.process_text(error_message)
            await send_ephemeral_reply(message, formatted_text, parse_mode=parse_mode)
            return

        deleted_count = db.messages.delete_messages_by_chat_id(chat_id)
        reset_history_cache()
        stats.stats.reset()

        success_message = (
            "✅ Контекст бота полностью сброшен.\n"
            "Следующее сообщение начнёт новый диалог."
        )
        formatted_text, parse_mode = telegram_formatter.process_text(success_message)
        await send_ephemeral_reply(message, formatted_text, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Ошибка при полном сбросе контекста (chat_id={chat_id}): {e}")
        error_message = "❌ Не удалось сбросить контекст. Попробуйте ещё раз позже."
        formatted_text, parse_mode = telegram_formatter.process_text(error_message)
        await send_ephemeral_reply(message, formatted_text, parse_mode=parse_mode)
    finally:
        db.close()

async def my_chat_member_handler(event: types.ChatMemberUpdated):
    """
    Обработчик событий изменения статуса бота в чате (добавление/удаление).
    Позволяет регистрировать группу сразу при добавлении бота.
    """
    new_state = event.new_chat_member
    
    # Проверяем, что событие касается именно нас (бота)
    if new_state.user.id != server_state.bot_id:
        return

    chat = event.chat
    chat_id = chat.id
    chat_type = chat.type
    chat_title = chat.title or f"Chat {chat_id}"

    # Статусы, означающие, что бот является членом группы
    is_member = new_state.status in {'member', 'administrator', 'creator'}

    if is_member and chat_type in {'group', 'supergroup'}:
        db = DatabaseManager()
        try:
            db.messages.update_chat(chat_id, chat_title=chat_title, chat_type=chat_type)
            logger.info(f"Бот добавлен в группу: {chat_title} ({chat_id}). Группа зарегистрирована.")
        except Exception as e:
            logger.error(f"Ошибка при регистрации группы {chat_id}: {e}")
        finally:
            db.close()
    elif new_state.status in {'left', 'kicked'} and chat_type in {'group', 'supergroup'}:
        logger.info(f"Бот удалён из группы: {chat_title} ({chat_id}).")
