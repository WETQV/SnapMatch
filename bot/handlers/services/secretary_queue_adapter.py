import time
from typing import Any, Awaitable, Callable, Dict, Optional

from utils.logger import setup_logger

from .secretary_debounce_manager import SecretaryBatch

logger = setup_logger(__name__)


async def enqueue_secretary_batch(
    batch: SecretaryBatch,
    *,
    request_queue: Any,
    message_counter: Any,
    increment_pending: Optional[Callable[[], Any]] = None,
) -> Dict:
    """Put one debounced secretary batch into the shared request queue."""

    user = dict(batch.user or {})
    user_priority = int(user.get("priority") or 0)
    queue_priority = -user_priority
    counter = await message_counter.increment()
    enqueue_time = time.time()

    request_context = dict(batch.request_context or {})
    request_context.update({
        "source_mode": "secretary",
        "secretary_owner_telegram_id": batch.owner_telegram_id,
        "secretary_source_chat_id": batch.chat_id,
    })

    payload = {
        "attachments": list(batch.attachments or []),
        "requires_vision": bool(batch.attachments),
        "retry_count": 0,
        "user_priority": user_priority,
        "text_content": batch.text_content,
        "source_mode": "secretary",
        "request_context": request_context,
        "secretary": {
            "owner_telegram_id": batch.owner_telegram_id,
            "business_connection_id": request_context.get("business_connection_id"),
            "session_id": request_context.get("secretary_session_id"),
            "response_mode": request_context.get("secretary_response_mode", "draft"),
            "system_prompt": request_context.get("secretary_system_prompt", ""),
            "save_history": bool(request_context.get("secretary_save_history", True)),
            "close_after_reply": bool(request_context.get("secretary_close_after_reply", False)),
            "turn_based_replies": bool(request_context.get("secretary_turn_based_replies", True)),
        },
    }

    await request_queue.put((queue_priority, counter, batch.message, user, enqueue_time, payload))
    if increment_pending is not None:
        result = increment_pending()
        if hasattr(result, "__await__"):
            await result

    logger.debug(
        "Secretary batch enqueued: owner=%s chat=%s user_priority=%s messages=%s",
        batch.owner_telegram_id,
        batch.chat_id,
        user_priority,
        len(batch.messages),
    )

    return {
        "queue_priority": queue_priority,
        "counter": counter,
        "enqueue_time": enqueue_time,
        "payload": payload,
    }
