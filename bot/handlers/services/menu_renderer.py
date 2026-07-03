from math import ceil
from html import escape
from typing import Any, Dict

from aiogram.enums import ButtonStyle, ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.services.access_control import ROLE_ADMIN, ROLE_SECRETARY_OWNER


EMOJI_BY_KIND = {
    "primary": "🔹",
    "secondary": "▫️",
    "success": "🟢",
    "warning": "🟡",
    "danger": "🔴",
}

STYLE_BY_KIND = {
    "primary": ButtonStyle.PRIMARY.value,
    "success": ButtonStyle.SUCCESS.value,
    "danger": ButtonStyle.DANGER.value,
}
MENU_PARSE_MODE = ParseMode.HTML.value


def _colored_enabled(settings: Dict[str, Any] | None = None) -> bool:
    if not isinstance(settings, dict):
        return True
    telegram_menu = settings.get("telegram_menu", {})
    if not isinstance(telegram_menu, dict):
        return True
    return bool(telegram_menu.get("colored_buttons_enabled", True))


def _button(
    builder: InlineKeyboardBuilder,
    text: str,
    callback_data: str,
    *,
    settings: Dict[str, Any] | None = None,
    kind: str = "secondary",
    emoji: str = "",
    emoji_key: str = "",
):
    enabled = _colored_enabled(settings)
    prefix = emoji or EMOJI_BY_KIND.get(kind, "")
    label = f"{prefix} {text}" if enabled and prefix else text
    style = STYLE_BY_KIND.get(kind) if enabled else None
    custom_emoji_id = None
    if enabled and emoji_key and isinstance(settings, dict):
        telegram_menu = settings.get("telegram_menu", {})
        custom_ids = telegram_menu.get("custom_emoji_ids", {}) if isinstance(telegram_menu, dict) else {}
        if isinstance(custom_ids, dict):
            custom_emoji_id = custom_ids.get(emoji_key)
    kwargs = {}
    if style:
        kwargs["style"] = style
    if custom_emoji_id:
        kwargs["icon_custom_emoji_id"] = custom_emoji_id
    builder.button(text=label, callback_data=callback_data, **kwargs)


def _state(value: bool) -> str:
    return "🟢 вкл" if value else "⚪ выкл"


def _nav(builder: InlineKeyboardBuilder, back_callback: str = "menu:root:open", *, settings: Dict[str, Any] | None = None):
    _button(builder, "Назад", back_callback, settings=settings, emoji="◀️", emoji_key="back")
    if back_callback != "menu:root:open":
        _button(builder, "Главное меню", "menu:root:open", settings=settings, kind="primary", emoji="🏠", emoji_key="home")


def _page(title: str, lines: list[str] | None = None, hint: str = "") -> str:
    formatted_lines = []
    for line in (lines or []):
        if line is None:
            continue
        sublines = str(line).splitlines() or [""]
        formatted_lines.extend(_format_line_html(subline) for subline in sublines)
    body = "\n".join(formatted_lines)
    parts = [f"<b>• {escape(str(title))}</b>"]
    if body:
        parts.append(body)
    if hint:
        parts.append(f"\n<i>{escape(str(hint))}</i>")
    return "\n".join(parts)


def _format_line_html(line: Any) -> str:
    text = str(line)
    if not text:
        return ""
    stripped = text.lstrip()
    indent = text[:len(text) - len(stripped)]
    if indent:
        return f"{escape(indent)}{escape(stripped)}"
    if ":" in text and not text[:1].isdigit():
        label, value = text.split(":", 1)
        if 0 < len(label) <= 32 and not label.startswith(("-", "•")):
            return f"<b>{escape(label)}:</b>{escape(value)}"
    return escape(text)


def _short(text: Any, limit: int = 34) -> str:
    value = str(text or "").strip()
    if not value:
        return "-"
    return value if len(value) <= limit else f"{value[:limit - 1]}…"


