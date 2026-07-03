import datetime
import mimetypes
import os
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from aiogram import types

from bot.handlers.queue_manager import (
    clean_hidden_characters,
    message_counter,
    request_queue,
    user_locks,
)
from bot.handlers.services.model_client_manager import has_active_vlm_model
from bot.handlers.services.access_control import (
    bot_command_targets_username,
    build_request_context,
    is_bot_message_allowed,
)
from bot.handlers.services.telegram_utils import send_ephemeral_reply
from config.settings import settings_manager
from utils.database.backlog_writer import backlog_message_writer
from utils import server_state, stats
from utils.database.database_manager import DatabaseManager
from utils.logger import setup_logger
from utils.voice_processor import voice_processor

logger = setup_logger(__name__)

UPLOADS_DIR = Path("assets") / "uploads"
USER_ACTIVITY_MIN_INTERVAL_SECONDS = 60
KNOWN_GROUP_CHATS: Dict[int, Tuple[Optional[str], Optional[str]]] = {}


def _ensure_uploads_dir() -> Path:
    try:
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return UPLOADS_DIR


def _build_full_name(user: types.User) -> str:
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    return full_name or (user.username or "") or "User"


async def _transcribe_voice_message(message: types.Message) -> str:
    media = message.voice or message.video_note
    if not media:
        return ""

    file_info = await message.bot.get_file(media.file_id)
    uploads_dir = _ensure_uploads_dir()
    suffix = Path(file_info.file_path).suffix or (".ogg" if message.voice else ".mp4")
    media_path = str(uploads_dir / f"{uuid4().hex}{suffix}")
    await message.bot.download_file(file_info.file_path, media_path)

    try:
        return await voice_processor.transcribe_media(media_path)
    finally:
        if os.path.exists(media_path):
            os.remove(media_path)


async def _extract_reply_annotation(
    message: types.Message,
    db: DatabaseManager,
    settings: Dict,
) -> Optional[str]:
    reply = message.reply_to_message
    quote = getattr(message, "quote", None)

    if not reply and not quote:
        return None

    author = "Сообщение"
    if reply:
        if reply.from_user:
            author = _build_full_name(reply.from_user)
        elif reply.sender_chat:
            author = reply.sender_chat.title or "Сообщение"

    preview = None

    if quote:
        quote_text = getattr(quote, "text", None)
        if not quote_text and reply and reply.text and hasattr(quote, "position") and hasattr(quote, "length"):
            start = max(0, quote.position)
            end = start + max(0, quote.length)
            quote_text = reply.text[start:end]
        if quote_text:
            preview = quote_text.strip()

    if preview is None:
        if not reply:
            return None

        if reply.text:
            preview = reply.text.strip()
        elif reply.caption:
            preview = reply.caption.strip()
        else:
            record = db.messages.get_message_by_telegram_id(reply.message_id, message.chat.id)
            if record and record.get("content"):
                preview = str(record.get("content") or "").strip()
            elif (reply.voice or reply.video_note) and settings.get("stt_enabled", False):
                try:
                    preview = (await _transcribe_voice_message(reply)).strip()
                except Exception as exc:
                    logger.warning("Не удалось распознать аудио из reply %s: %s", reply.message_id, exc)
            
            if not preview:
                if reply.photo:
                    preview = "[Фото]"
                elif reply.video:
                    preview = "[Видео]"
                elif reply.video_note:
                    preview = "[Кружочек]"
                elif reply.voice:
                    preview = "[Голосовое]"
                elif reply.document:
                    preview = "[Документ]"
                elif reply.sticker:
                    preview = "[Стикер]"

    if not preview:
        return None

    preview = preview.replace("\n", " ").strip()
    if len(preview) > 160:
        preview = preview[:157] + "..."

    prefix = "Цитата" if quote else "Ответ"
    return f'{prefix} на {author}: "{preview}"'


@dataclass
class AddressingDecision:
    should_process: bool
    has_explicit_mention: bool
    text_without_mentions: str


