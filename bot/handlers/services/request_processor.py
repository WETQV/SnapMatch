# bot/handlers/services/request_processor.py
"""
Сервис для обработки отдельного запроса пользователя.
Содержит основную логику async process_request.
"""

import asyncio
import hashlib
import random
import time
import re
import random
from typing import Dict, Optional
from copy import deepcopy

from utils import server_state, stats
from utils.database.database_manager import DatabaseManager
from utils.logger import setup_logger
from utils.markdown_formatter import telegram_formatter
from utils.tokenizer import count_tokens, count_message_tokens
from utils.history_manager import get_history_summarizer

from .text_cleaner import clean_response
from .message_processor import prepare_model_messages
from .role_manager import ensure_alternating_roles
from .context_manager import adjust_history_for_context_limit, trim_messages_to_context_limit
from .context_snapshot import build_group_context_snapshot
from .image_processor import build_image_data_url, redownload_image
from .model_client_manager import (
    get_response_from_model,
    stream_from_model,
    is_anthropic_client,
    get_model_stats_lock,
    model_usage_stats,
    model_capabilities,
    select_model_for_request,
    active_models,
)
from .mcp_permissions import allowed_openai_tools_for_context
from .mcp_runtime import is_mcp_sdk_available
from .rich_message_sender import (
    prepare_legacy_fallback_text,
    rich_message_streaming_enabled,
    rich_messages_fallback_enabled,
    try_send_rich_message,
    try_send_rich_message_draft,
)
from .telegram_utils import send_ephemeral_reply

logger = setup_logger(__name__)


async def _mark_secretary_message_read(message, db: DatabaseManager, owner_id: Optional[int], chat_id: int) -> None:
    business_connection_id = getattr(message, "business_connection_id", None)
    message_id = getattr(message, "message_id", None)
    if not business_connection_id or not message_id:
        return
    try:
        await message.bot.read_business_message(
            business_connection_id=business_connection_id,
            chat_id=chat_id,
            message_id=message_id,
        )
        if owner_id is not None:
            db.secretary.add_event(owner_id, "read", f"message_id={message_id}", chat_id=chat_id)
    except Exception as exc:
        logger.warning("Secretary readBusinessMessage failed: chat_id=%s message_id=%s error=%s", chat_id, message_id, exc)
        if owner_id is not None:
            db.secretary.add_event(owner_id, "read_failed", str(exc)[:180], chat_id=chat_id)

# Константы
LEGACY_IMAGE_PLACEHOLDER = "[изображение пользователя]"
ROLE_PLACEHOLDER_TEXT = "[нет ответа — служебный плейсхолдер]"
ROLE_PLACEHOLDER_PROMPT_HINT = (
    "Если в истории встречаются строки в квадратных скобках (например, "
    "'[нет ответа — служебный плейсхолдер]'), воспринимай их как системные метки, "
    "а не как готовый ответ. Сформулируй собственный осмысленный ответ."
)
RICH_MARKDOWN_PROMPT_HINT = (
    "Форматируй ответы в Telegram Rich Markdown. Для формул используй $inline$ и "
    "$$block$$ или ```math, не используй LaTeX-разделители \\[...\\] и \\(...\\). "
    "Таблицы пиши в GitHub-flavored Markdown с корректной строкой разделителей для всех колонок."
)


def _apply_user_preferences(settings: Dict, user: Dict, db: DatabaseManager) -> Dict:
    if not user:
        return settings
    preferences = db.users.get_user_preferences(user)
    if not preferences:
        return settings
    merged = dict(settings)
    for key in ("stream_mode", "format_markdown", "format_html"):
        if key in preferences:
            merged[key] = bool(preferences.get(key))
    return merged


async def response_watchdog(message, model_id, user, watchdog_delay: int = 600):
    """Отправляет предупреждение если модель долго обрабатывает запрос."""
    try:
        await asyncio.sleep(watchdog_delay)
        logger.warning(
            f"Долгая генерация ответа: модель {model_id} обрабатывает запрос пользователя "
            f"{user.get('telegram_id')} уже более {watchdog_delay // 60} минут"
        )
        warning_text = (
            "⏳ Модель всё ещё формирует ответ. Пожалуйста, подождите — запрос обрабатывается."
        )
        try:
            await send_ephemeral_reply(message, warning_text)
        except Exception as warn_e:
            logger.warning(f"Не удалось отправить предупреждение о долгой генерации: {warn_e}")
    except asyncio.CancelledError:
        pass


async def send_typing_action(bot, chat_id):
    """Отправляет статус "печатает" каждые 4 секунды."""
    try:
        while True:
            try:
                await bot.send_chat_action(chat_id=chat_id, action='typing')
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Не удалось отправить статус набора текста (chat_id=%s): %s",
                    chat_id,
                    exc,
                )
                break
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


def _format_author_display_name(message_record: Dict) -> str:
    """Формирует отображаемое имя автора сообщения."""
    author = (
        message_record.get("author_username")
        or message_record.get("author_full_name")
        or (f"user_{message_record.get('author_telegram_id')}" if message_record.get("author_telegram_id") else "Пользователь")
    )
    if message_record.get("author_is_bot"):
        return f"Bot @{author}" if message_record.get("author_username") else f"Bot {author}"
    return author


def _telegram_user_display_name(user_obj) -> str:
    if not user_obj:
        return ""
    full_name = " ".join(
        part
        for part in [
            getattr(user_obj, "first_name", "") or "",
            getattr(user_obj, "last_name", "") or "",
        ]
        if part
    ).strip()
    return full_name or getattr(user_obj, "username", "") or str(getattr(user_obj, "id", "") or "")


def _dict_user_display_name(user_data: Dict) -> str:
    if not user_data:
        return ""
    full_name = " ".join(
        part
        for part in [
            user_data.get("first_name") or "",
            user_data.get("last_name") or "",
        ]
        if part
    ).strip()
    return full_name or user_data.get("username") or str(user_data.get("telegram_id") or "")


def _secretary_prompt_placeholders(request_context: Dict, user: Dict, message, chat_id: int) -> Dict[str, str]:
    if not isinstance(request_context, dict):
        return {}
    has_secretary_context = (
        request_context.get("source_mode") == "secretary"
        or request_context.get("secretary_owner_telegram_id") is not None
        or request_context.get("secretary_source_chat_id") is not None
        or request_context.get("business_connection_id")
    )
    if not has_secretary_context:
        return {}

    owner_id = request_context.get("secretary_owner_telegram_id") or (user or {}).get("telegram_id")
    counterparty_id = request_context.get("secretary_counterparty_id")
    from_user = getattr(message, "from_user", None)
    if counterparty_id is None and from_user is not None:
        counterparty_id = getattr(from_user, "id", None)

    return {
        "{{owner_name}}": _dict_user_display_name(user),
        "{{owner_id}}": str(owner_id or ""),
        "{{counterparty_name}}": _telegram_user_display_name(from_user),
        "{{counterparty_id}}": str(counterparty_id or ""),
        "{{secretary_chat_id}}": str(request_context.get("secretary_source_chat_id") or chat_id or ""),
    }


def _is_error_response(text: str) -> bool:
    """Проверяет, является ли ответ сообщением об ошибке."""
    if not text:
        return False
    error_prefixes = [
        "Извините, произошла ошибка",
        "Извините, модель",
        "Извините, не получилось",
        "Извините, ответ не сформирован",
        "Извините, не могу сформулировать",
        "Извините, ваш аккаунт",
        "Sorry, an error occurred",
        "Sorry, the model",
        "Sorry, I couldn't",
    ]
    text_lower = text.strip().lower()
    return any(text_lower.startswith(prefix.lower()) for prefix in error_prefixes)