def render_main_menu(role: str, chat_type: str, settings: Dict[str, Any]):
    builder = InlineKeyboardBuilder()
    is_group = chat_type in {"group", "supergroup"}

    _button(builder, "Статус", "menu:status:view", settings=settings, kind="primary", emoji="📊", emoji_key="status")
    _button(builder, "История", "menu:history:open", settings=settings, emoji="🧾", emoji_key="history")

    if role == ROLE_ADMIN:
        _button(builder, "Модели", "menu:models:open", settings=settings, emoji="🧠", emoji_key="models")
        _button(builder, "Пользователи", "menu:users:open", settings=settings, emoji="👥", emoji_key="users")
        if is_group:
            _button(builder, "Группа", "menu:group:open", settings=settings, emoji="💬")
        _button(builder, "MCP", "menu:mcp:open", settings=settings, emoji="🧩", emoji_key="mcp")
        _button(builder, "Секретари", "menu:admin_secretaries:open", settings=settings, emoji="🪪", emoji_key="secretaries")
        _button(builder, "Логи", "menu:logs:open", settings=settings, emoji="📄", emoji_key="logs")
        _button(builder, "Действия", "menu:actions:open", settings=settings, emoji="🕘", emoji_key="actions")
        _button(builder, "Настройки", "menu:settings:open", settings=settings, emoji="⚙️", emoji_key="settings")
    else:
        _button(builder, "Мои настройки", "menu:user_settings:open", settings=settings, emoji="⚙️")
        if role == ROLE_SECRETARY_OWNER:
            _button(builder, "Секретарь", "menu:secretary:open", settings=settings, emoji="🪪")

    builder.adjust(2)

    title = "Меню администратора" if role == ROLE_ADMIN else "Меню пользователя"
    if is_group:
        title = f"{title} группы"
    return _page(title, ["👋 Добро пожаловать в меню SnapMatch."], "Выберите раздел ниже."), builder.as_markup()


def render_history_menu():
    builder = InlineKeyboardBuilder()
    _button(builder, "Очистить историю", "menu:history:clear_confirm", kind="danger", emoji="🧹")
    _nav(builder)
    builder.adjust(1)
    return _page("История", ["Очистка затронет текущий диалог."], "Перед удалением будет подтверждение."), builder.as_markup()


def render_user_settings_menu(user, preferences: Dict[str, Any], settings: Dict[str, Any]):
    builder = InlineKeyboardBuilder()
    banned = bool((user or {}).get("is_banned", 0))

    def _value(key: str, global_key: str):
        if key in preferences:
            return "вкл" if preferences.get(key) else "выкл"
        return f"global {'вкл' if settings.get(global_key, False) else 'выкл'}"

    stream = _value("stream_mode", "stream_mode")
    markdown = _value("format_markdown", "format_markdown")
    html = _value("format_html", "format_html")

    _button(builder, f"Стриминг: {stream}", "menu:user_settings:toggle:stream_mode", settings=settings, emoji="⚡")
    _button(builder, f"Markdown: {markdown}", "menu:user_settings:toggle:format_markdown", settings=settings, emoji="📝")
    _button(builder, f"HTML: {html}", "menu:user_settings:toggle:format_html", settings=settings, emoji="🌐")
    _nav(builder, settings=settings)
    builder.adjust(1)

    text = _page("Мои настройки", [
        f"Бот для вас: {'⛔ выключен' if banned else '🟢 включен'}",
        f"Стриминг: {stream}",
        f"Markdown: {markdown}",
        f"HTML: {html}",
    ])
    return text, builder.as_markup()


def render_status_menu(body: str):
    builder = InlineKeyboardBuilder()
    _nav(builder)
    builder.adjust(1)
    body = str(body or "")
    if body.startswith("Статус\n"):
        body = body.split("\n", 1)[1]
    return _page("Статус", [body]), builder.as_markup()