def _strip_spans(text: str, spans: List[Tuple[int, int]]) -> str:
    if not spans or not text:
        return text
    result = []
    last_index = 0
    for start, end in sorted(spans):
        if start > last_index:
            result.append(text[last_index:start])
        last_index = max(last_index, end)
    result.append(text[last_index:])
    return "".join(result)


def _evaluate_addressing(
    message: types.Message,
    *,
    respond_only_on_mention: bool,
) -> AddressingDecision:
    bot_id = server_state.bot_id
    bot_username = (server_state.bot_username or "").lower()
    if message.text is not None:
        text = message.text
        entities = message.entities or []
    else:
        text = message.caption or ""
        entities = message.caption_entities or []

    mention_spans: List[Tuple[int, int]] = []
    has_explicit_mention = False
    has_foreign_bot_command = False

    for entity in entities:
        entity_text = text[entity.offset: entity.offset + entity.length] if text else ""
        if entity.type == "mention" and bot_username:
            if entity_text.lower() == f"@{bot_username}":
                has_explicit_mention = True
                mention_spans.append((entity.offset, entity.offset + entity.length))
        elif entity.type == "text_mention" and entity.user:
            if bot_id is None or entity.user.id == bot_id:
                has_explicit_mention = True
                mention_spans.append((entity.offset, entity.offset + entity.length))
        elif entity.type == "bot_command":
            lower_text = entity_text.lower()
            targets_current_bot = bot_command_targets_username(lower_text, bot_username)
            if "@" in lower_text and not targets_current_bot:
                has_foreign_bot_command = True
                continue
            if targets_current_bot and not respond_only_on_mention:
                has_explicit_mention = True
                mention_spans.append((entity.offset, entity.offset + entity.length))
            elif targets_current_bot and bot_username and lower_text.endswith(f"@{bot_username}"):
                has_explicit_mention = True
                mention_spans.append((entity.offset, entity.offset + entity.length))

    if bot_username and f"@{bot_username}" in (text or ""):
        has_explicit_mention = True

    reply_to_bot = False
    if message.reply_to_message and message.reply_to_message.from_user:
        replied_user = message.reply_to_message.from_user
        if replied_user.is_bot and (bot_id is None or replied_user.id == bot_id):
            reply_to_bot = True

    text_without_mentions = _strip_spans(text, mention_spans).strip()

    if has_foreign_bot_command:
        logger.debug(
            "Сообщение в чате %s проигнорировано: команда адресована другому боту",
            message.chat.id,
        )
        return AddressingDecision(False, False, text_without_mentions)

    if message.chat.type == "private":
        return AddressingDecision(True, has_explicit_mention, text_without_mentions)

    if respond_only_on_mention:
        should_process = has_explicit_mention
        if not should_process:
            logger.debug(
                "Сообщение в чате %s проигнорировано: включён режим только по упоминанию",
                message.chat.id,
            )
    else:
        should_process = has_explicit_mention or reply_to_bot
        if not should_process:
            logger.debug(
                "Сообщение в чате %s проигнорировано: нет упоминания и это не ответ боту",
                message.chat.id,
            )

    return AddressingDecision(should_process, has_explicit_mention, text_without_mentions)


def _has_active_vlm_model() -> bool:
    try:
        return has_active_vlm_model(sync_if_needed=True)
    except Exception:
        return False


async def _save_image_from_telegram(
    message: types.Message,
    file_id: str,
    mime_hint: Optional[str],
) -> Optional[dict]:
    try:
        file = await message.bot.get_file(file_id)
        download_stream = await message.bot.download_file(file.file_path)
        if isinstance(download_stream, BytesIO):
            data = download_stream.getvalue()
        else:
            data = download_stream.read()

        mime = mime_hint or mimetypes.guess_type(file.file_path)[0] or "image/jpeg"
        suffix = Path(file.file_path).suffix or mimetypes.guess_extension(mime) or ".jpg"

        uploads_dir = _ensure_uploads_dir()
        filename = f"{uuid4().hex}{suffix}"
        target_path = uploads_dir / filename
        with open(target_path, "wb") as f:
            f.write(data)

        return {"path": str(target_path), "telegram_file_id": file_id, "mime": mime}
    except Exception as exc:
        logger.error(f"Не удалось сохранить изображение Telegram: {exc}")
        return None


