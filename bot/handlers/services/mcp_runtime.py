import asyncio
import os
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List

from bot.handlers.services.mcp_registry import normalize_server_config
from utils.database.database_manager import DatabaseManager
from utils.logger import setup_logger

logger = setup_logger(__name__)

try:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except Exception as import_error:  # pragma: no cover - depends on optional SDK install
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None
    MCP_IMPORT_ERROR = import_error
else:
    MCP_IMPORT_ERROR = None

try:
    from mcp.client.sse import sse_client
except Exception as import_error:  # pragma: no cover - optional transport
    sse_client = None
    MCP_SSE_IMPORT_ERROR = import_error
else:
    MCP_SSE_IMPORT_ERROR = None

try:
    from mcp.client.streamable_http import streamable_http_client
except Exception:
    try:
        from mcp.client.streamable_http import streamablehttp_client as streamable_http_client
    except Exception as import_error:  # pragma: no cover - optional transport
        streamable_http_client = None
        MCP_STREAMABLE_HTTP_IMPORT_ERROR = import_error
    else:
        MCP_STREAMABLE_HTTP_IMPORT_ERROR = None
else:
    MCP_STREAMABLE_HTTP_IMPORT_ERROR = None


class McpRuntimeError(RuntimeError):
    pass


_RUNNING_PROCESSES: Dict[str, subprocess.Popen] = {}
_PROCESS_STOP_TIMEOUT_SECONDS = 5.0


def is_mcp_sdk_available() -> bool:
    return MCP_IMPORT_ERROR is None


def get_mcp_sdk_error() -> str:
    return "" if MCP_IMPORT_ERROR is None else f"{type(MCP_IMPORT_ERROR).__name__}: {MCP_IMPORT_ERROR}"


def start_server_process(server_config: Dict[str, Any]) -> Dict[str, Any]:
    server = normalize_server_config(server_config)
    if server.get("transport") != "stdio":
        raise McpRuntimeError("Start/stop пока поддержан только для stdio MCP-серверов")
    if not server["command"]:
        raise McpRuntimeError("Не задана команда запуска MCP-сервера")
    _guard_against_starting_snapmatch(server)

    existing = _RUNNING_PROCESSES.get(server["name"])
    if existing and existing.poll() is None:
        return {"status": "started", "pid": existing.pid, "details": "process already running"}

    env = os.environ.copy()
    env.update(server.get("env") or {})
    env = _with_windows_node_path(env)
    command = _resolve_command(server["command"], env)
    creationflags = _process_creation_flags()
    try:
        process = subprocess.Popen(
            [command, *(server.get("args") or [])],
            cwd=server.get("cwd") or None,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        time.sleep(0.2)
        if process.poll() is not None:
            details = f"process exited with code {process.returncode}"
            _record_server_status(server, "failed", details)
            raise McpRuntimeError(details)
        _RUNNING_PROCESSES[server["name"]] = process
        details = f"pid={process.pid}"
        _record_server_status(server, "started", details)
        logger.info("MCP server process started: server=%s, pid=%s", server["name"], process.pid)
        return {"status": "started", "pid": process.pid, "details": details}
    except McpRuntimeError:
        raise
    except Exception as e:
        _record_server_status(server, "failed", str(e))
        raise


def _guard_against_starting_snapmatch(server: Dict[str, Any]) -> None:
    command_name = Path(str(server.get("command") or "")).name.lower()
    args = [str(arg).strip() for arg in (server.get("args") or [])]
    arg_names = [Path(arg).name.lower() for arg in args]
    if command_name == "snapmatch.exe" or "main.py" in arg_names:
        raise McpRuntimeError(
            "Команда MCP похожа на запуск самого SnapMatch. "
            "Укажите команду MCP-сервера, например node/python/npx и файл или пакет сервера."
        )


def _process_creation_flags() -> int:
    if os.name != "nt":
        return 0
    return (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )


def _close_process_stdin(process: subprocess.Popen) -> None:
    stdin = getattr(process, "stdin", None)
    if not stdin:
        return
    try:
        stdin.close()
    except Exception:
        pass


def _taskkill_process_tree(pid: int, *, force: bool, timeout_seconds: float) -> None:
    if os.name != "nt":
        return
    command = ["taskkill", "/PID", str(pid), "/T"]
    if force:
        command.append("/F")
    try:
        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=max(1.0, timeout_seconds),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except Exception as exc:
        logger.debug("taskkill failed for pid=%s force=%s: %s", pid, force, exc)


def _stop_process_tree(process: subprocess.Popen, *, timeout_seconds: float) -> None:
    if process.poll() is not None:
        return

    _close_process_stdin(process)

    if os.name == "nt":
        _taskkill_process_tree(process.pid, force=False, timeout_seconds=timeout_seconds)
        try:
            process.wait(timeout=timeout_seconds)
            return
        except subprocess.TimeoutExpired:
            _taskkill_process_tree(process.pid, force=True, timeout_seconds=timeout_seconds)
            try:
                process.wait(timeout=timeout_seconds)
                return
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout_seconds)
                return

    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_seconds)


