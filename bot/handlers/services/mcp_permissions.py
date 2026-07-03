import re
from typing import Any, Dict, List

from bot.handlers.services.mcp_registry import get_mcp_settings, normalize_server_config

WEATHER_QUERY_MARKERS = (
    "погода",
    "погод",
    "температур",
    "прогноз",
    "осадки",
    "дожд",
    "снег",
    "ветер",
    "влажност",
    "weather",
    "forecast",
    "temperature",
    "rain",
    "wind",
    "humidity",
)

WEATHER_TOOL_MARKERS = (
    "weather",
    "meteo",
    "forecast",
    "temperature",
    "погода",
    "прогноз",
)

SEARCH_QUERY_MARKERS = (
    "найди",
    "поищи",
    "загугли",
    "в интернете",
    "из интернета",
    "актуальн",
    "свеж",
    "новост",
    "сейчас",
    "latest",
    "current",
    "news",
    "internet",
    "web",
    "search",
    "look up",
    "browse",
)

SEARCH_TOOL_MARKERS = (
    "web",
    "search",
    "searx",
    "internet",
    "поиск",
)

DOCS_QUERY_MARKERS = (
    "документац",
    "api",
    "sdk",
    "context7",
    "docs",
    "documentation",
    "library",
    "framework",
    "библиотек",
    "фреймворк",
)

DOCS_TOOL_MARKERS = (
    "context7",
    "docs",
    "documentation",
)

CALCULATOR_QUERY_MARKERS = (
    "посчитай",
    "калькулятор",
    "сколько будет",
    "calculate",
    "calculator",
    "compute",
)

CALCULATOR_TOOL_MARKERS = (
    "calculator",
    "calc",
    "math",
)

VAGUE_FOLLOWUP_MARKERS = (
    "а сейчас",
    "а сегодня",
    "а завтра",
    "посмотри",
    "проверь",
    "попробуй ещё",
    "попробуй еще",
    "узнай",
    "тогда пожалуйста",
    "а там",
)


