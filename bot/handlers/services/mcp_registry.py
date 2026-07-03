from typing import Any, Dict, List


SENSITIVE_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS")


def get_mcp_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    mcp = settings.get("mcp")
    if not isinstance(mcp, dict):
        return {"enabled": False, "servers": [], "limits": _default_limits()}
    servers = mcp.get("servers")
    if not isinstance(servers, list):
        servers = []
    limits = mcp.get("limits")
    if not isinstance(limits, dict):
        limits = {}
    normalized_limits = _default_limits()
    for key in normalized_limits:
        try:
            value = int(limits.get(key, normalized_limits[key]))
        except (TypeError, ValueError):
            value = normalized_limits[key]
        normalized_limits[key] = max(1, value)
    return {"enabled": bool(mcp.get("enabled", False)), "servers": servers, "limits": normalized_limits}


def _default_limits() -> Dict[str, int]:
    return {
        "tool_timeout_seconds": 30,
        "max_tool_calls_per_request": 5,
        "max_tool_result_chars": 12000,
    }


def normalize_server_config(config: Dict[str, Any]) -> Dict[str, Any]:
    name = str(config.get("name") or "").strip()
    transport = str(config.get("transport") or "stdio").strip() or "stdio"
    command = str(config.get("command") or "").strip()
    cwd = str(config.get("cwd") or "").strip()
    url = str(config.get("url") or "").strip()
    args = config.get("args") or []
    env = config.get("env") or {}
    access = config.get("access") or {}

    if isinstance(args, str):
        args = [part.strip() for part in args.splitlines() if part.strip()]
    if not isinstance(env, dict):
        env = {}
    if not isinstance(access, dict):
        access = {}

    return {
        "name": name,
        "enabled": bool(config.get("enabled", False)),
        "transport": transport,
        "command": command,
        "args": list(args),
        "cwd": cwd,
        "url": url,
        "env": {str(key): str(value) for key, value in env.items()},
        "auto_start": bool(config.get("auto_start", False)),
        "access": {
            "admin": bool(access.get("admin", True)),
            "private": bool(access.get("private", False)),
            "group": bool(access.get("group", False)),
            "secretary": bool(access.get("secretary", False)),
        },
        "description": str(config.get("description") or "").strip(),
        "tools": list(config.get("tools") or []),
        "resources": list(config.get("resources") or []),
        "resource_templates": list(config.get("resource_templates") or []),
        "prompts": list(config.get("prompts") or []),
    }


def mask_env(env: Dict[str, str]) -> Dict[str, str]:
    masked = {}
    for key, value in (env or {}).items():
        key_text = str(key)
        if any(marker in key_text.upper() for marker in SENSITIVE_ENV_MARKERS):
            masked[key_text] = "********" if value else ""
        else:
            masked[key_text] = str(value)
    return masked


def preview_servers(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    mcp = get_mcp_settings(settings)
    return [
        {**normalize_server_config(server), "env": mask_env((server or {}).get("env") or {})}
        for server in mcp["servers"]
        if isinstance(server, dict)
    ]
