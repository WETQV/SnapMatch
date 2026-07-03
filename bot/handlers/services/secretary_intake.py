from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from utils.database.database_manager import DatabaseManager
from utils.logger import setup_logger

from .secretary_debounce_manager import SecretaryDebounceManager

logger = setup_logger(__name__)


@dataclass
class SecretaryIntakeResult:
    status: str
    reason: str = ""
    session_id: Optional[int] = None


class SecretaryIntakeService:
    def __init__(
        self,
        debounce_manager: SecretaryDebounceManager,
        *,
        db_factory: Callable[[], DatabaseManager] = DatabaseManager,
    ):
        self.debounce_manager = debounce_manager
        self.db_factory = db_factory

    async def handle_message(
        self,
        *,
        owner_telegram_id: int,
        message: Any,
        business_connection_id: Optional[str] = None,
    ) -> SecretaryIntakeResult:
        db = self.db_factory()
        try:
            chat = getattr(message, "chat", None)
            from_user = getattr(message, "from_user", None)
            chat_id = int(getattr(chat, "id", 0) or 0)
            if chat_id == 0:
                return SecretaryIntakeResult(status="skipped", reason="missing_chat_id")

            profile = db.secretary.get_profile(owner_telegram_id)
            if not profile:
                db.secretary.add_event(owner_telegram_id, "unknown_owner", "Secretary owner is not configured", chat_id=chat_id)
                return SecretaryIntakeResult(status="skipped", reason="unknown_owner")

            runtime_settings = db.secretary.resolve_chat_runtime_settings(profile, chat_id)
            if not runtime_settings.get("enabled"):
                db.secretary.add_event(owner_telegram_id, "skipped", "Secretary profile disabled", chat_id=chat_id)
                return SecretaryIntakeResult(status="skipped", reason="disabled")

            response_mode = (runtime_settings.get("response_mode") or "confirm").lower()
            if response_mode == "off":
                db.secretary.add_event(owner_telegram_id, "skipped", "Secretary response mode is off", chat_id=chat_id)
                return SecretaryIntakeResult(status="skipped", reason="response_mode_off")

            author_is_bot = bool(getattr(from_user, "is_bot", False))
            if author_is_bot and runtime_settings.get("ignore_bot_messages", True):
                db.secretary.add_event(owner_telegram_id, "skipped", "Bot message ignored", chat_id=chat_id)
                return SecretaryIntakeResult(status="skipped", reason="bot_ignored")
            if runtime_settings.get("turn_based_replies", True) and self._is_outgoing_message(message, owner_telegram_id):
                db.secretary.add_event(owner_telegram_id, "skipped", "Outgoing message ignored by turn-based mode", chat_id=chat_id)
                return SecretaryIntakeResult(status="skipped", reason="outgoing_ignored")

            content = self._message_content(message)
            content_type = self._content_type(message)
            if not content.strip():
                db.secretary.add_event(owner_telegram_id, "skipped", "Empty secretary message", chat_id=chat_id)
                return SecretaryIntakeResult(status="skipped", reason="empty_message")

            owner_user = db.users.ensure_user(owner_telegram_id, first_name=profile.get("display_name"))
            if not owner_user:
                db.secretary.add_event(owner_telegram_id, "error", "Could not ensure owner user", chat_id=chat_id)
                return SecretaryIntakeResult(status="error", reason="owner_user_unavailable")

            counterparty_id = getattr(from_user, "id", None)
            active_session = db.secretary.get_active_session(owner_telegram_id, chat_id)
            if not active_session and runtime_settings.get("save_history", True):
                deleted_context = db.messages.delete_secretary_context(owner_telegram_id, chat_id=chat_id)
                if deleted_context:
                    db.secretary.add_event(
                        owner_telegram_id,
                        "context_reset",
                        f"new session started with clean context deleted={deleted_context}",
                        chat_id=chat_id,
                    )

            session = db.secretary.get_or_create_session(
                owner_telegram_id,
                chat_id,
                counterparty_id=counterparty_id,
                ttl_seconds=runtime_settings.get("session_ttl_seconds"),
            )
            session_id = session.get("id") if isinstance(session, dict) else None

            if runtime_settings.get("save_history", True):
                db.messages.add_message(
                    owner_user["id"],
                    "user",
                    content,
                    chat_id=chat_id,
                    chat_type=getattr(chat, "type", None),
                    chat_title=getattr(chat, "title", None),
                    author_telegram_id=counterparty_id,
                    author_username=getattr(from_user, "username", None),
                    author_full_name=self._full_name(from_user),
                    telegram_message_id=getattr(message, "message_id", None),
                    content_type=content_type,
                    is_addressed=1,
                    source_mode="secretary",
                    secretary_owner_telegram_id=owner_telegram_id,
                    secretary_source_chat_id=chat_id,
                    secretary_counterparty_id=counterparty_id,
                    secretary_session_id=session_id,
                    secretary_reply_status="received",
                )

            request_context = {
                "source_mode": "secretary",
                "actor_telegram_id": owner_telegram_id,
                "chat_id": chat_id,
                "chat_type": getattr(chat, "type", None),
                "business_connection_id": business_connection_id or getattr(message, "business_connection_id", None),
                "secretary_owner_telegram_id": owner_telegram_id,
                "secretary_source_chat_id": chat_id,
                "secretary_counterparty_id": counterparty_id,
                "secretary_session_id": session_id,
                "secretary_response_mode": response_mode,
                "secretary_system_prompt": runtime_settings.get("system_prompt") or "",
                "secretary_close_after_reply": bool(runtime_settings.get("close_after_reply")),
                "secretary_turn_based_replies": bool(runtime_settings.get("turn_based_replies", True)),
                "allowed_mcp": runtime_settings.get("allowed_mcp"),
                "author_is_bot": author_is_bot,
            }

            await self.debounce_manager.add_message(
                owner_telegram_id=owner_telegram_id,
                chat_id=chat_id,
                user=owner_user,
                message=message,
                text_content=content,
                attachments=[],
                request_context=request_context,
                delay_seconds=runtime_settings.get("delay_seconds"),
                burst_window_seconds=runtime_settings.get("burst_window_seconds"),
                max_batch_messages=runtime_settings.get("max_batch_messages"),
            )
            db.secretary.add_event(owner_telegram_id, "queued", f"session_id={session_id}", chat_id=chat_id)
            return SecretaryIntakeResult(status="queued", session_id=session_id)
        finally:
            db.close()

    @staticmethod
    def _message_content(message: Any) -> str:
        text = getattr(message, "text", None) or getattr(message, "caption", None)
        if text:
            return str(text)

        if getattr(message, "photo", None):
            return "[Фото]"
        if getattr(message, "video", None):
            return "[Видео]"
        if getattr(message, "video_note", None):
            return "[Кружочек]"
        if getattr(message, "voice", None):
            return "[Голосовое]"
        if getattr(message, "document", None):
            return "[Документ]"
        if getattr(message, "sticker", None):
            return "[Стикер]"
        return ""

    @staticmethod
    def _content_type(message: Any) -> str:
        if getattr(message, "photo", None):
            return "image"
        if getattr(message, "voice", None):
            return "voice"
        if getattr(message, "video_note", None):
            return "video_note"
        return "text"

    @staticmethod
    def _full_name(user: Any) -> Optional[str]:
        if not user:
            return None
        first_name = getattr(user, "first_name", None) or ""
        last_name = getattr(user, "last_name", None) or ""
        full_name = " ".join(part for part in [first_name, last_name] if part).strip()
        return full_name or getattr(user, "username", None)

    @staticmethod
    def _is_outgoing_message(message: Any, owner_telegram_id: int) -> bool:
        if getattr(message, "sender_business_bot", None) is not None:
            return True
        from_user = getattr(message, "from_user", None)
        if not from_user:
            return False
        try:
            return int(getattr(from_user, "id")) == int(owner_telegram_id)
        except (TypeError, ValueError):
            return False
