from aiogram import types
from aiogram.exceptions import TelegramBadRequest
import asyncio
from pathlib import Path
import time

from bot.handlers.queue_manager import get_model_usage_stats, reload_models
from bot.handlers.services.access_control import is_admin_user, resolve_user_role
from bot.handlers.services.mcp_permissions import allowed_tools_for_context
from bot.handlers.services.mcp_registry import normalize_server_config, preview_servers
from bot.handlers.services.mcp_runtime import McpRuntimeError, discover_server_capabilities, is_mcp_sdk_available
from bot.handlers.services.menu_renderer import (
    render_confirm,
    render_group_menu,
    render_history_menu,
    render_admin_text_view,
    render_admin_secretaries_menu,
    render_admin_secretary_card,
    MENU_PARSE_MODE,
    render_mcp_server_details,
    render_mcp_status_view,
    render_mcp_tools_view,
    render_main_menu,
    render_mcp_menu,
    render_models_menu,
    render_paged_text_view,
    render_secretary_menu,
    render_secretary_prompt_wait,
    render_settings_menu,
    render_status_menu,
    render_user_settings_menu,
    render_user_card,
    render_user_find_wait,
    render_users_menu,
)
from config.settings import settings_manager
from utils import server_state, stats
from utils.database.database_manager import DatabaseManager
from utils.history_manager import reset_history_cache
from utils.logger import setup_logger

logger = setup_logger(__name__)

_pending_menu_inputs = {}
_user_menu_filters = {}
_active_menu_sessions = {}


def _menu_session_key(actor_id: int, chat_id: int) -> tuple[int, int]:
    return int(actor_id), int(chat_id)


def _menu_ttl_seconds(settings: dict, chat_type: str) -> int:
    menu_settings = settings.get("telegram_menu", {}) if isinstance(settings, dict) else {}
    ttl = int(menu_settings.get("delete_menu_after_seconds", 300) or 300)
    if chat_type in {"group", "supergroup"}:
        return min(ttl, 120)
    return ttl


def _is_message_ttl_expired(message: types.Message, settings: dict) -> bool:
    ttl = _menu_ttl_seconds(settings, message.chat.type)
    if ttl <= 0:
        return False
    return time.time() > (message.date.timestamp() + ttl)


async def _edit_menu_message(message: types.Message, text: str, reply_markup=None):
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=MENU_PARSE_MODE)
    except TelegramBadRequest as exc:
        description = str(exc).lower()
        if "message is not modified" in description:
            return False
        if "can't parse entities" in description:
            await message.edit_text(text, reply_markup=reply_markup)
            return True
        raise
    return True


async def _reply_menu_message(message: types.Message, text: str, reply_markup=None):
    try:
        return await message.reply(text, reply_markup=reply_markup, parse_mode=MENU_PARSE_MODE)
    except TelegramBadRequest as exc:
        if "can't parse entities" not in str(exc).lower():
            raise
        return await message.reply(text, reply_markup=reply_markup)


async def _expire_menu_message(bot, chat_id: int, message_id: int, text: str = "Меню устарело. Откройте /menu заново."):
    try:
        await bot.delete_message(chat_id, message_id)
        return
    except TelegramBadRequest:
        pass
    except Exception as exc:
        logger.debug("Не удалось удалить старое menu-сообщение %s/%s: %s", chat_id, message_id, exc)
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
    except TelegramBadRequest:
        pass
    except Exception as exc:
        logger.debug("Не удалось пометить старое menu-сообщение %s/%s: %s", chat_id, message_id, exc)


async def _expire_previous_menu(message: types.Message, actor_id: int):
    key = _menu_session_key(actor_id, message.chat.id)
    previous = _active_menu_sessions.get(key)
    if not previous:
        return
    await _expire_menu_message(message.bot, previous["chat_id"], previous["message_id"])
    _active_menu_sessions.pop(key, None)


def _register_menu_session(actor_id: int, chat_id: int, chat_type: str, menu_message_id: int, settings: dict):
    ttl = _menu_ttl_seconds(settings, chat_type)
    now = time.time()
    _active_menu_sessions[_menu_session_key(actor_id, chat_id)] = {
        "actor_id": int(actor_id),
        "chat_id": int(chat_id),
        "chat_type": chat_type,
        "message_id": int(menu_message_id),
        "created_at": now,
        "expires_at": now + ttl if ttl > 0 else 0,
    }


async def _ensure_active_menu_callback(query: types.CallbackQuery, settings: dict) -> bool:
    message = query.message
    if not message:
        await query.answer("Меню устарело, откройте /menu заново.", show_alert=False)
        return False

    key = _menu_session_key(query.from_user.id, message.chat.id)
    session = _active_menu_sessions.get(key)
    expired_by_ttl = _is_message_ttl_expired(message, settings)
    expired_by_registry = bool(session and int(session.get("message_id", 0)) != int(message.message_id))
    expired_by_session = bool(session and session.get("expires_at") and time.time() > session["expires_at"])

    if expired_by_ttl or expired_by_registry or expired_by_session:
        await query.answer("Меню устарело, откройте /menu заново.", show_alert=False)
        await _expire_menu_message(message.bot, message.chat.id, message.message_id)
        if session and int(session.get("message_id", 0)) == int(message.message_id):
            _active_menu_sessions.pop(key, None)
        return False

    if not session:
        _register_menu_session(query.from_user.id, message.chat.id, message.chat.type, message.message_id, settings)
    return True


def _actor_from_update(update: types.Message | types.CallbackQuery):
    return update.from_user


def _chat_from_update(update: types.Message | types.CallbackQuery):
    if isinstance(update, types.CallbackQuery):
        return update.message.chat
    return update.chat


def _resolve_menu_role(actor: types.User):
    db = DatabaseManager()
    try:
        user = db.users.get_user_by_telegram_id(actor.id)
        settings = settings_manager.get_settings()
        profile = db.secretary.get_profile(actor.id)
        role = resolve_user_role(
            settings,
            user,
            actor.id,
            secretary_owner_telegram_id=actor.id if profile else None,
        )
        return role, user, settings
    finally:
        db.close()


