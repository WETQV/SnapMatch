import datetime

from aiogram import types

from bot.handlers import queue_manager
from bot.handlers.services.secretary_debounce_manager import SecretaryDebounceManager
from bot.handlers.services.secretary_queue_adapter import enqueue_secretary_batch
from utils import server_state
from utils import stats
from config.settings import settings_manager
from utils.database.database_manager import DatabaseManager
from utils.logger import setup_logger
from utils.markdown_formatter import telegram_formatter
from bot.handlers.services.rich_message_sender import (
    prepare_legacy_fallback_text,
    rich_messages_fallback_enabled,
    try_send_rich_message,
)

logger = setup_logger(__name__)
_secretary_debounce_manager = None
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


def _is_secretary_error_response(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return any(normalized.startswith(prefix) for prefix in SECRETARY_ERROR_PREFIXES)


def _get_secretary_debounce_manager() -> SecretaryDebounceManager:
    global _secretary_debounce_manager
    if _secretary_debounce_manager is None:
        _secretary_debounce_manager = SecretaryDebounceManager(_enqueue_debounced_secretary_batch)
    return _secretary_debounce_manager


async def _enqueue_debounced_secretary_batch(batch) -> None:
    if batch.user and batch.user.get("id") is not None:
        queue_manager.user_locks[batch.user["id"]] = True
    await enqueue_secretary_batch(
        batch,
        request_queue=queue_manager.request_queue,
        message_counter=queue_manager.message_counter,
        increment_pending=stats.stats.increment_pending_requests,
    )


async def close_secretary_handlers() -> None:
    global _secretary_debounce_manager
    if _secretary_debounce_manager is not None:
        await _secretary_debounce_manager.close()
        _secretary_debounce_manager = None


async def business_connection_handler(event: types.BusinessConnection):
    db = DatabaseManager()
    try:
        owner_id = event.user.id if event.user else None
        if owner_id is None:
            return
        db.secretary.upsert_business_connection(
            event.id,
            owner_id,
            user_chat_id=getattr(event, "user_chat_id", None),
            is_enabled=bool(event.is_enabled),
        )
        profile = db.secretary.get_profile(owner_id)
        if not profile:
            db.secretary.add_event(owner_id, "unknown_owner", "Business connection received for unknown owner")
            logger.info("Secretary business connection for unknown owner=%s", owner_id)
            return
        db.secretary.upsert_profile(
            owner_id,
            business_connection_id=event.id,
            owner_display_name=_user_display(event.user),
            enabled=int(bool(event.is_enabled) and bool(profile.get("enabled"))),
        )
        db.secretary.add_event(
            owner_id,
            "connection_enabled" if event.is_enabled else "connection_disabled",
            f"business_connection_id={event.id}",
        )
    finally:
        db.close()


async def business_message_handler(message: types.Message):
    if not message.business_connection_id:
        return

    db = DatabaseManager()
    try:
        profile = db.secretary.get_profile_by_connection_id(message.business_connection_id)
        owner_id = profile.get("owner_telegram_id") if profile else None
        if owner_id is None:
            owner_id = db.secretary.get_business_connection_owner(message.business_connection_id)
            profile = db.secretary.get_profile(owner_id) if owner_id is not None else None
        if owner_id is None:
            try:
                connection = await message.bot.get_business_connection(message.business_connection_id)
                owner_id = connection.user.id if connection and connection.user else None
                if owner_id is not None:
                    db.secretary.upsert_business_connection(
                        message.business_connection_id,
                        owner_id,
                        user_chat_id=getattr(connection, "user_chat_id", None),
                        is_enabled=bool(getattr(connection, "is_enabled", True)),
                    )
                    profile = db.secretary.get_profile(owner_id)
            except Exception as exc:
                logger.debug("Could not resolve business connection %s: %s", message.business_connection_id, exc)
        if owner_id is None:
            logger.info("Secretary business message skipped: owner unknown, chat_id=%s", message.chat.id)
            return
        if _is_stale_business_message(message):
            db.secretary.add_event(owner_id, "skipped", "Stale business message ignored after restart", chat_id=message.chat.id)
            logger.debug(
                "Secretary stale business message skipped: owner_id=%s chat_id=%s message_id=%s date=%s started_at=%s",
                owner_id,
                message.chat.id,
                message.message_id,
                getattr(message, "date", None),
                server_state.bot_started_at_utc,
            )
            return
        if not profile or not profile.get("enabled"):
            db.secretary.add_event(owner_id, "skipped", "Secretary profile missing or disabled", chat_id=message.chat.id)
            return
        chat_allowed, reason = _is_chat_allowed(profile, message.chat.id)
        if not chat_allowed:
            db.secretary.add_event(owner_id, "skipped", reason, chat_id=message.chat.id)
            logger.debug("Secretary event skipped: owner_id=%s chat_id=%s reason=%s", owner_id, message.chat.id, reason)
            return
        if profile.get("ignore_bot_messages", 1) and message.from_user and message.from_user.is_bot:
            db.secretary.add_event(owner_id, "skipped", "Bot author ignored", chat_id=message.chat.id)
            return

        runtime_settings = db.secretary.resolve_chat_runtime_settings(profile, message.chat.id)
        active_session = db.secretary.get_active_session(owner_id, message.chat.id)
        if runtime_settings.get("turn_based_replies", True) and _is_outgoing_business_message(message, owner_id):
            db.secretary.add_event(owner_id, "skipped", "Outgoing business message ignored by turn-based mode", chat_id=message.chat.id)
            return
        if message.from_user and int(message.from_user.id) == int(owner_id):
            behavior = runtime_settings.get("owner_message_behavior", "takeover")
            if behavior in {"takeover", "close_session"} and active_session and active_session.get("id"):
                db.secretary.close_session(int(active_session["id"]), reason=behavior)
                db.secretary.add_event(owner_id, "session_closed", f"owner_message_behavior={behavior}", chat_id=message.chat.id)
                return
            if behavior == "ignore":
                db.secretary.add_event(owner_id, "skipped", "Owner message ignored", chat_id=message.chat.id)
                return

        user = db.users.ensure_user(
            owner_id,
            None,
            profile.get("owner_display_name") or f"Secretary owner {owner_id}",
            None,
        )
        reply_context = _extract_secretary_reply_context(message, owner_id)
        media_result = await _prepare_secretary_media(message, runtime_settings, db, owner_id)
        if media_result.get("skip"):
            db.secretary.add_event(owner_id, "skipped", media_result.get("reason") or "Secretary media skipped", chat_id=message.chat.id)
            return
        content = _build_secretary_content(message, reply_context, media_result.get("text"))
        if not content.strip():
            db.secretary.add_event(owner_id, "skipped", "Empty/non-text business message", chat_id=message.chat.id)
            return

        active_session = db.secretary.get_active_session(owner_id, message.chat.id)
        if not active_session and runtime_settings.get("save_history", True):
            deleted_context = db.messages.delete_secretary_context(owner_id, chat_id=message.chat.id)
            if deleted_context:
                db.secretary.add_event(
                    owner_id,
                    "context_reset",
                    f"new session started with clean context deleted={deleted_context}",
                    chat_id=message.chat.id,
                )

        session = db.secretary.get_or_create_session(
            owner_id,
            message.chat.id,
            counterparty_id=getattr(message.from_user, "id", None),
            ttl_seconds=runtime_settings.get("session_ttl_seconds", 3600),
        )
        session_id = session.get("id")

        if runtime_settings.get("save_history", True):
            db.messages.add_message(
                user["id"],
                "user",
                content,
                chat_id=message.chat.id,
                chat_type=message.chat.type,
                chat_title=getattr(message.chat, "title", None),
                author_telegram_id=getattr(message.from_user, "id", None),
                author_username=getattr(message.from_user, "username", None),
                author_full_name=_user_display(message.from_user),
                telegram_message_id=message.message_id,
                content_type=media_result.get("content_type") or _secretary_content_type(message),
                image_path=media_result.get("image_path"),
                image_mime=media_result.get("image_mime"),
                telegram_file_id=media_result.get("telegram_file_id"),
                is_addressed=1,
                author_is_bot=int(bool(message.from_user and message.from_user.is_bot)),
                source_mode="secretary",
                secretary_owner_telegram_id=owner_id,
                secretary_source_chat_id=message.chat.id,
                secretary_counterparty_id=getattr(message.from_user, "id", None),
                secretary_session_id=session_id,
                secretary_reply_status="received",
            )
        db.secretary.add_event(owner_id, "received", f"Business message attached to session_id={session_id}", chat_id=message.chat.id)

        mode = (runtime_settings.get("response_mode") or "draft").lower()
        if mode == "off":
            db.secretary.add_event(owner_id, "skipped", "Secretary response mode is off", chat_id=message.chat.id)
            return

        await _enqueue_secretary_request(
            owner_id,
            user,
            profile,
            runtime_settings,
            session,
            message,
            content,
            attachments=media_result.get("attachments") or [],
        )
        db.secretary.add_event(owner_id, "queued", "Secretary request queued", chat_id=message.chat.id)
    finally:
        db.close()


async def secretary_callback_handler(query: types.CallbackQuery):
    data = query.data or ""
    parts = data.split(":")
    if len(parts) != 3:
        await query.answer("Некорректное действие.", show_alert=True)
        return
    _, action, pending_id_text = parts
    try:
        pending_id = int(pending_id_text)
    except ValueError:
        await query.answer("Некорректный ID.", show_alert=True)
        return

    db = DatabaseManager()
    try:
        pending = db.secretary.get_pending_response(pending_id)
        if not pending or pending.get("status") != "pending":
            await query.answer("Черновик уже обработан или устарел.", show_alert=True)
            return
        if int(pending.get("owner_telegram_id")) != int(query.from_user.id):
            await query.answer("Нет прав.", show_alert=True)
            return

        if action == "cancel":
            db.secretary.update_pending_response_status(pending_id, "cancelled")
            db.secretary.add_event(query.from_user.id, "cancelled", f"pending_id={pending_id}", chat_id=pending.get("chat_id"))
            if query.message:
                await query.message.edit_text("Черновик отменён.")
            await query.answer()
            return

        if action == "send":
            response_text = pending.get("response_text") or ""
            if _is_secretary_error_response(response_text):
                db.secretary.update_pending_response_status(pending_id, "cancelled")
                db.secretary.add_event(
                    query.from_user.id,
                    "error",
                    f"Pending secretary model error suppressed: {response_text[:180]}",
                    chat_id=pending.get("chat_id"),
                )
                logger.warning(
                    "Pending secretary model error suppressed: owner_id=%s pending_id=%s",
                    query.from_user.id,
                    pending_id,
                )
                if query.message:
                    await query.message.edit_text("Ответ не отправлен: модель вернула ошибку. Подробности записаны в логах.")
                await query.answer("Ошибка модели не отправлена собеседнику.", show_alert=True)
                return

            settings = settings_manager.get_settings()
            rich_result = await try_send_rich_message(
                bot=query.bot,
                chat_id=pending["chat_id"],
                text=response_text,
                settings=settings,
                business_connection_id=pending["business_connection_id"],
                reply_to_message_id=pending.get("reply_to_message_id"),
            )
            if not rich_result.sent:
                if rich_result.status == "failed":
                    db.secretary.add_event(
                        query.from_user.id,
                        "warning",
                        f"sendRichMessage fallback for pending_id={pending_id}: {rich_result.reason}",
                        chat_id=pending.get("chat_id"),
                    )
                if rich_result.status == "failed" and not rich_messages_fallback_enabled(settings):
                    db.secretary.add_event(
                        query.from_user.id,
                        "error",
                        f"sendRichMessage failed for pending_id={pending_id}: {rich_result.reason}",
                        chat_id=pending.get("chat_id"),
                    )
                    await query.answer("Не удалось отправить Rich Message.", show_alert=True)
                    return

                legacy_text = prepare_legacy_fallback_text(response_text) if pending.get("business_connection_id") else response_text
                formatted_text, parse_mode = telegram_formatter.process_text(legacy_text)
                await query.bot.send_message(
                    pending["chat_id"],
                    formatted_text,
                    parse_mode=parse_mode,
                    business_connection_id=pending["business_connection_id"],
                    reply_to_message_id=pending.get("reply_to_message_id"),
                )
            db.secretary.update_pending_response_status(pending_id, "sent")
            db.secretary.add_event(query.from_user.id, "sent", f"pending_id={pending_id}", chat_id=pending.get("chat_id"))
            if query.message:
                await query.message.edit_text("Ответ отправлен.")
            await query.answer()
            return

        await query.answer("Неизвестное действие.", show_alert=True)
    finally:
        db.close()


async def _enqueue_secretary_request(
    owner_id: int,
    user: dict,
    profile: dict,
    runtime_settings: dict,
    session: dict,
    message: types.Message,
    content: str,
    attachments: list | None = None,
) -> None:
    session_id = session.get("id") if isinstance(session, dict) else None
    request_context = {
        "source_mode": "secretary",
        "actor_telegram_id": owner_id,
        "chat_id": message.chat.id,
        "chat_type": message.chat.type,
        "is_admin": False,
        "role": "secretary_owner",
        "secretary_owner_telegram_id": owner_id,
        "secretary_source_chat_id": message.chat.id,
        "secretary_counterparty_id": getattr(message.from_user, "id", None),
        "secretary_session_id": session_id,
        "secretary_response_mode": (runtime_settings.get("response_mode") or "draft").lower(),
        "secretary_system_prompt": runtime_settings.get("system_prompt") or "",
        "secretary_save_history": bool(runtime_settings.get("save_history", True)),
        "secretary_close_after_reply": bool(runtime_settings.get("close_after_reply", False)),
        "secretary_turn_based_replies": bool(runtime_settings.get("turn_based_replies", True)),
        "business_connection_id": message.business_connection_id,
        "allowed_mcp": runtime_settings.get("allowed_mcp"),
        "author_is_bot": bool(message.from_user and message.from_user.is_bot),
        "is_addressed": True,
    }
    manager = _get_secretary_debounce_manager()
    await manager.add_message(
        owner_telegram_id=owner_id,
        chat_id=message.chat.id,
        user=user,
        message=message,
        text_content=content,
        attachments=list(attachments or []),
        request_context=request_context,
        delay_seconds=runtime_settings.get("delay_seconds"),
        burst_window_seconds=runtime_settings.get("burst_window_seconds"),
        max_batch_messages=runtime_settings.get("max_batch_messages"),
    )
    logger.debug(
        "Secretary request buffered: owner_id=%s chat_id=%s delay=%s burst=%s",
        owner_id,
        message.chat.id,
        runtime_settings.get("delay_seconds"),
        runtime_settings.get("burst_window_seconds"),
    )


def _user_display(user):
    if not user:
        return ""
    full_name = " ".join(part for part in [getattr(user, "first_name", ""), getattr(user, "last_name", "")] if part).strip()
    return full_name or getattr(user, "username", "") or str(getattr(user, "id", ""))


def _secretary_content_type(message: types.Message) -> str:
    if message.text:
        return "text"
    if message.photo:
        return "image"
    if message.document:
        return "document"
    if message.voice:
        return "voice"
    if message.video_note:
        return "video_note"
    if message.video:
        return "video"
    if message.sticker:
        return "sticker"
    return "text"


async def _prepare_secretary_media(
    message: types.Message,
    runtime_settings: dict,
    db: DatabaseManager,
    owner_id: int,
) -> dict:
    result = {
        "attachments": [],
        "image_path": None,
        "image_mime": None,
        "telegram_file_id": None,
        "content_type": _secretary_content_type(message),
        "text": None,
    }

    if message.photo:
        if not runtime_settings.get("media_images_enabled", False):
            return {"skip": True, "reason": "Photo ignored because secretary image handling is disabled"}
        from bot.handlers.message_handlers import _save_image_from_telegram

        media_result = await _save_image_from_telegram(message, message.photo[-1].file_id, "image/jpeg")
        if media_result:
            result["attachments"].append(media_result)
            result["image_path"] = media_result.get("path")
            result["image_mime"] = media_result.get("mime")
            result["telegram_file_id"] = media_result.get("telegram_file_id")
            result["content_type"] = "image"
        return result

    if message.document:
        document = message.document
        if not document.mime_type or not document.mime_type.startswith("image/"):
            return {"skip": True, "reason": "Document ignored because only images are supported"}
        if not runtime_settings.get("media_images_enabled", False):
            return {"skip": True, "reason": "Image document ignored because secretary image handling is disabled"}
        from bot.handlers.message_handlers import _save_image_from_telegram

        media_result = await _save_image_from_telegram(message, document.file_id, document.mime_type)
        if media_result:
            result["attachments"].append(media_result)
            result["image_path"] = media_result.get("path")
            result["image_mime"] = media_result.get("mime")
            result["telegram_file_id"] = media_result.get("telegram_file_id")
            result["content_type"] = "image"
        return result

    if message.voice or message.video_note:
        if not runtime_settings.get("media_stt_enabled", False):
            return {"skip": True, "reason": "Voice/video note ignored because secretary STT is disabled"}
        from config.settings import settings_manager

        if not settings_manager.get_settings().get("stt_enabled", False):
            return {"skip": True, "reason": "Voice/video note ignored because global STT is disabled"}
        from bot.handlers.message_handlers import _transcribe_voice_message

        transcribed_text = (await _transcribe_voice_message(message)).strip()
        if not transcribed_text:
            return {"skip": True, "reason": "Voice/video note STT returned empty text"}
        prefix = "[Кружочек]" if message.video_note else "[Голосовое]"
        result["text"] = f"{prefix}: {transcribed_text}"
        result["content_type"] = "video_note" if message.video_note else "voice"
        return result

    return result


def _is_outgoing_business_message(message: types.Message, owner_id: int) -> bool:
    sender_business_bot = getattr(message, "sender_business_bot", None)
    if sender_business_bot is not None:
        return True
    from_user = getattr(message, "from_user", None)
    if from_user is None:
        return False
    try:
        author_id = int(from_user.id)
    except (TypeError, ValueError):
        return False
    if author_id == int(owner_id):
        return True
    if server_state.bot_id and author_id == int(server_state.bot_id):
        return True
    return False


def _is_stale_business_message(message: types.Message) -> bool:
    message_date = getattr(message, "date", None)
    started_at = getattr(server_state, "bot_started_at_utc", None)
    if not message_date or not started_at:
        return False
    if message_date.tzinfo is None:
        message_date = message_date.replace(tzinfo=datetime.timezone.utc)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=datetime.timezone.utc)
    return message_date < (started_at - datetime.timedelta(seconds=5))


