from typing import Any, Dict, Optional

from utils import server_state
from utils.database.database_manager import DatabaseManager
from utils.logger import setup_logger
from utils.markdown_formatter import telegram_formatter

from .rich_message_sender import (
    prepare_legacy_fallback_text,
    rich_messages_fallback_enabled,
    try_send_rich_message,
)

logger = setup_logger(__name__)

SECRETARY_CALLBACK_PREFIX = "secretary"
SECRETARY_ERROR_PREFIXES = (
    "извините, произошла ошибка",
    "извините, модель",
    "извините, не получилось",
    "извините, ответ не сформирован",
    "извините, не могу сформулировать",
    "извините, ваш аккаунт",
    "sorry, an error occurred",
    "sorry, the model",
    "sorry, i couldn't",
)


def is_secretary_error_response(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return any(normalized.startswith(prefix) for prefix in SECRETARY_ERROR_PREFIXES)


def _error_preview(text: str, limit: int = 180) -> str:
    preview = " ".join((text or "").strip().split())
    if len(preview) > limit:
        return preview[:limit - 3].rstrip() + "..."
    return preview


async def handle_secretary_model_response(
    *,
    message: Any,
    user: Dict,
    response_text: str,
    request_context: Dict,
    db: Optional[DatabaseManager] = None,
) -> Dict:
    owns_db = db is None
    db = db or DatabaseManager()
    try:
        owner_id = int(request_context.get("secretary_owner_telegram_id") or user.get("telegram_id"))
        chat_id = int(request_context.get("secretary_source_chat_id") or getattr(getattr(message, "chat", None), "id"))
        response_mode = (request_context.get("secretary_response_mode") or "confirm").lower()
        session_id = request_context.get("secretary_session_id")
        business_connection_id = request_context.get("business_connection_id")
        reply_to_message_id = getattr(message, "message_id", None)

        if is_secretary_error_response(response_text):
            preview = _error_preview(response_text)
            db.secretary.add_event(
                owner_id,
                "error",
                f"Secretary model error suppressed: {preview}",
                chat_id=chat_id,
            )
            logger.warning(
                "Secretary model error suppressed: owner_id=%s chat_id=%s text=%s",
                owner_id,
                chat_id,
                preview,
            )
            return {"status": "error", "reason": "model_error_suppressed"}

        if response_mode == "off":
            db.secretary.add_event(owner_id, "skipped", "Secretary response mode is off", chat_id=chat_id)
            return {"status": "skipped"}

        if response_mode in {"draft", "confirm"}:
            pending_id = db.secretary.add_pending_response(
                owner_id,
                chat_id,
                response_text,
                session_id=session_id,
                business_connection_id=business_connection_id,
                reply_to_message_id=reply_to_message_id,
                status="pending" if response_mode == "confirm" else "draft",
            )
            db.secretary.add_event(
                owner_id,
                "pending" if response_mode == "confirm" else "draft",
                f"pending_id={pending_id}",
                chat_id=chat_id,
            )
            if response_mode == "confirm" and pending_id:
                await _send_confirm_request(message, owner_id, response_text, int(pending_id))
            return {"status": "pending" if response_mode == "confirm" else "draft", "pending_id": pending_id}

        if response_mode == "auto":
            from config.settings import settings_manager

            settings = settings_manager.get_settings()
            rich_result = await try_send_rich_message(
                bot=message.bot,
                chat_id=chat_id,
                text=response_text,
                settings=settings,
                business_connection_id=business_connection_id,
                reply_to_message_id=reply_to_message_id,
                message_thread_id=getattr(message, "message_thread_id", None),
            )
            if rich_result.sent:
                _save_secretary_assistant_message(
                    db,
                    user,
                    response_text,
                    chat_id=chat_id,
                    chat_type=getattr(getattr(message, "chat", None), "type", None),
                    chat_title=getattr(getattr(message, "chat", None), "title", None),
                    reply_to_message_id=reply_to_message_id,
                    owner_id=owner_id,
                    session_id=session_id,
                    counterparty_id=request_context.get("secretary_counterparty_id"),
                    status="sent",
                )
                db.secretary.add_event(owner_id, "sent", "Auto response sent via Rich Message", chat_id=chat_id)
                if request_context.get("secretary_close_after_reply") and session_id:
                    db.secretary.close_session(int(session_id), reason="close_after_reply")
                return {"status": "sent", "transport": "rich_message"}
            if rich_result.status == "failed" and not rich_messages_fallback_enabled(settings):
                db.secretary.add_event(owner_id, "error", f"sendRichMessage failed: {rich_result.reason}", chat_id=chat_id)
                return {"status": "error", "reason": "rich_message_failed"}
            if rich_result.status == "failed":
                db.secretary.add_event(owner_id, "warning", f"sendRichMessage fallback: {rich_result.reason}", chat_id=chat_id)

            legacy_text = prepare_legacy_fallback_text(response_text) if business_connection_id else response_text
            formatted_text, parse_mode = telegram_formatter.process_text(legacy_text)
            send_kwargs = {
                "chat_id": chat_id,
                "text": formatted_text,
                "parse_mode": parse_mode,
            }
            if business_connection_id:
                send_kwargs["business_connection_id"] = business_connection_id
            if reply_to_message_id:
                send_kwargs["reply_to_message_id"] = reply_to_message_id

            await message.bot.send_message(**send_kwargs)
            _save_secretary_assistant_message(
                db,
                user,
                response_text,
                chat_id=chat_id,
                chat_type=getattr(getattr(message, "chat", None), "type", None),
                chat_title=getattr(getattr(message, "chat", None), "title", None),
                reply_to_message_id=reply_to_message_id,
                owner_id=owner_id,
                session_id=session_id,
                counterparty_id=request_context.get("secretary_counterparty_id"),
                status="sent",
            )
            db.secretary.add_event(owner_id, "sent", "Auto response sent", chat_id=chat_id)
            if request_context.get("secretary_close_after_reply") and session_id:
                db.secretary.close_session(int(session_id), reason="close_after_reply")
            return {"status": "sent"}

        db.secretary.add_event(owner_id, "error", f"Unknown secretary response mode: {response_mode}", chat_id=chat_id)
        return {"status": "error", "reason": "unknown_response_mode"}
    finally:
        if owns_db:
            db.close()


def _save_secretary_assistant_message(
    db: DatabaseManager,
    user: Dict,
    response_text: str,
    *,
    chat_id: int,
    chat_type: Optional[str],
    chat_title: Optional[str],
    reply_to_message_id: Optional[int],
    owner_id: int,
    session_id: Optional[int],
    counterparty_id: Optional[int],
    status: str,
) -> None:
    bot_full_name = server_state.bot_full_name or server_state.bot_username or "Bot"
    db.messages.add_message(
        user["id"],
        "assistant",
        response_text,
        chat_id=chat_id,
        chat_type=chat_type,
        chat_title=chat_title,
        author_telegram_id=server_state.bot_id,
        author_username=server_state.bot_username,
        author_full_name=bot_full_name,
        content_type="text",
        reply_to_message_id=reply_to_message_id,
        is_addressed=1,
        source_mode="secretary",
        secretary_owner_telegram_id=owner_id,
        secretary_source_chat_id=chat_id,
        secretary_counterparty_id=counterparty_id,
        secretary_session_id=session_id,
        secretary_reply_status=status,
    )


async def _send_confirm_request(message: Any, owner_id: int, response_text: str, pending_id: int) -> None:
    preview = response_text.strip()
    if len(preview) > 3500:
        preview = preview[:3497].rstrip() + "..."

    try:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Отправить", callback_data=f"{SECRETARY_CALLBACK_PREFIX}:send:{pending_id}"),
            InlineKeyboardButton(text="Отменить", callback_data=f"{SECRETARY_CALLBACK_PREFIX}:cancel:{pending_id}"),
        ]])
        await message.bot.send_message(
            chat_id=owner_id,
            text=f"Черновик ответа секретаря:\n\n{preview}",
            reply_markup=markup,
        )
    except Exception as exc:
        logger.warning("Не удалось отправить владельцу confirm-запрос pending_id=%s: %s", pending_id, exc)