async def open_menu(message: types.Message):
    settings = settings_manager.get_settings()
    menu_settings = settings.get("telegram_menu", {})
    if not menu_settings.get("enabled", True):
        await message.reply("Telegram-меню отключено в настройках.")
        return
    if message.chat.type in {"group", "supergroup"} and not menu_settings.get("allow_group_menu", True):
        await message.reply("Меню в группах отключено. Откройте /menu в личном чате с ботом.")
        return

    role, _, settings = _resolve_menu_role(message.from_user)
    text, markup = render_main_menu(role, message.chat.type, settings)
    await _expire_previous_menu(message, message.from_user.id)
    sent_message = await _reply_menu_message(message, text, reply_markup=markup)
    if sent_message:
        _register_menu_session(message.from_user.id, message.chat.id, message.chat.type, sent_message.message_id, settings)
    logger.info(
        "Telegram menu opened: actor=%s, role=%s, chat_id=%s",
        message.from_user.id,
        role,
        message.chat.id,
    )


async def handle_menu_callback(query: types.CallbackQuery):
    actor = query.from_user
    if actor.is_bot:
        await query.answer("Callback от ботов игнорируется.", show_alert=False)
        return
    if not query.message:
        await query.answer("Меню устарело, откройте /menu заново.", show_alert=False)
        return

    chat = query.message.chat
    role, user, settings = _resolve_menu_role(actor)
    data = query.data or ""
    if not await _ensure_active_menu_callback(query, settings):
        return

    try:
        if data == "menu:root:open":
            text, markup = render_main_menu(role, chat.type, settings)
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data == "menu:status:view":
            text, markup = render_status_menu(_format_extended_status(settings))
            await _edit_menu_message(query.message, text[:3900], reply_markup=markup)
            await query.answer()
            return

        if data == "menu:history:open":
            text, markup = render_history_menu()
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data == "menu:history:clear_confirm":
            text, markup = render_confirm("Очистить историю текущего диалога?", "menu:history:clear")
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data == "menu:history:clear":
            await _clear_history_from_menu(query, actor, chat)
            return

        if data == "menu:user_settings:open":
            text, markup = _render_user_settings_menu(user, settings)
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:user_settings:toggle:"):
            await _toggle_user_preference_from_menu(query, user, settings, data.rsplit(":", 1)[-1])
            return

        if data == "menu:models:open":
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            text, markup = render_models_menu(settings, get_model_usage_stats())
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:models:page:"):
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            try:
                page = int(data.rsplit(":", 1)[-1])
            except ValueError:
                page = 0
            text, markup = render_models_menu(settings, get_model_usage_stats(), page=page)
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data == "menu:models:routing":
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            text, markup = render_admin_text_view("Model routing", _format_model_routing_summary(settings), "menu:models:open")
            await _edit_menu_message(query.message, text[:3900], reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:models:toggle:"):
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            await _toggle_model_from_menu(query, int(data.rsplit(":", 1)[-1]))
            return

        if data == "menu:models:reload":
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            result = reload_models()
            if result.get("status") == "success":
                text = (
                    f"Модели перезагружены.\n"
                    f"Активных: {result.get('models_count', 0)}\n"
                    f"Список: {', '.join(result.get('active_models') or []) or '-'}"
                )
            else:
                text = "Не удалось перезагрузить модели."
            markup = render_models_menu(settings_manager.get_settings(), get_model_usage_stats())[1]
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data == "menu:users:open":
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            _user_menu_filters.pop(actor.id, None)
            text, markup = _render_users_menu()
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:users:page:"):
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            parts = data.split(":")
            try:
                page = int(parts[3])
            except (IndexError, ValueError):
                page = 0
            sort = parts[4] if len(parts) > 4 else "activity"
            text, markup = _render_users_menu(page=page, sort=sort, query=_user_menu_filters.get(actor.id, ""))
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:users:sort:"):
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            sort = data.rsplit(":", 1)[-1]
            text, markup = _render_users_menu(sort=sort, query=_user_menu_filters.get(actor.id, ""))
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:users:view:"):
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            try:
                telegram_id = int(data.rsplit(":", 1)[-1])
            except ValueError:
                await query.answer("Некорректный Telegram ID.", show_alert=True)
                return
            db = DatabaseManager()
            try:
                target = db.users.get_user_by_telegram_id(telegram_id)
            finally:
                db.close()
            if not target:
                await query.answer("Пользователь не найден.", show_alert=True)
                return
            text, markup = render_user_card(target)
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data == "menu:admin_secretaries:open":
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            text, markup = _render_admin_secretaries_menu()
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:admin_secretaries:"):
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            await _handle_admin_secretaries_action(query, data)
            return

        if data == "menu:logs:open":
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            text, markup = _render_logs_menu(settings, page=0)
            await _edit_menu_message(query.message, text[:3900], reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:logs:page:"):
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            try:
                page = int(data.rsplit(":", 1)[-1])
            except ValueError:
                page = 0
            text, markup = _render_logs_menu(settings, page=page)
            await _edit_menu_message(query.message, text[:3900], reply_markup=markup)
            await query.answer()
            return

        if data == "menu:actions:open":
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            text, markup = _render_actions_menu(page=0)
            await _edit_menu_message(query.message, text[:3900], reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:actions:page:"):
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            try:
                page = int(data.rsplit(":", 1)[-1])
            except ValueError:
                page = 0
            text, markup = _render_actions_menu(page=page)
            await _edit_menu_message(query.message, text[:3900], reply_markup=markup)
            await query.answer()
            return

        if data == "menu:users:find":
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            _pending_menu_inputs[actor.id] = {
                "type": "admin_user_find",
                "expires_at": time.time() + settings.get("telegram_menu", {}).get("input_wait_timeout_seconds", 300),
            }
            text, markup = render_user_find_wait()
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data == "menu:users:find_cancel":
            _pending_menu_inputs.pop(actor.id, None)
            _user_menu_filters.pop(actor.id, None)
            text, markup = _render_users_menu()
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:users:ban:"):
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            await _toggle_user_ban_from_menu(query, int(data.rsplit(":", 1)[-1]))
            return

        if data.startswith("menu:users:prio_up:") or data.startswith("menu:users:prio_down:"):
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            direction = 1 if data.startswith("menu:users:prio_up:") else -1
            await _change_user_priority_from_menu(query, int(data.rsplit(":", 1)[-1]), direction)
            return

        if data == "menu:group:open":
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            text, markup = _render_group_menu_for_chat(chat, settings)
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:group:toggle:"):
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            setting_key = data.rsplit(":", 1)[-1]
            updated = _toggle_safe_setting(setting_key)
            text, markup = _render_group_menu_for_chat(chat, updated)
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer("Настройка обновлена.")
            logger.info("Menu group setting toggled: actor=%s, key=%s, chat_id=%s", actor.id, setting_key, chat.id)
            return

        if data == "menu:group:ban_confirm":
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            if chat.type not in {"group", "supergroup"}:
                await query.answer("Доступно только в группе.", show_alert=True)
                return
            db = DatabaseManager()
            try:
                is_banned = db.messages.is_group_banned(chat.id)
            finally:
                db.close()
            action_text = "Разбанить группу?" if is_banned else "Забанить группу?"
            text, markup = render_confirm(action_text, "menu:group:ban_toggle")
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data == "menu:group:ban_toggle":
            await _toggle_group_ban_from_menu(query, actor, chat, settings, user)
            return

        if data == "menu:group:reset_confirm":
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            text, markup = render_confirm("Сбросить весь контекст этой группы?", "menu:group:reset")
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data == "menu:group:reset":
            await _reset_group_context_from_menu(query, actor, chat, settings, user)
            return

        if data == "menu:settings:open":
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            text, markup = render_settings_menu(settings)
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:settings:toggle:"):
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            setting_key = data.rsplit(":", 1)[-1]
            updated = _toggle_safe_setting(setting_key)
            text, markup = render_settings_menu(updated)
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer("Настройка обновлена.")
            logger.info("Menu setting toggled: actor=%s, key=%s", actor.id, setting_key)
            return

        if data == "menu:mcp:open":
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            text, markup = _render_mcp_menu()
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:mcp:"):
            if not is_admin_user(settings, user, actor.id):
                await query.answer("Нет прав.", show_alert=True)
                return
            await _handle_mcp_menu_action(query, actor, chat, data)
            return

        if data == "menu:secretary:open":
            profile = DatabaseManager()
            try:
                secretary_profile = profile.secretary.get_profile(actor.id)
            finally:
                profile.close()
            if not secretary_profile:
                await query.answer("Секретарь не настроен для вашего профиля.", show_alert=True)
                return
            text, markup = render_secretary_menu(secretary_profile)
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data.startswith("menu:secretary:toggle:"):
            await _toggle_secretary_setting(query, actor, data.rsplit(":", 1)[-1])
            return

        if data == "menu:secretary:owner_behavior:cycle":
            await _cycle_secretary_owner_behavior(query, actor)
            return

        if data == "menu:secretary:events":
            await _show_secretary_events(query, actor)
            return

        if data.startswith("menu:secretary:session:"):
            await _handle_secretary_session_action(query, actor, data.rsplit(":", 1)[-1])
            return

        if data == "menu:secretary:history:clear_confirm":
            text, markup = render_confirm("Очистить всю историю Личного секретаря?", "menu:secretary:history:clear")
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data == "menu:secretary:history:clear":
            await _clear_secretary_history_from_menu(query, actor)
            return

        if data == "menu:secretary:mode:cycle":
            await _cycle_secretary_mode(query, actor)
            return

        if data == "menu:secretary:prompt:edit":
            if chat.type != "private":
                await query.answer("Prompt можно менять только в личном чате.", show_alert=True)
                return
            db = DatabaseManager()
            try:
                profile = db.secretary.get_profile(actor.id)
            finally:
                db.close()
            if not profile:
                await query.answer("Секретарь не настроен для вашего профиля.", show_alert=True)
                return
            _pending_menu_inputs[actor.id] = {
                "type": "secretary_prompt",
                "expires_at": time.time() + settings.get("telegram_menu", {}).get("input_wait_timeout_seconds", 300),
            }
            text, markup = render_secretary_prompt_wait()
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if data == "menu:secretary:prompt:cancel":
            _pending_menu_inputs.pop(actor.id, None)
            db = DatabaseManager()
            try:
                profile = db.secretary.get_profile(actor.id)
            finally:
                db.close()
            if profile:
                text, markup = render_secretary_menu(profile)
                await _edit_menu_message(query.message, text, reply_markup=markup)
            else:
                await _edit_menu_message(query.message, "Ввод отменён.")
            await query.answer()
            return

        await query.answer("Раздел ещё не подключён.", show_alert=False)
    except Exception as exc:
        logger.error("Ошибка обработки menu callback %s от %s: %s", data, actor.id, exc)
        await query.answer("Ошибка меню.", show_alert=True)


async def _clear_history_from_menu(query: types.CallbackQuery, actor: types.User, chat: types.Chat):
    db = DatabaseManager()
    try:
        user = db.users.ensure_user(actor.id, actor.username, actor.first_name, actor.last_name)
        if chat.type in {"group", "supergroup"}:
            deleted_count = db.messages.delete_group_conversation(chat.id)
        else:
            deleted_count = db.messages.delete_messages_by_chat_id(chat.id)
        reset_history_cache()
        await _edit_menu_message(query.message, f"История очищена. Удалено сообщений: {deleted_count}.")
        await query.answer()
        logger.info("Menu history clear: actor=%s, user_id=%s, chat_id=%s", actor.id, user.get("id") if user else None, chat.id)
    finally:
        db.close()


def _render_user_settings_menu(user, settings):
    db = DatabaseManager()
    try:
        current_user = user if isinstance(user, dict) else {}
        preferences = db.users.get_user_preferences(current_user) if current_user else {}
        return render_user_settings_menu(current_user, preferences, settings)
    finally:
        db.close()


async def _toggle_user_preference_from_menu(query: types.CallbackQuery, user, settings, key: str):
    allowed = {"stream_mode", "format_markdown", "format_html"}
    if key not in allowed:
        await query.answer("Настройка не поддерживается.", show_alert=True)
        return
    if not user:
        await query.answer("Пользователь не найден.", show_alert=True)
        return

    db = DatabaseManager()
    try:
        preferences = db.users.get_user_preferences(user)
        current = preferences.get(key, settings.get(key, False))
        preferences = db.users.update_user_preferences(user["id"], **{key: not bool(current)})
        updated_user = db.users.get_user_by_telegram_id(user["telegram_id"])
    finally:
        db.close()
    text, markup = render_user_settings_menu(updated_user or user, preferences, settings)
    await _edit_menu_message(query.message, text, reply_markup=markup)
    await query.answer("Настройка обновлена.")
    logger.info("Menu user preference toggled: actor=%s key=%s", query.from_user.id, key)


async def consume_menu_text_input(message: types.Message) -> bool:
    pending = _pending_menu_inputs.get(message.from_user.id)
    if not pending:
        return False
    if time.time() > pending.get("expires_at", 0):
        _pending_menu_inputs.pop(message.from_user.id, None)
        await message.reply("Ввод устарел. Откройте /menu заново.")
        return True
    if pending.get("type") != "secretary_prompt":
        if pending.get("type") == "admin_user_find":
            return await _consume_admin_user_find(message, pending)
        return False
    if message.chat.type != "private":
        await message.reply("Prompt можно отправить только в личном чате.")
        return True
    prompt = (message.text or "").strip()
    if not prompt:
        await message.reply("Prompt пустой. Отправьте текст или нажмите Отмена в меню.")
        return True

    db = DatabaseManager()
    try:
        profile = db.secretary.get_profile(message.from_user.id)
        if not profile:
            await message.reply("Секретарь не настроен для вашего профиля.")
            return True
        db.secretary.upsert_profile(message.from_user.id, system_prompt=prompt)
        db.secretary.add_event(message.from_user.id, "updated", "System prompt updated from Telegram menu")
    finally:
        db.close()
    _pending_menu_inputs.pop(message.from_user.id, None)
    await message.reply("Prompt секретаря сохранён.")
    logger.info("Secretary prompt updated from menu: actor=%s", message.from_user.id)
    return True


async def _consume_admin_user_find(message: types.Message, pending: dict) -> bool:
    role, admin_user, settings = _resolve_menu_role(message.from_user)
    if not is_admin_user(settings, admin_user, message.from_user.id):
        _pending_menu_inputs.pop(message.from_user.id, None)
        await message.reply("Нет прав.")
        return True
    if message.chat.type != "private":
        await message.reply("Поиск пользователя через меню доступен только в личном чате.")
        return True
    query_text = (message.text or "").strip()
    try:
        telegram_id = int(query_text)
    except ValueError:
        _pending_menu_inputs.pop(message.from_user.id, None)
        _user_menu_filters[message.from_user.id] = query_text
        text, markup = _render_users_menu(query=query_text)
        await _reply_menu_message(message, text, reply_markup=markup)
        logger.info("Menu user search: actor=%s query=%s", message.from_user.id, query_text[:80])
        return True

    db = DatabaseManager()
    try:
        target = db.users.get_user_by_telegram_id(telegram_id)
    finally:
        db.close()
    _pending_menu_inputs.pop(message.from_user.id, None)
    if not target:
        await message.reply("Пользователь не найден.")
        return True
    text, markup = render_user_card(target)
    await _reply_menu_message(message, text, reply_markup=markup)
    logger.info("Menu user found: actor=%s target=%s", message.from_user.id, telegram_id)
    return True


async def _toggle_secretary_setting(query: types.CallbackQuery, actor: types.User, key: str):
    allowed = {
        "enabled": "enabled",
        "save_history": "save_history",
        "ignore_bots": "ignore_bot_messages",
        "close_after_reply": "close_after_reply",
    }
    field = allowed.get(key)
    if not field:
        await query.answer("Настройка не поддерживается.", show_alert=True)
        return
    db = DatabaseManager()
    try:
        profile = db.secretary.get_profile(actor.id)
        if not profile:
            await query.answer("Секретарь не настроен для вашего профиля.", show_alert=True)
            return
        db.secretary.upsert_profile(actor.id, **{field: 0 if profile.get(field, 0) else 1})
        updated = db.secretary.get_profile(actor.id)
        db.secretary.add_event(actor.id, "updated", f"{field} toggled from Telegram menu")
    finally:
        db.close()
    text, markup = render_secretary_menu(updated)
    await _edit_menu_message(query.message, text, reply_markup=markup)
    await query.answer("Настройка обновлена.")


async def _cycle_secretary_owner_behavior(query: types.CallbackQuery, actor: types.User):
    behaviors = ["ignore", "takeover", "add_to_context", "close_session"]
    db = DatabaseManager()
    try:
        profile = db.secretary.get_profile(actor.id)
        if not profile:
            await query.answer("Секретарь не настроен для вашего профиля.", show_alert=True)
            return
        current = profile.get("owner_message_behavior") or "takeover"
        next_behavior = behaviors[(behaviors.index(current) + 1) % len(behaviors)] if current in behaviors else "takeover"
        db.secretary.upsert_profile(actor.id, owner_message_behavior=next_behavior)
        updated = db.secretary.get_profile(actor.id)
        db.secretary.add_event(actor.id, "updated", f"owner_message_behavior={next_behavior} from Telegram menu")
    finally:
        db.close()
    text, markup = render_secretary_menu(updated)
    await _edit_menu_message(query.message, text, reply_markup=markup)
    await query.answer("Поведение владельца обновлено.")


async def _cycle_secretary_mode(query: types.CallbackQuery, actor: types.User):
    modes = ["off", "draft", "confirm", "auto"]
    db = DatabaseManager()
    try:
        profile = db.secretary.get_profile(actor.id)
        if not profile:
            await query.answer("Секретарь не настроен для вашего профиля.", show_alert=True)
            return
        current = profile.get("response_mode") or "draft"
        next_mode = modes[(modes.index(current) + 1) % len(modes)] if current in modes else "draft"
        db.secretary.upsert_profile(actor.id, response_mode=next_mode)
        updated = db.secretary.get_profile(actor.id)
        db.secretary.add_event(actor.id, "updated", f"response_mode={next_mode} from Telegram menu")
    finally:
        db.close()
    text, markup = render_secretary_menu(updated)
    await _edit_menu_message(query.message, text, reply_markup=markup)
    await query.answer("Режим обновлён.")


async def _show_secretary_events(query: types.CallbackQuery, actor: types.User):
    db = DatabaseManager()
    try:
        profile = db.secretary.get_profile(actor.id)
        if not profile:
            await query.answer("Секретарь не настроен для вашего профиля.", show_alert=True)
            return
        events = db.secretary.list_events(actor.id, limit=10)
    finally:
        db.close()

    if events:
        body = "\n".join(
            f"- {event.get('created_at')} chat={event.get('chat_id') or '-'} "
            f"{event.get('status')}: {(event.get('details') or '')[:120]}"
            for event in events
        )
    else:
        body = "Событий пока нет."
    text, markup = render_admin_text_view("События секретаря", body, "menu:secretary:open")
    await _edit_menu_message(query.message, text[:3900], reply_markup=markup)
    await query.answer()


async def _handle_secretary_session_action(query: types.CallbackQuery, actor: types.User, action: str):
    db = DatabaseManager()
    try:
        profile = db.secretary.get_profile(actor.id)
        if not profile:
            await query.answer("Секретарь не настроен для вашего профиля.", show_alert=True)
            return
        session = db.secretary.get_latest_active_session(actor.id)
        if not session or not session.get("id"):
            await query.answer("Активной сессии нет.", show_alert=False)
            text, markup = render_secretary_menu(profile)
            await _edit_menu_message(query.message, text, reply_markup=markup)
            return
        reason = "manual_new_session" if action == "new" else "manual_close"
        db.secretary.close_session(int(session["id"]), reason=reason)
        db.secretary.add_event(actor.id, "session_closed", f"{reason} from Telegram menu", chat_id=session.get("chat_id"))
        updated = db.secretary.get_profile(actor.id)
    finally:
        db.close()

    text, markup = render_secretary_menu(updated)
    await _edit_menu_message(query.message, text, reply_markup=markup)
    await query.answer("Новая сессия начнется со следующего сообщения." if action == "new" else "Сессия закрыта.")


async def _clear_secretary_history_from_menu(query: types.CallbackQuery, actor: types.User):
    db = DatabaseManager()
    try:
        profile = db.secretary.get_profile(actor.id)
        if not profile:
            await query.answer("Секретарь не настроен для вашего профиля.", show_alert=True)
            return
        deleted_count = db.messages.delete_secretary_context(actor.id)
        session = db.secretary.get_latest_active_session(actor.id)
        if session and session.get("id"):
            db.secretary.close_session(int(session["id"]), reason="history_clear")
        db.secretary.add_event(actor.id, "context_reset", f"deleted={deleted_count} from Telegram menu")
        updated = db.secretary.get_profile(actor.id)
    finally:
        db.close()
    reset_history_cache()
    text, markup = render_secretary_menu(updated)
    await _edit_menu_message(query.message, f"{text}\n\nУдалено сообщений: {deleted_count}.", reply_markup=markup)
    await query.answer("История секретаря очищена.")


async def _toggle_user_ban_from_menu(query: types.CallbackQuery, target_telegram_id: int):
    db = DatabaseManager()
    try:
        target = db.users.get_user_by_telegram_id(target_telegram_id)
        if not target:
            await query.answer("Пользователь не найден.", show_alert=True)
            return
        new_ban = 0 if target.get("is_banned", 0) else 1
        db.users.update_user(target["id"], is_banned=new_ban)
        updated = db.users.get_user_by_telegram_id(target_telegram_id)
    finally:
        db.close()
    text, markup = render_user_card(updated)
    await _edit_menu_message(query.message, text, reply_markup=markup)
    await query.answer("Статус пользователя обновлён.")
    logger.info("Menu user ban toggled: actor=%s target=%s banned=%s", query.from_user.id, target_telegram_id, new_ban)


async def _toggle_model_from_menu(query: types.CallbackQuery, model_index: int):
    settings = settings_manager.get_settings()
    models = settings.get("models", [])
    if model_index < 0 or model_index >= len(models) or not isinstance(models[model_index], dict):
        await query.answer("Модель не найдена.", show_alert=True)
        return

    active_models = [model for model in models if isinstance(model, dict) and model.get("active", True)]
    current = models[model_index]
    new_active = not bool(current.get("active", True))
    if not new_active and len(active_models) <= 1:
        await query.answer("Нельзя выключить последнюю активную модель.", show_alert=True)
        return

    current["active"] = new_active
    settings_manager.settings["models"] = models
    settings_manager.save_settings()
    result = reload_models()
    updated = settings_manager.get_settings()
    text, markup = render_models_menu(updated, get_model_usage_stats())
    await _edit_menu_message(query.message, text[:3900], reply_markup=markup)
    await query.answer("Модель обновлена.")
    logger.info(
        "Menu model toggled: actor=%s model=%s active=%s reload_status=%s",
        query.from_user.id,
        current.get("id"),
        new_active,
        result.get("status"),
    )


async def _change_user_priority_from_menu(query: types.CallbackQuery, target_telegram_id: int, delta: int):
    db = DatabaseManager()
    try:
        target = db.users.get_user_by_telegram_id(target_telegram_id)
        if not target:
            await query.answer("Пользователь не найден.", show_alert=True)
            return
        new_priority = max(0, min(100, int(target.get("priority") or 0) + delta))
        db.users.update_user(target["id"], priority=new_priority)
        updated = db.users.get_user_by_telegram_id(target_telegram_id)
    finally:
        db.close()
    text, markup = render_user_card(updated)
    await _edit_menu_message(query.message, text, reply_markup=markup)
    await query.answer("Priority обновлён.")
    logger.info("Menu user priority changed: actor=%s target=%s priority=%s", query.from_user.id, target_telegram_id, new_priority)


def _toggle_safe_setting(setting_key: str):
    settings = settings_manager.get_settings()
    if setting_key == "accept_bot_messages":
        settings_manager.settings["accept_bot_messages"] = not settings.get("accept_bot_messages", True)
    elif setting_key == "respond_only_on_mention":
        settings_manager.settings["respond_only_on_mention"] = not settings.get("respond_only_on_mention", False)
    elif setting_key == "reject_empty_mentions":
        settings_manager.settings["reject_empty_mentions"] = not settings.get("reject_empty_mentions", True)
    elif setting_key == "group_parallel_mode":
        settings_manager.settings["group_parallel_mode"] = not settings.get("group_parallel_mode", False)
    elif setting_key == "stream_mode":
        settings_manager.settings["stream_mode"] = not settings.get("stream_mode", False)
    elif setting_key == "format_markdown":
        settings_manager.settings["format_markdown"] = not settings.get("format_markdown", True)
    elif setting_key == "format_html":
        settings_manager.settings["format_html"] = not settings.get("format_html", True)
    elif setting_key == "telegram_menu_enabled":
        telegram_menu = dict(settings.get("telegram_menu", {}) or {})
        telegram_menu["enabled"] = not telegram_menu.get("enabled", True)
        settings_manager.settings["telegram_menu"] = telegram_menu
    elif setting_key == "colored_buttons_enabled":
        telegram_menu = dict(settings.get("telegram_menu", {}) or {})
        telegram_menu["colored_buttons_enabled"] = not telegram_menu.get("colored_buttons_enabled", True)
        settings_manager.settings["telegram_menu"] = telegram_menu
    settings_manager.save_settings()
    return settings_manager.get_settings()


def _render_group_menu_for_chat(chat: types.Chat, settings):
    db = DatabaseManager()
    try:
        is_banned = db.messages.is_group_banned(chat.id) if chat.type in {"group", "supergroup"} else False
    finally:
        db.close()
    return render_group_menu(settings, is_banned=is_banned)


def _mcp_statuses_by_server():
    db = DatabaseManager()
    try:
        return {item.get("server_name"): item for item in db.mcp.list_server_statuses()}
    finally:
        db.close()


def _render_mcp_menu():
    return render_mcp_menu(settings_manager.get_settings(), _mcp_statuses_by_server())


def _render_logs_menu(settings, *, page: int = 0):
    return render_paged_text_view(
        "Логи приложения",
        _read_log_lines(settings, max_lines=120),
        page=page,
        per_page=8,
        page_callback="menu:logs:page",
        hint="Показаны последние строки. Новые записи идут первыми.",
    )


def _render_actions_menu(*, page: int = 0):
    return render_paged_text_view(
        "История действий",
        _recent_action_lines(limit=80),
        page=page,
        per_page=20,
        page_callback="menu:actions:page",
        hint="Это audit-лента MCP и секретаря. Новые события идут первыми.",
    )


def _render_admin_secretaries_menu():
    db = DatabaseManager()
    try:
        profiles = db.secretary.list_profiles()
    finally:
        db.close()
    return render_admin_secretaries_menu(profiles)


def _render_users_menu(*, page: int = 0, sort: str = "activity", query: str = ""):
    db = DatabaseManager()
    try:
        users = db.users.get_all_users()
    finally:
        db.close()
    users = _filter_users_for_menu(users, query)
    users = _sort_users_for_menu(users, sort)
    return render_users_menu(users, page=page, sort=sort, query=query)


def _filter_users_for_menu(users, query: str):
    needle = str(query or "").strip().lower()
    if not needle:
        return users
    result = []
    for item in users:
        fields = [
            item.get("telegram_id"),
            item.get("username"),
            item.get("first_name"),
            item.get("last_name"),
        ]
        if any(needle in str(value or "").lower() for value in fields):
            result.append(item)
    return result


def _sort_users_for_menu(users, sort: str):
    if sort == "priority":
        return sorted(
            users,
            key=lambda item: (
                -int(item.get("priority") or 0),
                int(item.get("is_banned") or 0),
                _user_last_activity_key(item),
            ),
        )
    if sort == "name":
        return sorted(users, key=lambda item: _user_name_key(item))
    return sorted(users, key=lambda item: _user_last_activity_key(item), reverse=True)


def _user_last_activity_key(item):
    return str(item.get("last_activity") or "")


def _user_name_key(item):
    username = item.get("username") or ""
    first_name = item.get("first_name") or ""
    last_name = item.get("last_name") or ""
    return (username or f"{first_name} {last_name}" or str(item.get("telegram_id") or "")).lower()


async def _handle_admin_secretaries_action(query: types.CallbackQuery, data: str):
    parts = data.split(":")
    if len(parts) < 4:
        await query.answer("Некорректное действие секретаря.", show_alert=True)
        return
    action = parts[2]
    try:
        owner_id = int(parts[3])
    except ValueError:
        await query.answer("Некорректный owner ID.", show_alert=True)
        return

    db = DatabaseManager()
    try:
        profile = db.secretary.get_profile(owner_id)
        if not profile:
            await query.answer("Профиль не найден.", show_alert=True)
            return

        if action == "view":
            events_count = len(db.secretary.list_events(owner_id, limit=100))
            text, markup = render_admin_secretary_card(profile, events_count)
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if action == "toggle":
            db.secretary.upsert_profile(owner_id, enabled=0 if profile.get("enabled") else 1)
            db.secretary.add_event(owner_id, "updated", f"enabled toggled by admin {query.from_user.id}")
            updated = db.secretary.get_profile(owner_id)
            events_count = len(db.secretary.list_events(owner_id, limit=100))
            text, markup = render_admin_secretary_card(updated, events_count)
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer("Профиль обновлён.")
            logger.info("Menu admin secretary toggled: actor=%s owner=%s", query.from_user.id, owner_id)
            return

        if action == "events":
            events = db.secretary.list_events(owner_id, limit=12)
            if events:
                body = "\n".join(
                    f"- {event.get('created_at')} chat={event.get('chat_id') or '-'} "
                    f"{event.get('status')}: {(event.get('details') or '')[:120]}"
                    for event in events
                )
            else:
                body = "Событий пока нет."
            text, markup = render_admin_text_view(
                f"Secretary events: {owner_id}",
                body,
                f"menu:admin_secretaries:view:{owner_id}",
            )
            await _edit_menu_message(query.message, text[:3900], reply_markup=markup)
            await query.answer()
            return

        if action == "reset_confirm":
            text, markup = render_confirm(
                f"Сбросить secretary context владельца {owner_id}?",
                f"menu:admin_secretaries:reset:{owner_id}",
            )
            await _edit_menu_message(query.message, text, reply_markup=markup)
            await query.answer()
            return

        if action == "reset":
            deleted_count = db.messages.delete_secretary_context(owner_id)
            db.secretary.add_event(owner_id, "context_reset", f"deleted={deleted_count} by admin {query.from_user.id}")
            text, markup = render_admin_secretary_card(db.secretary.get_profile(owner_id), len(db.secretary.list_events(owner_id, limit=100)))
            await _edit_menu_message(query.message, f"{text}\n\nContext reset: удалено сообщений {deleted_count}.", reply_markup=markup)
            await query.answer("Secretary context сброшен.")
            logger.info("Menu admin secretary context reset: actor=%s owner=%s deleted=%s", query.from_user.id, owner_id, deleted_count)
            return
    finally:
        db.close()

    await query.answer("Действие секретаря не поддерживается.", show_alert=True)


def _get_mcp_server(index: int):
    settings = settings_manager.get_settings()
    mcp = settings.get("mcp", {}) if isinstance(settings.get("mcp"), dict) else {}
    servers = mcp.get("servers", [])
    if index < 0 or index >= len(servers) or not isinstance(servers[index], dict):
        return None, settings, servers
    return normalize_server_config(servers[index]), settings, servers


async def _handle_mcp_menu_action(query: types.CallbackQuery, actor: types.User, chat: types.Chat, data: str):
    parts = data.split(":")
    if len(parts) < 4:
        await query.answer("Некорректное действие MCP.", show_alert=True)
        return
    action = parts[2]
    try:
        index = int(parts[3])
    except ValueError:
        await query.answer("Некорректный MCP ID.", show_alert=True)
        return

    server, settings, servers = _get_mcp_server(index)
    if not server:
        await query.answer("MCP-сервер не найден.", show_alert=True)
        return

    raw_server = dict(servers[index])
    if action == "server":
        statuses = _mcp_statuses_by_server()
        text, markup = render_mcp_server_details(server, index, settings, statuses.get(server.get("name"), {}))
        await query.answer()
        await _edit_menu_message(query.message, text, reply_markup=markup)
        return

    if action in {"tools", "tools_page"}:
        try:
            page = int(parts[4]) if action == "tools_page" and len(parts) > 4 else 0
        except ValueError:
            page = 0
        text, markup = render_mcp_tools_view(server, index, settings, page=page)
        await _edit_menu_message(query.message, text, reply_markup=markup)
        await query.answer()
        return

    if action == "status":
        statuses = _mcp_statuses_by_server()
        status = statuses.get(server.get("name"), {})
        text, markup = render_mcp_status_view(server, index, settings, status)
        await _edit_menu_message(query.message, text, reply_markup=markup)
        await query.answer()
        return

    if action == "discover":
        if not is_mcp_sdk_available():
            await query.answer("MCP SDK недоступен.", show_alert=True)
            return
        await query.answer("Запускаю discovery...")
        try:
            capabilities = await asyncio.to_thread(discover_server_capabilities, server)
        except McpRuntimeError as exc:
            await _edit_menu_message(query.message, 
                f"MCP discovery failed: {server.get('name')}\n{exc}",
                reply_markup=render_mcp_menu(settings, _mcp_statuses_by_server())[1],
            )
            return
        except Exception as exc:
            logger.error("Menu MCP discovery failed: actor=%s server=%s error=%s", actor.id, server.get("name"), exc)
            await _edit_menu_message(query.message, 
                f"MCP discovery failed: {server.get('name')}\n{exc}",
                reply_markup=render_mcp_menu(settings, _mcp_statuses_by_server())[1],
            )
            return

        raw_server["tools"] = capabilities.get("tools") or []
        raw_server["resources"] = capabilities.get("resources") or []
        raw_server["resource_templates"] = capabilities.get("resource_templates") or []
        raw_server["prompts"] = capabilities.get("prompts") or []
        servers[index] = raw_server
        _save_mcp_servers(settings, servers)
        statuses = _mcp_statuses_by_server()
        text = (
            f"MCP discovery: {server.get('name')}\n"
            f"Tools: {len(raw_server['tools'])}\n"
            f"Resources: {len(raw_server['resources'])}\n"
            f"Resource templates: {len(raw_server['resource_templates'])}\n"
            f"Prompts: {len(raw_server['prompts'])}"
        )
        text, markup = render_mcp_server_details(normalize_server_config(raw_server), index, settings_manager.get_settings(), statuses.get(server.get("name"), {}))
        await _edit_menu_message(query.message, text, reply_markup=markup)
        logger.info("Menu MCP discovery completed: actor=%s server=%s tools=%s", actor.id, server.get("name"), len(raw_server["tools"]))
        return

    if action == "toggle":
        raw_server["enabled"] = not bool(raw_server.get("enabled", False))
        servers[index] = raw_server
        _save_mcp_servers(settings, servers)
        text, markup = _render_mcp_menu()
        await _edit_menu_message(query.message, text, reply_markup=markup)
        await query.answer("MCP-сервер обновлён.")
        logger.info("Menu MCP server toggled: actor=%s server=%s enabled=%s", actor.id, server.get("name"), raw_server["enabled"])
        return

    if action == "access":
        access = dict(raw_server.get("access") or {})
        if chat.type in {"group", "supergroup"}:
            access["group"] = not bool(access.get("group", False))
            message = "Доступ для групп обновлён."
        else:
            access["private"] = not bool(access.get("private", False))
            message = "Доступ для личных чатов обновлён."
        raw_server["access"] = access
        servers[index] = raw_server
        _save_mcp_servers(settings, servers)
        text, markup = _render_mcp_menu()
        await _edit_menu_message(query.message, text, reply_markup=markup)
        await query.answer(message)
        logger.info("Menu MCP access toggled: actor=%s server=%s chat_type=%s access=%s", actor.id, server.get("name"), chat.type, access)
        return

    await query.answer("Действие MCP не поддерживается.", show_alert=True)


def _save_mcp_servers(settings, servers):
    current_mcp = dict(settings.get("mcp") or {})
    current_mcp["servers"] = servers
    settings_manager.settings["mcp"] = current_mcp
    settings_manager.save_settings()


def _format_mcp_server_details(server):
    access = server.get("access") or {}
    access_text = ", ".join(key for key, value in access.items() if value) or "нет"
    return (
        f"MCP server: {server.get('name')}\n"
        f"Enabled: {'yes' if server.get('enabled') else 'no'}\n"
        f"Command: {server.get('command') or '-'}\n"
        f"Tools: {len(server.get('tools') or [])}\n"
        f"Access: {access_text}\n\n"
        "Env, args и command редактируются только в desktop GUI."
    )


def _format_extended_status(settings) -> str:
    server_status = "активен" if server_state.server_active else "остановлен"
    models = [model for model in settings.get("models", []) if isinstance(model, dict)]
    active_config_models = [model for model in models if model.get("active", True)]
    usage_stats = get_model_usage_stats()
    loaded_models = [model_id for model_id, item in usage_stats.items() if item.get("is_active")]

    db = DatabaseManager()
    try:
        users_count = db.users.count_users()
        groups_count = len(db.messages.get_group_chats(limit=500))
    finally:
        db.close()

    last_errors = _read_recent_errors(settings, max_lines=3)
    return (
        "Статус\n"
        f"Сервер: {server_status}\n"
        f"Очередь: {stats.stats.get_pending_requests()}\n"
        f"Запросов за сеанс: {stats.stats.get_request_count()}\n"
        f"Обрезаний контекста: {stats.stats.get_context_truncated_count()}\n"
        f"Токены: in={stats.stats.get_input_tokens_total()} out={stats.stats.get_output_tokens_total()}\n"
        f"Пользователей: {users_count}\n"
        f"Групп: {groups_count}\n"
        f"Модели в конфиге: {len(active_config_models)}/{len(models)} активны\n"
        f"Загружены: {', '.join(loaded_models[:6]) if loaded_models else '-'}\n"
        f"Routing: {settings.get('load_balancing_strategy', 'round_robin')}\n"
        f"Последние ошибки:\n{last_errors}"
    )


def _format_model_routing_summary(settings) -> str:
    models = [model for model in settings.get("models", []) if isinstance(model, dict)]
    usage_stats = get_model_usage_stats()
    lines = [
        f"Стратегия: {settings.get('load_balancing_strategy', 'round_robin')}",
        f"Моделей: {sum(1 for model in models if model.get('active', True))}/{len(models)} активны",
        "",
    ]
    if not models:
        lines.append("Модели не настроены.")
        return "\n".join(lines)

    for index, model in enumerate(models[:20]):
        model_id = str(model.get("id") or f"model_{index}")
        runtime = usage_stats.get(model_id, {})
        lines.append(
            f"- {model_id}: active={'yes' if model.get('active', True) else 'no'}, "
            f"loaded={'yes' if runtime.get('is_active') else 'no'}, "
            f"api={model.get('api_type', 'openai')}, "
            f"weight={model.get('weight', 1)}, "
            f"max_parallel={model.get('max_concurrent_requests', 1)}, "
            f"context={model.get('context_window_size', settings.get('default_context_length', 4096))}, "
            f"reasoning={model.get('reasoning_mode', 'default')}/{model.get('reasoning_provider', 'auto')}, "
            f"active_req={runtime.get('active_requests', 0)}"
        )
    return "\n".join(lines)


def _read_log_tail(settings, max_lines: int = 24) -> str:
    return "\n".join(reversed(_read_log_lines(settings, max_lines=max_lines)))


def _read_log_lines(settings, max_lines: int = 120) -> list[str]:
    log_file = settings.get("log_file", "app.log")
    path = Path(log_file)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return [f"Файл логов не найден: {path}"]
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        return [f"Не удалось прочитать лог: {exc}"]
    if not lines:
        return ["Лог пустой."]
    tail = lines[-max_lines:]
    return [_sanitize_log_line(line) for line in reversed(tail)]


def _read_recent_errors(settings, max_lines: int = 3) -> str:
    log_file = settings.get("log_file", "app.log")
    path = Path(log_file)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return "-"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return "-"
    errors = [line for line in lines if "ERROR" in line or "CRITICAL" in line]
    if not errors:
        return "-"
    return "\n".join(_sanitize_log_line(line) for line in errors[-max_lines:])


def _sanitize_log_line(line: str) -> str:
    text = str(line)
    markers = ("TOKEN", "KEY", "SECRET", "PASSWORD", "PASS", "COOKIE")
    if any(marker in text.upper() for marker in markers):
        return "[скрыто: строка похожа на секрет]"
    return text[:220]


def _format_recent_actions(limit: int = 8) -> str:
    return "\n".join(_recent_action_lines(limit=limit))


def _recent_action_lines(limit: int = 80) -> list[str]:
    db = DatabaseManager()
    try:
        tool_calls = db.mcp.list_tool_calls(limit=limit)
        denials = db.mcp.list_access_denials(limit=limit)
        secretary_events = db.secretary.list_recent_events(limit=limit)
    finally:
        db.close()

    entries = []
    for item in tool_calls:
        entries.append((
            str(item.get("created_at") or ""),
            "MCP tool",
            f"{item.get('server_name')}.{item.get('tool_name')}",
            f"status={item.get('status') or '-'} actor={item.get('actor_telegram_id') or '-'}",
        ))
    for item in denials:
        entries.append((
            str(item.get("created_at") or ""),
            "MCP denied",
            f"{item.get('server_name')}.{item.get('tool_name')}",
            f"actor={item.get('actor_telegram_id') or '-'} reason={item.get('reason') or '-'}",
        ))
    for item in secretary_events:
        details = _sanitize_log_line(item.get("details") or "")[:120]
        entries.append((
            str(item.get("created_at") or ""),
            "Secretary",
            f"owner={item.get('owner_telegram_id')} chat={item.get('chat_id') or '-'}",
            f"{item.get('status') or '-'}: {details}",
        ))
    if not entries:
        return ["Записей нет."]
    entries.sort(key=lambda item: item[0], reverse=True)
    lines = []
    for created_at, category, title, details in entries[:limit]:
        lines.extend([f"{created_at} · {category}", f"   {title}", f"   {details}", ""])
    return lines


async def _reset_group_context_from_menu(
    query: types.CallbackQuery,
    actor: types.User,
    chat: types.Chat,
    settings,
    user,
):
    if chat.type not in {"group", "supergroup"}:
        await query.answer("Доступно только в группе.", show_alert=True)
        return
    if not is_admin_user(settings, user, actor.id):
        await query.answer("Нет прав.", show_alert=True)
        return

    db = DatabaseManager()
    try:
        deleted_count = db.messages.delete_messages_by_chat_id(chat.id)
        reset_history_cache()
        stats.stats.reset()
        await _edit_menu_message(query.message, f"Контекст группы сброшен. Удалено сообщений: {deleted_count}.")
        await query.answer()
        logger.info("Menu group context reset: actor=%s, chat_id=%s", actor.id, chat.id)
    finally:
        db.close()


async def _toggle_group_ban_from_menu(
    query: types.CallbackQuery,
    actor: types.User,
    chat: types.Chat,
    settings,
    user,
):
    if chat.type not in {"group", "supergroup"}:
        await query.answer("Доступно только в группе.", show_alert=True)
        return
    if not is_admin_user(settings, user, actor.id):
        await query.answer("Нет прав.", show_alert=True)
        return

    db = DatabaseManager()
    try:
        current = db.messages.is_group_banned(chat.id)
        db.messages.toggle_group_ban(chat.id, not current)
        updated_settings = settings_manager.get_settings()
        text, markup = render_group_menu(updated_settings, is_banned=not current)
        await _edit_menu_message(query.message, text, reply_markup=markup)
        await query.answer("Статус группы обновлён.")
        logger.info("Menu group ban toggled: actor=%s, chat_id=%s, banned=%s", actor.id, chat.id, not current)
    finally:
        db.close()
