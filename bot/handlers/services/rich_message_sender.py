from dataclasses import dataclass
from typing import Any, Dict, Optional
import re

import httpx

from utils.logger import setup_logger

logger = setup_logger(__name__)

RICH_MESSAGE_TEXT_LIMIT = 32768
TELEGRAM_API_BASE_URL = "https://api.telegram.org"


@dataclass
class RichMessageResult:
    status: str
    message: Any = None
    reason: str = ""

    @property
    def sent(self) -> bool:
        return self.status == "sent"


def rich_messages_enabled(settings: Dict) -> bool:
    rich_settings = settings.get("rich_messages") or {}
    return bool(rich_settings.get("enabled", False))


def rich_messages_fallback_enabled(settings: Dict) -> bool:
    rich_settings = settings.get("rich_messages") or {}
    return bool(rich_settings.get("fallback_to_legacy", True))


def rich_message_streaming_enabled(settings: Dict) -> bool:
    rich_settings = settings.get("rich_messages") or {}
    return rich_messages_enabled(settings) and bool(rich_settings.get("streaming_enabled", True))


async def try_send_rich_message(
    *,
    bot: Any,
    chat_id: int | str,
    text: str,
    settings: Dict,
    business_connection_id: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
    message_thread_id: Optional[int] = None,
) -> RichMessageResult:
    rich_settings = settings.get("rich_messages") or {}
    if not rich_messages_enabled(settings):
        return RichMessageResult("skipped", reason="disabled")

    if not text or not text.strip():
        return RichMessageResult("skipped", reason="empty_text")

    if business_connection_id:
        logger.info("Skipping sendRichMessage for Telegram Business context: unsupported by Telegram")
        return RichMessageResult("skipped", reason="business_unsupported")

    rich_message, text, reason = _build_input_rich_message(text, settings, draft=False)
    if reason:
        return RichMessageResult("skipped", reason=reason)

    token = getattr(bot, "token", None)
    if not token:
        return RichMessageResult("failed", reason="missing_bot_token")

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "rich_message": rich_message,
    }
    if reply_to_message_id:
        payload["reply_parameters"] = {"message_id": int(reply_to_message_id)}
    if message_thread_id:
        payload["message_thread_id"] = int(message_thread_id)

    url = f"{TELEGRAM_API_BASE_URL}/bot{token}/sendRichMessage"
    try:
        logger.info(
            "Trying sendRichMessage: chat_id=%s business=%s format=%s length=%s",
            chat_id,
            bool(business_connection_id),
            next(iter(rich_message.keys()), "unknown"),
            len(text),
        )
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, json=payload)
        data = response.json()
    except Exception as exc:
        logger.warning("sendRichMessage failed before Telegram response: %s", exc)
        return RichMessageResult("failed", reason=str(exc))

    if not data.get("ok"):
        description = str(data.get("description") or f"HTTP {response.status_code}")
        logger.warning(
            "sendRichMessage rejected by Telegram: chat_id=%s business=%s reason=%s",
            chat_id,
            bool(business_connection_id),
            description,
        )
        return RichMessageResult("failed", reason=description)

    return RichMessageResult("sent", message=data.get("result"))