def render_models_menu(settings: Dict[str, Any], usage_stats: Dict[str, Dict[str, Any]] | None = None, page: int = 0):
    usage_stats = usage_stats or {}
    models = [model for model in settings.get("models", []) if isinstance(model, dict)]
    strategy = settings.get("load_balancing_strategy", "round_robin")
    builder = InlineKeyboardBuilder()
    per_page = 5
    total_pages = max(1, ceil(len(models) / per_page))
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    visible_models = models[start:start + per_page]
    lines = [f"Стратегия: {strategy}", f"Страница: {page + 1}/{total_pages}", ""]

    if models:
        for offset, model in enumerate(visible_models):
            index = start + offset
            model_id = str(model.get("id") or f"model_{index}")
            active = bool(model.get("active", True))
            runtime = usage_stats.get(model_id, {})
            status = "🟢 включена" if active else "⚪ выключена"
            loaded = "загружена" if runtime.get("is_active") else "не загружена"
            active_requests = runtime.get("active_requests", 0)
            lines.extend([
                f"{index + 1}. {_short(model_id, 48)}",
                f"   {status}, {loaded}, запросов: {active_requests}",
                f"   API: {model.get('api_type', 'openai')} | weight: {model.get('weight', 1)}",
                f"   reasoning: {model.get('reasoning_mode', 'default')}",
                "",
            ])
            _button(
                builder,
                _short(model_id, 28),
                f"menu:models:toggle:{index}",
                settings=settings,
                kind="success" if active else "secondary",
                emoji="🟢" if active else "⚪",
            )
    else:
        lines.append("Модели не настроены.")

    if total_pages > 1:
        if page > 0:
            _button(builder, "Предыдущая", f"menu:models:page:{page - 1}", settings=settings, emoji="◀️", emoji_key="back")
        if page < total_pages - 1:
            _button(builder, "Следующая", f"menu:models:page:{page + 1}", settings=settings, emoji="▶️", emoji_key="next")
    _button(builder, "Routing summary", "menu:models:routing", settings=settings, emoji="🧭")
    _button(builder, "Перезагрузить", "menu:models:reload", settings=settings, kind="primary", emoji="🔄")
    _nav(builder, settings=settings)
    builder.adjust(1)
    return _page("Модели", lines), builder.as_markup()


def _user_display(user: Dict[str, Any]) -> str:
    username = user.get("username")
    if username:
        return f"@{username}"
    full_name = " ".join(part for part in [user.get("first_name") or "", user.get("last_name") or ""] if part).strip()
    return full_name or str(user.get("telegram_id") or "-")


def render_users_menu(users: list[Dict[str, Any]] | None = None, *, page: int = 0, sort: str = "activity", query: str = ""):
    users = users or []
    per_page = 5
    total_pages = max(1, ceil(len(users) / per_page))
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    visible_users = users[start:start + per_page]
    builder = InlineKeyboardBuilder()
    lines = [
        f"Всего: {len(users)}",
        f"Страница: {page + 1}/{total_pages}",
        f"Сортировка: {_users_sort_label(sort)}",
    ]
    if query:
        lines.append(f"Фильтр: {query}")
    lines.append("")

    if visible_users:
        for index, item in enumerate(visible_users, start=start + 1):
            telegram_id = int(item.get("telegram_id") or 0)
            priority = int(item.get("priority") or 0)
            banned = "⛔" if item.get("is_banned") else "🟢"
            name = _short(_user_display(item), 28)
            lines.append(f"{index}. {banned} {name} | id {telegram_id} | p{priority}")
            _button(builder, f"{name} · p{priority}", f"menu:users:view:{telegram_id}", emoji="👤")
    else:
        lines.append("Пользователи не найдены.")

    if total_pages > 1:
        if page > 0:
            _button(builder, "Предыдущая", f"menu:users:page:{page - 1}:{sort}", emoji="◀️", emoji_key="back")
        if page < total_pages - 1:
            _button(builder, "Следующая", f"menu:users:page:{page + 1}:{sort}", emoji="▶️", emoji_key="next")
    _button(builder, "Найти по Telegram ID", "menu:users:find", emoji="🔎", emoji_key="search")
    _button(builder, "По активности", "menu:users:sort:activity", kind="primary" if sort == "activity" else "secondary", emoji="🕘")
    _button(builder, "По priority", "menu:users:sort:priority", kind="primary" if sort == "priority" else "secondary", emoji="⭐")
    _button(builder, "По имени", "menu:users:sort:name", kind="primary" if sort == "name" else "secondary", emoji="🔤")
    _nav(builder)
    builder.adjust(1, 2, 1, 3, 1)
    return _page("Пользователи", lines), builder.as_markup()


