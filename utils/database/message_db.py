from pathlib import Path
from typing import Dict, List, Optional

from .base_db import BaseDB
from utils.logger import setup_logger

logger = setup_logger(__name__)


class MessageDB(BaseDB):
    def __init__(self):
        super().__init__()

    def get_user_messages(self, user_id, limit=100):
        try:
            self.cursor.execute("SELECT * FROM messages WHERE user_id = ? ORDER BY timestamp ASC LIMIT ?", (user_id, limit))
            messages = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in messages]
        except Exception as e:
            logger.error(f"Ошибка при получении сообщений пользователя {user_id}: {e}")
            return []

    def get_user_messages_by_telegram_id(self, telegram_id, limit=100):
        try:
            self.cursor.execute(
                """
                SELECT messages.* FROM messages
                JOIN users ON messages.user_id = users.id
                WHERE users.telegram_id = ?
                ORDER BY messages.timestamp ASC
                LIMIT ?
                """,
                (telegram_id, limit),
            )
            messages = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in messages]
        except Exception as e:
            logger.error(f"Ошибка при получении сообщений пользователя с telegram_id {telegram_id}: {e}")
            return []

    def get_chat_messages(self, chat_id: int, limit: int = 200) -> List[Dict]:
        try:
            self.cursor.execute(
                """
                SELECT * FROM messages
                WHERE chat_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (chat_id, limit),
            )
            messages = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in messages]
        except Exception as e:
            logger.error(f"Ошибка при получении сообщений чата {chat_id}: {e}")
            return []

    def get_recent_chat_messages(self, chat_id: int, limit: int = 40) -> List[Dict]:
        try:
            self.cursor.execute(
                """
                SELECT * FROM messages
                WHERE chat_id = ? AND is_archived = 0
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (chat_id, limit),
            )
            messages = self.cursor.fetchall()
            rows = [dict(zip([column[0] for column in self.cursor.description], row)) for row in messages]
            return list(reversed(rows))
        except Exception as e:
            logger.error(f"Ошибка при получении последних сообщений чата {chat_id}: {e}")
            return []

    def get_group_chats(self, limit: int = 50) -> List[Dict]:
        try:
            self.cursor.execute(
                """
                SELECT
                    g.chat_id,
                    COALESCE(g.chat_title, MAX(m.chat_title), '') AS chat_title,
                    g.chat_type,
                    MAX(m.timestamp) AS last_timestamp,
                    COUNT(m.id) AS messages_count,
                    g.is_banned
                FROM group_chats g
                LEFT JOIN messages m ON g.chat_id = m.chat_id
                WHERE g.chat_type IN ('group', 'supergroup')
                  AND NOT (
                      g.chat_type = 'group'
                      AND NOT EXISTS (
                          SELECT 1 FROM messages old_messages
                          WHERE old_messages.chat_id = g.chat_id
                      )
                      AND EXISTS (
                          SELECT 1 FROM group_chats migrated
                          WHERE migrated.chat_type = 'supergroup'
                            AND migrated.chat_title = g.chat_title
                            AND COALESCE(g.chat_title, '') <> ''
                      )
                  )
                GROUP BY g.chat_id
                ORDER BY last_timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
            chats = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in chats]
        except Exception as e:
            logger.error(f"Ошибка при получении списка групповых чатов: {e}")
            return []

    def add_message(
        self,
        user_id,
        role,
        content,
        *,
        chat_id: Optional[int] = None,
        chat_type: Optional[str] = None,
        chat_title: Optional[str] = None,
        author_telegram_id: Optional[int] = None,
        author_username: Optional[str] = None,
        author_full_name: Optional[str] = None,
        telegram_message_id: Optional[int] = None,
        reply_to_message_id: Optional[int] = None,
        is_deleted: int = 0,
        edited_at: Optional[str] = None,
        is_summary: int = 0,
        summary_source_ids: Optional[str] = None,
        content_type: str = 'text',
        image_path: Optional[str] = None,
        image_mime: Optional[str] = None,
        telegram_file_id: Optional[str] = None,
        is_addressed: int = 0,
        author_is_bot: int = 0,
        source_mode: str = 'normal',
        secretary_owner_telegram_id: Optional[int] = None,
        secretary_source_chat_id: Optional[int] = None,
        secretary_counterparty_id: Optional[int] = None,
        secretary_session_id: Optional[int] = None,
        secretary_reply_status: Optional[str] = None,
    ):
        try:
            def operation():
                self.cursor.execute(
                    """
                    INSERT INTO messages (
                        user_id,
                        role,
                        content,
                        content_type,
                        image_path,
                        image_mime,
                        telegram_file_id,
                        chat_id,
                        chat_type,
                        chat_title,
                        author_telegram_id,
                        author_username,
                        author_full_name,
                        telegram_message_id,
                        reply_to_message_id,
                        is_deleted,
                        edited_at,
                        is_archived,
                        is_summary,
                        summary_source_ids,
                        is_addressed,
                        author_is_bot,
                        source_mode,
                        secretary_owner_telegram_id,
                        secretary_source_chat_id,
                        secretary_counterparty_id,
                        secretary_session_id,
                        secretary_reply_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        role,
                        content,
                        content_type,
                        image_path,
                        image_mime,
                        telegram_file_id,
                        chat_id,
                        chat_type,
                        chat_title,
                        author_telegram_id,
                        author_username,
                        author_full_name,
                        telegram_message_id,
                        reply_to_message_id,
                        is_deleted,
                        edited_at,
                        0,
                        is_summary,
                        summary_source_ids,
                        is_addressed,
                        author_is_bot,
                        source_mode,
                        secretary_owner_telegram_id,
                        secretary_source_chat_id,
                        secretary_counterparty_id,
                        secretary_session_id,
                        secretary_reply_status,
                    ),
                )
                self.connection.commit()

            self._run_write(operation)
            logger.info(
                "Сообщение от пользователя %s добавлено (chat_id=%s, role=%s, is_summary=%s).",
                user_id,
                chat_id,
                role,
                is_summary,
            )
        except Exception as e:
            logger.error(f"Ошибка при добавлении сообщения пользователя {user_id}: {e}")

    def add_messages_batch(self, messages: List[Dict]) -> int:
        if not messages:
            return 0

        rows = []
        for message in messages:
            rows.append(
                (
                    message['user_id'],
                    message['role'],
                    message['content'],
                    message.get('content_type', 'text'),
                    message.get('image_path'),
                    message.get('image_mime'),
                    message.get('telegram_file_id'),
                    message.get('chat_id'),
                    message.get('chat_type'),
                    message.get('chat_title'),
                    message.get('author_telegram_id'),
                    message.get('author_username'),
                    message.get('author_full_name'),
                    message.get('telegram_message_id'),
                    message.get('reply_to_message_id'),
                    message.get('is_deleted', 0),
                    message.get('edited_at'),
                    message.get('is_archived', 0),
                    message.get('is_summary', 0),
                    message.get('summary_source_ids'),
                    message.get('is_addressed', 0),
                    message.get('author_is_bot', 0),
                    message.get('source_mode', 'normal'),
                    message.get('secretary_owner_telegram_id'),
                    message.get('secretary_source_chat_id'),
                    message.get('secretary_counterparty_id'),
                    message.get('secretary_reply_status'),
                )
            )

        try:
            def operation():
                self.cursor.executemany(
                    """
                    INSERT INTO messages (
                        user_id,
                        role,
                        content,
                        content_type,
                        image_path,
                        image_mime,
                        telegram_file_id,
                        chat_id,
                        chat_type,
                        chat_title,
                        author_telegram_id,
                        author_username,
                        author_full_name,
                        telegram_message_id,
                        reply_to_message_id,
                        is_deleted,
                        edited_at,
                        is_archived,
                        is_summary,
                        summary_source_ids,
                        is_addressed,
                        author_is_bot,
                        source_mode,
                        secretary_owner_telegram_id,
                        secretary_source_chat_id,
                        secretary_counterparty_id,
                        secretary_reply_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                self.connection.commit()

            self._run_write(operation)
            logger.info("Пакетно добавлено %s сообщений.", len(rows))
            return len(rows)
        except Exception as e:
            logger.error(f"Ошибка при пакетном добавлении сообщений: {e}")
            return 0

    def has_secretary_assistant_reply(
        self,
        owner_telegram_id: int,
        chat_id: int,
        reply_to_message_id: int,
    ) -> bool:
        try:
            self.cursor.execute(
                """
                SELECT 1 FROM messages
                WHERE source_mode = 'secretary'
                  AND role = 'assistant'
                  AND secretary_owner_telegram_id = ?
                  AND secretary_source_chat_id = ?
                  AND reply_to_message_id = ?
                  AND is_deleted = 0
                LIMIT 1
                """,
                (owner_telegram_id, chat_id, reply_to_message_id),
            )
            return self.cursor.fetchone() is not None
        except Exception as e:
            logger.error("Ошибка проверки дубля secretary-ответа: %s", e)
            return False

    def delete_messages_by_user_id(self, user_id) -> int:
        try:
            def operation():
                self.cursor.execute("SELECT image_path FROM messages WHERE user_id = ?", (user_id,))
                image_rows = self.cursor.fetchall()
                self.cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
                deleted_rows = self.cursor.rowcount
                self.connection.commit()
                return image_rows, deleted_rows

            image_rows, deleted_rows = self._run_write(operation)
            logger.info(f"Сообщения пользователя {user_id} были удалены ({deleted_rows}).")
            for (image_path,) in image_rows:
                if image_path:
                    try:
                        Path(image_path).unlink(missing_ok=True)
                    except Exception as exc:
                        logger.warning(f"Не удалось удалить файл изображения {image_path}: {exc}")
            return deleted_rows
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщений пользователя {user_id}: {e}")
            return 0

    def delete_messages_by_chat_and_user(self, chat_id: int, user_id: int) -> int:
        try:
            def operation():
                self.cursor.execute("SELECT image_path FROM messages WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
                image_rows = self.cursor.fetchall()
                self.cursor.execute("DELETE FROM messages WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
                deleted_rows = self.cursor.rowcount
                self.connection.commit()
                return image_rows, deleted_rows

            image_rows, deleted_rows = self._run_write(operation)
            logger.info("Удалено %s сообщений пользователя %s в чате %s", deleted_rows, user_id, chat_id)
            for (image_path,) in image_rows:
                if image_path:
                    try:
                        Path(image_path).unlink(missing_ok=True)
                    except Exception as exc:
                        logger.warning("Не удалось удалить файл изображения %s при очистке чата %s: %s", image_path, chat_id, exc)
            return deleted_rows
        except Exception as e:
            logger.error("Ошибка при удалении сообщений пользователя %s в чате %s: %s", user_id, chat_id, e)
            return 0

    def delete_messages_by_chat_id(self, chat_id: int) -> int:
        try:
            def operation():
                self.cursor.execute("SELECT image_path FROM messages WHERE chat_id = ?", (chat_id,))
                image_rows = self.cursor.fetchall()
                self.cursor.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
                deleted_rows = self.cursor.rowcount
                self.connection.commit()
                return image_rows, deleted_rows

            image_rows, deleted_rows = self._run_write(operation)
            logger.info(f"Удалено {deleted_rows} сообщений чата {chat_id}.")
            for (image_path,) in image_rows:
                if image_path:
                    try:
                        Path(image_path).unlink(missing_ok=True)
                    except Exception as exc:
                        logger.warning(f"Не удалось удалить файл изображения {image_path}: {exc}")
            return deleted_rows
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщений чата {chat_id}: {e}")
            return 0

    def delete_group_conversation(self, chat_id: int) -> int:
        try:
            def operation():
                self.cursor.execute(
                    """
                    SELECT image_path FROM messages
                    WHERE chat_id = ? AND (role = 'assistant' OR is_addressed = 1)
                    """,
                    (chat_id,),
                )
                image_rows = self.cursor.fetchall()
                self.cursor.execute(
                    """
                    DELETE FROM messages
                    WHERE chat_id = ? AND (role = 'assistant' OR is_addressed = 1)
                    """,
                    (chat_id,),
                )
                deleted_rows = self.cursor.rowcount
                self.connection.commit()
                return image_rows, deleted_rows

            image_rows, deleted_rows = self._run_write(operation)
            logger.info(f"Удалено {deleted_rows} адресованных сообщений в чате {chat_id}.")
            for (image_path,) in image_rows:
                if image_path:
                    try:
                        Path(image_path).unlink(missing_ok=True)
                    except Exception as exc:
                        logger.warning(f"Не удалось удалить файл изображения {image_path}: {exc}")
            return deleted_rows
        except Exception as e:
            logger.error(f"Ошибка при частичной очистке истории чата {chat_id}: {e}")
            return 0

    def delete_secretary_context(self, owner_telegram_id: int, chat_id: Optional[int] = None) -> int:
        try:
            where = "source_mode = 'secretary' AND secretary_owner_telegram_id = ?"
            params = [owner_telegram_id]
            if chat_id is not None:
                where += " AND (secretary_source_chat_id = ? OR chat_id = ?)"
                params.extend([chat_id, chat_id])

            def operation():
                self.cursor.execute(
                    f"SELECT image_path FROM messages WHERE {where}",
                    tuple(params),
                )
                image_rows = self.cursor.fetchall()
                self.cursor.execute(
                    f"DELETE FROM messages WHERE {where}",
                    tuple(params),
                )
                deleted_rows = self.cursor.rowcount
                self.connection.commit()
                return image_rows, deleted_rows

            image_rows, deleted_rows = self._run_write(operation)
            logger.info(
                "Удалено %s secretary-сообщений владельца %s%s.",
                deleted_rows,
                owner_telegram_id,
                f" в чате {chat_id}" if chat_id is not None else "",
            )
            for (image_path,) in image_rows:
                if image_path:
                    try:
                        Path(image_path).unlink(missing_ok=True)
                    except Exception as exc:
                        logger.warning("Не удалось удалить файл изображения %s при очистке secretary context: %s", image_path, exc)
            return deleted_rows
        except Exception as e:
            logger.error(f"Ошибка при очистке secretary context владельца {owner_telegram_id}: {e}")
            return 0

    def delete_messages_older_than(self, user_id, message_id):
        try:
            def operation():
                self.cursor.execute("DELETE FROM messages WHERE user_id = ? AND id < ?", (user_id, message_id))
                deleted_rows = self.cursor.rowcount
                self.connection.commit()
                return deleted_rows

            deleted_rows = self._run_write(operation)
            logger.info(f"Удалено {deleted_rows} старых сообщений пользователя {user_id} (ID < {message_id}).")
            return deleted_rows
        except Exception as e:
            logger.error(f"Ошибка при удалении старых сообщений пользователя {user_id}: {e}")
            return 0

    def get_message_by_telegram_id(self, telegram_message_id: int, chat_id: int) -> Optional[Dict]:
        try:
            self.cursor.execute(
                "SELECT * FROM messages WHERE telegram_message_id = ? AND chat_id = ? LIMIT 1",
                (telegram_message_id, chat_id),
            )
            row = self.cursor.fetchone()
            if row:
                return dict(zip([column[0] for column in self.cursor.description], row))
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении сообщения telegram_id={telegram_message_id}: {e}")
            return None

    def update_message_image(
        self,
        telegram_message_id: int,
        chat_id: int,
        image_path: str,
        image_mime: Optional[str],
        telegram_file_id: Optional[str] = None,
    ) -> bool:
        try:
            def operation():
                self.cursor.execute(
                    """
                    UPDATE messages
                    SET image_path = ?, image_mime = ?, telegram_file_id = COALESCE(?, telegram_file_id), content_type = COALESCE(content_type, 'image')
                    WHERE telegram_message_id = ? AND chat_id = ?
                    """,
                    (image_path, image_mime, telegram_file_id, telegram_message_id, chat_id),
                )
                self.connection.commit()
                return self.cursor.rowcount > 0

            updated = self._run_write(operation)
            if updated:
                logger.info(f"Обновлена информация об изображении для сообщения telegram_id={telegram_message_id}")
            return updated
        except Exception as e:
            logger.error(f"Ошибка при обновлении изображения сообщения telegram_id={telegram_message_id}: {e}")
            return False

    def mark_message_as_deleted(self, telegram_message_id: int, chat_id: int) -> bool:
        try:
            def operation():
                self.cursor.execute(
                    """
                    UPDATE messages
                    SET is_deleted = 1, edited_at = CURRENT_TIMESTAMP
                    WHERE telegram_message_id = ? AND chat_id = ?
                    """,
                    (telegram_message_id, chat_id),
                )
                self.connection.commit()
                return self.cursor.rowcount > 0

            updated = self._run_write(operation)
            if updated:
                logger.info(f"Сообщение telegram_id={telegram_message_id} отмечено как удалённое")
            return updated
        except Exception as e:
            logger.error(f"Ошибка при отметке сообщения как удалённого: {e}")
            return False

    def update_message_content(self, telegram_message_id: int, chat_id: int, new_content: str) -> bool:
        try:
            def operation():
                self.cursor.execute(
                    """
                    UPDATE messages
                    SET content = ?, edited_at = CURRENT_TIMESTAMP
                    WHERE telegram_message_id = ? AND chat_id = ?
                    """,
                    (new_content, telegram_message_id, chat_id),
                )
                self.connection.commit()
                return self.cursor.rowcount > 0

            updated = self._run_write(operation)
            if updated:
                logger.info(f"Сообщение telegram_id={telegram_message_id} обновлено (отредактировано)")
            return updated
        except Exception as e:
            logger.error(f"Ошибка при обновлении содержимого сообщения: {e}")
            return False

    def get_group_chat(self, chat_id: int) -> Optional[Dict]:
        try:
            self.cursor.execute("SELECT * FROM group_chats WHERE chat_id = ? LIMIT 1", (chat_id,))
            row = self.cursor.fetchone()
            if row:
                return dict(zip([column[0] for column in self.cursor.description], row))
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении информации о чате {chat_id}: {e}")
            return None

    def update_chat(self, chat_id: int, **kwargs):
        try:
            def operation():
                existing_chat = self.get_group_chat(chat_id)
                update_fields = []
                update_values = []

                for key, value in kwargs.items():
                    if key == 'chat_title':
                        if not existing_chat or existing_chat.get('chat_title') != value:
                            update_fields.append('chat_title = ?')
                            update_values.append(value)
                    elif key == 'chat_type':
                        if not existing_chat or existing_chat.get('chat_type') != value:
                            update_fields.append('chat_type = ?')
                            update_values.append(value)
                    elif key == 'is_banned':
                        normalized_value = int(value)
                        if not existing_chat or int(existing_chat.get('is_banned', 0)) != normalized_value:
                            update_fields.append('is_banned = ?')
                            update_values.append(normalized_value)

                if existing_chat and not update_fields:
                    return False

                if existing_chat:
                    update_sql = "UPDATE group_chats SET " + ", ".join(update_fields) + " WHERE chat_id = ?"
                    update_values.append(chat_id)
                    self.cursor.execute(update_sql, tuple(update_values))
                else:
                    self.cursor.execute(
                        """
                        INSERT INTO group_chats (chat_id, chat_type, chat_title, is_banned)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            chat_id,
                            kwargs.get('chat_type', 'group'),
                            kwargs.get('chat_title'),
                            int(kwargs.get('is_banned', 0)),
                        ),
                    )

                self.connection.commit()
                return True

            updated = self._run_write(operation)
            if updated:
                logger.info(f"Информация о чате {chat_id} обновлена ({', '.join(f'{k}={v}' for k, v in kwargs.items())})")
            return updated
        except Exception as e:
            logger.error(f"Ошибка при обновлении информации о чате {chat_id}: {e}")
            return False

    def migrate_group_chat(
        self,
        old_chat_id: int,
        new_chat_id: int,
        *,
        chat_title: Optional[str] = None,
        chat_type: str = "supergroup",
    ) -> bool:
        if old_chat_id == new_chat_id:
            return False

        try:
            def operation():
                self.cursor.execute(
                    "SELECT chat_title, is_banned FROM group_chats WHERE chat_id = ?",
                    (old_chat_id,),
                )
                old_row = self.cursor.fetchone()
                self.cursor.execute(
                    "SELECT chat_title, is_banned FROM group_chats WHERE chat_id = ?",
                    (new_chat_id,),
                )
                new_row = self.cursor.fetchone()

                merged_title = (
                    chat_title
                    or (new_row[0] if new_row else None)
                    or (old_row[0] if old_row else None)
                )
                merged_ban = max(
                    int(old_row[1] if old_row else 0),
                    int(new_row[1] if new_row else 0),
                )

                self.cursor.execute(
                    """
                    UPDATE messages
                    SET chat_id = ?,
                        chat_type = ?,
                        chat_title = COALESCE(?, chat_title)
                    WHERE chat_id = ?
                    """,
                    (new_chat_id, chat_type, merged_title, old_chat_id),
                )
                self.cursor.execute(
                    """
                    UPDATE messages
                    SET secretary_source_chat_id = ?
                    WHERE secretary_source_chat_id = ?
                    """,
                    (new_chat_id, old_chat_id),
                )

                if new_row:
                    self.cursor.execute(
                        """
                        UPDATE group_chats
                        SET chat_type = ?,
                            chat_title = COALESCE(?, chat_title),
                            is_banned = ?,
                            last_activity = CURRENT_TIMESTAMP
                        WHERE chat_id = ?
                        """,
                        (chat_type, merged_title, merged_ban, new_chat_id),
                    )
                else:
                    self.cursor.execute(
                        """
                        INSERT INTO group_chats (
                            chat_id, chat_type, chat_title, is_banned, last_activity
                        ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """,
                        (new_chat_id, chat_type, merged_title, merged_ban),
                    )

                self.cursor.execute(
                    "DELETE FROM group_chats WHERE chat_id = ?",
                    (old_chat_id,),
                )
                self.connection.commit()
                return True

            migrated = self._run_write(operation)
            if migrated:
                logger.info(
                    "Group chat migrated: %s -> %s (%s)",
                    old_chat_id,
                    new_chat_id,
                    chat_title or "",
                )
            return bool(migrated)
        except Exception as e:
            logger.error(
                "Failed to migrate group chat %s -> %s: %s",
                old_chat_id,
                new_chat_id,
                e,
            )
            return False

    def get_average_wait_time(self):
        from utils import stats
        try:
            wait_times = stats.stats.get_wait_times()
            if wait_times:
                return sum(wait_times) / len(wait_times)
            return 0
        except Exception as e:
            logger.error(f"Ошибка при вычислении среднего времени ожидания: {e}")
            return 0

    def get_average_response_time(self):
        from utils import stats
        try:
            response_times = stats.stats.get_response_times()
            if response_times:
                return sum(response_times) / len(response_times)
            return 0
        except Exception as e:
            logger.error(f"Ошибка при вычислении среднего времени ответа: {e}")
            return 0

    def is_group_banned(self, chat_id: int) -> bool:
        try:
            self.cursor.execute("SELECT is_banned FROM group_chats WHERE chat_id = ?", (chat_id,))
            result = self.cursor.fetchone()
            if result:
                return bool(result[0])
            return False
        except Exception as e:
            logger.error(f"Ошибка при проверке статуса группы {chat_id}: {e}")
            return False

    def toggle_group_ban(self, chat_id: int, is_banned: bool) -> bool:
        try:
            def operation():
                self.cursor.execute("UPDATE group_chats SET is_banned = ? WHERE chat_id = ?", (int(is_banned), chat_id))
                if self.cursor.rowcount == 0:
                    self.cursor.execute(
                        "INSERT INTO group_chats (chat_id, chat_type, is_banned) VALUES (?, 'group', ?)",
                        (chat_id, int(is_banned)),
                    )
                self.connection.commit()
                return True

            self._run_write(operation)
            status = "забанена" if is_banned else "разбанена"
            logger.info(f"Группа {chat_id} {status}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при изменении статуса группы {chat_id}: {e}")
            return False

    def get_chat_messages_active(
        self,
        chat_id: int,
        limit: int = 200,
        *,
        source_mode: Optional[str] = None,
        secretary_owner_telegram_id: Optional[int] = None,
        secretary_source_chat_id: Optional[int] = None,
    ) -> List[Dict]:
        try:
            query = [
                "SELECT * FROM messages",
                "WHERE chat_id = ?",
                "AND is_archived = 0",
            ]
            params: List = [chat_id]
            if source_mode is not None:
                query.append("AND (source_mode = ? OR source_mode IS NULL)")
                params.append(source_mode)
            if secretary_owner_telegram_id is not None:
                query.append("AND secretary_owner_telegram_id = ?")
                params.append(secretary_owner_telegram_id)
            if secretary_source_chat_id is not None:
                query.append("AND secretary_source_chat_id = ?")
                params.append(secretary_source_chat_id)
            query.append("ORDER BY timestamp ASC")
            query.append("LIMIT ?")
            params.append(limit)
            self.cursor.execute(" ".join(query), tuple(params))
            messages = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in messages]
        except Exception as e:
            logger.error(f"Ошибка при получении активных сообщений чата {chat_id}: {e}")
            return []

    def get_user_messages_active(
        self,
        user_id,
        limit=100,
        *,
        chat_type: Optional[str] = None,
        chat_id: Optional[int] = None,
        source_mode: Optional[str] = None,
        secretary_owner_telegram_id: Optional[int] = None,
        secretary_source_chat_id: Optional[int] = None,
    ):
        try:
            query = [
                "SELECT * FROM messages",
                "WHERE user_id = ?",
                "AND is_archived = 0",
            ]
            params: List = [user_id]

            if chat_type is not None:
                query.append("AND chat_type = ?")
                params.append(chat_type)

            if chat_id is not None:
                query.append("AND chat_id = ?")
                params.append(chat_id)

            if source_mode is not None:
                query.append("AND (source_mode = ? OR source_mode IS NULL)")
                params.append(source_mode)
            if secretary_owner_telegram_id is not None:
                query.append("AND secretary_owner_telegram_id = ?")
                params.append(secretary_owner_telegram_id)
            if secretary_source_chat_id is not None:
                query.append("AND secretary_source_chat_id = ?")
                params.append(secretary_source_chat_id)

            query.append("ORDER BY timestamp ASC")
            query.append("LIMIT ?")
            params.append(limit)

            final_query = " ".join(query)
            self.cursor.execute(final_query, tuple(params))
            messages = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in messages]
        except Exception as e:
            logger.error(f"Ошибка при получении активных сообщений пользователя {user_id}: {e}")
            return []

    def get_secretary_owner_messages_active(
        self,
        owner_telegram_id: int,
        limit: int = 500,
        *,
        chat_id: Optional[int] = None,
    ) -> List[Dict]:
        try:
            query = [
                "SELECT * FROM messages",
                "WHERE source_mode = 'secretary'",
                "AND secretary_owner_telegram_id = ?",
                "AND is_archived = 0",
            ]
            params: List = [owner_telegram_id]

            if chat_id is not None:
                query.append("AND (chat_id = ? OR secretary_source_chat_id = ?)")
                params.extend([chat_id, chat_id])

            query.append("ORDER BY timestamp ASC")
            query.append("LIMIT ?")
            params.append(limit)

            self.cursor.execute(" ".join(query), tuple(params))
            messages = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in messages]
        except Exception as e:
            logger.error(f"Ошибка при получении secretary-истории владельца {owner_telegram_id}: {e}")
            return []

    def archive_messages_by_ids(self, message_ids: List[int]) -> int:
        if not message_ids:
            return 0
        try:
            placeholders = ','.join('?' * len(message_ids))

            def operation():
                self.cursor.execute(
                    f"UPDATE messages SET is_archived = 1 WHERE id IN ({placeholders})",
                    tuple(message_ids),
                )
                self.connection.commit()
                return self.cursor.rowcount

            archived_count = self._run_write(operation)
            logger.info(f"Архивировано {archived_count} сообщений (IDs: {message_ids})")
            return archived_count
        except Exception as e:
            logger.error(f"Ошибка при архивировании сообщений: {e}")
            return 0

    def get_archived_messages_summary(self, chat_id: int) -> int:
        try:
            self.cursor.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ? AND is_archived = 1", (chat_id,))
            count = self.cursor.fetchone()[0]
            return count
        except Exception as e:
            logger.error(f"Ошибка при подсчёте архивированных сообщений: {e}")
            return 0

    def get_oldest_active_messages(self, chat_id: int, limit: int = 10) -> List[Dict]:
        try:
            self.cursor.execute(
                """
                SELECT * FROM messages
                WHERE chat_id = ? AND is_archived = 0
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (chat_id, limit),
            )
            messages = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in messages]
        except Exception as e:
            logger.error(f"Ошибка при получении старых сообщений чата {chat_id}: {e}")
            return []