def _message_preview(message: types.Message) -> str:
    if not message:
        return ""
    text = (message.text or message.caption or "").strip()
    if text:
        preview = text.replace("\n", " ").strip()
    elif message.photo:
        preview = "[Фото]"
    elif message.video:
        preview = "[Видео]"
    elif message.video_note:
        preview = "[Кружочек]"
    elif message.voice:
        preview = "[Голосовое]"
    elif message.document:
        preview = "[Документ]"
    elif message.sticker:
        preview = "[Стикер]"
    else:
        preview = "[Неподдержанное сообщение]"
    return preview[:157] + "..." if len(preview) > 160 else preview


def _extract_secretary_reply_context(message: types.Message, owner_id: int) -> str:
    reply = message.reply_to_message
    quote = getattr(message, "quote", None)
    if not reply and not quote:
        return ""

    if quote and getattr(quote, "text", None):
        preview = str(quote.text).strip().replace("\n", " ")
        prefix = "Цитата"
    elif reply:
        preview = _message_preview(reply)
        prefix = "Ответ"
    else:
        return ""

    author = "сообщение"
    if reply and reply.from_user:
        if int(reply.from_user.id) == int(owner_id):
            author = "владельца"
        elif reply.from_user.is_bot:
            author = "ответ бота"
        else:
            author = _user_display(reply.from_user)
    elif reply and reply.sender_chat:
        author = reply.sender_chat.title or "чат"

    return f'{prefix} на {author}: "{preview}"'


