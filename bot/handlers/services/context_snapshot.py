from dataclasses import dataclass
from typing import List, Dict, Set

from utils.logger import setup_logger
from utils import server_state
from utils.database.database_manager import DatabaseManager
from .text_cleaner import clean_hidden_characters

logger = setup_logger(__name__)

SNAPSHOT_DEFAULT_LIMIT = 40
SNAPSHOT_NEIGHBOR_WINDOW = 4
SNAPSHOT_MAX_LINE_LENGTH = 160


@dataclass
class _SnapshotEntry:
    role: str
    author: str
    text: str


def _build_author_display(message: Dict) -> str:
    if message.get('role') == 'assistant':
        return server_state.bot_full_name or server_state.bot_username or "Бот"

    username = message.get('author_username')
    if username:
        return f"@{username}"

    full_name = (message.get('author_full_name') or "").strip()
    if full_name:
        return full_name

    author_id = message.get('author_telegram_id')
    if author_id:
        return f"user_{author_id}"

    return "Участник чата"


def _compact_text(message: Dict) -> str:
    content_type = (message.get('content_type') or 'text').lower()
    raw_content = clean_hidden_characters(message.get('content') or "")
    raw_content = raw_content.replace('\n', ' ').strip()

    if content_type in {'image', 'image_ref'}:
        description = "изображение"
        if raw_content:
            description = raw_content
        else:
            mime = message.get('image_mime')
            if mime:
                description = f"изображение ({mime})"
        return description

    if not raw_content:
        return ""

    if len(raw_content) > SNAPSHOT_MAX_LINE_LENGTH:
        raw_content = raw_content[:SNAPSHOT_MAX_LINE_LENGTH - 3].rstrip() + "..."
    return raw_content


def _collect_relevant_indices(messages: List[Dict], window: int) -> Set[int]:
    relevant: Set[int] = set()
    for idx, msg in enumerate(messages):
        if msg.get('role') == 'assistant' or msg.get('is_addressed'):
            start = max(0, idx - window)
            end = min(len(messages), idx + window + 1)
            relevant.update(range(start, end))
    return relevant


def build_group_context_snapshot(
    chat_id: int,
    *,
    limit: int = SNAPSHOT_DEFAULT_LIMIT,
    neighbor_window: int = SNAPSHOT_NEIGHBOR_WINDOW,
) -> str:
    """
    Формирует краткую сводку последних событий в групповом чате.
    Используется как дополнительный контекст для модели.
    """
    db = DatabaseManager()
    try:
        raw_messages = db.messages.get_recent_chat_messages(chat_id, limit=limit * 3)
    finally:
        db.close()

    if not raw_messages:
        logger.debug("Снапшот для чата %s пуст: нет сообщений", chat_id)
        return ""

    relevant_indices = _collect_relevant_indices(raw_messages, neighbor_window)
    if relevant_indices:
        selected = [raw_messages[i] for i in sorted(relevant_indices)]
    else:
        selected = raw_messages[-limit:]

    if len(selected) > limit:
        selected = selected[-limit:]

    snapshot_entries: List[_SnapshotEntry] = []
    for msg in selected:
        if msg.get('is_deleted'):
            continue
        author = _build_author_display(msg)
        compact = _compact_text(msg)
        if not compact:
            continue
        role = msg.get('role') or 'user'
        snapshot_entries.append(_SnapshotEntry(role=role, author=author, text=compact))

    if not snapshot_entries:
        logger.debug("Снапшот для чата %s пуст: нет релевантных записей", chat_id)
        return ""

    lines: List[str] = []
    for entry in snapshot_entries:
        prefix = "🤖" if entry.role == 'assistant' else "•"
        lines.append(f"{prefix} {entry.author}: {entry.text}")

    header = "Краткий контекст последних сообщений:\n"
    return header + "\n".join(lines)