def _with_windows_node_path(env: Dict[str, str]) -> Dict[str, str]:
    if os.name != "nt":
        return env

    env = dict(env)
    path_value = env.get("PATH") or env.get("Path") or ""
    path_parts = [part for part in path_value.split(os.pathsep) if part]
    lower_parts = {part.lower() for part in path_parts}
    candidates = [
        r"C:\Program Files\nodejs",
        str(Path.home() / "AppData" / "Roaming" / "npm"),
    ]
    for candidate in candidates:
        if Path(candidate).exists() and candidate.lower() not in lower_parts:
            path_parts.append(candidate)
            lower_parts.add(candidate.lower())
    env["PATH"] = os.pathsep.join(path_parts)
    return env


def _resolve_command(command: str, env: Dict[str, str]) -> str:
    command = str(command or "").strip()
    if not command:
        raise McpRuntimeError("Не задана команда запуска MCP-сервера")

    if Path(command).is_absolute():
        if Path(command).exists():
            return command
        raise McpRuntimeError(f"Команда MCP не найдена: {command}")

    resolved = shutil.which(command, path=env.get("PATH"))
    if resolved:
        return resolved

    if os.name == "nt" and not command.lower().endswith((".exe", ".cmd", ".bat")):
        for suffix in (".cmd", ".exe", ".bat"):
            resolved = shutil.which(f"{command}{suffix}", path=env.get("PATH"))
            if resolved:
                return resolved

    raise McpRuntimeError(
        f"Команда MCP не найдена: {command}. "
        "Проверьте установку Node.js/npm или укажите полный путь к исполняемому файлу."
    )


def stop_server_process(server_config: Dict[str, Any]) -> Dict[str, Any]:
    server = normalize_server_config(server_config)
    process = _RUNNING_PROCESSES.pop(server["name"], None)
    if process is None:
        details = "no process tracked in this GUI session"
        _record_server_status(server, "stopped", details)
        return {"status": "stopped", "details": details}
    _stop_process_tree(process, timeout_seconds=_PROCESS_STOP_TIMEOUT_SECONDS)
    details = f"exit_code={process.returncode}"
    _record_server_status(server, "stopped", details)
    logger.info("MCP server process stopped: server=%s, %s", server["name"], details)
    return {"status": "stopped", "details": details}


def stop_all_server_processes(timeout_seconds: float = 5.0) -> None:
    for server_name, process in list(_RUNNING_PROCESSES.items()):
        _RUNNING_PROCESSES.pop(server_name, None)
        _stop_process_tree(process, timeout_seconds=timeout_seconds)
        details = f"exit_code={process.returncode}"
        _record_server_status({"name": server_name, "tools": []}, "stopped", details)
        logger.info("MCP server process stopped on app shutdown: server=%s, %s", server_name, details)


def list_server_tools(server_config: Dict[str, Any], timeout_seconds: float = 20.0) -> List[Dict[str, Any]]:
    if MCP_IMPORT_ERROR is not None:
        raise McpRuntimeError(f"MCP Python SDK недоступен: {MCP_IMPORT_ERROR}")

    return asyncio.run(
        asyncio.wait_for(
            _list_server_tools_async(server_config),
            timeout=timeout_seconds,
        )
    )


