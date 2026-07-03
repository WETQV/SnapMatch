import asyncio
from typing import Optional

from aiogram import types

from utils.logger import setup_logger

logger = setup_logger(__name__)


async def send_ephemeral_reply(
    message: types.Message,
    text: str,
    *,
    delay_seconds: float = 20.0,
    parse_mode: Optional[str] = None,
) -> Optional[types.Message]:
    """
    Отправляет временное сообщение и автоматически удаляет его спустя delay_seconds.

    Args:
        message: исходное сообщение пользователя
        text: текст ответа
        delay_seconds: задержка перед удалением
        parse_mode: режим форматирования (MarkdownV2, HTML и т.д.)
    """
    try:
        sent_message = await message.reply(text, parse_mode=parse_mode)
    except Exception as exc:
        logger.warning(f"Не удалось отправить временное уведомление: {exc}")
        return None

    async def _auto_delete():
        try:
            await asyncio.sleep(delay_seconds)
            await message.bot.delete_message(
                chat_id=sent_message.chat.id,
                message_id=sent_message.message_id,
            )
        except Exception as delete_exc:
            # Не шумим лишними предупреждениями, потому что удаление может быть запрещено правами.
            logger.debug(f"Не удалось удалить временное уведомление: {delete_exc}")

    asyncio.create_task(_auto_delete())
    return sent_message