async def _handle_secretary_response(
    *,
    db: DatabaseManager,
    message,
    user: Dict,
    payload: Dict,
    cleaned_response: str,
    response_text: str,
    model_id: str,
    chat_id: int,
    chat_type: str,
    chat_title: Optional[str],
    secretary_owner_telegram_id: Optional[int],
    secretary_source_chat_id: Optional[int],
) -> None:
    secretary_payload = payload.get("secretary") if isinstance(payload, dict) else {}
    secretary_payload = secretary_payload or {}
    mode = (secretary_payload.get("response_mode") or "draft").lower()
    business_connection_id = secretary_payload.get("business_connection_id") or getattr(message, "business_connection_id", None)
    session_id = secretary_payload.get("session_id")
    counterparty_id = getattr(message.from_user, "id", None) if getattr(message, "from_user", None) else None

    if _is_error_response(cleaned_response) or _is_error_response(response_text):
        db.secretary.add_event(
            secretary_owner_telegram_id,
            "error",
            "Secretary model response was an error",
            chat_id=chat_id,
        )
        return

    reply_status = "sent" if mode == "auto" else ("pending_confirm" if mode == "confirm" else "drafted")
    save_history = bool(secretary_payload.get("save_history", True))
    reply_to_message_id = getattr(message, "message_id", None)

    if mode == "auto":
        if reply_to_message_id:
            lock_owner_id = int(secretary_owner_telegram_id)
            lock_chat_id = int(secretary_source_chat_id or chat_id)
            lock_message_id = int(reply_to_message_id)
            if db.messages.has_secretary_assistant_reply(lock_owner_id, lock_chat_id, lock_message_id):
                db.secretary.add_event(
                    secretary_owner_telegram_id,
                    "skipped",
                    f"Duplicate auto response suppressed by history for message_id={reply_to_message_id}",
                    chat_id=chat_id,
                )
                return
            if not db.secretary.claim_response_lock(lock_owner_id, lock_chat_id, lock_message_id):
                db.secretary.add_event(
                    secretary_owner_telegram_id,
                    "skipped",
                    f"Duplicate auto response suppressed by lock for message_id={reply_to_message_id}",
                    chat_id=chat_id,
                )
                return
        transport = await _send_response_in_parts(message, cleaned_response, response_text, model_id, user["telegram_id"])
        if reply_to_message_id:
            db.secretary.mark_response_lock_sent(
                int(secretary_owner_telegram_id),
                int(secretary_source_chat_id or chat_id),
                int(reply_to_message_id),
            )
        db.secretary.add_event(
            secretary_owner_telegram_id,
            "sent",
            f"Auto response sent via {transport or 'legacy'}",
            chat_id=chat_id,
        )
    elif mode == "confirm":
        if not business_connection_id:
            db.secretary.add_event(
                secretary_owner_telegram_id,
                "error",
                "Missing business_connection_id for confirmation response",
                chat_id=chat_id,
            )
            return
        from aiogram.utils.keyboard import InlineKeyboardBuilder

        pending_id = db.secretary.create_pending_response(
            secretary_owner_telegram_id,
            business_connection_id,
            chat_id,
            cleaned_response,
            session_id=session_id,
            reply_to_message_id=message.message_id,
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="Отправить", callback_data=f"secretary:send:{pending_id}")
        builder.button(text="Отмена", callback_data=f"secretary:cancel:{pending_id}")
        builder.adjust(2)
        await message.bot.send_message(
            secretary_owner_telegram_id,
            "Черновик ответа секретаря:\n\n"
            f"{cleaned_response}",
            reply_markup=builder.as_markup(),
        )
        db.secretary.add_event(
            secretary_owner_telegram_id,
            "pending_confirmation",
            "Draft sent to owner for confirmation",
            chat_id=chat_id,
        )
    else:
        db.secretary.add_event(secretary_owner_telegram_id, "draft", "Draft generated and saved", chat_id=chat_id)

    if save_history:
        bot_full_name = server_state.bot_full_name or server_state.bot_username or "Bot"
        db.messages.add_message(
            user["id"],
            "assistant",
            cleaned_response,
            chat_id=chat_id,
            chat_type=chat_type,
            chat_title=chat_title,
            author_telegram_id=server_state.bot_id or secretary_owner_telegram_id,
            author_username=server_state.bot_username,
            author_full_name=bot_full_name,
            content_type="text",
            reply_to_message_id=reply_to_message_id,
            is_addressed=1,
            author_is_bot=1,
            source_mode="secretary",
            secretary_owner_telegram_id=secretary_owner_telegram_id,
            secretary_source_chat_id=secretary_source_chat_id or chat_id,
            secretary_counterparty_id=counterparty_id,
            secretary_session_id=session_id,
            secretary_reply_status=reply_status,
        )

    if mode == "auto" and secretary_payload.get("close_after_reply") and session_id:
        db.secretary.close_session(int(session_id), reason="close_after_reply")
        db.secretary.add_event(secretary_owner_telegram_id, "session_closed", "close_after_reply", chat_id=chat_id)