async def _resolve_reply_attachments(message: types.Message, db: DatabaseManager) -> List[dict]:
    reply = message.reply_to_message
    if not reply:
        return []

    chat_id = message.chat.id
    attachments: List[dict] = []

    try:
        record = db.messages.get_message_by_telegram_id(reply.message_id, chat_id)
    except Exception:
        record = None

    if record and record.get("image_path"):
        attachments.append({
            "path": record.get("image_path"),
            "mime": record.get("image_mime"),
        })
        return attachments

    media_result = None
    if reply.photo:
        media_result = await _save_image_from_telegram(reply, reply.photo[-1].file_id, "image/jpeg")
    elif reply.document and reply.document.mime_type and reply.document.mime_type.startswith("image/"):
        media_result = await _save_image_from_telegram(reply, reply.document.file_id, reply.document.mime_type)

    if media_result:
        path = media_result["path"]
        mime = media_result["mime"]
        updated = db.messages.update_message_image(reply.message_id, chat_id, path, mime)
        if not updated and record:
            logger.warning("Не удалось обновить запись изображения для сообщения %s", reply.message_id)
        attachments.append({"path": path, "mime": mime})

    return attachments


def _build_content_for_storage(base_text: str, prefix: Optional[str]) -> str:
    if prefix and base_text:
        return f"{prefix}\n{base_text}".strip()
    return (prefix or base_text or "").strip()


def _build_message_record(
    user_id: int,
    content: str,
    *,
    chat_id: int,
    chat_type: str,
    chat_title: Optional[str],
    author_telegram_id: int,
    author_username: Optional[str],
    author_full_name: str,
    telegram_message_id: int,
    reply_to_message_id: Optional[int],
    content_type: str,
    image_path: Optional[str],
    image_mime: Optional[str],
    telegram_file_id: Optional[str],
    is_addressed: int,
    author_is_bot: int,
    source_mode: str,
    secretary_owner_telegram_id: Optional[int] = None,
) -> Dict:
    return {
        "user_id": user_id,
        "role": "user",
        "content": content,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "chat_title": chat_title,
        "author_telegram_id": author_telegram_id,
        "author_username": author_username,
        "author_full_name": author_full_name,
        "telegram_message_id": telegram_message_id,
        "reply_to_message_id": reply_to_message_id,
        "content_type": content_type,
        "image_path": image_path,
        "image_mime": image_mime,
        "telegram_file_id": telegram_file_id,
        "is_addressed": is_addressed,
        "author_is_bot": author_is_bot,
        "source_mode": source_mode,
        "secretary_owner_telegram_id": secretary_owner_telegram_id,
    }


def _update_backlog_state(is_old: bool) -> None:
    if is_old:
        server_state.is_catching_up = True
        server_state.backlog_processed_count += 1
        server_state.last_backlog_message_at = time.monotonic()


def _maybe_update_chat_metadata(db: DatabaseManager, chat_id: int, chat_title: Optional[str], chat_type: Optional[str]) -> None:
    known_chat_state = KNOWN_GROUP_CHATS.get(chat_id)
    current_chat_state = (chat_title, chat_type)
    if known_chat_state != current_chat_state:
        db.messages.update_chat(chat_id, chat_title=chat_title, chat_type=chat_type)
        KNOWN_GROUP_CHATS[chat_id] = current_chat_state


