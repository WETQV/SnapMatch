from typing import Optional

from config.settings import settings_manager
from utils import stats

from .services.secretary_debounce_manager import SecretaryDebounceManager
from .services.secretary_intake import SecretaryIntakeResult, SecretaryIntakeService
from .services.secretary_queue_adapter import enqueue_secretary_batch

_debounce_manager: Optional[SecretaryDebounceManager] = None
_intake_service: Optional[SecretaryIntakeService] = None


def get_secretary_intake_service() -> SecretaryIntakeService:
    global _debounce_manager, _intake_service

    if _intake_service is not None:
        return _intake_service

    secretary_settings = (settings_manager.get_settings().get("secretary_mode") or {})

    async def enqueue_batch(batch):
        from . import queue_manager

        await enqueue_secretary_batch(
            batch,
            request_queue=queue_manager.request_queue,
            message_counter=queue_manager.message_counter,
            increment_pending=stats.stats.increment_pending_requests,
        )

    _debounce_manager = SecretaryDebounceManager(
        enqueue_batch,
        default_delay_seconds=secretary_settings.get("default_delay_seconds", 2.0),
        default_burst_window_seconds=secretary_settings.get("default_burst_window_seconds", 2.0),
        default_max_batch_messages=secretary_settings.get("default_max_batch_messages", 10),
    )
    _intake_service = SecretaryIntakeService(_debounce_manager)
    return _intake_service


async def handle_secretary_message(
    *,
    owner_telegram_id: int,
    message,
    business_connection_id: Optional[str] = None,
) -> SecretaryIntakeResult:
    service = get_secretary_intake_service()
    return await service.handle_message(
        owner_telegram_id=owner_telegram_id,
        message=message,
        business_connection_id=business_connection_id,
    )


async def close_secretary_runtime() -> None:
    global _debounce_manager, _intake_service

    if _debounce_manager is not None:
        await _debounce_manager.close()

    _debounce_manager = None
    _intake_service = None