def _users_sort_label(sort: str) -> str:
    labels = {
        "activity": "последняя активность",
        "priority": "priority",
        "name": "имя",
    }
    return labels.get(sort, labels["activity"])


def render_admin_text_view(title: str, body: str, back_callback: str = "menu:root:open"):
    builder = InlineKeyboardBuilder()
    _nav(builder, back_callback)
    builder.adjust(1)
    return _page(title, [body]), builder.as_markup()


def render_paged_text_view(
    title: str,
    lines: list[str],
    *,
    page: int = 0,
    per_page: int = 8,
    page_callback: str,
    back_callback: str = "menu:root:open",
    hint: str = "",
):
    builder = InlineKeyboardBuilder()
    total_pages = max(1, ceil(len(lines) / per_page))
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    visible = lines[start:start + per_page]
    body = [f"Страница: {page + 1}/{total_pages}", ""]
    body.extend(visible or ["Записей нет."])
    if total_pages > 1:
        if page > 0:
            _button(builder, "Предыдущая", f"{page_callback}:{page - 1}", emoji="◀️", emoji_key="back")
        if page < total_pages - 1:
            _button(builder, "Следующая", f"{page_callback}:{page + 1}", emoji="▶️", emoji_key="next")
    _nav(builder, back_callback)
    builder.adjust(2, 1)
    return _page(title, body, hint), builder.as_markup()


def render_mcp_server_details(server: Dict[str, Any], index: int, settings: Dict[str, Any], status: Dict[str, Any] | None = None):
    status = status or {}
    access = server.get("access") or {}
    access_enabled = ", ".join(key for key, value in access.items() if value) or "нет"
    builder = InlineKeyboardBuilder()
    _button(builder, "Tools", f"menu:mcp:tools:{index}", settings=settings, emoji="🧰")
    _button(builder, "Вкл/выкл", f"menu:mcp:toggle:{index}", settings=settings, emoji="🔁")
    _button(builder, "Доступ", f"menu:mcp:access:{index}", settings=settings, emoji="🔐")
    _button(builder, "Discovery", f"menu:mcp:discover:{index}", settings=settings, kind="primary", emoji="🔎")
    _button(builder, "Статус", f"menu:mcp:status:{index}", settings=settings, emoji="📊")
    _nav(builder, "menu:mcp:open", settings=settings)
    builder.adjust(2, 3, 1)
    lines = [
        f"Сервер: {server.get('name')}",
        f"Состояние: {'🟢 включён' if server.get('enabled') else '⚪ выключен'}",
        f"Транспорт: {server.get('transport') or 'stdio'}",
        f"Tools: {len(server.get('tools') or [])}",
        f"Доступ: {access_enabled}",
        f"Последний статус: {status.get('status') or 'нет данных'}",
        "",
        "Что делают кнопки:",
        "Tools: показывает найденные инструменты сервера.",
        "Вкл/выкл: включает сервер в обработку MCP-запросов.",
        "Доступ: переключает доступ для текущего типа чата.",
        "Discovery: заново читает tools/resources/prompts.",
        "Статус: показывает последний audit/status.",
        "",
        "Команда, env, cwd и URL редактируются в desktop GUI.",
    ]
    return _page("MCP сервер", lines), builder.as_markup()