async def try_send_rich_message_draft(
    *,
    bot: Any,
    chat_id: int | str,
    draft_id: int,
    text: str,
    settings: Dict,
    message_thread_id: Optional[int] = None,
) -> RichMessageResult:
    if not rich_message_streaming_enabled(settings):
        return RichMessageResult("skipped", reason="disabled")

    if not text or not text.strip():
        return RichMessageResult("skipped", reason="empty_text")

    rich_message, text, reason = _build_input_rich_message(text, settings, draft=True)
    if reason:
        return RichMessageResult("skipped", reason=reason)

    token = getattr(bot, "token", None)
    if not token:
        return RichMessageResult("failed", reason="missing_bot_token")

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "draft_id": int(draft_id) or 1,
        "rich_message": rich_message,
    }
    if message_thread_id:
        payload["message_thread_id"] = int(message_thread_id)

    url = f"{TELEGRAM_API_BASE_URL}/bot{token}/sendRichMessageDraft"
    try:
        logger.debug(
            "Trying sendRichMessageDraft: chat_id=%s draft_id=%s format=%s length=%s",
            chat_id,
            draft_id,
            next(iter(rich_message.keys()), "unknown"),
            len(text),
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
        data = response.json()
    except Exception as exc:
        logger.warning("sendRichMessageDraft failed before Telegram response: %s", exc)
        return RichMessageResult("failed", reason=str(exc))

    if not data.get("ok"):
        description = str(data.get("description") or f"HTTP {response.status_code}")
        logger.debug("sendRichMessageDraft rejected by Telegram: chat_id=%s reason=%s", chat_id, description)
        return RichMessageResult("failed", reason=description)

    return RichMessageResult("sent", message=True)


def _build_input_rich_message(text: str, settings: Dict, *, draft: bool) -> tuple[Optional[Dict[str, str]], str, str]:
    rich_settings = settings.get("rich_messages") or {}
    rich_format = rich_settings.get("format", "markdown")
    if rich_format not in {"markdown", "html"}:
        rich_format = "markdown"

    if rich_format == "markdown":
        text = _normalize_rich_draft_markdown(text) if draft else _normalize_rich_markdown(text)

    if len(text) > RICH_MESSAGE_TEXT_LIMIT:
        return None, text, "too_long"

    rich_message = {
        rich_format: text,
    }
    if rich_settings.get("skip_entity_detection", False):
        rich_message["skip_entity_detection"] = True

    return rich_message, text, ""


def _normalize_rich_markdown(text: str) -> str:
    text = _normalize_latex_math_delimiters(text)
    return _normalize_markdown_tables(text)


def _normalize_rich_draft_markdown(text: str) -> str:
    text = _normalize_rich_markdown(text)
    if text.count("```") % 2 == 1:
        text += "\n```"
    if text.count("$$") % 2 == 1:
        text += "\n$$"

    single_dollar_count = len(re.findall(r"(?<!\$)\$(?!\$)", text))
    if single_dollar_count % 2 == 1:
        text += "$"
    return text


def prepare_legacy_fallback_text(text: str) -> str:
    text = _normalize_rich_markdown(text or "")
    text = _convert_block_math_to_code(text)
    text = _remove_inline_math_delimiters(text)
    return _convert_markdown_tables_to_code_blocks(text)


def _normalize_latex_math_delimiters(text: str) -> str:
    text = re.sub(
        r"\\\[\s*([\s\S]*?)\s*\\\]",
        lambda match: "$$" + match.group(1).strip() + "$$",
        text,
    )
    text = re.sub(
        r"\\\(\s*([\s\S]*?)\s*\\\)",
        lambda match: "$" + match.group(1).strip() + "$",
        text,
    )
    return text


def _convert_block_math_to_code(text: str) -> str:
    return re.sub(
        r"\$\$\s*([\s\S]*?)\s*\$\$",
        lambda match: "```\n" + match.group(1).strip() + "\n```",
        text,
    )


def _remove_inline_math_delimiters(text: str) -> str:
    return re.sub(
        r"(?<!\$)\$([^$\n]+)\$(?!\$)",
        lambda match: match.group(1).strip(),
        text,
    )


def _normalize_markdown_tables(text: str) -> str:
    lines = text.splitlines()
    normalized = list(lines)

    for index in range(len(lines) - 1):
        header = lines[index]
        separator = lines[index + 1]
        if not _looks_like_table_row(header) or not _looks_like_table_separator(separator):
            continue

        header_columns = _count_markdown_table_columns(header)
        separator_columns = _count_markdown_table_columns(separator)
        if header_columns <= 0 or separator_columns == header_columns:
            continue

        normalized[index + 1] = "| " + " | ".join(["---"] * header_columns) + " |"

    return "\n".join(normalized)


def _convert_markdown_tables_to_code_blocks(text: str) -> str:
    lines = text.splitlines()
    result = []
    index = 0

    while index < len(lines):
        if index + 1 >= len(lines):
            result.append(lines[index])
            index += 1
            continue

        header = lines[index]
        separator = lines[index + 1]
        if not _looks_like_table_row(header) or not _looks_like_table_separator(separator):
            result.append(lines[index])
            index += 1
            continue

        table_lines = [header]
        index += 2
        while index < len(lines) and _looks_like_table_row(lines[index]):
            table_lines.append(lines[index])
            index += 1

        result.append("```")
        result.extend(_format_table_rows(table_lines))
        result.append("```")

    return "\n".join(result)


def _format_table_rows(table_lines: list[str]) -> list[str]:
    rows = [_split_table_row(line) for line in table_lines]
    column_count = max((len(row) for row in rows), default=0)
    if column_count == 0:
        return table_lines

    for row in rows:
        row.extend([""] * (column_count - len(row)))

    widths = [
        max(len(row[column].strip()) for row in rows)
        for column in range(column_count)
    ]

    formatted = []
    for row_index, row in enumerate(rows):
        formatted.append(" | ".join(row[column].strip().ljust(widths[column]) for column in range(column_count)))
        if row_index == 0:
            formatted.append("-+-".join("-" * width for width in widths))
    return formatted


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _looks_like_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _looks_like_table_separator(line: str) -> bool:
    stripped = line.strip()
    if not _looks_like_table_row(stripped):
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _count_markdown_table_columns(line: str) -> int:
    return len([cell for cell in line.strip().strip("|").split("|")])