def discover_server_capabilities(server_config: Dict[str, Any], timeout_seconds: float = 20.0) -> Dict[str, List[Dict[str, Any]]]:
    if MCP_IMPORT_ERROR is not None:
        raise McpRuntimeError(f"MCP Python SDK недоступен: {MCP_IMPORT_ERROR}")

    return asyncio.run(
        asyncio.wait_for(
            _discover_server_capabilities_async(server_config),
            timeout=timeout_seconds,
        )
    )


def call_server_tool(
    server_config: Dict[str, Any],
    tool_name: str,
    arguments: Dict[str, Any],
    timeout_seconds: float = 30.0,
) -> str:
    if MCP_IMPORT_ERROR is not None:
        raise McpRuntimeError(f"MCP Python SDK недоступен: {MCP_IMPORT_ERROR}")

    return asyncio.run(
        asyncio.wait_for(
            _call_server_tool_async(server_config, tool_name, arguments),
            timeout=timeout_seconds,
        )
    )


async def call_server_tool_async(
    server_config: Dict[str, Any],
    tool_name: str,
    arguments: Dict[str, Any],
    timeout_seconds: float = 30.0,
) -> str:
    if MCP_IMPORT_ERROR is not None:
        raise McpRuntimeError(f"MCP Python SDK недоступен: {MCP_IMPORT_ERROR}")
    return await asyncio.wait_for(
        _call_server_tool_async(server_config, tool_name, arguments),
        timeout=timeout_seconds,
    )