def render_mcp_tools_view(server: Dict[str, Any], index: int, settings: Dict[str, Any], *, page: int = 0):
    tools = [tool for tool in (server.get("tools") or []) if isinstance(tool, dict)]
    total_pages = max(1, ceil(len(tools) / 5))
    page = max(0, min(page, total_pages - 1))
    start = page * 5
    visible = tools[start:start + 5]
    builder = InlineKeyboardBuilder()
    if total_pages > 1:
        if page > 0:
            _button(builder, "Предыдущая", f"menu:mcp:tools_page:{index}:{page - 1}", settings=settings, emoji="◀️", emoji_key="back")
        if page < total_pages - 1:
            _button(builder, "Следующая", f"menu:mcp:tools_page:{index}:{page + 1}", settings=settings, emoji="▶️", emoji_key="next")
    _nav(builder, f"menu:mcp:server:{index}", settings=settings)
    builder.adjust(2, 1)
    lines = [f"Сервер: {server.get('name')}", f"Страница: {page + 1}/{total_pages}", ""]
    if visible:
        for offset, tool in enumerate(visible, start=start + 1):
            name = _short(tool.get("name"), 42)
            description = _short(tool.get("description") or "Описание не задано.", 180)
            lines.extend([f"{offset}. {name}", f"   {description}", ""])
    else:
        lines.append("Tools не обнаружены. Нажмите Discovery или проверьте сервер в desktop GUI.")
    return _page("MCP tools", lines, "Это справочник. Сами tool calls происходят во время ответа бота."), builder.as_markup()


def render_mcp_status_view(server: Dict[str, Any], index: int, settings: Dict[str, Any], status: Dict[str, Any] | None = None):
    status = status or {}
    builder = InlineKeyboardBuilder()
    _button(builder, "Discovery", f"menu:mcp:discover:{index}", settings=settings, kind="primary", emoji="🔎")
    _nav(builder, f"menu:mcp:server:{index}", settings=settings)
    builder.adjust(1)
    lines = [
        f"Сервер: {server.get('name')}",
        f"Статус: {status.get('status') or 'нет данных'}",
        f"Tools: {status.get('tools_count', len(server.get('tools') or []))}",
        f"Обновлено: {status.get('updated_at') or '-'}",
        f"Детали: {status.get('details') or '-'}",
        "",
        "Если статус старый или пустой, нажмите Discovery.",
    ]
    return _page("MCP статус", lines), builder.as_markup()


def render_admin_secretaries_menu(profiles):
    builder = InlineKeyboardBuilder()
    lines = []
    if profiles:
        for profile in profiles[:12]:
            owner_id = int(profile.get("owner_telegram_id"))
            enabled = "🟢 on" if profile.get("enabled") else "⚪ off"
            mode = profile.get("response_mode") or "draft"
            name = profile.get("owner_display_name") or str(owner_id)
            lines.append(f"- {name} ({owner_id}): {enabled}, {mode}")
            _button(
                builder,
                f"{name}: {enabled}",
                f"menu:admin_secretaries:view:{owner_id}",
                kind="success" if profile.get("enabled") else "secondary",
                emoji="🪪",
            )
    else:
        lines.append("Профили не настроены.")
    _nav(builder)
    builder.adjust(1)
    return _page("Секретари", lines), builder.as_markup()


