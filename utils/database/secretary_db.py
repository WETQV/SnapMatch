import time
from typing import Dict, List, Optional

from .base_db import BaseDB
from utils.logger import setup_logger

logger = setup_logger(__name__)


class SecretaryDB(BaseDB):
    def list_profiles(self) -> List[Dict]:
        try:
            self.cursor.execute("SELECT * FROM secretary_profiles ORDER BY owner_telegram_id ASC")
            rows = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка при получении secretary-профилей: {e}")
            return []

    def get_profile(self, owner_telegram_id: int) -> Optional[Dict]:
        try:
            self.cursor.execute(
                "SELECT * FROM secretary_profiles WHERE owner_telegram_id = ? LIMIT 1",
                (owner_telegram_id,),
            )
            row = self.cursor.fetchone()
            if not row:
                return None
            return dict(zip([column[0] for column in self.cursor.description], row))
        except Exception as e:
            logger.error(f"Ошибка при получении secretary-профиля {owner_telegram_id}: {e}")
            return None

    def upsert_profile(self, owner_telegram_id: int, **fields) -> bool:
        current = self.get_profile(owner_telegram_id)
        allowed = {
            "owner_display_name",
            "business_connection_id",
            "enabled",
            "response_mode",
            "system_prompt",
            "save_history",
            "ignore_bot_messages",
            "media_stt_enabled",
            "media_images_enabled",
            "allowed_chats",
            "blocked_chats",
            "default_delay_seconds",
            "burst_window_seconds",
            "max_batch_messages",
            "default_session_ttl_seconds",
            "close_after_reply",
            "owner_message_behavior",
            "turn_based_replies",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        try:
            def operation():
                if current:
                    assignments = ", ".join(f"{key} = ?" for key in values)
                    params = list(values.values()) + [owner_telegram_id]
                    if assignments:
                        self.cursor.execute(
                            f"UPDATE secretary_profiles SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE owner_telegram_id = ?",
                            tuple(params),
                        )
                else:
                    columns = ["owner_telegram_id"] + list(values.keys())
                    placeholders = ", ".join("?" for _ in columns)
                    self.cursor.execute(
                        f"INSERT INTO secretary_profiles ({', '.join(columns)}) VALUES ({placeholders})",
                        tuple([owner_telegram_id] + list(values.values())),
                    )
                self.connection.commit()

            self._run_write(operation)
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения secretary-профиля {owner_telegram_id}: {e}")
            return False

    def delete_profile(self, owner_telegram_id: int) -> int:
        try:
            def operation():
                self.cursor.execute("DELETE FROM secretary_profiles WHERE owner_telegram_id = ?", (owner_telegram_id,))
                self.connection.commit()
                return self.cursor.rowcount

            return self._run_write(operation)
        except Exception as e:
            logger.error(f"Ошибка удаления secretary-профиля {owner_telegram_id}: {e}")
            return 0

    def get_profile_by_connection_id(self, business_connection_id: str) -> Optional[Dict]:
        try:
            self.cursor.execute(
                "SELECT * FROM secretary_profiles WHERE business_connection_id = ? LIMIT 1",
                (business_connection_id,),
            )
            row = self.cursor.fetchone()
            if not row:
                return None
            return dict(zip([column[0] for column in self.cursor.description], row))
        except Exception as e:
            logger.error(f"Ошибка получения secretary-профиля по business_connection_id: {e}")
            return None

    def add_event(self, owner_telegram_id: int, status: str, details: str = "", chat_id: Optional[int] = None) -> None:
        try:
            def operation():
                self.cursor.execute(
                    "INSERT INTO secretary_events (owner_telegram_id, chat_id, status, details) VALUES (?, ?, ?, ?)",
                    (owner_telegram_id, chat_id, status, details),
                )
                self.connection.commit()

            self._run_write(operation)
            self.prune_events(owner_telegram_id)
        except Exception as e:
            logger.error(f"Ошибка записи secretary-события {owner_telegram_id}: {e}")

    def claim_response_lock(self, owner_telegram_id: int, chat_id: int, reply_to_message_id: int) -> bool:
        try:
            def operation():
                self.cursor.execute(
                    """
                    INSERT OR IGNORE INTO secretary_response_locks (
                        owner_telegram_id,
                        chat_id,
                        reply_to_message_id,
                        status
                    ) VALUES (?, ?, ?, 'claimed')
                    """,
                    (owner_telegram_id, chat_id, reply_to_message_id),
                )
                inserted = self.cursor.rowcount > 0
                self.connection.commit()
                return inserted

            return bool(self._run_write(operation))
        except Exception as e:
            logger.error("Ошибка claim secretary response lock: %s", e)
            return False

    def mark_response_lock_sent(self, owner_telegram_id: int, chat_id: int, reply_to_message_id: int) -> None:
        try:
            def operation():
                self.cursor.execute(
                    """
                    UPDATE secretary_response_locks
                    SET status = 'sent', updated_at = CURRENT_TIMESTAMP
                    WHERE owner_telegram_id = ? AND chat_id = ? AND reply_to_message_id = ?
                    """,
                    (owner_telegram_id, chat_id, reply_to_message_id),
                )
                self.connection.commit()

            self._run_write(operation)
        except Exception as e:
            logger.error("Ошибка mark secretary response lock sent: %s", e)

    def prune_events(self, owner_telegram_id: Optional[int] = None) -> int:
        try:
            from config.settings import settings_manager

            retention = settings_manager.get_settings().get("audit_retention", {}) or {}
            days = int(retention.get("secretary_events_days", 90) or 0)
            max_per_owner = int(retention.get("secretary_events_max_per_owner", 2000) or 0)

            def operation():
                deleted = 0
                if days > 0:
                    if owner_telegram_id is None:
                        self.cursor.execute(
                            "DELETE FROM secretary_events WHERE created_at < datetime('now', ?)",
                            (f"-{days} days",),
                        )
                    else:
                        self.cursor.execute(
                            """
                            DELETE FROM secretary_events
                            WHERE owner_telegram_id = ?
                              AND created_at < datetime('now', ?)
                            """,
                            (owner_telegram_id, f"-{days} days"),
                        )
                    deleted += self.cursor.rowcount

                if max_per_owner > 0:
                    if owner_telegram_id is None:
                        self.cursor.execute("SELECT DISTINCT owner_telegram_id FROM secretary_events")
                        owner_ids = [row[0] for row in self.cursor.fetchall()]
                    else:
                        owner_ids = [owner_telegram_id]
                    for current_owner_id in owner_ids:
                        self.cursor.execute(
                            """
                            DELETE FROM secretary_events
                            WHERE owner_telegram_id = ?
                              AND id NOT IN (
                                  SELECT id FROM secretary_events
                                  WHERE owner_telegram_id = ?
                                  ORDER BY created_at DESC, id DESC
                                  LIMIT ?
                              )
                            """,
                            (current_owner_id, current_owner_id, max_per_owner),
                        )
                        deleted += self.cursor.rowcount

                self.connection.commit()
                return deleted

            return int(self._run_write(operation) or 0)
        except Exception as e:
            logger.error(f"Ошибка очистки secretary-событий: {e}")
            return 0

    def get_chat_settings(self, owner_telegram_id: int, chat_id: int) -> Optional[Dict]:
        try:
            self.cursor.execute(
                """
                SELECT * FROM secretary_chat_settings
                WHERE owner_telegram_id = ? AND chat_id = ?
                LIMIT 1
                """,
                (owner_telegram_id, chat_id),
            )
            row = self.cursor.fetchone()
            if not row:
                return None
            return dict(zip([column[0] for column in self.cursor.description], row))
        except Exception as e:
            logger.error(f"Ошибка получения secretary chat settings {owner_telegram_id}/{chat_id}: {e}")
            return None

    def upsert_chat_settings(self, owner_telegram_id: int, chat_id: int, **fields) -> bool:
        allowed = {
            "response_mode",
            "system_prompt",
            "history_enabled",
            "delay_seconds",
            "burst_window_seconds",
            "max_batch_messages",
            "session_ttl_seconds",
            "close_after_reply",
            "owner_message_behavior",
            "turn_based_replies",
            "allowed_mcp",
            "media_stt_enabled",
            "media_images_enabled",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        current = self.get_chat_settings(owner_telegram_id, chat_id)
        try:
            def operation():
                if current:
                    assignments = ", ".join(f"{key} = ?" for key in values)
                    if assignments:
                        self.cursor.execute(
                            f"UPDATE secretary_chat_settings SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE owner_telegram_id = ? AND chat_id = ?",
                            tuple(list(values.values()) + [owner_telegram_id, chat_id]),
                        )
                else:
                    columns = ["owner_telegram_id", "chat_id"] + list(values.keys())
                    placeholders = ", ".join("?" for _ in columns)
                    self.cursor.execute(
                        f"INSERT INTO secretary_chat_settings ({', '.join(columns)}) VALUES ({placeholders})",
                        tuple([owner_telegram_id, chat_id] + list(values.values())),
                    )
                self.connection.commit()

            self._run_write(operation)
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения secretary chat settings {owner_telegram_id}/{chat_id}: {e}")
            return False

    def list_recent_chats(self, owner_telegram_id: int, limit: int = 50) -> List[Dict]:
        chats: Dict[int, Dict] = {}

        def ensure_chat(chat_id, *, chat_title=None, last_seen=None, message_count=0, has_override=False):
            if chat_id is None:
                return
            try:
                normalized_chat_id = int(chat_id)
            except (TypeError, ValueError):
                return
            current = chats.setdefault(
                normalized_chat_id,
                {
                    "chat_id": normalized_chat_id,
                    "chat_title": "",
                    "last_seen": None,
                    "message_count": 0,
                    "has_override": False,
                },
            )
            if chat_title and not current["chat_title"]:
                current["chat_title"] = str(chat_title)
            if last_seen and (not current["last_seen"] or str(last_seen) > str(current["last_seen"])):
                current["last_seen"] = last_seen
            current["message_count"] += int(message_count or 0)
            current["has_override"] = current["has_override"] or bool(has_override)

        try:
            self.cursor.execute(
                """
                SELECT
                    secretary_source_chat_id AS chat_id,
                    COALESCE(MAX(NULLIF(chat_title, '')), '') AS chat_title,
                    MAX(timestamp) AS last_seen,
                    COUNT(*) AS message_count
                FROM messages
                WHERE source_mode = 'secretary'
                  AND secretary_owner_telegram_id = ?
                  AND secretary_source_chat_id IS NOT NULL
                GROUP BY secretary_source_chat_id
                """,
                (owner_telegram_id,),
            )
            for row in self.cursor.fetchall():
                ensure_chat(row[0], chat_title=row[1], last_seen=row[2], message_count=row[3])

            self.cursor.execute(
                """
                SELECT chat_id, MAX(updated_at) AS last_seen
                FROM secretary_sessions
                WHERE owner_telegram_id = ?
                GROUP BY chat_id
                """,
                (owner_telegram_id,),
            )
            for row in self.cursor.fetchall():
                ensure_chat(row[0], last_seen=row[1])

            self.cursor.execute(
                """
                SELECT chat_id, MAX(created_at) AS last_seen
                FROM secretary_events
                WHERE owner_telegram_id = ? AND chat_id IS NOT NULL
                GROUP BY chat_id
                """,
                (owner_telegram_id,),
            )
            for row in self.cursor.fetchall():
                ensure_chat(row[0], last_seen=row[1])

            self.cursor.execute(
                """
                SELECT chat_id, updated_at
                FROM secretary_chat_settings
                WHERE owner_telegram_id = ?
                """,
                (owner_telegram_id,),
            )
            for row in self.cursor.fetchall():
                ensure_chat(row[0], last_seen=row[1], has_override=True)

            for chat in chats.values():
                if chat["chat_title"]:
                    continue
                self.cursor.execute("SELECT chat_title FROM group_chats WHERE chat_id = ? LIMIT 1", (chat["chat_id"],))
                row = self.cursor.fetchone()
                if row and row[0]:
                    chat["chat_title"] = row[0]

            return sorted(
                chats.values(),
                key=lambda item: str(item.get("last_seen") or ""),
                reverse=True,
            )[:limit]
        except Exception as e:
            logger.error(f"Ошибка получения recent secretary chats {owner_telegram_id}: {e}")
            return []

    def count_chat_messages(self, owner_telegram_id: int, chat_id: int) -> int:
        try:
            self.cursor.execute(
                """
                SELECT COUNT(*)
                FROM messages
                WHERE source_mode = 'secretary'
                  AND secretary_owner_telegram_id = ?
                  AND (secretary_source_chat_id = ? OR chat_id = ?)
                """,
                (owner_telegram_id, chat_id, chat_id),
            )
            row = self.cursor.fetchone()
            return int(row[0] or 0) if row else 0
        except Exception as e:
            logger.error(f"Ошибка подсчёта secretary-сообщений {owner_telegram_id}/{chat_id}: {e}")
            return 0

    def list_prompt_history(self, owner_telegram_id: int, limit: int = 15) -> List[Dict]:
        try:
            self.cursor.execute(
                """
                SELECT text, created_at
                FROM secretary_prompt_history
                WHERE owner_telegram_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (owner_telegram_id, limit),
            )
            rows = self.cursor.fetchall()
            history = [
                {"text": row[0] or "", "updated_at": row[1] or ""}
                for row in rows
            ]
            return list(reversed(history))
        except Exception as e:
            logger.error(f"Ошибка получения secretary prompt history {owner_telegram_id}: {e}")
            return []

    def save_prompt_history(self, owner_telegram_id: int, history: List[Dict], limit: int = 15) -> bool:
        normalized = [
            str(item.get("text") or "").rstrip()
            for item in list(history or [])[-limit:]
            if str(item.get("text") or "").strip()
        ]
        try:
            def operation():
                self.cursor.execute(
                    "DELETE FROM secretary_prompt_history WHERE owner_telegram_id = ?",
                    (owner_telegram_id,),
                )
                for text in normalized:
                    self.cursor.execute(
                        """
                        INSERT INTO secretary_prompt_history (owner_telegram_id, text)
                        VALUES (?, ?)
                        """,
                        (owner_telegram_id, text),
                    )
                self.connection.commit()
                return True

            return bool(self._run_write(operation))
        except Exception as e:
            logger.error(f"Ошибка сохранения secretary prompt history {owner_telegram_id}: {e}")
            return False

    def list_prompt_templates(self, owner_telegram_id: int) -> List[Dict]:
        try:
            self.cursor.execute(
                """
                SELECT name, text, updated_at
                FROM secretary_prompt_templates
                WHERE owner_telegram_id = ?
                ORDER BY name COLLATE NOCASE ASC
                """,
                (owner_telegram_id,),
            )
            return [
                {"name": row[0] or "Без имени", "text": row[1] or "", "updated_at": row[2] or ""}
                for row in self.cursor.fetchall()
            ]
        except Exception as e:
            logger.error(f"Ошибка получения secretary prompt templates {owner_telegram_id}: {e}")
            return []

    def save_prompt_templates(self, owner_telegram_id: int, templates: List[Dict]) -> bool:
        normalized = []
        seen = set()
        for item in templates or []:
            name = str(item.get("name") or "").strip()
            text = str(item.get("text") or "")
            if not name or name in seen:
                continue
            seen.add(name)
            normalized.append({"name": name, "text": text})
        try:
            def operation():
                self.cursor.execute(
                    "DELETE FROM secretary_prompt_templates WHERE owner_telegram_id = ?",
                    (owner_telegram_id,),
                )
                for item in normalized:
                    self.cursor.execute(
                        """
                        INSERT INTO secretary_prompt_templates (owner_telegram_id, name, text)
                        VALUES (?, ?, ?)
                        """,
                        (owner_telegram_id, item["name"], item["text"]),
                    )
                self.connection.commit()
                return True

            return bool(self._run_write(operation))
        except Exception as e:
            logger.error(f"Ошибка сохранения secretary prompt templates {owner_telegram_id}: {e}")
            return False

    def resolve_chat_runtime_settings(self, profile: Dict, chat_id: int) -> Dict:
        owner_id = int(profile.get("owner_telegram_id"))
        chat_settings = self.get_chat_settings(owner_id, chat_id) or {}
        ttl = chat_settings.get("session_ttl_seconds")
        if ttl is None:
            ttl = profile.get("default_session_ttl_seconds")
        if ttl is None:
            ttl = 3600
        try:
            ttl = int(ttl)
            if ttl < 0:
                ttl = 3600
            elif 0 < ttl < 60:
                ttl = 60
        except (TypeError, ValueError):
            ttl = 3600

        response_mode = chat_settings.get("response_mode") or profile.get("response_mode") or "draft"
        system_prompt = chat_settings.get("system_prompt")
        if system_prompt is None:
            system_prompt = profile.get("system_prompt") or ""
        history_enabled = chat_settings.get("history_enabled")
        if history_enabled is None:
            history_enabled = profile.get("save_history", 1)
        close_after_reply = chat_settings.get("close_after_reply")
        if close_after_reply is None:
            close_after_reply = profile.get("close_after_reply", 0)
        owner_message_behavior = chat_settings.get("owner_message_behavior") or profile.get("owner_message_behavior") or "takeover"
        if owner_message_behavior not in {"ignore", "takeover", "add_to_context", "close_session"}:
            owner_message_behavior = "takeover"
        turn_based_replies = chat_settings.get("turn_based_replies")
        if turn_based_replies is None:
            turn_based_replies = profile.get("turn_based_replies", 1)
        media_stt_enabled = chat_settings.get("media_stt_enabled")
        if media_stt_enabled is None:
            media_stt_enabled = profile.get("media_stt_enabled", 0)
        media_images_enabled = chat_settings.get("media_images_enabled")
        if media_images_enabled is None:
            media_images_enabled = profile.get("media_images_enabled", 0)

        return {
            "enabled": bool(profile.get("enabled", 0)),
            "response_mode": str(response_mode).lower(),
            "system_prompt": system_prompt,
            "save_history": bool(history_enabled),
            "ignore_bot_messages": bool(profile.get("ignore_bot_messages", 1)),
            "delay_seconds": float(
                chat_settings.get("delay_seconds")
                if chat_settings.get("delay_seconds") is not None
                else profile.get("default_delay_seconds", 2.0)
            ),
            "burst_window_seconds": float(
                chat_settings.get("burst_window_seconds")
                if chat_settings.get("burst_window_seconds") is not None
                else profile.get("burst_window_seconds", 2.0)
            ),
            "max_batch_messages": int(
                chat_settings.get("max_batch_messages")
                if chat_settings.get("max_batch_messages") is not None
                else profile.get("max_batch_messages", 10)
            ),
            "session_ttl_seconds": ttl,
            "close_after_reply": bool(close_after_reply),
            "owner_message_behavior": owner_message_behavior,
            "turn_based_replies": bool(turn_based_replies),
            "allowed_mcp": chat_settings.get("allowed_mcp"),
            "media_stt_enabled": bool(media_stt_enabled),
            "media_images_enabled": bool(media_images_enabled),
        }

    def get_active_session(self, owner_telegram_id: int, chat_id: int) -> Optional[Dict]:
        now = int(time.time())
        try:
            self.cursor.execute(
                """
                SELECT * FROM secretary_sessions
                WHERE owner_telegram_id = ?
                  AND chat_id = ?
                  AND status = 'active'
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (owner_telegram_id, chat_id, now),
            )
            row = self.cursor.fetchone()
            if not row:
                return None
            return dict(zip([column[0] for column in self.cursor.description], row))
        except Exception as e:
            logger.error(f"Ошибка получения active secretary session {owner_telegram_id}/{chat_id}: {e}")
            return None

    def get_latest_active_session(self, owner_telegram_id: int) -> Optional[Dict]:
        now = int(time.time())
        try:
            self.cursor.execute(
                """
                SELECT * FROM secretary_sessions
                WHERE owner_telegram_id = ?
                  AND status = 'active'
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (owner_telegram_id, now),
            )
            row = self.cursor.fetchone()
            if not row:
                return None
            return dict(zip([column[0] for column in self.cursor.description], row))
        except Exception as e:
            logger.error(f"Ошибка получения latest active secretary session {owner_telegram_id}: {e}")
            return None

    def get_or_create_session(
        self,
        owner_telegram_id: int,
        chat_id: int,
        *,
        counterparty_id: Optional[int] = None,
        ttl_seconds: int = 3600,
    ) -> Dict:
        current = self.get_active_session(owner_telegram_id, chat_id)
        now = int(time.time())
        normalized_ttl = int(ttl_seconds if ttl_seconds is not None else 3600)
        expires_at = None if normalized_ttl <= 0 else now + max(60, normalized_ttl)
        if current:
            self.touch_session(int(current["id"]), ttl_seconds=ttl_seconds)
            current["expires_at"] = expires_at
            current["updated_at"] = now
            return current

        try:
            def operation():
                self.cursor.execute(
                    """
                    INSERT INTO secretary_sessions (
                        owner_telegram_id,
                        chat_id,
                        counterparty_id,
                        status,
                        created_at,
                        updated_at,
                        expires_at
                    ) VALUES (?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (owner_telegram_id, chat_id, counterparty_id, now, now, expires_at),
                )
                self.connection.commit()
                session_id = self.cursor.lastrowid
                return {
                    "id": session_id,
                    "owner_telegram_id": owner_telegram_id,
                    "chat_id": chat_id,
                    "counterparty_id": counterparty_id,
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                    "expires_at": expires_at,
                }

            return self._run_write(operation)
        except Exception as e:
            logger.error(f"Ошибка создания secretary session {owner_telegram_id}/{chat_id}: {e}")
            return {"id": None, "owner_telegram_id": owner_telegram_id, "chat_id": chat_id}

    def touch_session(self, session_id: int, *, ttl_seconds: int = 3600) -> bool:
        now = int(time.time())
        normalized_ttl = int(ttl_seconds if ttl_seconds is not None else 3600)
        expires_at = None if normalized_ttl <= 0 else now + max(60, normalized_ttl)
        try:
            def operation():
                self.cursor.execute(
                    "UPDATE secretary_sessions SET updated_at = ?, expires_at = ? WHERE id = ? AND status = 'active'",
                    (now, expires_at, session_id),
                )
                self.connection.commit()
                return self.cursor.rowcount > 0

            return bool(self._run_write(operation))
        except Exception as e:
            logger.error(f"Ошибка обновления secretary session {session_id}: {e}")
            return False

    def close_session(self, session_id: int, reason: str = "closed") -> bool:
        now = int(time.time())
        try:
            def operation():
                self.cursor.execute(
                    """
                    UPDATE secretary_sessions
                    SET status = 'closed', closed_at = ?, close_reason = ?, updated_at = ?
                    WHERE id = ? AND status = 'active'
                    """,
                    (now, reason, now, session_id),
                )
                self.connection.commit()
                return self.cursor.rowcount > 0

            return bool(self._run_write(operation))
        except Exception as e:
            logger.error(f"Ошибка закрытия secretary session {session_id}: {e}")
            return False

    def list_events(self, owner_telegram_id: int, limit: int = 50) -> List[Dict]:
        try:
            self.cursor.execute(
                """
                SELECT * FROM secretary_events
                WHERE owner_telegram_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (owner_telegram_id, limit),
            )
            rows = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения secretary-событий {owner_telegram_id}: {e}")
            return []

    def list_recent_events(self, limit: int = 50) -> List[Dict]:
        try:
            self.cursor.execute(
                """
                SELECT * FROM secretary_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения последних secretary-событий: {e}")
            return []

    def create_pending_response(
        self,
        owner_telegram_id: int,
        business_connection_id: str,
        chat_id: int,
        response_text: str,
        session_id: Optional[int] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> Optional[int]:
        try:
            def operation():
                self.cursor.execute(
                    """
                    INSERT INTO secretary_pending_responses (
                        owner_telegram_id,
                        business_connection_id,
                        chat_id,
                        session_id,
                        reply_to_message_id,
                        response_text,
                        status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (owner_telegram_id, business_connection_id, chat_id, session_id, reply_to_message_id, response_text),
                )
                self.connection.commit()
                return self.cursor.lastrowid

            return self._run_write(operation)
        except Exception as e:
            logger.error(f"Ошибка создания pending secretary-response: {e}")
            return None

    def get_pending_response(self, pending_id: int) -> Optional[Dict]:
        try:
            self.cursor.execute(
                "SELECT * FROM secretary_pending_responses WHERE id = ? LIMIT 1",
                (pending_id,),
            )
            row = self.cursor.fetchone()
            if not row:
                return None
            return dict(zip([column[0] for column in self.cursor.description], row))
        except Exception as e:
            logger.error(f"Ошибка получения pending secretary-response {pending_id}: {e}")
            return None

    def update_pending_response_status(self, pending_id: int, status: str) -> bool:
        try:
            def operation():
                self.cursor.execute(
                    "UPDATE secretary_pending_responses SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (status, pending_id),
                )
                self.connection.commit()
                return self.cursor.rowcount > 0

            return bool(self._run_write(operation))
        except Exception as e:
            logger.error(f"Ошибка обновления pending secretary-response {pending_id}: {e}")
            return False

    def add_pending_response(
        self,
        owner_telegram_id: int,
        chat_id: int,
        response_text: str,
        *,
        session_id: Optional[int] = None,
        business_connection_id: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        status: str = "pending",
    ) -> Optional[int]:
        try:
            def operation():
                self.cursor.execute(
                    """
                    INSERT INTO secretary_pending_responses (
                        owner_telegram_id,
                        business_connection_id,
                        chat_id,
                        session_id,
                        reply_to_message_id,
                        response_text,
                        status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        owner_telegram_id,
                        business_connection_id or "",
                        chat_id,
                        session_id,
                        reply_to_message_id,
                        response_text,
                        status,
                    ),
                )
                self.connection.commit()
                return self.cursor.lastrowid

            return self._run_write(operation)
        except Exception as e:
            logger.error(f"Failed to add pending secretary response: {e}")
            return None

    def upsert_business_connection(
        self,
        business_connection_id: str,
        owner_telegram_id: int,
        *,
        user_chat_id: Optional[int] = None,
        is_enabled: bool = True,
    ) -> bool:
        try:
            def operation():
                self.cursor.execute(
                    """
                    INSERT INTO secretary_business_connections (
                        business_connection_id,
                        owner_telegram_id,
                        user_chat_id,
                        is_enabled,
                        updated_at
                    ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(business_connection_id) DO UPDATE SET
                        owner_telegram_id = excluded.owner_telegram_id,
                        user_chat_id = excluded.user_chat_id,
                        is_enabled = excluded.is_enabled,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (business_connection_id, owner_telegram_id, user_chat_id, int(bool(is_enabled))),
                )
                self.connection.commit()
                return True

            return bool(self._run_write(operation))
        except Exception as e:
            logger.error(f"Failed to save secretary business connection: {e}")
            return False

    def get_business_connection_owner(self, business_connection_id: str) -> Optional[int]:
        try:
            self.cursor.execute(
                """
                SELECT owner_telegram_id
                FROM secretary_business_connections
                WHERE business_connection_id = ? AND is_enabled = 1
                LIMIT 1
                """,
                (business_connection_id,),
            )
            row = self.cursor.fetchone()
            return int(row[0]) if row else None
        except Exception as e:
            logger.error(f"Failed to resolve secretary business connection owner: {e}")
            return None