async def _send_response_in_parts(
    message,
    cleaned_response: str,
    response_text: str,
    model_id: str,
    user_id: int,
    existing_message=None,
    allow_rich: bool = True,
):
    """Отправляет ответ разбитым на части, с попытками форматирования."""
    try:
        from config.settings import settings_manager
        settings = settings_manager.get_settings()
        allow_md = settings.get('format_markdown', True)
        allow_html = settings.get('format_html', True)
        business_connection_id = getattr(message, "business_connection_id", None)

        if allow_rich and existing_message is None:
            rich_result = await try_send_rich_message(
                bot=message.bot,
                chat_id=message.chat.id,
                text=cleaned_response,
                settings=settings,
                business_connection_id=business_connection_id,
                reply_to_message_id=getattr(message, "message_id", None),
                message_thread_id=getattr(message, "message_thread_id", None),
            )
            if rich_result.sent:
                logger.info("Ответ отправлен через sendRichMessage")
                return "rich_message"
            if rich_result.status == "failed" and not rich_messages_fallback_enabled(settings):
                raise RuntimeError(f"sendRichMessage failed: {rich_result.reason}")
            if rich_result.status == "failed":
                logger.warning("sendRichMessage не сработал, fallback на sendMessage: %s", rich_result.reason)

        if business_connection_id:
            cleaned_response = prepare_legacy_fallback_text(cleaned_response)
            response_text = prepare_legacy_fallback_text(response_text)

        if allow_md or allow_html:
            formatted_text, parse_mode = telegram_formatter.process_text(cleaned_response)
        else:
            formatted_text, parse_mode = cleaned_response, None

        if not formatted_text or formatted_text.strip() == "":
            logger.warning(f"Получен пустой ответ от модели {model_id} после форматирования")
            await message.reply(clean_response(response_text))
            logger.info(f"Отправлен неформатированный ответ")
            return "legacy_plain"
        
        if not allow_md and parse_mode == 'MarkdownV2':
            plain_text = telegram_formatter.unescape_markdown_v2(formatted_text)
            if allow_html:
                formatted_text = telegram_formatter.force_html(plain_text)
                parse_mode = 'HTML'
            else:
                formatted_text = plain_text
                parse_mode = None
        if not allow_html and parse_mode == 'HTML':
            parse_mode = None
            formatted_text = telegram_formatter.html_to_plain_text(formatted_text)

        parts, parts_parse_mode = telegram_formatter.split_for_telegram(formatted_text, parse_mode)

        sent_any = False
        for idx, part in enumerate(parts):
            try:
                if idx == 0 and existing_message:
                    if parts_parse_mode:
                        await existing_message.edit_text(part, parse_mode=parts_parse_mode)
                    else:
                        await existing_message.edit_text(part)
                else:
                    if parts_parse_mode:
                        await message.reply(part, parse_mode=parts_parse_mode)
                    else:
                        await message.reply(part)
                sent_any = True
            except Exception as send_err:
                if idx == 0 and existing_message and "message is not modified" in str(send_err).lower():
                    sent_any = True
                    continue
                logger.warning(f"Ошибка отправки части ответа: {send_err}. Пытаюсь HTML.")
                try:
                    if parts_parse_mode == 'MarkdownV2':
                        part = telegram_formatter.unescape_markdown_v2(part)
                    html_part = telegram_formatter.force_html(part)
                    if idx == 0 and existing_message:
                        await existing_message.edit_text(html_part, parse_mode='HTML')
                    else:
                        await message.reply(html_part, parse_mode='HTML')
                    sent_any = True
                except Exception as send_err2:
                    if idx == 0 and existing_message and "message is not modified" in str(send_err2).lower():
                        sent_any = True
                        continue
                    logger.warning(f"Ошибка HTML, отправляю без форматирования: {send_err2}")
                    if parts_parse_mode == 'MarkdownV2':
                        part = telegram_formatter.unescape_markdown_v2(part)
                    try:
                        if idx == 0 and existing_message:
                            await existing_message.edit_text(clean_response(part))
                        else:
                            await message.reply(clean_response(part))
                        sent_any = True
                    except Exception as plain_err:
                        if idx == 0 and existing_message and "message is not modified" in str(plain_err).lower():
                            sent_any = True
                            continue
                        raise

        if not sent_any:
            await message.reply(clean_response(response_text))
        return "legacy"
        
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")
        clean_text = clean_response(response_text)
        await message.reply(clean_text)
        logger.info(f"Ответ отправлен пользователю {user_id} без форматирования (после ошибки)")
        return "legacy_error"


def _strip_think_tags(text: str) -> str:
    """Удаляет теги <think> и их содержимое (даже если тег не закрыт)."""
    # Удаляем закрытые теги
    text = re.sub(r'<think>[\s\S]*?</think>', '', text)
    # Удаляем открытый тег (если генерация ещё идёт)
    text = re.sub(r'<think>[\s\S]*$', '', text)
    return text.strip()

async def _send_response_streaming(
    message,
    prepared_messages: list,
    settings: dict,
    model_id: str,
    user_id: int,
) -> Optional[str]:
    """
    Стриминг ответа через edit_text + финальная отправка через _send_response_in_parts.

    Возвращает накопленный текст ответа (для сохранения в БД),
    или None если стриминг не удался (вызывающий должен сделать фолбэк на обычный путь).
    """
    accumulated = ""
    last_edit_time = 0.0
    last_sent_len = 0
    edit_interval = 1.0  # Базовый интервал 1.0с для стабильности
    MIN_CHARS_TO_EDIT = 15  # Обновлять каждые 15 символов
    
    sent_msg = None
    try:
        sent_msg = await message.reply("...")
    except Exception as e:
        logger.warning(f"Не удалось отправить placeholder для стриминга: {e}")

    try:
        async for chunk in stream_from_model(prepared_messages, settings, model_id):
            accumulated += chunk
            
            preview = _strip_think_tags(accumulated)
            
            now = time.monotonic()
            # Обновляем, если прошло время И накопилось достаточно новых символов
            if now - last_edit_time >= edit_interval and len(preview) >= last_sent_len + MIN_CHARS_TO_EDIT:
                try:
                    if sent_msg:
                        # Применяем умное форматирование с автозакрытием тегов
                        formatted_preview, fmt_mode = telegram_formatter.safe_format_for_streaming(
                            preview[:4000],
                            allow_markdown=settings.get('format_markdown', True),
                            allow_html=settings.get('format_html', True),
                        )
                        if fmt_mode:
                            await sent_msg.edit_text(formatted_preview, parse_mode=fmt_mode)
                        else:
                            await sent_msg.edit_text(formatted_preview)
                    last_edit_time = now
                    last_sent_len = len(preview)
                except Exception as edit_err:
                    err_msg = str(edit_err)
                    if "429" in err_msg or "Too Many Requests" in err_msg:
                        # Если поймали 429 — не стопаем процесс, просто увеличиваем интервал
                        # и пропускаем это обновление. Модель продолжает генерить в фон.
                        edit_interval = min(edit_interval + 0.5, 5.0)
                        logger.debug("Стриминг: словили 429, увеличиваем интервал до %.1fs", edit_interval)
                    else:
                        logger.debug("edit_text ошибка (игнорируем): %s", edit_err)

        if not accumulated.strip():
            logger.warning("Стриминг для модели %s вернул пустой ответ", model_id)
            if sent_msg:
                try:
                    await sent_msg.delete()
                except Exception:
                    pass
            return None

        # Финальная очистка и отправка
        cleaned = _strip_think_tags(accumulated)
        # Убираем clean_response здесь, так как он может портить отступы в коде.
        # Очистка от скрытых символов и Harmony-тегов будет сделана в _send_response_in_parts.
        
        await _send_response_in_parts(message, cleaned, cleaned, model_id, user_id, existing_message=sent_msg)
        return cleaned

    except RuntimeError as e:
        # Anthropic или другой несовместимый клиент
        logger.warning("Стриминг недоступен для модели %s: %s", model_id, e)
        if sent_msg:
            try:
                await sent_msg.delete()
            except Exception:
                pass
        return None
    except Exception as e:
        logger.error("Ошибка стриминга для модели %s: %s", model_id, e)
        # Фолбэк: если что-то накопилось — отправляем это
        if accumulated.strip():
            try:
                cleaned = _strip_think_tags(accumulated)
                cleaned = clean_response(cleaned)
                await _send_response_in_parts(message, cleaned, cleaned, model_id, user_id, existing_message=sent_msg)
                return cleaned
            except Exception:
                pass
                
        if sent_msg:
            try:
                await sent_msg.delete()
            except Exception:
                pass
        return None


