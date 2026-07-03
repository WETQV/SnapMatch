from .base_db import BaseDB
from utils.logger import setup_logger
import datetime
import json

logger = setup_logger(__name__)


class UserDB(BaseDB):
    ALLOWED_UPDATE_COLUMNS = {
        'username',
        'first_name',
        'last_name',
        'priority',
        'is_banned',
        'last_activity',
        'preferences',
    }

    def __init__(self):
        super().__init__()

    def get_all_users(self):
        try:
            self.cursor.execute("SELECT * FROM users")
            users = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in users]
        except Exception as e:
            logger.error(f"Ошибка при получении всех пользователей: {e}")
            return []

    def get_user_by_telegram_id(self, telegram_id):
        try:
            self.cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user = self.cursor.fetchone()
            if user:
                return dict(zip([column[0] for column in self.cursor.description], user))
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении пользователя {telegram_id}: {e}")
            return None

    def ensure_user(self, telegram_id, username=None, first_name=None, last_name=None):
        try:
            def operation():
                self.cursor.execute(
                    """
                    INSERT OR IGNORE INTO users (telegram_id, username, first_name, last_name, last_activity)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (telegram_id, username, first_name, last_name, datetime.datetime.now()),
                )
                # INSERT OR IGNORE still opens a write transaction for existing users.
                # Commit immediately so the users connection does not keep the database locked
                # while message writes proceed through a separate connection.
                self.connection.commit()

                inserted = self.cursor.rowcount > 0
                user = self.get_user_by_telegram_id(telegram_id)
                if not user:
                    return None

                updates = {}
                if username is not None and user.get('username') != username:
                    updates['username'] = username
                if first_name is not None and user.get('first_name') != first_name:
                    updates['first_name'] = first_name
                if last_name is not None and user.get('last_name') != last_name:
                    updates['last_name'] = last_name

                if updates:
                    columns = ', '.join(f"{key} = ?" for key in updates.keys())
                    values = list(updates.values()) + [telegram_id]
                    self.cursor.execute(f"UPDATE users SET {columns} WHERE telegram_id = ?", values)

                if inserted or updates:
                    self.connection.commit()
                    user = self.get_user_by_telegram_id(telegram_id)

                return user

            return self._run_write(operation)
        except Exception as e:
            logger.error(f"Ошибка при обеспечении записи пользователя {telegram_id}: {e}")
            return None

    def add_user(self, telegram_id, username=None, first_name=None, last_name=None):
        try:
            def operation():
                self.cursor.execute(
                    """
                    INSERT OR IGNORE INTO users (telegram_id, username, first_name, last_name, last_activity)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (telegram_id, username, first_name, last_name, datetime.datetime.now()),
                )
                self.connection.commit()

            self._run_write(operation)
            logger.info(f"Пользователь {telegram_id} добавлен в базу данных.")
        except Exception as e:
            logger.error(f"Ошибка при добавлении пользователя {telegram_id}: {e}")

    def update_user(self, user_id, **kwargs):
        try:
            safe_kwargs = {
                key: value for key, value in kwargs.items()
                if key in self.ALLOWED_UPDATE_COLUMNS
            }

            if not safe_kwargs:
                logger.warning(
                    f"Попытка обновить пользователя {user_id} с недопустимыми полями: {kwargs.keys()}"
                )
                return

            columns = ', '.join(f"{key} = ?" for key in safe_kwargs.keys())
            values = list(safe_kwargs.values()) + [user_id]
            def operation():
                self.cursor.execute(f"UPDATE users SET {columns} WHERE id = ?", values)
                self.connection.commit()

            self._run_write(operation)
            logger.info(f"Пользователь {user_id} обновлён: {safe_kwargs}")
        except Exception as e:
            logger.error(f"Ошибка при обновлении пользователя {user_id}: {e}")

    def get_user_preferences(self, user_or_id):
        try:
            user = user_or_id
            if not isinstance(user_or_id, dict):
                self.cursor.execute("SELECT preferences FROM users WHERE id = ?", (user_or_id,))
                row = self.cursor.fetchone()
                raw = row[0] if row else ""
            else:
                raw = user.get("preferences") or ""
            if not raw:
                return {}
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error(f"Ошибка чтения preferences пользователя: {e}")
            return {}

    def update_user_preferences(self, user_id: int, **preferences):
        allowed = {"stream_mode", "format_markdown", "format_html"}
        try:
            current = self.get_user_preferences(user_id)
            for key, value in preferences.items():
                if key in allowed:
                    current[key] = bool(value)
            encoded = json.dumps(current, ensure_ascii=False)
            self.update_user(user_id, preferences=encoded)
            return current
        except Exception as e:
            logger.error(f"Ошибка обновления preferences пользователя {user_id}: {e}")
            return {}

    def update_user_activity(self, telegram_id, *, min_interval_seconds: int = 0):
        try:
            def operation():
                if min_interval_seconds > 0:
                    self.cursor.execute("SELECT last_activity FROM users WHERE telegram_id = ?", (telegram_id,))
                    row = self.cursor.fetchone()
                    if row and row[0]:
                        try:
                            last_activity = datetime.datetime.fromisoformat(str(row[0]))
                        except ValueError:
                            last_activity = None
                        if last_activity is not None:
                            elapsed = (datetime.datetime.now() - last_activity).total_seconds()
                            if elapsed < min_interval_seconds:
                                return False

                self.cursor.execute(
                    """
                    UPDATE users SET last_activity = ? WHERE telegram_id = ?
                    """,
                    (datetime.datetime.now(), telegram_id),
                )
                self.connection.commit()
                return self.cursor.rowcount > 0

            return self._run_write(operation)
        except Exception as e:
            logger.error(f"Ошибка при обновлении активности пользователя {telegram_id}: {e}")
            return False

    def count_users(self):
        try:
            self.cursor.execute("SELECT COUNT(*) FROM users")
            count = self.cursor.fetchone()[0]
            return count
        except Exception as e:
            logger.error(f"Ошибка при подсчёте пользователей: {e}")
            return 0

    def get_online_users_count(self, timeout_minutes=2):
        try:
            time_threshold = datetime.datetime.now() - datetime.timedelta(minutes=timeout_minutes)
            self.cursor.execute(
                """
                SELECT COUNT(*) FROM users WHERE last_activity >= ?
                """,
                (time_threshold,),
            )
            count = self.cursor.fetchone()[0]
            return count
        except Exception as e:
            logger.error(f"Ошибка при подсчёте онлайн пользователей: {e}")
            return 0
