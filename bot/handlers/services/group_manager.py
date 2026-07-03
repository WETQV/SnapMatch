# bot/handlers/services/group_manager.py
"""
Сервис для управления обработкой групповых чатов.
Обеспечивает последовательную или параллельную обработку сообщений.
"""

import asyncio
from typing import Dict

from utils.logger import setup_logger

logger = setup_logger(__name__)


class GroupManager:
    """Управляет обработкой сообщений в групповых чатах."""
    
    def __init__(self):
        """Инициализирует менеджер групп."""
        self._group_state_lock = None
        self.group_active_requests: Dict[int, int] = {}
    
    def _get_lock(self) -> asyncio.Lock:
        """Возвращает Lock, создавая его при необходимости в текущем event loop."""
        if self._group_state_lock is None:
            self._group_state_lock = asyncio.Lock()
        return self._group_state_lock

    def reset(self):
        self._group_state_lock = None
        self.group_active_requests.clear()
    
    async def try_acquire_group_slot(self, chat_id: int) -> bool:
        """
        Пытается заняться слотом для группы (последовательная обработка).
        
        Args:
            chat_id: ID группы
            
        Returns:
            True если слот получен, False если группа уже обрабатывает запрос
        """
        async with self._get_lock():
            active = self.group_active_requests.get(chat_id, 0)
            if active > 0:
                return False
            self.group_active_requests[chat_id] = active + 1
            logger.debug("Групповой чат %s заблокирован для последовательной обработки", chat_id)
            return True

    async def release_group_slot(self, chat_id: int):
        """
        Освобождает слот группы.
        
        Args:
            chat_id: ID группы
        """
        async with self._get_lock():
            active = self.group_active_requests.get(chat_id, 0)
            if active <= 1:
                self.group_active_requests.pop(chat_id, None)
                logger.debug("Групповой чат %s разблокирован (активных=0)", chat_id)
            else:
                self.group_active_requests[chat_id] = active - 1
                logger.debug("Групповой чат %s разблокирован (активных=%s)", chat_id, self.group_active_requests.get(chat_id, 0))
    
    def get_status(self, chat_id: int) -> Dict:
        """
        Получает статус группы.
        
        Args:
            chat_id: ID группы
            
        Returns:
            Словарь со статусом
        """
        active = self.group_active_requests.get(chat_id, 0)
        return {
            'chat_id': chat_id,
            'active_requests': active,
            'is_idle': active == 0
        }