def _build_secretary_content(message: types.Message, reply_context: str = "", media_text: str | None = None) -> str:
    parts = []
    base_text = (media_text or message.text or message.caption or "").strip()
    if base_text:
        parts.append(base_text)
    else:
        placeholder = _message_preview(message)
        if placeholder:
            parts.append(placeholder)
    if reply_context:
        parts.insert(0, reply_context)
    return "\n\n".join(part for part in parts if part).strip()


def _parse_chat_ids(raw_value):
    if raw_value is None:
        return set()
    if isinstance(raw_value, (list, tuple, set)):
        raw_items = raw_value
    else:
        raw_items = str(raw_value).replace(",", "\n").replace(";", "\n").splitlines()

    chat_ids = set()
    for item in raw_items:
        text = str(item).strip()
        if not text:
            continue
        try:
            chat_ids.add(int(text))
        except ValueError:
            logger.warning("Secretary chat_id skipped because it is not an integer: %s", text)
    return chat_ids


def _is_chat_allowed(profile: dict, chat_id: int) -> tuple[bool, str]:
    blocked_chats = _parse_chat_ids(profile.get("blocked_chats"))
    if int(chat_id) in blocked_chats:
        return False, "Chat is blocked by secretary profile"

    allowed_chats = _parse_chat_ids(profile.get("allowed_chats"))
    if allowed_chats and int(chat_id) not in allowed_chats:
        return False, "Chat is not in secretary allowed_chats"

    return True, ""
