# bot/handlers/queue_manager.py
"""
Менеджер очереди запросов - главный оркестратор обработки сообщений.
Координирует работу всех сервисов:
- request_processor: обработка отдельных запросов
- queue_processor: управление очередью
- group_manager: управление групповыми чатами
- model_client_manager: управление клиентами моделей
"""

import asyncio
from typing import Dict, Set

from utils.logger import setup_logger
from .active_tasks_registry import active_tasks
from .services import (
    QueueProcessor,
    GroupManager,
    process_request,
    init_model_clients,
    close_all_clients,
)

logger = setup_logger(__name__)


class AsyncCounter:
    """Потокобезопасный счётчик для asyncio окружения."""
    def __init__(self, initial_value=0):
        self.value = initial_value
        self._lock = None
    
    def _get_lock(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock
    
    async def increment(self):
        """Инкрементирует счётчик и возвращает новое значение."""
        async with self._get_lock():
            self.value += 1
            return self.value

    def reset(self, initial_value=0):
        self.value = initial_value
        self._lock = None
    
    async def get(self):
        """Возвращает текущее значение счётчика."""
        async with self._get_lock():
            return self.value


# Global queue and locks
request_queue = asyncio.PriorityQueue()
user_locks: Dict = {}
message_counter = AsyncCounter(0)

# Initialize managers
group_manager = GroupManager()


def _rebind_runtime_refs():
    try:
        from . import message_handlers

        message_handlers.request_queue = request_queue
        message_handlers.user_locks = user_locks
        message_handlers.message_counter = message_counter
    except Exception as exc:
        logger.debug("Не удалось перевязать runtime refs после reset: %s", exc)


def reset_runtime_state():
    global request_queue

    request_queue = asyncio.PriorityQueue()
    user_locks.clear()
    message_counter.reset(0)
    group_manager.reset()

    from .services.model_client_manager import reset_runtime_state as reset_model_runtime_state

    reset_model_runtime_state()
    _rebind_runtime_refs()


async def process_queue():
    """
    Основной цикл обработки очереди.
    Делегирует работу QueueProcessor сервису.
    """
    processor = QueueProcessor(
        request_queue=request_queue,
        user_locks=user_locks,
        group_manager=group_manager,
        process_request_func=process_request,
    )
    await processor.process_queue()


# Legacy function names for backwards compatibility
async def try_acquire_group_slot(chat_id: int) -> bool:
    """Попытка получить слот группы (backwards compatibility)."""
    return await group_manager.try_acquire_group_slot(chat_id)


async def release_group_slot(chat_id: int):
    """Освободить слот группы (backwards compatibility)."""
    await group_manager.release_group_slot(chat_id)


async def wait_for_active_tasks(timeout: float = 10.0):
    """
    Ожидает завершения всех активных задач обработки запросов.
    
    Args:
        timeout: Максимальное время ожидания в секундах.
    """
    if not active_tasks:
        logger.info("Нет активных задач для ожидания.")
        return

    logger.info(f"Ожидание завершения {len(active_tasks)} активных задач (таймаут {timeout}с)...")
    
    # Создаем задачу ожидания
    done, pending = await asyncio.wait(
        active_tasks, 
        timeout=timeout, 
        return_when=asyncio.ALL_COMPLETED
    )

    if pending:
        logger.warning(f"Таймаут ожидания: {len(pending)} задач будут принудительно отменены.")
        for task in pending:
            task.cancel()
        
        # Даем немного времени на обработку CancelledError
        await asyncio.gather(*pending, return_exceptions=True)
    
    logger.info("Все активные задачи завершены или отменены.")


def get_model_usage_stats():
    """Получить статистику использования моделей."""
    from .services.model_client_manager import (
        model_usage_stats,
        active_models,
    )
    stats_copy = {}
    for model_id, stats in model_usage_stats.items():
        stats_copy[model_id] = stats.copy()
        stats_copy[model_id]["is_idle"] = stats.get("active_requests", 0) == 0
        stats_copy[model_id]["is_active"] = model_id in active_models
    
    return stats_copy


def reload_models():
    """Перезагружает список моделей."""
    from .services.model_client_manager import active_models
    
    init_model_clients()
    
    from config.settings import settings_manager
    settings = settings_manager.get_settings()
    logger.info(f"Обновленная стратегия балансировки: {settings.get('load_balancing_strategy', 'round_robin')}")
    logger.info(f"Обновленные активные модели: {active_models}")
    
    return {
        "status": "success",
        "active_models": active_models,
        "models_count": len(active_models)
    }


def get_available_placeholders():
    """Возвращает список доступных плейсхолдеров."""
    from .services.prompt_manager import get_available_placeholders
    return get_available_placeholders()


def validate_system_prompt(prompt: str):
    """Проверяет системный промпт на потенциальные проблемы."""
    from .services.prompt_manager import validate_system_prompt
    return validate_system_prompt(prompt)


# Re-export frequently used items for backward compatibility
from .services import (
    prepare_model_messages,
    clean_response,
    clean_hidden_characters,
    ensure_alternating_roles,
    adjust_history_for_context_limit,
    trim_messages_to_context_limit,
    build_image_data_url,
    prepare_system_prompt,
)
from .services.model_client_manager import (
    get_model_stats_lock,
    model_usage_stats,
    model_clients,
    active_models,
    model_capabilities,
    get_response_from_model,
    select_model_for_request,
    close_all_clients,
)

__all__ = [
    # Queue management
    'request_queue',
    'user_locks',
    'message_counter',
    'process_queue',
    'reset_runtime_state',
    'group_manager',
    # Group functions
    'try_acquire_group_slot',
    'release_group_slot',
    # Model functions
    'get_model_usage_stats',
    'reload_models',
    'init_model_clients',
    'get_response_from_model',
    'select_model_for_request',
    # Prompt functions
    'get_available_placeholders',
    'validate_system_prompt',
    'prepare_system_prompt',
    # Message processing
    'prepare_model_messages',
    'clean_response',
    'clean_hidden_characters',
    'ensure_alternating_roles',
    'adjust_history_for_context_limit',
    'trim_messages_to_context_limit',
    'build_image_data_url',
    # Cleanup
    'close_all_clients',
    # Global state
    'get_model_stats_lock',
    'model_usage_stats',
    'model_clients',
    'active_models',
    'model_capabilities',
]
