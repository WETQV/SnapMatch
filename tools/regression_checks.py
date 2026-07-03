import os
import sys
import tempfile
import asyncio
import importlib.util
import types
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _install_cryptography_stub():
    try:
        import cryptography  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    cryptography = types.ModuleType("cryptography")
    fernet_mod = types.ModuleType("cryptography.fernet")
    hazmat_mod = types.ModuleType("cryptography.hazmat")
    primitives_mod = types.ModuleType("cryptography.hazmat.primitives")
    hashes_mod = types.ModuleType("cryptography.hazmat.primitives.hashes")
    kdf_mod = types.ModuleType("cryptography.hazmat.primitives.kdf")
    pbkdf2_mod = types.ModuleType("cryptography.hazmat.primitives.kdf.pbkdf2")

    class Fernet:
        @staticmethod
        def generate_key():
            return b"regression-test-key"

        def __init__(self, key):
            self.key = key

        def encrypt(self, value):
            return value

        def decrypt(self, value):
            return value

    class PBKDF2HMAC:
        def __init__(self, *args, **kwargs):
            pass

    fernet_mod.Fernet = Fernet
    pbkdf2_mod.PBKDF2HMAC = PBKDF2HMAC
    sys.modules.update({
        "cryptography": cryptography,
        "cryptography.fernet": fernet_mod,
        "cryptography.hazmat": hazmat_mod,
        "cryptography.hazmat.primitives": primitives_mod,
        "cryptography.hazmat.primitives.hashes": hashes_mod,
        "cryptography.hazmat.primitives.kdf": kdf_mod,
        "cryptography.hazmat.primitives.kdf.pbkdf2": pbkdf2_mod,
    })