def _handle_group_migration(message: types.Message) -> bool:
    migrate_to_chat_id = getattr(message, "migrate_to_chat_id", None)
    migrate_from_chat_id = getattr(message, "migrate_from_chat_id", None)
    if not migrate_to_chat_id and not migrate_from_chat_id:
        return False

    if migrate_to_chat_id:
        old_chat_id = message.chat.id
        new_chat_id = int(migrate_to_chat_id)
    else:
        old_chat_id = int(migrate_from_chat_id)
        new_chat_id = message.chat.id

    chat_title = getattr(message.chat, "title", None)
    db = DatabaseManager()
    try:
        migrated = db.messages.migrate_group_chat(
            old_chat_id,
            new_chat_id,
            chat_title=chat_title,
            chat_type="supergroup",
        )
    finally:
        db.close()

    KNOWN_GROUP_CHATS.pop(old_chat_id, None)
    KNOWN_GROUP_CHATS[new_chat_id] = (chat_title, "supergroup")
    return migrated


async def message_handler(message: types.Message):
    if not server_state.server_active:
        return

    if _handle_group_migration(message):
        return

    is_voice = message.content_type in {"voice", "video_note"}
    if message.content_type not in {"text", "photo", "document", "voice", "video_note"}:
        return

    raw_text = ""
    msg_age = (datetime.datetime.now(datetime.timezone.utc) - message.date).total_seconds()
    is_old = msg_age > 20
    _update_backlog_state(is_old)

    telegram_id = message.from_user.id
    author_is_bot = bool(getattr(message.from_user, "is_bot", False))
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    author_full_name = _build_full_name(message.from_user)

    chat = message.chat
    chat_id = chat.id
    chat_type = chat.type
    chat_title = getattr(chat, "title", None)

    vlm_available = _has_active_vlm_model()
    settings = settings_manager.get_settings()
    if author_is_bot:
        allowed, reason = is_bot_message_allowed(
            settings,
            bot_telegram_id=telegram_id,
            chat_type=chat_type,
            source_mode="bot_to_bot",
        )
        if not allowed:
            logger.debug(
                "Bot message ignored by bot access policy (%s, telegram_id=%s, chat_id=%s)",
                reason,
                telegram_id,
                chat_id,
            )
            return

    if message.content_type == "text" and chat_type == "private" and not author_is_bot:
        try:
            from bot.handlers.menu_handlers import consume_menu_text_input

            if await consume_menu_text_input(message):
                return
        except Exception as exc:
            logger.error("Ошибка обработки ожидаемого ввода меню: %s", exc)

    source_mode = "bot_to_bot" if author_is_bot else "normal"
    respond_only_on_mention = settings.get("respond_only_on_mention", False)
    reject_empty_mentions = settings.get("reject_empty_mentions", True)
    addressing = _evaluate_addressing(message, respond_only_on_mention=respond_only_on_mention)

    db = DatabaseManager()
    try:
        user = db.users.ensure_user(telegram_id, username, first_name, last_name)
        if not user:
            return

        if not is_old:
            db.users.update_user_activity(
                telegram_id,
                min_interval_seconds=USER_ACTIVITY_MIN_INTERVAL_SECONDS,
            )

        if user.get("is_banned", 0):
            logger.debug("Пользователь %s заблокирован, пропускаем обработку", telegram_id)
            return

        if chat_type in {"group", "supergroup"}:
            _maybe_update_chat_metadata(db, chat_id, chat_title, chat_type)
            if db.messages.is_group_banned(chat_id):
                logger.debug("Группа %s заблокирована, пропускаем обработку", chat_id)
                return

        reply_annotation = await _extract_reply_annotation(message, db, settings)
        attachments: List[dict] = []
        image_path: Optional[str] = None
        image_mime: Optional[str] = None
        telegram_file_id: Optional[str] = None

        if message.content_type == "photo":
            media_result = await _save_image_from_telegram(message, message.photo[-1].file_id, "image/jpeg")
            if media_result:
                attachments.append(media_result)
                image_path = media_result["path"]
                image_mime = media_result["mime"]
                telegram_file_id = media_result.get("telegram_file_id")
        elif message.content_type in {"voice", "video_note"}:
            if not settings.get("stt_enabled", False):
                if addressing.should_process:
                    await send_ephemeral_reply(message, "Поддержка голосовых сообщений и кружочков отключена в настройках.")
                return

            try:
                transcribed_text = await _transcribe_voice_message(message)
                if transcribed_text:
                    raw_text = transcribed_text
                    transcribed_text = f"[length={len(raw_text)}]"
                    logger.info("Аудио-сообщение (%s) от %s распознано: %s", message.content_type, telegram_id, transcribed_text)
                    transcribed_text = raw_text
                    if settings.get("stt_annotate", False):
                        prefix = "[Кружочек]" if message.content_type == "video_note" else "[Голосовое]"
                        reply_annotation = f"{prefix}: {reply_annotation}" if reply_annotation else prefix
                else:
                    if addressing.should_process:
                        await send_ephemeral_reply(message, "Не удалось распознать речь в голосовом сообщении или кружочке.")
                    return
            except Exception as exc:
                logger.error(f"Ошибка распознавания речи: {exc}")
                if addressing.should_process:
                    await send_ephemeral_reply(
                        message,
                        "Произошла ошибка при обработке голосового сообщения или кружочка. Пожалуйста, попробуйте ещё раз.",
                    )
                return
        elif message.content_type == "document":
            document = message.document
            if not document.mime_type or not document.mime_type.startswith("image/"):
                if addressing.should_process:
                    await send_ephemeral_reply(
                        message,
                        "Пока поддерживаются только изображения (фото или картинки).",
                    )
                return
            media_result = await _save_image_from_telegram(message, document.file_id, document.mime_type)
            if media_result:
                attachments.append(media_result)
                image_path = media_result["path"]
                image_mime = media_result["mime"]
                telegram_file_id = media_result.get("telegram_file_id")

        if message.content_type == "text":
            reply_images = await _resolve_reply_attachments(message, db)
            if reply_images:
                attachments.extend(reply_images)
                if not image_path:
                    image_path = reply_images[0]["path"]
                    image_mime = reply_images[0].get("mime")

        if chat_type == "private":
            chat_title = chat_title or author_full_name

        if not is_voice:
            raw_text = message.text or message.caption or ""
            mentionless_text = addressing.text_without_mentions or ""
        else:
            mentionless_text = raw_text

        text_clean = clean_hidden_characters(raw_text)
        mentionless_clean = clean_hidden_characters(mentionless_text)
        stored_content = _build_content_for_storage(text_clean, reply_annotation)
        payload_content = _build_content_for_storage(mentionless_clean, reply_annotation)

        content_type_value = "text"
        if attachments and message.content_type in {"photo", "document"}:
            content_type_value = "image"
        elif attachments:
            content_type_value = "image_ref"
        elif message.content_type == "voice":
            content_type_value = "voice"
        elif message.content_type == "video_note":
            content_type_value = "video_note"

        has_meaningful_payload = bool(payload_content.strip()) or bool(attachments)

        if addressing.should_process and respond_only_on_mention and reject_empty_mentions and not has_meaningful_payload:
            await send_ephemeral_reply(
                message,
                "Добавьте текст или вложение к обращению, чтобы я мог ответить.",
            )
            should_process = False
        else:
            should_process = addressing.should_process

        if is_old:
            should_process = False

        if not stored_content and not attachments:
            if should_process:
                await send_ephemeral_reply(message, "Пожалуйста, отправьте текстовое сообщение.")
            return

        reply_to_message_id = message.reply_to_message.message_id if message.reply_to_message else None
        request_context = build_request_context(
            settings=settings,
            user=user,
            actor_telegram_id=telegram_id,
            chat_id=chat_id,
            chat_type=chat_type,
            author_is_bot=author_is_bot,
            is_addressed=bool(should_process),
            source_mode=source_mode,
        )

        message_record = _build_message_record(
            user["id"],
            stored_content,
            chat_id=chat_id,
            chat_type=chat_type,
            chat_title=chat_title,
            author_telegram_id=telegram_id,
            author_username=username,
            author_full_name=author_full_name,
            telegram_message_id=message.message_id,
            reply_to_message_id=reply_to_message_id,
            content_type=content_type_value,
            image_path=image_path,
            image_mime=image_mime,
            telegram_file_id=telegram_file_id,
            is_addressed=int(should_process),
            author_is_bot=int(author_is_bot),
            source_mode=source_mode,
        )

        if is_old:
            await backlog_message_writer.enqueue(message_record)
        else:
            db.messages.add_message(
                message_record["user_id"],
                message_record["role"],
                message_record["content"],
                chat_id=message_record["chat_id"],
                chat_type=message_record["chat_type"],
                chat_title=message_record["chat_title"],
                author_telegram_id=message_record["author_telegram_id"],
                author_username=message_record["author_username"],
                author_full_name=message_record["author_full_name"],
                telegram_message_id=message_record["telegram_message_id"],
                reply_to_message_id=message_record["reply_to_message_id"],
                content_type=message_record["content_type"],
                image_path=message_record["image_path"],
                image_mime=message_record["image_mime"],
                telegram_file_id=message_record["telegram_file_id"],
                is_addressed=message_record["is_addressed"],
                author_is_bot=message_record["author_is_bot"],
                source_mode=message_record["source_mode"],
                secretary_owner_telegram_id=message_record["secretary_owner_telegram_id"],
            )

        if not should_process:
            return

        # Требование VLM определяется наличием вложений, но если VLM сейчас недоступен,
        # деградируем в text-only без агрессивных сообщений.
        requires_vision = bool(attachments) and vlm_available

        # Практический минимум: если пользователь прислал только изображение без текста,
        # а VLM нет, не отправляем "пустой" запрос в LLM — просим добавить текст-задание.
        if attachments and not vlm_available and not (payload_content or "").strip():
            await send_ephemeral_reply(
                message,
                "Добавьте текст-задание к изображению, чтобы я мог помочь.",
            )
            return

        user_id = user["id"]
        enqueue_success = False
        if user_locks.get(user_id, False):
            logger.debug(
                "Пользователь %s отправил запрос, но предыдущий ещё обрабатывается",
                user_id,
            )
            return

        user_locks[user_id] = True

        user_priority = int(user.get("priority") or 0)
        queue_priority = -user_priority
        counter = await message_counter.increment()

        enqueue_time = time.time()
        payload = {
            "attachments": attachments,
            "requires_vision": requires_vision,
            "retry_count": 0,
            "user_priority": user_priority,
            "text_content": payload_content,
            "request_context": request_context.to_dict(),
        }
        await request_queue.put((queue_priority, counter, message, user, enqueue_time, payload))
        stats.stats.increment_pending_requests()
        enqueue_success = True

        logger.debug(
            "Запрос пользователя %s добавлен в очередь (user_priority=%s, queue_priority=%s, chat_id=%s, chat_type=%s, requires_vision=%s)",
            telegram_id,
            user_priority,
            queue_priority,
            chat_id,
            chat_type,
            requires_vision,
        )

    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")
        if 'user_id' in locals() and not enqueue_success:
            user_locks[user_id] = False
    finally:
        db.close()


async def edited_message_handler(message: types.Message):
    if not message.edit_date:
        return

    try:
        chat_id = message.chat.id
        telegram_message_id = message.message_id
        new_content = message.text or ""

        db = DatabaseManager()
        try:
            success = db.messages.update_message_content(telegram_message_id, chat_id, new_content)
            if success:
                logger.info(
                    "Сообщение telegram_id=%s было отредактировано в чате %s",
                    telegram_message_id,
                    chat_id,
                )
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Ошибка при обработке редактирования сообщения: {e}")


async def deleted_message_handler(message: types.Message):
    try:
        chat_id = message.chat.id
        telegram_message_id = message.message_id

        db = DatabaseManager()
        try:
            success = db.messages.mark_message_as_deleted(telegram_message_id, chat_id)
            if success:
                logger.info(
                    "Сообщение telegram_id=%s было удалено из чата %s",
                    telegram_message_id,
                    chat_id,
                )
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Ошибка при обработке удаления сообщения: {e}")