def render_admin_secretary_card(profile, events_count: int = 0):
    owner_id = int(profile.get("owner_telegram_id"))
    enabled = "on" if profile.get("enabled") else "off"
    mode = profile.get("response_mode") or "draft"
    name = profile.get("owner_display_name") or "-"
    prompt = "задан" if (profile.get("system_prompt") or "").strip() else "пустой"

    builder = InlineKeyboardBuilder()
    _button(
        builder,
        "Выключить" if profile.get("enabled") else "Включить",
        f"menu:admin_secretaries:toggle:{owner_id}",
        kind="warning" if profile.get("enabled") else "success",
        emoji="🟢" if not profile.get("enabled") else "⏸️",
    )
    _button(builder, "События", f"menu:admin_secretaries:events:{owner_id}", emoji="🕘")
    _button(builder, "Сбросить context", f"menu:admin_secretaries:reset_confirm:{owner_id}", kind="danger", emoji="🧹")
    _nav(builder, "menu:admin_secretaries:open")
    builder.adjust(1)

    text = _page("Secretary owner", [
        f"Owner: {owner_id}",
        f"Name: {name}",
        f"Enabled: {enabled}",
        f"Mode: {mode}",
        f"Prompt: {prompt}",
        f"Save history: {'yes' if profile.get('save_history', 1) else 'no'}",
        f"Ignore bots: {'yes' if profile.get('ignore_bot_messages', 1) else 'no'}",
        f"Events: {events_count}",
    ])
    return text, builder.as_markup()


def render_user_card(user: Dict[str, Any]):
    telegram_id = int(user.get("telegram_id"))
    username = user.get("username") or "-"
    full_name = " ".join(
        part for part in [user.get("first_name") or "", user.get("last_name") or ""] if part
    ).strip() or "-"
    priority = int(user.get("priority") or 0)
    banned = bool(user.get("is_banned", 0))

    builder = InlineKeyboardBuilder()
    _button(builder, "Разбанить" if banned else "Забанить", f"menu:users:ban:{telegram_id}", kind="danger", emoji="⛔")
    _button(builder, "Priority +1", f"menu:users:prio_up:{telegram_id}", emoji="⬆️")
    _button(builder, "Priority -1", f"menu:users:prio_down:{telegram_id}", emoji="⬇️")
    _nav(builder, "menu:users:open")
    builder.adjust(1)

    text = _page("Пользователь", [
        f"Telegram ID: {telegram_id}",
        f"Username: {username}",
        f"Имя: {full_name}",
        f"Priority: {priority}",
        f"Бан: {'да' if banned else 'нет'}",
    ])
    return text, builder.as_markup()


def render_user_find_wait():
    builder = InlineKeyboardBuilder()
    _button(builder, "Отмена", "menu:users:find_cancel", kind="danger", emoji="✖️")
    builder.adjust(1)
    return _page("Поиск пользователя", ["Отправьте Telegram ID, username или часть имени следующим сообщением."]), builder.as_markup()


def render_mcp_menu(settings: Dict[str, Any], statuses: Dict[str, Dict[str, Any]] | None = None):
    statuses = statuses or {}
    mcp = settings.get("mcp", {}) if isinstance(settings.get("mcp"), dict) else {}
    servers = [server for server in mcp.get("servers", []) if isinstance(server, dict)]
    builder = InlineKeyboardBuilder()

    for index, server in enumerate(servers[:10]):
        name = str(server.get("name") or f"server_{index}")
        is_enabled = bool(server.get("enabled"))
        enabled = "🟢 on" if is_enabled else "⚪ off"
        status = statuses.get(name, {}).get("status", "нет статуса")
        _button(builder, f"{name}: {enabled}", f"menu:mcp:server:{index}", settings=settings, kind="success" if is_enabled else "secondary", emoji="🧩")
        _button(builder, "Tools", f"menu:mcp:tools:{index}", settings=settings, emoji="🧰")
        _button(builder, "Вкл/выкл", f"menu:mcp:toggle:{index}", settings=settings, emoji="🔁")
        _button(builder, "Доступ", f"menu:mcp:access:{index}", settings=settings, emoji="🔐")
        _button(builder, "Discovery", f"menu:mcp:discover:{index}", settings=settings, kind="primary", emoji="🔎")
        _button(builder, "Статус", f"menu:mcp:status:{index}", settings=settings, emoji="📊")

    _nav(builder, settings=settings)
    builder.adjust(1, 2, 3)

    enabled = "включён" if mcp.get("enabled", False) else "выключен"
    if servers:
        lines = []
        for server in servers[:10]:
            name = str(server.get("name") or "-")
            status = statuses.get(name, {}).get("status", "нет статуса")
            lines.extend([
                f"Сервер: {name}",
                f"   {'🟢 включён' if server.get('enabled') else '⚪ выключен'} | tools: {len(server.get('tools') or [])} | status: {status}",
                "",
            ])
        body = "\n".join(lines)
    else:
        body = "Серверы не добавлены."
    return _page("MCP", [
        f"Глобально: {enabled}",
        body,
        "Как читать кнопки:",
        "Карточка сервера открывает детали.",
        "Tools показывает список инструментов.",
        "Вкл/выкл включает сервер в MCP-запросы.",
        "Доступ меняет разрешение для текущего типа чата.",
        "Discovery обновляет список возможностей сервера.",
        "Статус показывает последний audit/status.",
    ], "Env и команды редактируются в desktop GUI."), builder.as_markup()


