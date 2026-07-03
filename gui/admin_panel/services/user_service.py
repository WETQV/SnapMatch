from typing import Callable, Dict, List, Optional, Tuple

from utils.database.database_manager import DatabaseManager
from utils.logger import setup_logger

logger = setup_logger(__name__)


def filter_group_history_messages(messages: List[Dict], *, addressed_only: bool) -> List[Dict]:
    if not addressed_only:
        return list(messages)

    return [
        msg for msg in messages
        if msg.get('role') == 'assistant'
        or msg.get('is_summary')
        or (msg.get('role') == 'user' and msg.get('is_addressed'))
    ]


class UserService:
    """Сервис управления пользователями и чатами."""

    def __init__(self):
        self.db = None

    def _with_db(self, func: Callable[[DatabaseManager], object], default):
        db = DatabaseManager()
        try:
            return func(db)
        except Exception as e:
            logger.error(f"Ошибка при работе с UserService: {e}")
            return default
        finally:
            db.close()

    def get_all_users(self) -> List[Dict]:
        return self._with_db(lambda db: db.users.get_all_users(), [])

    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[Dict]:
        return self._with_db(lambda db: db.users.get_user_by_telegram_id(telegram_id), None)

    def get_group_chats(self) -> List[Dict]:
        return self._with_db(lambda db: db.messages.get_group_chats(), [])

    def get_user_history(self, telegram_id: int, limit: int = 500) -> List[Dict]:
        def operation(db: DatabaseManager):
            user = db.users.get_user_by_telegram_id(telegram_id)
            if not user:
                return []

            return db.messages.get_user_messages_active(
                user['id'],
                limit=limit,
                chat_type='private',
                chat_id=telegram_id,
            )

        return self._with_db(operation, [])

    def get_secretary_history(self, owner_telegram_id: int, limit: int = 500) -> List[Dict]:
        return self._with_db(
            lambda db: db.messages.get_secretary_owner_messages_active(owner_telegram_id, limit=limit),
            [],
        )

    def get_group_history(self, chat_id: int, limit: int = 500, addressed_only: bool = False) -> List[Dict]:
        def operation(db: DatabaseManager):
            messages = db.messages.get_chat_messages_active(chat_id, limit=limit)
            return filter_group_history_messages(messages, addressed_only=addressed_only)

        return self._with_db(operation, [])

    def change_user_priority(self, user_id: int, new_priority: int) -> Tuple[bool, str]:
        def operation(db: DatabaseManager):
            db.users.update_user(user_id, priority=new_priority)
            logger.info(f"Приоритет пользователя {user_id} изменён на {new_priority}")
            return True, "Приоритет обновлён"

        return self._with_db(operation, (False, "Не удалось обновить приоритет"))

    def toggle_user_ban(self, user: Dict) -> Tuple[bool, str]:
        def operation(db: DatabaseManager):
            new_status = not user['is_banned']
            db.users.update_user(user['id'], is_banned=new_status)
            status_text = "забанен" if new_status else "разбанен"
            logger.info(f"Пользователь {user.get('id')} {status_text}")
            return True, status_text

        return self._with_db(operation, (False, "Не удалось изменить бан пользователя"))

    def toggle_group_ban(self, chat: Dict) -> Tuple[bool, str]:
        def operation(db: DatabaseManager):
            new_status = not chat['is_banned']
            db.messages.update_chat(chat['chat_id'], is_banned=new_status)
            status_text = "забанена" if new_status else "разбанена"
            logger.info(f"Группа {chat.get('chat_id')} {status_text}")
            return True, status_text

        return self._with_db(operation, (False, "Не удалось изменить бан группы"))

    def count_total_users(self) -> int:
        return self._with_db(lambda db: db.users.count_users(), 0)

    def count_online_users(self) -> int:
        return self._with_db(lambda db: db.users.get_online_users_count(), 0)