async def _send_response_rich_streaming(
    message,
    prepared_messages: list,
    settings: dict,
    model_id: str,
    user_id: int,
) -> Optional[str]:
    """
    Нативный Rich-стриминг Telegram через sendRichMessageDraft.

    Draft является временным preview, поэтому после генерации обязательно
    отправляем финальный sendRichMessage. Если draft-часть не поддержана,
    продолжаем генерацию без preview и всё равно пытаемся отправить финал.
    """
    accumulated = ""
    last_draft_time = 0.0
    last_draft_len = 0
    draft_failures = 0
    draft_disabled = False

    rich_settings = settings.get("rich_messages") or {}
    try:
        draft_interval = float(rich_settings.get("stream_draft_interval_seconds", 0.8))
    except (TypeError, ValueError):
        draft_interval = 0.8
    draft_interval = max(0.3, min(draft_interval, 5.0))
    min_chars_to_draft = 20
    draft_id = random.randint(1, 2_147_483_647)

    try:
        async for chunk in stream_from_model(prepared_messages, settings, model_id):
            accumulated += chunk
            preview = _strip_think_tags(accumulated)
            if not preview:
                continue

            now = time.monotonic()
            if (
                not draft_disabled
                and now - last_draft_time >= draft_interval
                and len(preview) >= last_draft_len + min_chars_to_draft
            ):
                draft_result = await try_send_rich_message_draft(
                    bot=message.bot,
                    chat_id=message.chat.id,
                    draft_id=draft_id,
                    text=preview,
                    settings=settings,
                    message_thread_id=getattr(message, "message_thread_id", None),
                )
                if draft_result.sent:
                    last_draft_time = now
                    last_draft_len = len(preview)
                    draft_failures = 0
                elif draft_result.status == "failed":
                    draft_failures += 1
                    logger.debug("Rich draft update failed: %s", draft_result.reason)
                    if draft_failures >= 3:
                        draft_disabled = True
                        logger.warning("Rich draft streaming disabled for this response after repeated failures: %s", draft_result.reason)

        if not accumulated.strip():
            logger.warning("Rich-стриминг для модели %s вернул пустой ответ", model_id)
            return None

        cleaned = _strip_think_tags(accumulated)
        final_result = await try_send_rich_message(
            bot=message.bot,
            chat_id=message.chat.id,
            text=cleaned,
            settings=settings,
            reply_to_message_id=getattr(message, "message_id", None),
            message_thread_id=getattr(message, "message_thread_id", None),
        )
        if final_result.sent:
            logger.info("Финальный ответ отправлен через sendRichMessage после draft-стриминга")
            return cleaned

        if final_result.status == "failed" and not rich_messages_fallback_enabled(settings):
            logger.warning("Финальный sendRichMessage после draft-стриминга не сработал: %s", final_result.reason)
            return None

        logger.warning(
            "Финальный sendRichMessage после draft-стриминга ушёл в legacy fallback: %s",
            final_result.reason,
        )
        await _send_response_in_parts(
            message,
            cleaned,
            cleaned,
            model_id,
            user_id,
            allow_rich=False,
        )
        return cleaned

    except RuntimeError as e:
        logger.warning("Rich-стриминг недоступен для модели %s: %s", model_id, e)
        return None
    except Exception as e:
        logger.error("Ошибка Rich-стриминга для модели %s: %s", model_id, e)
        if accumulated.strip():
            cleaned = clean_response(_strip_think_tags(accumulated))
            await _send_response_in_parts(
                message,
                cleaned,
                cleaned,
                model_id,
                user_id,
                allow_rich=False,
            )
            return cleaned
        return None