async def _list_server_tools_async(server_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    capabilities = await _discover_server_capabilities_async(server_config)
    return capabilities["tools"]


async def _discover_server_capabilities_async(server_config: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    server = normalize_server_config(server_config)
    logger.info("MCP discovery start: server=%s, transport=%s", server["name"], server.get("transport"))
    db = DatabaseManager()
    try:
        async with _open_client_transport(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_response = await session.list_tools()
                tools = [_serialize_tool(tool) for tool in tools_response.tools]
                resources = await _safe_list_resources(session, server["name"])
                resource_templates = await _safe_list_resource_templates(session, server["name"])
                prompts = await _safe_list_prompts(session, server["name"])
                db.mcp.upsert_server_status(
                    server_name=server["name"],
                    status="discovered",
                    details=(
                        f"tools={len(tools)}, resources={len(resources)}, "
                        f"resource_templates={len(resource_templates)}, prompts={len(prompts)}"
                    ),
                    tools_count=len(tools),
                )
                logger.info(
                    "MCP discovery ok: server=%s, tools=%s, resources=%s, prompts=%s",
                    server["name"],
                    len(tools),
                    len(resources),
                    len(prompts),
                )
                return {
                    "tools": tools,
                    "resources": resources,
                    "resource_templates": resource_templates,
                    "prompts": prompts,
                }
    except Exception as e:
        db.mcp.upsert_server_status(
            server_name=server["name"],
            status="failed",
            details=str(e),
            tools_count=len(server.get("tools") or []),
        )
        raise
    finally:
        db.close()


async def _call_server_tool_async(server_config: Dict[str, Any], tool_name: str, arguments: Dict[str, Any]) -> str:
    server = normalize_server_config(server_config)
    logger.info("MCP tool call start: server=%s, transport=%s, tool=%s", server["name"], server.get("transport"), tool_name)
    async with _open_client_transport(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments or {})
            return _serialize_tool_result(result)


@asynccontextmanager
async def _open_client_transport(server: Dict[str, Any]):
    transport = server.get("transport") or "stdio"

    if transport == "stdio":
        if not server["command"]:
            raise McpRuntimeError("Не задана команда запуска MCP-сервера")
        _guard_against_starting_snapmatch(server)
        env = os.environ.copy()
        env.update(server.get("env") or {})
        env = _with_windows_node_path(env)
        command = _resolve_command(server["command"], env)
        params = StdioServerParameters(
            command=command,
            args=server.get("args") or [],
            env=env,
            cwd=server.get("cwd") or None,
        )
        async with stdio_client(params) as (read, write):
            yield read, write
            return

    if transport == "streamable_http":
        if streamable_http_client is None:
            raise McpRuntimeError(f"MCP streamable_http transport недоступен в установленном SDK: {MCP_STREAMABLE_HTTP_IMPORT_ERROR}")
        if not server.get("url"):
            raise McpRuntimeError("Не задан URL MCP streamable_http сервера")
        async with streamable_http_client(server["url"]) as streams:
            yield streams[0], streams[1]
            return

    if transport == "sse":
        if sse_client is None:
            raise McpRuntimeError(f"MCP SSE transport недоступен в установленном SDK: {MCP_SSE_IMPORT_ERROR}")
        if not server.get("url"):
            raise McpRuntimeError("Не задан URL MCP SSE сервера")
        async with sse_client(server["url"]) as (read, write):
            yield read, write
            return

    raise McpRuntimeError(f"Неизвестный MCP transport: {transport}")


def _serialize_tool(tool: Any) -> Dict[str, Any]:
    input_schema = getattr(tool, "inputSchema", None)
    if hasattr(input_schema, "model_dump"):
        input_schema = input_schema.model_dump()

    return {
        "name": getattr(tool, "name", ""),
        "description": getattr(tool, "description", "") or "",
        "input_schema": input_schema or {},
    }


def _record_server_status(server: Dict[str, Any], status: str, details: str) -> None:
    db = DatabaseManager()
    try:
        db.mcp.upsert_server_status(
            server_name=server["name"],
            status=status,
            details=details,
            tools_count=len(server.get("tools") or []),
        )
    finally:
        db.close()


async def _safe_list_resources(session: Any, server_name: str) -> List[Dict[str, Any]]:
    try:
        resources_response = await session.list_resources()
    except Exception as e:
        logger.info("MCP resources discovery skipped: server=%s, error=%s", server_name, e)
        return []
    return [_serialize_resource(resource) for resource in getattr(resources_response, "resources", []) or []]


async def _safe_list_resource_templates(session: Any, server_name: str) -> List[Dict[str, Any]]:
    try:
        templates_response = await session.list_resource_templates()
    except Exception as e:
        logger.info("MCP resource templates discovery skipped: server=%s, error=%s", server_name, e)
        return []
    return [
        _serialize_resource_template(template)
        for template in getattr(templates_response, "resourceTemplates", []) or []
    ]


async def _safe_list_prompts(session: Any, server_name: str) -> List[Dict[str, Any]]:
    try:
        prompts_response = await session.list_prompts()
    except Exception as e:
        logger.info("MCP prompts discovery skipped: server=%s, error=%s", server_name, e)
        return []
    return [_serialize_prompt(prompt) for prompt in getattr(prompts_response, "prompts", []) or []]


def _serialize_resource(resource: Any) -> Dict[str, Any]:
    return {
        "name": getattr(resource, "name", "") or "",
        "title": getattr(resource, "title", "") or "",
        "description": getattr(resource, "description", "") or "",
        "uri": str(getattr(resource, "uri", "") or ""),
        "mime_type": getattr(resource, "mimeType", "") or "",
    }


def _serialize_resource_template(template: Any) -> Dict[str, Any]:
    return {
        "name": getattr(template, "name", "") or "",
        "title": getattr(template, "title", "") or "",
        "description": getattr(template, "description", "") or "",
        "uri_template": str(getattr(template, "uriTemplate", "") or ""),
        "mime_type": getattr(template, "mimeType", "") or "",
    }


def _serialize_prompt(prompt: Any) -> Dict[str, Any]:
    arguments = []
    for argument in getattr(prompt, "arguments", []) or []:
        arguments.append({
            "name": getattr(argument, "name", "") or "",
            "description": getattr(argument, "description", "") or "",
            "required": bool(getattr(argument, "required", False)),
        })
    return {
        "name": getattr(prompt, "name", "") or "",
        "title": getattr(prompt, "title", "") or "",
        "description": getattr(prompt, "description", "") or "",
        "arguments": arguments,
    }


def _serialize_tool_result(result: Any) -> str:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return str(structured)

    parts = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(str(text))
        else:
            parts.append(str(block))
    return "\n".join(parts).strip()