def render_group_menu(settings: Dict[str, Any], *, is_banned: bool = False):
    builder = InlineKeyboardBuilder()
    mention_only = "вкл" if settings.get("respond_only_on_mention", False) else "выкл"
    reject_empty = "вкл" if settings.get("reject_empty_mentions", True) else "выкл"
    parallel = "вкл" if settings.get("group_parallel_mode", False) else "выкл"
    ban_status = "разбанить" if is_banned else "забанить"
    _button(builder, f"Только @: {mention_only}", "menu:group:toggle:respond_only_on_mention", settings=settings, emoji="📣")
    _button(builder, f"Пустые @: reject {reject_empty}", "menu:group:toggle:reject_empty_mentions", settings=settings, emoji="🚫")
    _button(builder, f"Parallel: {parallel}", "menu:group:toggle:group_parallel_mode", settings=settings, emoji="⚡")
    _button(builder, f"Группу: {ban_status}", "menu:group:ban_confirm", settings=settings, kind="danger", emoji="⛔")
    _button(builder, "Сбросить контекст", "menu:group:reset_confirm", settings=settings, kind="danger", emoji="🧹")
    _nav(builder, settings=settings)
    builder.adjust(1)
    text = _page("Группа", [
        f"Только по упоминанию: {mention_only}",
        f"Отклонять пустые упоминания: {reject_empty}",
        f"Параллельная обработка групп: {parallel}",
        f"Бан группы: {'да' if is_banned else 'нет'}",
    ])
    return text, builder.as_markup()


def render_settings_menu(settings: Dict[str, Any]):
    builder = InlineKeyboardBuilder()
    accept_bots = "вкл" if settings.get("accept_bot_messages", True) else "выкл"
    mention_only = "вкл" if settings.get("respond_only_on_mention", False) else "выкл"
    reject_empty = "вкл" if settings.get("reject_empty_mentions", True) else "выкл"
    stream_mode = "вкл" if settings.get("stream_mode", False) else "выкл"
    markdown = "вкл" if settings.get("format_markdown", True) else "выкл"
    html = "вкл" if settings.get("format_html", True) else "выкл"
    menu_enabled = "вкл" if settings.get("telegram_menu", {}).get("enabled", True) else "выкл"
    colored = "вкл" if settings.get("telegram_menu", {}).get("colored_buttons_enabled", True) else "выкл"
    _button(builder, f"Боты: {accept_bots}", "menu:settings:toggle:accept_bot_messages", settings=settings, emoji="🤖")
    _button(builder, f"Только @: {mention_only}", "menu:settings:toggle:respond_only_on_mention", settings=settings, emoji="📣")
    _button(builder, f"Пустые @: reject {reject_empty}", "menu:settings:toggle:reject_empty_mentions", settings=settings, emoji="🚫")
    _button(builder, f"Стриминг: {stream_mode}", "menu:settings:toggle:stream_mode", settings=settings, emoji="⚡")
    _button(builder, f"Markdown: {markdown}", "menu:settings:toggle:format_markdown", settings=settings, emoji="📝")
    _button(builder, f"HTML: {html}", "menu:settings:toggle:format_html", settings=settings, emoji="🌐")
    _button(builder, f"Меню: {menu_enabled}", "menu:settings:toggle:telegram_menu_enabled", settings=settings, emoji="🧭")
    _button(builder, f"Emoji-кнопки: {colored}", "menu:settings:toggle:colored_buttons_enabled", settings=settings, kind="primary", emoji="🎛")
    _nav(builder, settings=settings)
    builder.adjust(1)
    return _page("Настройки", ["Глобальные переключатели Telegram-бота."]), builder.as_markup()