def allowed_servers_for_context(settings: Dict[str, Any], request_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    mcp = get_mcp_settings(settings)
    if not mcp["enabled"]:
        return []

    source_mode = request_context.get("source_mode") or "normal"
    chat_type = request_context.get("chat_type") or "private"
    is_admin = bool(request_context.get("is_admin"))

    allowed = []
    for raw_server in mcp["servers"]:
        if not isinstance(raw_server, dict):
            continue
        server = normalize_server_config(raw_server)
        if not server.get("enabled", False):
            continue
        access = server.get("access", {})
        if is_admin and access.get("admin", True):
            allowed.append(server)
        elif source_mode == "secretary" and access.get("secretary", False):
            allowed.append(server)
        elif chat_type in {"group", "supergroup"} and access.get("group", False):
            allowed.append(server)
        elif chat_type == "private" and access.get("private", False):
            allowed.append(server)
    return allowed


def allowed_tools_for_context(settings: Dict[str, Any], request_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    allowed_mcp_names = _parse_allowed_mcp_names(request_context.get("allowed_mcp"))
    tools = []
    for server in allowed_servers_for_context(settings, request_context):
        server_name = str(server.get("name") or "").strip()
        if allowed_mcp_names and server_name not in allowed_mcp_names:
            server_tools = server.get("tools") or []
            has_allowed_tool = any(
                f"{server_name}__{str(tool.get('name') or '').strip()}" in allowed_mcp_names
                or str(tool.get("name") or "").strip() in allowed_mcp_names
                for tool in server_tools
                if isinstance(tool, dict)
            )
            if not has_allowed_tool:
                continue
        for tool in server.get("tools") or []:
            tool_name = str(tool.get("name") or "").strip()
            if not tool_name:
                continue
            if allowed_mcp_names and server_name not in allowed_mcp_names:
                full_name = f"{server_name}__{tool_name}"
                if full_name not in allowed_mcp_names and tool_name not in allowed_mcp_names:
                    continue
            tools.append({
                "server": server_name,
                "name": tool_name,
                "description": tool.get("description", "") or "",
                "input_schema": tool.get("input_schema") or {},
            })
    tools = _prefer_resilient_web_tools(tools)

    # Explicit MCP selection means the caller intentionally asked for these tools.
    # Otherwise keep the prompt small and expose only tools that match the request.
    if allowed_mcp_names:
        return tools

    return _prioritize_tools_for_request(tools, request_context)


def _prefer_resilient_web_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    has_open_websearch = any(
        str(tool.get("server") or "").strip().lower() == "open-websearch"
        for tool in tools
    )
    if not has_open_websearch:
        return tools
    return [
        tool
        for tool in tools
        if not (
            str(tool.get("server") or "").strip().lower() == "web"
            and str(tool.get("name") or "").strip().lower() == "duckduckgo_web_search"
        )
    ]


def _prioritize_tools_for_request(tools: List[Dict[str, Any]], request_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    query = str(request_context.get("query_text") or request_context.get("text_content") or "").lower()
    recent_context = str(request_context.get("recent_context_text") or "").lower()
    explicit_weather = any(marker in query for marker in WEATHER_QUERY_MARKERS)
    inherited_weather = (
        any(marker in query for marker in VAGUE_FOLLOWUP_MARKERS)
        and any(marker in recent_context for marker in WEATHER_QUERY_MARKERS)
    )
    if not query:
        return []

    if not (explicit_weather or inherited_weather):
        selected_tools = []
        if _has_search_intent(query, recent_context):
            selected_tools.extend(_matching_tools(tools, SEARCH_TOOL_MARKERS))
        if _has_docs_intent(query, recent_context):
            selected_tools.extend(_matching_tools(tools, DOCS_TOOL_MARKERS))
        if _has_calculator_intent(query):
            selected_tools.extend(_matching_tools(tools, CALCULATOR_TOOL_MARKERS))
        return _dedupe_tools(selected_tools)

    weather_tools = _matching_tools(tools, WEATHER_TOOL_MARKERS)

    if not weather_tools:
        return []

    # Для погодных запросов не даём модели уходить в поисковик с капчей,
    # если доступен специализированный weather/open-meteo инструмент.
    preferred_names = {"geocoding", "weather_forecast"}
    if "качество воздуха" in query or "air quality" in query:
        preferred_names.add("air_quality")
    if any(marker in query for marker in ("море", "волны", "marine", "wave")):
        preferred_names.add("marine_weather")

    preferred_weather_tools = [
        tool
        for tool in weather_tools
        if str(tool.get("name") or "").strip().lower() in preferred_names
    ]
    return preferred_weather_tools or weather_tools


def _matching_tools(tools: List[Dict[str, Any]], markers: tuple[str, ...]) -> List[Dict[str, Any]]:
    matched = []
    for tool in tools:
        haystack = " ".join(
            str(part or "").lower()
            for part in (
                tool.get("server"),
                tool.get("name"),
                tool.get("description"),
            )
        )
        if any(marker in haystack for marker in markers):
            matched.append(tool)
    return matched


def _dedupe_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique = []
    seen = set()
    for tool in tools:
        key = (str(tool.get("server") or ""), str(tool.get("name") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(tool)
    return unique


def _has_search_intent(query: str, recent_context: str) -> bool:
    if any(marker in query for marker in SEARCH_QUERY_MARKERS):
        return True
    return (
        any(marker in query for marker in VAGUE_FOLLOWUP_MARKERS)
        and any(marker in recent_context for marker in SEARCH_QUERY_MARKERS)
    )


def _has_docs_intent(query: str, recent_context: str) -> bool:
    if any(marker in query for marker in DOCS_QUERY_MARKERS):
        return True
    return (
        any(marker in query for marker in VAGUE_FOLLOWUP_MARKERS)
        and any(marker in recent_context for marker in DOCS_QUERY_MARKERS)
    )


def _has_calculator_intent(query: str) -> bool:
    if any(marker in query for marker in CALCULATOR_QUERY_MARKERS):
        return True
    return bool(re.search(r"\d+(?:[.,]\d+)?\s*[+\-*/%]\s*\d+", query))


def _parse_allowed_mcp_names(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        raw_items = value.replace(",", "\n").replace(";", "\n").splitlines()
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = [value]
    return {str(item).strip() for item in raw_items if str(item).strip()}


def to_openai_tool_schema(tool: Dict[str, Any]) -> Dict[str, Any]:
    server_name = str(tool.get("server") or "").strip()
    tool_name = str(tool.get("name") or "").strip()
    function_name = f"{server_name}__{tool_name}" if server_name else tool_name
    function_name = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in function_name)
    return {
        "type": "function",
        "function": {
            "name": function_name[:64],
            "description": str(tool.get("description") or "")[:1024],
            "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
        },
    }


def allowed_openai_tools_for_context(settings: Dict[str, Any], request_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [to_openai_tool_schema(tool) for tool in allowed_tools_for_context(settings, request_context)]


def to_anthropic_tool_schema(tool: Dict[str, Any]) -> Dict[str, Any]:
    openai_tool = to_openai_tool_schema(tool)
    function = openai_tool["function"]
    return {
        "name": function["name"],
        "description": function["description"],
        "input_schema": function["parameters"],
    }


def allowed_anthropic_tools_for_context(settings: Dict[str, Any], request_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [to_anthropic_tool_schema(tool) for tool in allowed_tools_for_context(settings, request_context)]