async def process_request(
    priority,
    counter,
    message,
    user,
    enqueue_time,
    model_id,
    chat_id,
    chat_type,
    chat_title,
    sequential_group,
    payload,
    # Глобальные переменные передаём как параметры для инъекции
    user_locks: Dict,
    release_group_slot_func,
    watchdog_delay: int = 600,
):
    """
    Обрабатывает один запрос пользователя.
    
    Args:
        priority, counter, message, user, enqueue_time, model_id, chat_id, chat_type, chat_title, sequential_group, payload:
            Параметры запроса из очереди
        user_locks: Словарь блокировок пользователя
        release_group_slot_func: Функция для освобождения слота группы
        watchdog_delay: Задержка перед предупреждением о долгой генерации (сек)
    """
    db = DatabaseManager()
    typing_task = None
    try:
        attachments = []
        requires_vision = False
        request_context = {}
        if isinstance(payload, dict):
            attachments = payload.get('attachments') or []
            request_context = payload.get('request_context') or {}
            if isinstance(request_context, dict):
                request_context = dict(request_context)
                request_context["query_text"] = str(payload.get("text_content") or "")
            # Уважаем явную деградацию (requires_vision может быть принудительно выключен).
            if 'requires_vision' in payload:
                requires_vision = bool(payload.get('requires_vision'))
            else:
                # Defensive: если флаг не проставлен, считаем по наличию вложений.
                requires_vision = bool(attachments)
        supports_vision = model_capabilities.get(model_id, {}).get('supports_vision', False)
        source_mode = request_context.get('source_mode') if isinstance(request_context, dict) else None
        if source_mode != "secretary" and isinstance(request_context, dict):
            has_secretary_context = bool(
                request_context.get("secretary_owner_telegram_id")
                or request_context.get("secretary_source_chat_id")
                or request_context.get("business_connection_id")
            )
            has_secretary_payload = isinstance(payload, dict) and bool(payload.get("secretary"))
            if has_secretary_context or has_secretary_payload:
                source_mode = "secretary"
        secretary_owner_telegram_id = (
            request_context.get('secretary_owner_telegram_id')
            if isinstance(request_context, dict)
            else None
        )
        secretary_source_chat_id = (
            request_context.get('secretary_source_chat_id')
            if isinstance(request_context, dict)
            else None
        )

        # Увеличиваем счётчик активных запросов
        async with get_model_stats_lock():
            if model_id not in model_usage_stats:
                model_usage_stats[model_id] = {"requests": 0, "errors": 0, "active_requests": 0}
            model_usage_stats[model_id]["active_requests"] += 1
            logger.debug(f"Счётчик активных запросов для {model_id} увеличен до {model_usage_stats[model_id]['active_requests']}")
        
        wait_time = time.time() - enqueue_time
        stats.stats.add_wait_time(wait_time)

        from config.settings import settings_manager
        settings = settings_manager.get_settings()
        settings = _apply_user_preferences(settings, user, db)
        logger.debug(
            "Используем настройки: temperature=%s, max_tokens=%s, strategy=%s",
            settings.get('temperature'),
            settings.get('max_tokens'),
            settings.get('load_balancing_strategy', 'round_robin'),
        )

        process_start_time = time.time()

        if source_mode == "secretary":
            await _mark_secretary_message_read(message, db, secretary_owner_telegram_id, chat_id)

        # Start typing action task
        typing_task = asyncio.create_task(send_typing_action(message.bot, message.chat.id))

        # Fetch message history
        if chat_type in {'group', 'supergroup'}:
            history_limit = 120
            raw_history = db.messages.get_chat_messages_active(
                chat_id,
                limit=history_limit,
                source_mode=source_mode,
                secretary_owner_telegram_id=secretary_owner_telegram_id,
                secretary_source_chat_id=secretary_source_chat_id,
            )
            filtered_history = [
                row for row in raw_history
                if (row.get('role') == 'assistant') or bool(row.get('is_addressed'))
            ]
            if not filtered_history:
                history = raw_history[-20:]
            else:
                history = filtered_history[-history_limit:]
            snapshot_text = build_group_context_snapshot(chat_id, limit=40)
        else:
            history_limit = 200
            history = db.messages.get_chat_messages_active(
                chat_id,
                limit=history_limit,
                source_mode=source_mode,
                secretary_owner_telegram_id=secretary_owner_telegram_id,
                secretary_source_chat_id=secretary_source_chat_id,
            )
            # Для совместимости с очень старыми записями, где chat_id мог отсутствовать,
            # пытаемся забрать приватные сообщения пользователя в качестве резервного варианта.
            if not history:
                history = db.messages.get_user_messages_active(
                    user['id'],
                    limit=history_limit,
                    chat_type='private',
                    chat_id=chat_id,
                    source_mode=source_mode,
                    secretary_owner_telegram_id=secretary_owner_telegram_id,
                    secretary_source_chat_id=secretary_source_chat_id,
                )
            snapshot_text = ""
        logger.debug(
            "История сообщений для контекста (chat_id=%s, type=%s): %s записей",
            chat_id,
            chat_type,
            len(history),
        )

        # Build messages list with metadata
        messages = []
        relevant_message_ids = {message.message_id}
        batched_message_ids = set()
        if source_mode == "secretary" and isinstance(request_context, dict):
            for value in request_context.get("secretary_batched_message_ids") or []:
                try:
                    batched_message_ids.add(int(value))
                except (TypeError, ValueError):
                    continue
            relevant_message_ids.update(batched_message_ids)
        if message.reply_to_message:
            relevant_message_ids.add(message.reply_to_message.message_id)
        
        for row in history:
            if batched_message_ids and row.get('telegram_message_id') in batched_message_ids:
                continue
            role = row['role']
            content = row['content']
            author_display = None
            if chat_type in {'group', 'supergroup'} and role == 'user':
                author_display = _format_author_display_name(row)
                if content:
                    content = f"{author_display}: {content}"
            
            entry = {
                'role': role, 
                'content': content,
                'id': row.get('id'),
                'chat_id': row.get('chat_id'),
                'author_telegram_id': row.get('author_telegram_id'),
                'author_username': row.get('author_username'),
                'author_full_name': row.get('author_full_name'),
                'author_is_bot': row.get('author_is_bot', 0),
                'source_mode': row.get('source_mode') or 'normal',
                'secretary_owner_telegram_id': row.get('secretary_owner_telegram_id'),
                'secretary_source_chat_id': row.get('secretary_source_chat_id'),
                'secretary_counterparty_id': row.get('secretary_counterparty_id'),
                'secretary_reply_status': row.get('secretary_reply_status'),
                'is_summary': row.get('is_summary', 0),
                'content_type': row.get('content_type') or 'text',
                'image_path': row.get('image_path'),
                'image_mime': row.get('image_mime'),
                'telegram_file_id': row.get('telegram_file_id'),
                'telegram_message_id': row.get('telegram_message_id'),
            }

            # Handle old images without actual file
            if entry.get('content_type') in {'image', 'image_ref'} and entry.get('telegram_message_id') not in relevant_message_ids:
                entry['image_path'] = None
                entry['image_mime'] = None
                if entry['content_type'] == 'image':
                    entry['content_type'] = 'image_ref'
                if not (entry.get('content') or '').strip():
                    placeholder_text = LEGACY_IMAGE_PLACEHOLDER
                    if author_display:
                        placeholder_text = f"{author_display}: {LEGACY_IMAGE_PLACEHOLDER}"
                    entry['content'] = placeholder_text
                    entry['was_image_placeholder'] = True
                    logger.debug(
                        "Восстановлен текстовый плейсхолдер для изображения без подписи (chat_id=%s, message_id=%s)",
                        chat_id,
                        entry.get('telegram_message_id'),
                    )

            messages.append(entry)

        if isinstance(request_context, dict):
            recent_context_parts = []
            for entry in messages[-6:]:
                content = str(entry.get("content") or "").strip()
                if content:
                    recent_context_parts.append(content)
            request_context["recent_context_text"] = "\n".join(recent_context_parts)

        # Add attachments from current request
        if attachments and messages:
            last_msg = messages[-1]
            if not last_msg.get('image_path') and attachments:
                last_msg['image_path'] = attachments[0].get('path')
                last_msg['image_mime'] = attachments[0].get('mime')
                if last_msg.get('content_type') == 'text':
                    last_msg['content_type'] = 'image'

        # Best-effort context-aware upgrade:
        # если "сырой" контекст не помещается в доступное окно модели, пробуем подобрать
        # модель с большим context_window_size, сохраняя стратегию балансировки в рамках подходящих.
        try:
            models = settings.get('models', [])
            default_context_length = settings.get('default_context_length', 4096)
            models_config = {m.get('id'): m for m in models if m.get('id')}

            def _context_window_size(mid: str) -> int:
                return int(models_config.get(mid, {}).get('context_window_size', default_context_length) or default_context_length)

            def _available_context_for_window(model_context_length: int) -> int:
                max_tokens = settings.get('max_tokens', 0) or 0
                if max_tokens and max_tokens > 0:
                    reserved_for_response = min(max_tokens, int(model_context_length * 0.5))
                else:
                    reserved_for_response = max(512, int(model_context_length * 0.5))
                safety_buffer = max(256, int(model_context_length * 0.1))
                return max(256, model_context_length - reserved_for_response - safety_buffer)

            raw_tokens = count_message_tokens(messages, model_id=model_id)
            current_window = _context_window_size(model_id)
            current_available = _available_context_for_window(current_window)

            if raw_tokens > current_available:
                eligible: list[str] = []
                for mid in active_models:
                    if requires_vision and not model_capabilities.get(mid, {}).get('supports_vision', False):
                        continue
                    win = _context_window_size(mid)
                    avail = _available_context_for_window(win)
                    if raw_tokens <= avail:
                        eligible.append(mid)

                if eligible and model_id not in eligible:
                    upgraded = select_model_for_request(
                        requires_vision=requires_vision,
                        eligible_model_ids=eligible,
                    )
                    if upgraded and upgraded != model_id:
                        async with get_model_stats_lock():
                            upgraded_cfg = models_config.get(upgraded, {})
                            upgraded_max = upgraded_cfg.get('max_concurrent_requests', 1)
                            upgraded_active = model_usage_stats.get(upgraded, {}).get('active_requests', 0)

                            if upgraded_active < upgraded_max:
                                if upgraded not in model_usage_stats:
                                    model_usage_stats[upgraded] = {"requests": 0, "errors": 0, "active_requests": 0}

                                # Переносим "бронь" активного запроса со старой модели на новую.
                                if model_id in model_usage_stats:
                                    model_usage_stats[model_id]["active_requests"] = max(
                                        0,
                                        model_usage_stats[model_id].get("active_requests", 1) - 1,
                                    )
                                model_usage_stats[upgraded]["active_requests"] += 1

                                logger.info(
                                    "Context-upgrade: %s -> %s (raw_tokens=%s, current_available=%s, new_window=%s)",
                                    model_id,
                                    upgraded,
                                    raw_tokens,
                                    current_available,
                                    _context_window_size(upgraded),
                                )
                                model_id = upgraded
                                supports_vision = model_capabilities.get(model_id, {}).get('supports_vision', False)
                            else:
                                logger.debug(
                                    "Context-upgrade отменён: модель %s занята (%s/%s)",
                                    upgraded,
                                    upgraded_active,
                                    upgraded_max,
                                )
        except Exception as exc:
            logger.warning("Не удалось выполнить context-upgrade (best-effort): %s", exc)

        # Фиксируем, что запрос назначен финальной модели (после возможного апгрейда).
        async with get_model_stats_lock():
            if model_id not in model_usage_stats:
                model_usage_stats[model_id] = {"requests": 0, "errors": 0, "active_requests": 0}
            model_usage_stats[model_id]["requests"] = model_usage_stats[model_id].get("requests", 0) + 1

        # Apply history summarization (только для групп)
        summarizer = get_history_summarizer(model_id, settings) if chat_type in {'group', 'supergroup'} else None
        
        # Calculate available context
        models = settings.get('models', [])
        default_context_length = settings.get('default_context_length', 4096)
        model_context_length = default_context_length
        for model in models:
            if model.get('id') == model_id:
                model_context_length = model.get('context_window_size', default_context_length)
                break
        
        max_tokens = settings.get('max_tokens', 0) or 0
        if max_tokens and max_tokens > 0:
            reserved_for_response = min(max_tokens, int(model_context_length * 0.5))
        else:
            reserved_for_response = max(512, int(model_context_length * 0.5))
        
        safety_buffer = max(256, int(model_context_length * 0.1))
        available_context = max(256, model_context_length - reserved_for_response - safety_buffer)
        
        logger.debug(
            f"Расчёт контекста для {model_id}: "
            f"context_window={model_context_length}, "
            f"reserved_for_response={reserved_for_response}, "
            f"safety_buffer={safety_buffer}, "
            f"available_context={available_context}"
        )
        
        total_tokens_before_summary = count_message_tokens(messages, model_id=model_id)
        summary_info = {
            'status': 'skipped_private' if chat_type == 'private' else 'not_started',
            'summarized': False,
            'initial_tokens': total_tokens_before_summary,
            'final_tokens': total_tokens_before_summary,
            'initial_message_count': len(messages),
            'final_message_count': len(messages),
        }

        if summarizer is not None:
            messages, summary_info = summarizer.ensure_context_fits(
                chat_id=chat_id,
                user_id=user['id'],
                messages=messages,
                available_context=available_context
            )
        
        if summary_info.get('summarized'):
            logger.info(
                f"Контекст адаптирован через суммаризацию: "
                f"{summary_info['initial_tokens']} -> {summary_info['final_tokens']} токенов, "
                f"{summary_info['initial_message_count']} -> {summary_info['final_message_count']} сообщений"
            )
        
        # Extract summaries from history
        summaries_content = []
        messages_without_summaries = []
        for msg in messages:
            if msg.get('is_summary'):
                summaries_content.append(msg.get('content', ''))
                msg = {**msg, 'content': f"[length={len(str(msg.get('content') or ''))}]"}
                logger.debug("Извлечена сводка из истории: %s", msg.get('content', ''))
            else:
                messages_without_summaries.append(msg)
        
        if summaries_content:
            logger.info(f"Извлечено {len(summaries_content)} сводок из истории, сообщений без сводок: {len(messages_without_summaries)}")
        
        messages = messages_without_summaries
        
        # Double-check no summaries remain
        remaining_summaries = [msg for msg in messages if msg.get('is_summary')]
        if remaining_summaries:
            logger.error(f"ОШИБКА: В messages остались сводки после извлечения! Количество: {len(remaining_summaries)}")
            messages = [msg for msg in messages if not msg.get('is_summary')]
        
        # Adjust history for context limit
        messages, context_info = adjust_history_for_context_limit(messages, model_id, settings)
        
        # Remove system message if present
        if messages and messages[0].get('role') == 'system':
            messages = messages[1:]
        
        if context_info.get('status') == 'truncated':
            stats.stats.increment_context_truncated()
            ratio = stats.stats.get_context_truncated_ratio()
            logger.info(f"Контекст был обрезан для этого запроса. Всего обрезаний: {stats.stats.get_context_truncated_count()}, доля: {ratio:.1f}%")
        
        # Build system prompt with summaries
        secretary_payload = payload.get("secretary") if isinstance(payload, dict) else {}
        secretary_system_prompt = (secretary_payload or {}).get("system_prompt") if source_mode == "secretary" else None
        base_system_prompt = secretary_system_prompt or settings.get('system_prompt', "")
        configured_max_summaries = settings.get('max_summaries_in_prompt', 5)
        max_summaries_in_prompt = max(1, min(configured_max_summaries, 3))
        
        system_prompt_parts = []
        if base_system_prompt:
            system_prompt_parts.append(base_system_prompt)

        if chat_type in {'group', 'supergroup'} and snapshot_text:
            system_prompt_parts.append(f"--- Контекст чата ---\n{snapshot_text}")

        if summaries_content:
            limited_summaries = summaries_content[-max_summaries_in_prompt:]
            if len(summaries_content) > max_summaries_in_prompt:
                logger.debug(
                    f"Ограничено количество сводок в системном промпте: "
                    f"{len(summaries_content)} -> {len(limited_summaries)} (макс {max_summaries_in_prompt}, настройка={configured_max_summaries})"
                )
            summaries_text = "\n\n".join(limited_summaries)
            system_prompt_parts.append(f"--- Сводка истории ---\n{summaries_text}")

        system_prompt_parts.append(ROLE_PLACEHOLDER_PROMPT_HINT)
        if (settings.get("rich_messages") or {}).get("enabled"):
            system_prompt_parts.append(RICH_MARKDOWN_PROMPT_HINT)
        system_prompt = "\n\n".join(part for part in system_prompt_parts if part)
        
        # Prepare system prompt
        from .prompt_manager import prepare_system_prompt
        system_prompt = prepare_system_prompt(
            system_prompt,
            model_id,
            user,
            message.chat.id,
            chat_type=chat_type,
            chat_title=chat_title,
            extra_placeholders=_secretary_prompt_placeholders(request_context, user, message, chat_id),
        )
        if system_prompt:
            prompt_source = "secretary" if secretary_system_prompt else "global"
            prompt_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:12]
            logger.info(
                "System prompt applied: source=%s chat_type=%s chars=%s hash=%s",
                prompt_source,
                chat_type,
                len(system_prompt),
                prompt_hash,
            )
        else:
            logger.warning(
                "System prompt is empty: source_mode=%s chat_type=%s model=%s",
                source_mode or "normal",
                chat_type,
                model_id,
            )
        
        # Build system message
        system_message = None
        if system_prompt:
            system_message = {'role': 'system', 'content': system_prompt}
        
        # Ensure alternating roles
        messages = ensure_alternating_roles(messages, system_message)

        # Final context check after role merging
        messages, trimmed_after_merge = trim_messages_to_context_limit(messages, model_id, settings)
        if trimmed_after_merge:
            stats.stats.increment_context_truncated()
        
        # Validate role sequence
        role_sequence = [msg.get('role') for msg in messages]
        logger.debug(f"Порядок ролей перед отправкой: {role_sequence}")
        
        # Check for consecutive same roles and fix
        violations = []
        prev_role = None
        for i, msg in enumerate(messages):
            current_role = msg.get('role')
            if prev_role and prev_role != 'system' and current_role == prev_role:
                violations.append((i, prev_role, current_role))
            prev_role = current_role
        
        if violations:
            logger.error(f"ОБНАРУЖЕНО {len(violations)} НАРУШЕНИЙ ЧЕРЕДОВАНИЯ РОЛЕЙ")
            logger.error(f"Полная последовательность: {role_sequence}")
            for i, prev_role, current_role in reversed(violations):
                placeholder_role = 'assistant' if current_role == 'user' else 'user'
                placeholder_msg = {
                    'role': placeholder_role,
                    'content': '...',
                    'is_placeholder': True
                }
                messages.insert(i, placeholder_msg)
                logger.warning(f"Вставлен плейсхолдер {placeholder_role} на позиции {i} для исправления чередования")
        
        # Prepare messages for model
        role_sequence_before_prep = [msg.get('role') for msg in messages]
        logger.debug("Порядок ролей ПЕРЕД prepare_model_messages: count=%s roles=%s", len(role_sequence_before_prep), role_sequence_before_prep)
        
        prepared_messages = prepare_model_messages(messages, supports_vision)
        if not prepared_messages:
            logger.error("Не удалось подготовить сообщения для модели %s", model_id)
            return

        # Final role sequence check
        final_role_sequence = [msg.get('role') for msg in prepared_messages]
        logger.debug("Финальный порядок ролей перед отправкой в модель %s: count=%s roles=%s", model_id, len(final_role_sequence), final_role_sequence)
        
        # Check final sequence for violations
        prev_role = None
        for i, msg in enumerate(prepared_messages):
            current_role = msg.get('role')
            if prev_role and prev_role != 'system' and current_role == prev_role:
                logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: Нарушение чередования после подготовки на позиции {i}: {prev_role} -> {current_role}")
                logger.error(f"Полная последовательность: {final_role_sequence}")
                logger.error(
                    "Первые 3 сообщения для отладки: %s",
                    [
                        {
                            'role': m.get('role'),
                            'content_length': len(str(m.get('content') or '')),
                        }
                        for m in prepared_messages[:3]
                    ],
                )
                for idx, ctx_msg in enumerate(prepared_messages):
                    logger.error(
                        "Контекст[%s]: role=%s, content_type=%s, placeholder=%s, image_placeholder=%s, telegram_id=%s, content_length=%s",
                        idx,
                        ctx_msg.get('role'),
                        ctx_msg.get('content_type'),
                        ctx_msg.get('is_placeholder'),
                        ctx_msg.get('was_image_placeholder'),
                        ctx_msg.get('telegram_message_id'),
                        len(str(ctx_msg.get('content') or '')),
                    )
                await send_ephemeral_reply(
                    message,
                    "Произошла ошибка при подготовке контекста. Попробуйте ещё раз или используйте /clear_history.",
                )
                return
            prev_role = current_role

        # Ensure current user message is in prepared messages
        last_role = prepared_messages[-1].get('role') if prepared_messages else None
        
        if last_role != 'user':
            current_user_message_content = None
            if isinstance(payload, dict):
                current_user_message_content = payload.get('text_content')
            if not current_user_message_content and message.text:
                current_user_message_content = message.text
            elif not current_user_message_content and message.caption:
                current_user_message_content = message.caption
            
            found_current_message = False
            for msg in messages:
                if (msg.get('telegram_message_id') == message.message_id and 
                    msg.get('role') == 'user'):
                    found_current_message = True
                    logger.debug(
                        "Найдено текущее сообщение пользователя в истории: [length=%s]",
                        len(str(msg.get('content') or '')),
                    )
                    break
            
            if not found_current_message:
                logger.warning(f"Текущее сообщение пользователя (message_id={message.message_id}) не найдено в истории! Добавляем вручную.")
                
                user_content = current_user_message_content or message.text or message.caption or ""
                
                current_user_msg = {
                    'role': 'user',
                    'content': user_content,
                    'telegram_message_id': message.message_id,
                    'content_type': 'text',
                    'image_path': attachments[0].get('path') if attachments else None,
                    'image_mime': attachments[0].get('mime') if attachments else None,
                }
                
                if current_user_msg.get('image_path'):
                    current_user_msg['content_type'] = 'image'
                
                if supports_vision and current_user_msg.get('image_path'):
                    # Добавляем маркер чтобы модель понимала что фото прислал пользователь
                    image_text = f"[Изображение пользователя]: {user_content}" if user_content else "[изображение пользователя]"
                    image_content = [
                        {'type': 'text', 'text': image_text},
                        {'type': 'image_url', 'image_url': {'url': build_image_data_url(current_user_msg['image_path'], current_user_msg['image_mime'])}}
                    ]
                    image_content = [item for item in image_content if item is not None]
                    prepared_messages.append({
                        'role': 'user',
                        'content': image_content
                    })
                else:
                    prepared_messages.append({
                        'role': 'user',
                        'content': user_content
                    })
                
                logger.info(
                    "Добавлено текущее сообщение пользователя вручную: [length=%s]",
                    len(user_content or ""),
                )
            else:
                logger.warning(f"Текущее сообщение пользователя найдено в истории, но не попало в prepared_messages. Ищем и добавляем.")
                
                for msg in messages:
                    if (msg.get('telegram_message_id') == message.message_id and 
                        msg.get('role') == 'user'):
                        user_content = msg.get('content', '')
                        image_path = msg.get('image_path')
                        image_mime = msg.get('image_mime')
                        
                        if supports_vision and image_path:
                            # Добавляем маркер чтобы модель понимала что фото прислал пользователь
                            image_text = f"[Изображение пользователя]: {user_content}" if user_content else "[изображение пользователя]"
                            image_content = [
                                {'type': 'text', 'text': image_text},
                                {
                                    'type': 'image_url',
                                    'image_url': {'url': build_image_data_url(image_path, image_mime)}
                                }
                            ]
                            prepared_messages.append({
                                'role': 'user',
                                'content': image_content
                            })
                        else:
                            prepared_messages.append({
                                'role': 'user',
                                'content': user_content
                            })
                        
                        logger.info(
                            "Добавлено текущее сообщение пользователя из истории: [length=%s]",
                            len(user_content or ""),
                        )
                        break
        
        # Check context status
        if context_info.get('status') == 'critical':
            logger.error(f"Критическое переполнение контекста для модели {model_id}, прерываем обработку")
            return
        
        if requires_vision and not supports_vision:
            logger.warning("Запрос содержит изображение, но модель %s не поддерживает VLM. Изображение будет проигнорировано.", model_id)

        # Get response from model
        logger.info(f"Отправка запроса на модель {model_id}")
        final_check_roles = [m.get('role') for m in prepared_messages]
        logger.debug("ФИНАЛЬНАЯ ПРОВЕРКА: модель=%s, count=%s, roles=%s", model_id, len(final_check_roles), final_check_roles)
        logger.debug(f"Количество сообщений: {len(prepared_messages)}")

        # Определяем режим ответа: стриминг или обычный.
        # Текущий SSE-стример передаёт только текстовые чанки, поэтому для MCP-запросов
        # используем обычный путь с полноценной обработкой tool_calls.
        mcp_tools_available = False
        if isinstance(request_context, dict) and request_context and is_mcp_sdk_available():
            try:
                mcp_tools_available = bool(allowed_openai_tools_for_context(settings, request_context))
            except Exception as exc:
                logger.debug("Не удалось проверить MCP tools для стриминга: %s", exc)
        use_streaming = (
            settings.get('stream_mode', False)
            and chat_type == 'private'
            and source_mode != 'secretary'
            and not getattr(message, "business_connection_id", None)
            and not is_anthropic_client(model_id)
            and not mcp_tools_available
        )
        use_rich_streaming = (
            use_streaming
            and rich_message_streaming_enabled(settings)
        )
        if settings.get('stream_mode', False) and mcp_tools_available:
            logger.info("Стриминг отключён для запроса: доступны MCP tools, нужен обычный tool-aware путь")

        watchdog_task = None
        if source_mode != "secretary":
            watchdog_task = asyncio.create_task(response_watchdog(message, model_id, user, watchdog_delay))
        try:
            if use_streaming:
                if use_rich_streaming:
                    logger.info("Используем Rich draft-стриминг для chat_id=%s", chat_id)
                    streaming_result = await _send_response_rich_streaming(
                        message, prepared_messages, settings, model_id, user['telegram_id']
                    )
                else:
                    # --- Режим плавного стриминга ---
                    logger.info("Используем legacy edit_text-стриминг для chat_id=%s", chat_id)
                    streaming_result = await _send_response_streaming(
                        message, prepared_messages, settings, model_id, user['telegram_id']
                    )
                if streaming_result is not None:
                    # Стриминг прошёл успешно — сохраняем ответ в БД
                    cleaned_response = streaming_result
                    is_error = _is_error_response(cleaned_response)
                    if not is_error:
                        bot_full_name = server_state.bot_full_name or server_state.bot_username or "Bot"
                        db.messages.add_message(
                            user['id'],
                            'assistant',
                            cleaned_response,
                            chat_id=chat_id,
                            chat_type=chat_type,
                            chat_title=chat_title,
                            author_telegram_id=server_state.bot_id,
                            author_username=server_state.bot_username,
                            author_full_name=bot_full_name,
                            content_type='text',
                            reply_to_message_id=message.message_id,
                            is_addressed=1,
                            author_is_bot=1,
                            source_mode=source_mode or 'normal',
                            secretary_owner_telegram_id=secretary_owner_telegram_id,
                            secretary_source_chat_id=secretary_source_chat_id,
                        )
                    else:
                        await send_ephemeral_reply(message, cleaned_response)
                else:
                    # Фолбэк на обычный режим
                    logger.warning("Стриминг недоступен/не удался, используем обычный режим")
                    response_text = await get_response_from_model(
                        prepared_messages,
                        settings,
                        model_id,
                        supports_vision=supports_vision,
                        request_context=request_context,
                    )
                    cleaned_response = clean_response(response_text)
                    is_error = _is_error_response(cleaned_response) or _is_error_response(response_text)
                    if is_error:
                        await send_ephemeral_reply(message, cleaned_response)
                    else:
                        await _send_response_in_parts(message, cleaned_response, response_text, model_id, user['telegram_id'])
                        bot_full_name = server_state.bot_full_name or server_state.bot_username or "Bot"
                        db.messages.add_message(
                            user['id'],
                            'assistant',
                            cleaned_response,
                            chat_id=chat_id,
                            chat_type=chat_type,
                            chat_title=chat_title,
                            author_telegram_id=server_state.bot_id,
                            author_username=server_state.bot_username,
                            author_full_name=bot_full_name,
                            content_type='text',
                            reply_to_message_id=message.message_id,
                            is_addressed=1,
                            author_is_bot=1,
                            source_mode=source_mode or 'normal',
                            secretary_owner_telegram_id=secretary_owner_telegram_id,
                            secretary_source_chat_id=secretary_source_chat_id,
                        )
            else:
                # --- Обычный режим (старый путь, без изменений) ---
                response_text = await get_response_from_model(
                    prepared_messages,
                    settings,
                    model_id,
                    supports_vision=supports_vision,
                    request_context=request_context,
                )
        finally:
            if watchdog_task:
                watchdog_task.cancel()
                try:
                    await watchdog_task
                except asyncio.CancelledError:
                    pass

        # Продолжаем только если НЕ стриминг (или стриминг дал фолбэк — тогда response_text уже обработан выше)
        if not use_streaming:
            # Clean response
            cleaned_response = clean_response(response_text)

            # Проверяем, является ли ответ ошибкой
            is_error = _is_error_response(cleaned_response) or _is_error_response(response_text)

            if is_error:
                logger.warning(
                    "Обнаружена ошибка в ответе модели %s: [length=%s]",
                    model_id,
                    len(cleaned_response or ""),
                )
                if source_mode == "secretary":
                    try:
                        db.secretary.add_event(
                            secretary_owner_telegram_id,
                            "error",
                            f"Secretary model response suppressed: {cleaned_response[:180]}",
                            chat_id=chat_id,
                        )
                    except Exception:
                        pass
                else:
                    await send_ephemeral_reply(message, cleaned_response)
                # Не сохраняем ошибки в БД как ответы ассистента
            else:
                if source_mode == "secretary":
                    await _handle_secretary_response(
                        db=db,
                        message=message,
                        user=user,
                        payload=payload if isinstance(payload, dict) else {},
                        cleaned_response=cleaned_response,
                        response_text=response_text,
                        model_id=model_id,
                        chat_id=chat_id,
                        chat_type=chat_type,
                        chat_title=chat_title,
                        secretary_owner_telegram_id=secretary_owner_telegram_id,
                        secretary_source_chat_id=secretary_source_chat_id,
                    )
                    response_time = time.time() - process_start_time
                    stats.stats.add_response_time(response_time)
                    stats.stats.increment_request_count()
                    return

                # Send response in parts with formatting
                # Сначала отправляем, потом сохраняем. Чтобы в истории не было сообщений, которые не дошли до ТГ.
                await _send_response_in_parts(message, cleaned_response, response_text, model_id, user['telegram_id'])

                # Save response to database
                logger.debug(
                    "Сохраняем ответ ассистента в базу: [length=%s]",
                    len(cleaned_response or ""),
                )
                bot_full_name = server_state.bot_full_name or server_state.bot_username or "Bot"
                db.messages.add_message(
                    user['id'],
                    'assistant',
                    cleaned_response,
                    chat_id=chat_id,
                    chat_type=chat_type,
                    chat_title=chat_title,
                    author_telegram_id=server_state.bot_id,
                    author_username=server_state.bot_username,
                    author_full_name=bot_full_name,
                    content_type='text',
                    reply_to_message_id=message.message_id,
                    is_addressed=1,
                    author_is_bot=1,
                    source_mode=source_mode or 'normal',
                    secretary_owner_telegram_id=secretary_owner_telegram_id,
                    secretary_source_chat_id=secretary_source_chat_id,
                )

        # Update statistics
        response_time = time.time() - process_start_time
        stats.stats.add_response_time(response_time)
        stats.stats.increment_request_count()

    except Exception as e:
        logger.error(f"Ошибка при обработке запроса: {e}")
        if model_id in model_usage_stats:
            model_usage_stats[model_id]["errors"] += 1
        
        response_time = time.time() - process_start_time
        stats.stats.add_response_time(response_time)
        stats.stats.increment_request_count()
        
        error_message = (
            "Извините, произошла техническая ошибка при обработке запроса. "
            "Пожалуйста, попробуйте ещё раз через некоторое время."
        )

        if source_mode == "secretary":
            try:
                db.secretary.add_event(
                    secretary_owner_telegram_id,
                    "error",
                    "Secretary queued request failed",
                    chat_id=chat_id,
                )
            except Exception:
                pass
        else:
            await send_ephemeral_reply(message, error_message)
    finally:
        # Stop typing action
        if typing_task:
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug("Задача статуса набора текста завершилась с ошибкой: %s", exc)
        
        # Release user lock
        user_locks[user['id']] = False
        
        # Decrease model active request counter
        async with get_model_stats_lock():
            if model_id in model_usage_stats:
                model_usage_stats[model_id]["active_requests"] = max(
                    0, 
                    model_usage_stats[model_id].get("active_requests", 1) - 1
                )
                logger.debug(f"Счетчик активных запросов для {model_id} уменьшен до {model_usage_stats[model_id]['active_requests']}")
        
        if sequential_group:
            await release_group_slot_func(chat_id)

        db.close()
        stats.stats.decrement_pending_requests()
