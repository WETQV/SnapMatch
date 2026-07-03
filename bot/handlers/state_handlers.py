import asyncio
from collections import deque, defaultdict
from datetime import datetime
from typing import Deque, Dict, Any
from utils.logger import setup_logger

logger = setup_logger(__name__)

class UserState:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.history: Deque[Dict[str, Any]] = deque(maxlen=50)  # История сообщений пользователя
        self.lock = asyncio.Lock()  # Для обеспечения потокобезопасности при обработке запросов
        self.last_active: datetime = datetime.utcnow()  # Время последней активности пользователя
        self.in_queue: bool = False  # Флаг, указывающий, находится ли пользователь в очереди

    def add_message(self, role: str, content: str):
        self.history.append({"role": role, "content": content})
        self.last_active = datetime.utcnow()
        logger.debug(
            "Добавлено сообщение для пользователя %s: %s - [length=%s]",
            self.user_id,
            role,
            len(content or ""),
        )

    def get_history(self):
        return list(self.history)

class UserStateManager:
    def __init__(self):
        self.user_states: Dict[int, UserState] = defaultdict(lambda: None)
        self.lock = asyncio.Lock()

    async def get_state(self, user_id: int) -> UserState:
        async with self.lock:
            if self.user_states[user_id] is None:
                self.user_states[user_id] = UserState(user_id)
                logger.info(f"Создано новое состояние для пользователя {user_id}")
            return self.user_states[user_id]

    async def reset_state(self, user_id: int):
        async with self.lock:
            if user_id in self.user_states:
                self.user_states[user_id] = UserState(user_id)
                logger.info(f"Состояние пользователя {user_id} сброшено")

    async def remove_state(self, user_id: int):
        async with self.lock:
            if user_id in self.user_states:
                del self.user_states[user_id]
                logger.info(f"Состояние пользователя {user_id} удалено")

# Функции для работы с состояниями
state_manager = UserStateManager()

async def get_user_state(user_id: int) -> UserState:
    """Возвращает состояние пользователя по его ID"""
    return await state_manager.get_state(user_id)

async def reset_user_state(user_id: int):
    """Сбрасывает состояние пользователя"""
    await state_manager.reset_state(user_id)