def render_secretary_menu(profile: Dict[str, Any]):
    builder = InlineKeyboardBuilder()
    enabled = "вкл" if profile.get("enabled") else "выкл"
    save_history = "вкл" if profile.get("save_history", 1) else "выкл"
    ignore_bots = "вкл" if profile.get("ignore_bot_messages", 1) else "выкл"
    close_after_reply = "вкл" if profile.get("close_after_reply", 0) else "выкл"
    owner_behavior = profile.get("owner_message_behavior") or "takeover"
    mode = profile.get("response_mode") or "draft"
    prompt = (profile.get("system_prompt") or "").strip()
    prompt_status = "задан" if prompt else "пустой"

    _button(builder, f"Секретарь: {enabled}", "menu:secretary:toggle:enabled", kind="success" if profile.get("enabled") else "secondary", emoji="🪪")
    _button(builder, f"Режим: {mode}", "menu:secretary:mode:cycle", emoji="🔁")
    _button(builder, f"История: {save_history}", "menu:secretary:toggle:save_history", emoji="🧾")
    _button(builder, f"Игнор ботов: {ignore_bots}", "menu:secretary:toggle:ignore_bots", emoji="🤖")
    _button(builder, f"Закрывать после ответа: {close_after_reply}", "menu:secretary:toggle:close_after_reply", emoji="🔚")
    _button(builder, f"Владелец: {owner_behavior}", "menu:secretary:owner_behavior:cycle", emoji="👤")
    _button(builder, "Новая сессия", "menu:secretary:session:new", emoji="🆕")
    _button(builder, "Закрыть сессию", "menu:secretary:session:close", emoji="🔒")
    _button(builder, "Очистить историю", "menu:secretary:history:clear_confirm", kind="danger", emoji="🧹")
    _button(builder, "Последние события", "menu:secretary:events", emoji="🕘")
    _button(builder, "Изменить prompt", "menu:secretary:prompt:edit", emoji="✏️")
    _nav(builder)
    builder.adjust(1, 1, 2, 2, 1, 2, 1)

    text = _page("Секретарь", [
        f"Статус: {enabled}",
        f"Режим: {mode}",
        f"История: {save_history}",
        f"Игнорировать ботов: {ignore_bots}",
        f"Закрывать после ответа: {close_after_reply}",
        f"Поведение владельца: {owner_behavior}",
        "Сессии: можно закрыть текущую активную или начать новую.",
        f"Prompt: {prompt_status}",
    ])
    return text, builder.as_markup()


def render_secretary_prompt_wait():
    builder = InlineKeyboardBuilder()
    _button(builder, "Отмена", "menu:secretary:prompt:cancel", kind="danger", emoji="✖️")
    builder.adjust(1)
    return _page("Новый prompt секретаря", [
        "Отправьте следующим сообщением новый system prompt.",
        "Это сообщение не попадет в LLM-историю.",
    ]), builder.as_markup()


def render_confirm(text: str, confirm_callback: str):
    builder = InlineKeyboardBuilder()
    _button(builder, "Подтвердить", confirm_callback, kind="danger", emoji="✅")
    _button(builder, "Отмена", "menu:root:open", emoji="✖️")
    builder.adjust(2)
    return _page("Подтверждение", [text]), builder.as_markup()
