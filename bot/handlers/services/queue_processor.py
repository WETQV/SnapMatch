# bot/handlers/services/queue_processor.py
"""
Сервис для обработки очереди запросов.
Содержит основную логику process_queue.
"""

import asyncio
import time
from typing import Callable, Dict

from config.settings import settings_manager
from utils import stats
from utils.logger import setup_logger
from .model_client_manager import (
    init_model_clients,
    select_model_for_request,
    get_model_stats_lock,
    model_usage_stats,
    active_models,
    has_active_vlm_model,
)
from ..active_tasks_registry import active_tasks
from .telegram_utils import send_ephemeral_reply
from .secretary_queue_policy import suppress_model_unavailable_notice

logger = setup_logger(__name__)

# Constants
QUEUE_NOTICE_THRESHOLD = 60  # секунд

MAX_MODEL_RETRY_COUNT = 8
MAX_MODEL_QUEUE_AGE_SECONDS = 180


class QueueProcessor:
    """Обрабатывает очередь запросов."""
    
    def __init__(
        self,
        request_queue: asyncio.PriorityQueue,
        user_locks: Dict,
        group_manager,
        process_request_func: Callable,
    ):
        """
        Инициализирует обработчик очереди.
        
        Args:
            request_queue: Очередь запросов
            user_locks: Словарь блокировок пользователя
            group_manager: Менеджер групп
            process_request_func: Функция для обработки одного запроса
        """
        self.request_queue = request_queue
        self.user_locks = user_locks
        self.group_manager = group_manager
        self.process_request_func = process_request_func
    
    async def process_queue(self):
        """Основной цикл обработки очереди запросов."""
        # Инициализируем клиенты моделей
        init_model_clients()
        
        # Логируем настройки
        settings = settings_manager.get_settings()
        logger.info(f"Стратегия балансировки: {settings.get('load_balancing_strategy', 'round_robin')}")
        logger.info(f"Активные модели: {active_models}")
        
        # Основной цикл обработки запросов
        while True:
            try:
                group_slot_acquired = False
                chat_id = None
                sequential_group = False
                queue_item_acquired = False
                task_done_called = False
                request_delegated = False
                request_requeued = False
                current_user_id = None
                
                if not self.request_queue.empty():
                    # Get next request from queue
                    priority, counter, message, user, enqueue_time, payload = await self.request_queue.get()
                    queue_item_acquired = True
                    current_user_id = user.get('id') if isinstance(user, dict) else None
                    user_priority = payload.get('user_priority') if isinstance(payload, dict) else None

                    chat = message.chat
                    chat_id = chat.id
                    chat_type = chat.type
                    chat_title = getattr(chat, 'title', None)
                    if chat_type == 'private':
                        chat_title = chat_title or (message.from_user.full_name or message.from_user.username)

                    current_settings = settings_manager.get_settings()
                    group_parallel_mode = current_settings.get('group_parallel_mode', False)
                    sequential_group = chat_type in {'group', 'supergroup'} and not group_parallel_mode

                    wait_time = time.time() - enqueue_time

                    # Try to acquire group slot if sequential mode
                    if sequential_group:
                        if not await self.group_manager.try_acquire_group_slot(chat_id):
                            # Put request back in queue with exponential backoff
                            retry_count = payload.get('retry_count', 0) if isinstance(payload, dict) else 0
                            delay = min(0.2 * (1.5 ** retry_count), 2.0)

                            if isinstance(payload, dict) and wait_time > QUEUE_NOTICE_THRESHOLD and not payload.get('queue_notice_sent'):
                                await send_ephemeral_reply(
                                    message,
                                    "Запрос принят и ожидает своей очереди. Я вернусь с ответом чуть позже 🕐",
                                )
                                payload['queue_notice_sent'] = True
                            
                            payload = payload.copy() if isinstance(payload, dict) else payload
                            if isinstance(payload, dict):
                                payload['retry_count'] = retry_count + 1
                            
                            await self.request_queue.put((priority, counter, message, user, enqueue_time, payload))
                            request_requeued = True
                            logger.debug(
                                "Чат %s в последовательном режиме (user_priority=%s): предыдущий ответ еще формируется, "
                                "запрос возвращен в очередь (ожидание: %.1f сек, задержка: %.2f сек)",
                                chat_id, user_priority, wait_time, delay
                            )
                            self.request_queue.task_done()
                            task_done_called = True
                            await asyncio.sleep(delay)
                            continue
                        group_slot_acquired = True

                    # Check if request requires VLM.
                    # Не отклоняем запросы только из-за отсутствия VLM: деградируем до text-only.
                    requires_vision = False
                    attachments = None
                    if isinstance(payload, dict):
                        attachments = payload.get('attachments') or []
                        if 'requires_vision' in payload:
                            requires_vision = bool(payload.get('requires_vision'))
                        else:
                            # Defensive: если флаг не проставлен, считаем по наличию вложений.
                            requires_vision = bool(attachments)

                    if requires_vision and not has_active_vlm_model(sync_if_needed=True):
                        logger.info(
                            "VLM недоступен в рантайме (chat_id=%s). Деградируем запрос до text-only.",
                            chat_id,
                        )
                        requires_vision = False
                        if isinstance(payload, dict):
                            payload = payload.copy()
                            payload['requires_vision'] = False
                    
                    # Select model according to load balancing strategy
                    model_id = select_model_for_request(requires_vision=requires_vision)

                    if not model_id:
                        # No model available - put request back with exponential backoff
                        model_retry_count = payload.get('model_retry_count', 0) if isinstance(payload, dict) else 0
                        delay = min(0.5 * (1.5 ** model_retry_count), 3.0)
                        retry_exhausted = (
                            model_retry_count >= MAX_MODEL_RETRY_COUNT
                            or wait_time >= MAX_MODEL_QUEUE_AGE_SECONDS
                        )

                        suppress_notice = suppress_model_unavailable_notice(payload)
                        if (
                            isinstance(payload, dict)
                            and wait_time > QUEUE_NOTICE_THRESHOLD
                            and not payload.get('queue_notice_sent')
                            and not suppress_notice
                        ):
                            await send_ephemeral_reply(
                                message,
                                "Все модели заняты. Я сохраню ваш запрос и отвечу, как только освобожусь.",
                            )
                            payload['queue_notice_sent'] = True
                        
                        if retry_exhausted:
                            logger.warning(
                                "No model available for too long; dropping request (user_priority=%s, wait_time=%.1f, retries=%s)",
                                user_priority,
                                wait_time,
                                model_retry_count,
                            )
                            if suppress_notice:
                                logger.warning(
                                    "Secretary request dropped without user-facing model notice "
                                    "(user_priority=%s, wait_time=%.1f, retries=%s)",
                                    user_priority,
                                    wait_time,
                                    model_retry_count,
                                )
                            else:
                                await send_ephemeral_reply(
                                    message,
                                    "Сейчас нет доступных моделей. Попробуйте отправить запрос чуть позже.",
                                )
                            if current_user_id is not None:
                                self.user_locks[current_user_id] = False
                            if group_slot_acquired and chat_id is not None:
                                await self.group_manager.release_group_slot(chat_id)
                            self.request_queue.task_done()
                            task_done_called = True
                            stats.stats.decrement_pending_requests()
                            continue

                        logger.debug(
                            "Подходящая модель не найдена (user_priority=%s), возвращаем запрос в очередь "
                            "(ожидание: %.1f сек, задержка: %.2f сек)",
                            user_priority, wait_time, delay
                        )
                        
                        payload = payload.copy() if isinstance(payload, dict) else payload
                        if isinstance(payload, dict):
                            payload['model_retry_count'] = model_retry_count + 1
                            payload['retry_count'] = payload.get('retry_count', 0) + 1
                        
                        await self.request_queue.put((priority, counter, message, user, enqueue_time, payload))
                        request_requeued = True
                        if group_slot_acquired and chat_id is not None:
                            await self.group_manager.release_group_slot(chat_id)
                        self.request_queue.task_done()
                        task_done_called = True
                        await asyncio.sleep(delay)
                        continue

                    # Model is selected and has capacity - log and create task
                    async with get_model_stats_lock():
                        active_count = model_usage_stats.get(model_id, {}).get("active_requests", 0)
                        total_requests = model_usage_stats.get(model_id, {}).get("requests", 0)

                        max_concurrent = 1
                        for model in current_settings.get('models', []):
                            if model.get('id') == model_id:
                                max_concurrent = model.get('max_concurrent_requests', 1)
                                break

                        logger.info(
                            "Выбрана модель %s для запроса. Активных запросов: %s/%s, всего запросов: %s, user_priority=%s",
                            model_id,
                            active_count,
                            max_concurrent,
                            total_requests,
                            user_priority,
                        )

                    # Create task to process this request
                    task = asyncio.create_task(
                        self.process_request_func(
                            priority,
                            counter,
                            message,
                            user,
                            enqueue_time,
                            model_id,
                            chat_id,
                            chat_type,
                            chat_title,
                            sequential_group,
                            payload,
                            self.user_locks,
                            self.group_manager.release_group_slot,
                        )
                    )
                    # Add to active tasks registry and ensure removal on completion
                    active_tasks.add(task)
                    task.add_done_callback(active_tasks.discard)
                    request_delegated = True
                    
                    self.request_queue.task_done()
                    task_done_called = True
                else:
                    # Queue is empty - sleep briefly
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Ошибка в обработчике очереди: {e}")
                if sequential_group and group_slot_acquired and chat_id is not None:
                    await self.group_manager.release_group_slot(chat_id)
                if (
                    queue_item_acquired
                    and current_user_id is not None
                    and not request_delegated
                    and not request_requeued
                ):
                    self.user_locks[current_user_id] = False
                if queue_item_acquired and not task_done_called:
                    try:
                        self.request_queue.task_done()
                    except Exception:
                        pass
                if queue_item_acquired and not request_requeued:
                    stats.stats.decrement_pending_requests()
                await asyncio.sleep(1)  # Pause on error