def _load_secretary_handlers():
    if "aiohttp" not in sys.modules:
        aiohttp_mod = types.ModuleType("aiohttp")
        aiohttp_mod.ClientSession = object
        aiohttp_mod.ClientTimeout = lambda **kwargs: kwargs
        aiohttp_mod.ClientSSLError = RuntimeError
        aiohttp_mod.ClientError = RuntimeError
        sys.modules["aiohttp"] = aiohttp_mod

    aiogram_mod = types.ModuleType("aiogram")
    aiogram_types = types.ModuleType("aiogram.types")
    aiogram_types.BusinessConnection = object
    aiogram_types.Message = object
    aiogram_types.CallbackQuery = object
    aiogram_mod.types = aiogram_types
    sys.modules["aiogram"] = aiogram_mod
    sys.modules["aiogram.types"] = aiogram_types

    for package_name, package_path in {
        "bot": PROJECT_ROOT / "bot",
        "bot.handlers": PROJECT_ROOT / "bot" / "handlers",
    }.items():
        package = types.ModuleType(package_name)
        package.__path__ = [str(package_path)]
        sys.modules[package_name] = package

    path = PROJECT_ROOT / "bot" / "handlers" / "secretary_handlers.py"
    spec = importlib.util.spec_from_file_location("bot.handlers.secretary_handlers", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_install_cryptography_stub()
secretary_handlers = _load_secretary_handlers()
_build_secretary_content = secretary_handlers._build_secretary_content
_extract_secretary_reply_context = secretary_handlers._extract_secretary_reply_context
_message_preview = secretary_handlers._message_preview
_secretary_content_type = secretary_handlers._secretary_content_type
from bot.handlers.services.access_control import bot_command_targets_username, is_bot_message_allowed
from bot.handlers.services.mcp_permissions import allowed_tools_for_context, to_anthropic_tool_schema
from bot.handlers.services.model_client_manager import (
    _anthropic_assistant_tool_message,
    _extract_anthropic_tool_uses,
    _close_old_clients_sync,
    _geocoding_name_candidates,
    _is_mcp_error_result,
    _normalize_geocoding_arguments,
    model_clients,
)
from bot.handlers.services.secretary_debounce_manager import SecretaryDebounceManager
from bot.handlers.services.secretary_queue_policy import suppress_model_unavailable_notice
from bot.handlers.services.prompt_manager import build_system_prompt_status
from config.settings import settings_manager
from gui.admin_panel.services.user_service import filter_group_history_messages
from utils.database import base_db
from utils.database.message_db import MessageDB
from utils.database.mcp_db import McpDB
from utils.database.secretary_db import SecretaryDB


def check_bot_access_policy():
    assert bot_command_targets_username("/reset_context", "La_Lamina_bot") is True
    assert bot_command_targets_username("/reset_context@La_Lamina_bot", "La_Lamina_bot") is True
    assert bot_command_targets_username("/reset_context@BorisOs232_bot", "La_Lamina_bot") is False

    settings = {"accept_bot_messages": True, "bot_access_policy": {"mode": "all", "apply_in_private": True}}
    assert is_bot_message_allowed(settings, bot_telegram_id=10, chat_type="private")[0] is True

    settings = {"accept_bot_messages": False, "bot_access_policy": {"mode": "all"}}
    assert is_bot_message_allowed(settings, bot_telegram_id=10, chat_type="private")[0] is False

    settings = {"accept_bot_messages": True, "bot_access_policy": {"mode": "off", "apply_in_private": True}}
    assert is_bot_message_allowed(settings, bot_telegram_id=10, chat_type="private")[0] is False

    settings = {
        "accept_bot_messages": True,
        "bot_access_policy": {"mode": "allowlist", "allow_bot_ids": [10], "apply_in_private": True},
    }
    assert is_bot_message_allowed(settings, bot_telegram_id=10, chat_type="private")[0] is True
    assert is_bot_message_allowed(settings, bot_telegram_id=11, chat_type="private")[0] is False

    settings = {
        "accept_bot_messages": True,
        "bot_access_policy": {"mode": "denylist", "deny_bot_ids": [10], "apply_in_groups": True},
    }
    assert is_bot_message_allowed(settings, bot_telegram_id=10, chat_type="group")[0] is False
    assert is_bot_message_allowed(settings, bot_telegram_id=11, chat_type="group")[0] is True


def check_secretary_db_and_messages():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old_path = base_db.DATABASE_PATH
    old_created = base_db.BaseDB._tables_created
    try:
        base_db.DATABASE_PATH = path
        base_db.BaseDB._tables_created = False

        secretary = SecretaryDB()
        assert secretary.upsert_profile(
            101,
            response_mode="draft",
            save_history=1,
            default_delay_seconds=1.5,
            burst_window_seconds=2.5,
            max_batch_messages=7,
            default_session_ttl_seconds=0,
            close_after_reply=0,
            turn_based_replies=1,
            media_stt_enabled=1,
            media_images_enabled=0,
        )
        assert secretary.upsert_chat_settings(
            101,
            202,
            response_mode="auto",
            history_enabled=0,
            session_ttl_seconds=600,
            close_after_reply=1,
            owner_message_behavior="close_session",
            turn_based_replies=0,
            media_stt_enabled=0,
            media_images_enabled=1,
            allowed_mcp="demo__ping",
        )
        profile = secretary.get_profile(101)
        resolved = secretary.resolve_chat_runtime_settings(profile, 202)
        assert resolved["response_mode"] == "auto"
        assert resolved["save_history"] is False
        assert resolved["session_ttl_seconds"] == 600
        assert resolved["close_after_reply"] is True
        assert resolved["owner_message_behavior"] == "close_session"
        assert resolved["turn_based_replies"] is False
        assert resolved["media_stt_enabled"] is False
        assert resolved["media_images_enabled"] is True
        assert resolved["allowed_mcp"] == "demo__ping"
        assert resolved["delay_seconds"] == 1.5
        assert resolved["burst_window_seconds"] == 2.5
        assert resolved["max_batch_messages"] == 7
        assert secretary.upsert_business_connection("bc-regression", 101, user_chat_id=404)
        assert secretary.get_business_connection_owner("bc-regression") == 101

        session = secretary.get_or_create_session(101, 202, counterparty_id=303, ttl_seconds=0)
        assert session["id"]
        assert session["expires_at"] is None
        assert secretary.get_active_session(101, 202)["id"] == session["id"]
        assert secretary.close_session(session["id"], reason="regression")
        assert secretary.get_active_session(101, 202) is None
        assert secretary.claim_response_lock(101, 202, 777) is True
        assert secretary.claim_response_lock(101, 202, 777) is False
        secretary.mark_response_lock_sent(101, 202, 777)
        secretary.close()

        base_db.BaseDB._tables_created = False
        messages = MessageDB()
        messages.cursor.execute("INSERT INTO users (telegram_id, first_name) VALUES (?, ?)", (101, "Owner"))
        messages.connection.commit()
        user_id = messages.cursor.lastrowid
        messages.add_message(
            user_id,
            "user",
            "hello",
            source_mode="secretary",
            secretary_owner_telegram_id=101,
            secretary_source_chat_id=202,
            secretary_counterparty_id=303,
            secretary_session_id=1,
        )
        messages.add_message(
            user_id,
            "assistant",
            "regular reply",
            chat_id=101,
            chat_type="private",
            source_mode="normal",
        )
        messages.add_message(
            user_id,
            "assistant",
            "secretary reply",
            chat_id=202,
            reply_to_message_id=777,
            source_mode="secretary",
            secretary_owner_telegram_id=101,
            secretary_source_chat_id=202,
            secretary_session_id=1,
        )
        assert messages.has_secretary_assistant_reply(101, 202, 777) is True
        assert messages.has_secretary_assistant_reply(101, 202, 778) is False
        messages.cursor.execute("SELECT secretary_session_id FROM messages LIMIT 1")
        assert messages.cursor.fetchone()[0] == 1
        secretary_history = messages.get_secretary_owner_messages_active(101, limit=50)
        assert len(secretary_history) == 2
        assert secretary_history[0]["source_mode"] == "secretary"
        assert secretary_history[0]["secretary_owner_telegram_id"] == 101
        assert {row["role"] for row in secretary_history} == {"user", "assistant"}
        messages.close()
    finally:
        base_db.DATABASE_PATH = old_path
        base_db.BaseDB._tables_created = old_created
        try:
            os.remove(path)
        except OSError:
            pass


def check_group_chat_migration():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old_path = base_db.DATABASE_PATH
    old_created = base_db.BaseDB._tables_created
    try:
        base_db.DATABASE_PATH = path
        base_db.BaseDB._tables_created = False
        messages = MessageDB()
        messages.cursor.execute(
            "INSERT INTO users (telegram_id, first_name) VALUES (?, ?)",
            (101, "Owner"),
        )
        user_id = messages.cursor.lastrowid
        messages.update_chat(-123, chat_type="group", chat_title="Test group", is_banned=1)
        messages.update_chat(-100456, chat_type="supergroup", chat_title="Test group")
        messages.update_chat(-999, chat_type="group", chat_title="Empty migrated group")
        messages.update_chat(-100999, chat_type="supergroup", chat_title="Empty migrated group")
        visible_chat_ids = {row["chat_id"] for row in messages.get_group_chats(limit=20)}
        assert -999 not in visible_chat_ids
        assert -100999 in visible_chat_ids
        messages.add_message(
            user_id,
            "user",
            "before migration",
            chat_id=-123,
            chat_type="group",
            chat_title="Test group",
        )
        messages.add_message(
            user_id,
            "assistant",
            "after migration",
            chat_id=-100456,
            chat_type="supergroup",
            chat_title="Test group",
        )

        assert messages.migrate_group_chat(
            -123,
            -100456,
            chat_title="Test group",
            chat_type="supergroup",
        )
        assert messages.get_group_chat(-123) is None
        migrated = messages.get_group_chat(-100456)
        assert migrated["chat_type"] == "supergroup"
        assert migrated["chat_title"] == "Test group"
        assert migrated["is_banned"] == 1
        history = messages.get_chat_messages(-100456, limit=10)
        assert [row["content"] for row in history] == ["before migration", "after migration"]
        assert all(row["chat_type"] == "supergroup" for row in history)
        messages.close()
    finally:
        base_db.DATABASE_PATH = old_path
        base_db.BaseDB._tables_created = old_created
        try:
            os.remove(path)
        except OSError:
            pass


def check_group_history_filter():
    history = [
        {"id": 1, "role": "user", "is_addressed": 0},
        {"id": 2, "role": "user", "is_addressed": 1},
        {"id": 3, "role": "assistant", "is_addressed": 1},
        {"id": 4, "role": "system", "is_summary": 1},
    ]
    assert [row["id"] for row in filter_group_history_messages(history, addressed_only=True)] == [2, 3, 4]
    assert [row["id"] for row in filter_group_history_messages(history, addressed_only=False)] == [1, 2, 3, 4]


def check_system_prompt_status():
    status = build_system_prompt_status("test prompt", "2026-06-11 12:34:56")
    assert "11 симв." in status
    assert "2026-06-11 12:34:56" in status
    assert "со следующего запроса" in status
    assert "SHA " in status


def check_audit_retention():
    from config.settings import settings_manager

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old_path = base_db.DATABASE_PATH
    old_created = base_db.BaseDB._tables_created
    old_retention = dict(settings_manager.settings.get("audit_retention", {}) or {})
    try:
        settings_manager.settings["audit_retention"] = {
            "secretary_events_days": 0,
            "secretary_events_max_per_owner": 2,
            "mcp_tool_calls_days": 0,
            "mcp_tool_calls_max": 2,
            "mcp_access_audit_days": 0,
            "mcp_access_audit_max": 2,
        }
        base_db.DATABASE_PATH = path
        base_db.BaseDB._tables_created = False

        secretary = SecretaryDB()
        for index in range(4):
            secretary.add_event(555, "test", f"event={index}", chat_id=100)
        secretary.cursor.execute("SELECT COUNT(*) FROM secretary_events WHERE owner_telegram_id = ?", (555,))
        assert secretary.cursor.fetchone()[0] == 2
        secretary.close()

        base_db.BaseDB._tables_created = False
        mcp = McpDB()
        for index in range(4):
            mcp.add_tool_call(server_name="demo", tool_name="ping", status="completed", arguments={"i": index})
            mcp.add_access_denied(server_name="demo", tool_name="ping", reason=f"denied={index}")
        mcp.cursor.execute("SELECT COUNT(*) FROM mcp_tool_calls")
        assert mcp.cursor.fetchone()[0] == 2
        mcp.cursor.execute("SELECT COUNT(*) FROM mcp_access_audit")
        assert mcp.cursor.fetchone()[0] == 2
        mcp.close()
    finally:
        settings_manager.settings["audit_retention"] = old_retention
        base_db.DATABASE_PATH = old_path
        base_db.BaseDB._tables_created = old_created
        try:
            os.remove(path)
        except OSError:
            pass


def check_secretary_reply_and_media_helpers():
    owner = SimpleNamespace(id=100, is_bot=False, first_name="Owner", last_name="", username="owner")
    reply = SimpleNamespace(
        text="Owner answer",
        caption=None,
        photo=None,
        video=None,
        video_note=None,
        voice=None,
        document=None,
        sticker=None,
        from_user=owner,
        sender_chat=None,
    )
    message = SimpleNamespace(
        text="Question",
        caption=None,
        photo=None,
        video=None,
        video_note=None,
        voice=None,
        document=None,
        sticker=None,
        reply_to_message=reply,
        quote=None,
    )
    context = _extract_secretary_reply_context(message, 100)
    content = _build_secretary_content(message, context)
    assert "Owner answer" in context
    assert "Owner answer" in content and content.endswith("Question")

    photo_message = SimpleNamespace(
        text=None,
        caption=None,
        photo=[1],
        video=None,
        video_note=None,
        voice=None,
        document=None,
        sticker=None,
        reply_to_message=None,
        quote=None,
    )
    assert _message_preview(photo_message).startswith("[")
    assert _secretary_content_type(photo_message) == "image"


def check_mcp_permissions_and_anthropic_helpers():
    settings = {
        "mcp": {
            "enabled": True,
            "servers": [
                {"name": "a", "enabled": True, "access": {"secretary": True}, "tools": [{"name": "one"}, {"name": "two"}]},
                {"name": "b", "enabled": True, "access": {"secretary": True}, "tools": [{"name": "one"}]},
            ],
        }
    }
    context = {"source_mode": "secretary", "chat_type": "private", "allowed_mcp": "a__two"}
    tools = allowed_tools_for_context(settings, context)
    assert len(tools) == 1
    assert tools[0]["server"] == "a" and tools[0]["name"] == "two"

    schema = to_anthropic_tool_schema({
        "server": "demo",
        "name": "ping",
        "description": "Ping tool",
        "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
    })
    assert schema["name"] == "demo__ping"
    assert schema["input_schema"]["type"] == "object"

    response = SimpleNamespace(raw_anthropic={
        "content": [
            {"type": "text", "text": "checking"},
            {"type": "tool_use", "id": "u1", "name": "demo__ping", "input": {"x": "1"}},
        ]
    })
    tool_uses = _extract_anthropic_tool_uses(response)
    assert len(tool_uses) == 1 and tool_uses[0]["id"] == "u1"
    assistant_message = _anthropic_assistant_tool_message(response)
    assert assistant_message["role"] == "assistant"
    assert assistant_message["content"][1]["type"] == "tool_use"

    routing_settings = {
        "mcp": {
            "enabled": True,
            "servers": [
                {
                    "name": "web",
                    "enabled": True,
                    "access": {"private": True},
                    "tools": [{"name": "duckduckgo_web_search", "description": "Search web"}],
                },
                {
                    "name": "open-websearch",
                    "enabled": True,
                    "access": {"private": True},
                    "tools": [{"name": "search", "description": "Search with multiple engines"}],
                },
                {
                    "name": "weather-open-meteo",
                    "enabled": True,
                    "access": {"private": True},
                    "tools": [
                        {"name": "geocoding", "description": "Find location coordinates"},
                        {"name": "weather_forecast", "description": "Weather forecast"},
                    ],
                },
            ],
        }
    }
    followup_tools = allowed_tools_for_context(
        routing_settings,
        {
            "chat_type": "private",
            "query_text": "А сейчас?",
            "recent_context_text": "Какая погода в Анапе?",
        },
    )
    assert {tool["server"] for tool in followup_tools} == {"weather-open-meteo"}
    assert {tool["name"] for tool in followup_tools} == {"geocoding", "weather_forecast"}

    search_tools = allowed_tools_for_context(
        routing_settings,
        {"chat_type": "private", "query_text": "Найди новости про Telegram"},
    )
    search_names = {f"{tool['server']}__{tool['name']}" for tool in search_tools}
    assert "web__duckduckgo_web_search" not in search_names
    assert "open-websearch__search" in search_names

    normalized = _normalize_geocoding_arguments({
        "name": "Краснодара",
        "count": "3",
        "format": "JSON",
        "countryCode": "ru",
    })
    assert normalized["format"] == "json"
    assert normalized["countryCode"] == "RU"
    assert normalized["count"] == 3
    assert "Краснодар" in _geocoding_name_candidates("Краснодара")
    assert "Анапа" in _geocoding_name_candidates("Анапе")
    assert "Анапа" in _geocoding_name_candidates("Анапы")
    assert _is_mcp_error_result("Error: invalid input") is True


async def check_secretary_batching():
    batches = []

    async def enqueue(batch):
        batches.append(batch)

    manager = SecretaryDebounceManager(
        enqueue,
        default_delay_seconds=60,
        default_burst_window_seconds=60,
        default_max_batch_messages=3,
    )
    message = SimpleNamespace(message_id=1)
    await manager.add_message(
        owner_telegram_id=101,
        chat_id=202,
        user={"id": 1},
        message=message,
        text_content="first",
    )
    await manager.add_message(
        owner_telegram_id=101,
        chat_id=202,
        user={"id": 1},
        message=SimpleNamespace(message_id=2),
        text_content="second",
    )
    await manager.flush(101, 202)
    assert len(batches) == 1
    assert batches[0].text_content == "first\nsecond"
    assert batches[0].request_context["secretary_batch_size"] == 2
    await manager.close()


async def check_secretary_handler_queue_integration():
    queued = []

    class FakeQueue:
        async def put(self, item):
            queued.append(item)

    class FakeCounter:
        value = 0

        async def increment(self):
            self.value += 1
            return self.value

    original_queue = secretary_handlers.queue_manager.request_queue
    original_counter = secretary_handlers.queue_manager.message_counter
    original_manager = secretary_handlers._secretary_debounce_manager
    original_increment = secretary_handlers.stats.stats.increment_pending_requests
    try:
        secretary_handlers.queue_manager.request_queue = FakeQueue()
        secretary_handlers.queue_manager.message_counter = FakeCounter()
        secretary_handlers.stats.stats.increment_pending_requests = lambda: None
        secretary_handlers._secretary_debounce_manager = None

        message = SimpleNamespace(
            chat=SimpleNamespace(id=202, type="private"),
            from_user=SimpleNamespace(id=303, is_bot=False),
            business_connection_id="bc1",
            message_id=44,
        )
        runtime_settings = {
            "response_mode": "confirm",
            "system_prompt": "secretary prompt",
            "save_history": True,
            "close_after_reply": False,
            "delay_seconds": 60,
            "burst_window_seconds": 60,
            "max_batch_messages": 10,
        }
        await secretary_handlers._enqueue_secretary_request(
            101,
            {"id": 1, "priority": 3},
            {},
            runtime_settings,
            {"id": 9},
            message,
            "hello",
        )
        manager = secretary_handlers._secretary_debounce_manager
        assert manager.pending_count(101, 202) == 1
        await manager.flush(101, 202)
        assert len(queued) == 1
        payload = queued[0][5]
        assert payload["source_mode"] == "secretary"
        assert payload["secretary"]["response_mode"] == "confirm"
        assert payload["request_context"]["secretary_session_id"] == 9
        await manager.close()
    finally:
        secretary_handlers.queue_manager.request_queue = original_queue
        secretary_handlers.queue_manager.message_counter = original_counter
        secretary_handlers.stats.stats.increment_pending_requests = original_increment
        secretary_handlers._secretary_debounce_manager = original_manager


def check_secretary_queue_policy_and_settings():
    secretary_mode = settings_manager.get_settings().get("secretary_mode")
    assert secretary_mode["allow_infinite_sessions"] is True
    assert secretary_mode["suppress_model_unavailable_notice"] is True
    assert suppress_model_unavailable_notice({
        "request_context": {"source_mode": "secretary"},
    }) is True
    assert suppress_model_unavailable_notice({
        "request_context": {"source_mode": "normal"},
    }) is False


def check_model_client_reinit_close():
    class FakeClient:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    fake = FakeClient()
    model_clients["regression-close"] = fake
    try:
        _close_old_clients_sync()
        assert fake.closed is True
    finally:
        model_clients.pop("regression-close", None)


def check_markdown_technical_identifiers():
    from utils.markdown_formatter import telegram_formatter

    simple_text, simple_mode = telegram_formatter.process_text("**Q4_K_M / Q5_K_M**")
    assert simple_mode == "MarkdownV2"
    assert simple_text == "*Q4\\_K\\_M / Q5\\_K\\_M*"

    complex_text, complex_mode = telegram_formatter.process_text(
        "Выбор: **Q6_K / Q8_0 / BF16**\n```\nGemma Q4_0\n```"
    )
    assert complex_mode == "HTML"
    assert "<b>Q6_K / Q8_0 / BF16</b>" in complex_text
    assert "<i>" not in complex_text
    assert "<pre><code>Gemma Q4_0" in complex_text


def main():
    check_bot_access_policy()
    check_secretary_db_and_messages()
    check_group_chat_migration()
    check_group_history_filter()
    check_system_prompt_status()
    check_audit_retention()
    check_secretary_reply_and_media_helpers()
    check_mcp_permissions_and_anthropic_helpers()
    asyncio.run(check_secretary_batching())
    asyncio.run(check_secretary_handler_queue_integration())
    check_secretary_queue_policy_and_settings()
    check_model_client_reinit_close()
    check_markdown_technical_identifiers()
    print("regression checks passed")


if __name__ == "__main__":
    main()
