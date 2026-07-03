import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class SecretaryBufferedMessage:
    owner_telegram_id: int
    chat_id: int
    user: Dict[str, Any]
    message: Any
    text_content: str
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    request_context: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class SecretaryBatch:
    owner_telegram_id: int
    chat_id: int
    user: Dict[str, Any]
    message: Any
    text_content: str
    attachments: List[Dict[str, Any]]
    request_context: Dict[str, Any]
    messages: List[SecretaryBufferedMessage]


class SecretaryDebounceManager:
    """Buffers secretary messages and flushes one batch after a quiet window."""

    def __init__(
        self,
        enqueue_batch: Callable[[SecretaryBatch], Awaitable[None]],
        *,
        default_delay_seconds: float = 2.0,
        default_burst_window_seconds: float = 2.0,
        default_max_batch_messages: int = 10,
    ):
        self.enqueue_batch = enqueue_batch
        self.default_delay_seconds = max(0.0, float(default_delay_seconds))
        self.default_burst_window_seconds = max(0.0, float(default_burst_window_seconds))
        self.default_max_batch_messages = max(1, int(default_max_batch_messages))
        self._buffers: Dict[Tuple[int, int], List[SecretaryBufferedMessage]] = {}
        self._tasks: Dict[Tuple[int, int], asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def add_message(
        self,
        *,
        owner_telegram_id: int,
        chat_id: int,
        user: Dict[str, Any],
        message: Any,
        text_content: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
        request_context: Optional[Dict[str, Any]] = None,
        delay_seconds: Optional[float] = None,
        burst_window_seconds: Optional[float] = None,
        max_batch_messages: Optional[int] = None,
    ) -> None:
        key = (int(owner_telegram_id), int(chat_id))
        delay = self._normalize_seconds(delay_seconds, self.default_delay_seconds)
        burst_window = self._normalize_seconds(burst_window_seconds, self.default_burst_window_seconds)
        max_messages = max(1, int(max_batch_messages or self.default_max_batch_messages))

        entry = SecretaryBufferedMessage(
            owner_telegram_id=int(owner_telegram_id),
            chat_id=int(chat_id),
            user=dict(user or {}),
            message=message,
            text_content=text_content or "",
            attachments=list(attachments or []),
            request_context=dict(request_context or {}),
        )

        async with self._lock:
            buffer = self._buffers.setdefault(key, [])
            buffer.append(entry)
            if len(buffer) > max_messages:
                del buffer[:-max_messages]

            previous_task = self._tasks.get(key)
            if previous_task and not previous_task.done():
                previous_task.cancel()

            wait_seconds = max(delay, burst_window)
            self._tasks[key] = asyncio.create_task(self._delayed_flush(key, wait_seconds))

    async def flush(self, owner_telegram_id: int, chat_id: int) -> bool:
        key = (int(owner_telegram_id), int(chat_id))
        task = None
        async with self._lock:
            task = self._tasks.pop(key, None)
            if task and not task.done():
                task.cancel()
        return await self._flush_key(key)

    async def cancel(self, owner_telegram_id: int, chat_id: int) -> None:
        key = (int(owner_telegram_id), int(chat_id))
        async with self._lock:
            task = self._tasks.pop(key, None)
            if task and not task.done():
                task.cancel()
            self._buffers.pop(key, None)

    async def close(self) -> None:
        async with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
            self._buffers.clear()
        for task in tasks:
            if not task.done():
                task.cancel()

    def pending_count(self, owner_telegram_id: int, chat_id: int) -> int:
        return len(self._buffers.get((int(owner_telegram_id), int(chat_id)), []))

    async def _delayed_flush(self, key: Tuple[int, int], wait_seconds: float) -> None:
        try:
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            await self._flush_key(key)
        except asyncio.CancelledError:
            pass

    async def _flush_key(self, key: Tuple[int, int]) -> bool:
        async with self._lock:
            messages = self._buffers.pop(key, [])
            self._tasks.pop(key, None)

        if not messages:
            return False

        batch = self._build_batch(messages)
        try:
            await self.enqueue_batch(batch)
            logger.debug(
                "Secretary batch flushed: owner=%s chat=%s messages=%s",
                batch.owner_telegram_id,
                batch.chat_id,
                len(batch.messages),
            )
            return True
        except Exception as exc:
            logger.error(
                "Ошибка при enqueue secretary batch owner=%s chat=%s: %s",
                batch.owner_telegram_id,
                batch.chat_id,
                exc,
            )
            return False

    def _build_batch(self, messages: List[SecretaryBufferedMessage]) -> SecretaryBatch:
        latest = messages[-1]
        parts = [item.text_content.strip() for item in messages if item.text_content.strip()]
        attachments: List[Dict[str, Any]] = []
        for item in messages:
            attachments.extend(item.attachments)

        text_content = "\n".join(parts)
        request_context = dict(latest.request_context)
        request_context.update({
            "source_mode": "secretary",
            "secretary_owner_telegram_id": latest.owner_telegram_id,
            "secretary_source_chat_id": latest.chat_id,
            "secretary_batch_size": len(messages),
            "secretary_batched_message_ids": [
                getattr(item.message, "message_id", None)
                for item in messages
                if getattr(item.message, "message_id", None) is not None
            ],
        })

        return SecretaryBatch(
            owner_telegram_id=latest.owner_telegram_id,
            chat_id=latest.chat_id,
            user=latest.user,
            message=latest.message,
            text_content=text_content,
            attachments=attachments,
            request_context=request_context,
            messages=list(messages),
        )

    @staticmethod
    def _normalize_seconds(value: Optional[float], default: float) -> float:
        if value is None:
            return max(0.0, float(default))
        return max(0.0, float(value))
