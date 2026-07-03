from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


ROLE_ADMIN = "admin"
ROLE_REGULAR = "regular"
ROLE_SECRETARY_OWNER = "secretary_owner"


def bot_command_targets_username(command_text: str, bot_username: str) -> bool:
    command = str(command_text or "").strip().lower()
    username = str(bot_username or "").strip().lstrip("@").lower()
    if not command.startswith("/"):
        return False
    if "@" not in command:
        return True
    return bool(username and command.rsplit("@", 1)[-1] == username)


def normalize_admin_telegram_ids(settings: Dict[str, Any]) -> set[int]:
    admin_ids = settings.get("admin_telegram_ids", [])
    if isinstance(admin_ids, str):
        values = admin_ids.replace("\n", ",").replace(";", ",").split(",")
    else:
        values = admin_ids or []

    normalized = set()
    for value in values:
        try:
            normalized.add(int(str(value).strip()))
        except (TypeError, ValueError):
            continue
    return normalized


def normalize_telegram_id_set(value: Any) -> set[int]:
    if isinstance(value, str):
        values = value.replace("\n", ",").replace(";", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        values = value
    elif value is None:
        values = []
    else:
        values = [value]

    normalized = set()
    for item in values:
        try:
            normalized.add(int(str(item).strip()))
        except (TypeError, ValueError):
            continue
    return normalized


def normalize_bot_access_policy(settings: Dict[str, Any]) -> Dict[str, Any]:
    policy = settings.get("bot_access_policy")
    if not isinstance(policy, dict):
        policy = {}

    mode = str(policy.get("mode", "all")).strip().lower()
    if mode not in {"all", "off", "allowlist", "denylist"}:
        mode = "all"

    return {
        "mode": mode,
        "allow_bot_ids": normalize_telegram_id_set(policy.get("allow_bot_ids")),
        "deny_bot_ids": normalize_telegram_id_set(policy.get("deny_bot_ids")),
        "apply_in_private": bool(policy.get("apply_in_private", True)),
        "apply_in_groups": bool(policy.get("apply_in_groups", True)),
        "apply_in_secretary": bool(policy.get("apply_in_secretary", False)),
    }


def is_bot_message_allowed(
    settings: Dict[str, Any],
    *,
    bot_telegram_id: int,
    chat_type: str,
    source_mode: str = "normal",
) -> tuple[bool, str]:
    if not settings.get("accept_bot_messages", True):
        return False, "accept_bot_messages=false"

    policy = normalize_bot_access_policy(settings)
    applies = False
    if source_mode == "secretary":
        applies = policy["apply_in_secretary"]
    elif chat_type == "private":
        applies = policy["apply_in_private"]
    elif chat_type in {"group", "supergroup"}:
        applies = policy["apply_in_groups"]

    if not applies:
        return True, "policy_not_applied"

    mode = policy["mode"]
    if mode == "all":
        return True, "mode=all"
    if mode == "off":
        return False, "mode=off"
    if mode == "allowlist":
        allowed = int(bot_telegram_id) in policy["allow_bot_ids"]
        return allowed, "allowlist_match" if allowed else "allowlist_miss"
    if mode == "denylist":
        denied = int(bot_telegram_id) in policy["deny_bot_ids"]
        return not denied, "denylist_match" if denied else "denylist_miss"

    return True, "fallback"


def is_admin_user(settings: Dict[str, Any], user: Optional[Dict[str, Any]], telegram_id: int) -> bool:
    if int(telegram_id) in normalize_admin_telegram_ids(settings):
        return True
    return bool(user and int(user.get("priority") or 0) >= 100)


def resolve_user_role(
    settings: Dict[str, Any],
    user: Optional[Dict[str, Any]],
    telegram_id: int,
    *,
    secretary_owner_telegram_id: Optional[int] = None,
) -> str:
    if is_admin_user(settings, user, telegram_id):
        return ROLE_ADMIN
    if secretary_owner_telegram_id is not None and int(telegram_id) == int(secretary_owner_telegram_id):
        return ROLE_SECRETARY_OWNER
    return ROLE_REGULAR


@dataclass(frozen=True)
class RequestContext:
    source_mode: str
    actor_telegram_id: int
    chat_id: int
    chat_type: str
    is_admin: bool
    role: str
    secretary_owner_telegram_id: Optional[int]
    author_is_bot: bool
    is_addressed: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_request_context(
    *,
    settings: Dict[str, Any],
    user: Optional[Dict[str, Any]],
    actor_telegram_id: int,
    chat_id: int,
    chat_type: str,
    author_is_bot: bool = False,
    is_addressed: bool = True,
    source_mode: str = "normal",
    secretary_owner_telegram_id: Optional[int] = None,
) -> RequestContext:
    role = resolve_user_role(
        settings,
        user,
        actor_telegram_id,
        secretary_owner_telegram_id=secretary_owner_telegram_id,
    )
    return RequestContext(
        source_mode=source_mode,
        actor_telegram_id=actor_telegram_id,
        chat_id=chat_id,
        chat_type=chat_type,
        is_admin=role == ROLE_ADMIN,
        role=role,
        secretary_owner_telegram_id=secretary_owner_telegram_id,
        author_is_bot=author_is_bot,
        is_addressed=is_addressed,
    )
