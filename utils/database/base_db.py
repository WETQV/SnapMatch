import sqlite3
import threading
from typing import Set

from config.settings import DATABASE_PATH
from utils.logger import setup_logger

logger = setup_logger(__name__)


class BaseDB:
    _lock = threading.Lock()
    _write_lock = threading.Lock()
    _tables_created = False

    def __init__(self):
        self.connection = sqlite3.connect(
            DATABASE_PATH,
            check_same_thread=False,
            timeout=30.0,
        )
        self.cursor = self.connection.cursor()

        try:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA busy_timeout=30000")
            self.connection.execute("PRAGMA synchronous=NORMAL")
        except Exception as e:
            logger.warning(f"Не удалось установить PRAGMA настройки SQLite: {e}")

        with BaseDB._lock:
            if not BaseDB._tables_created:
                self.create_tables()
                BaseDB._tables_created = True

    def create_tables(self):
        try:
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    priority INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    preferences TEXT,
                    last_activity DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER,
                    chat_type TEXT,
                    chat_title TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_type TEXT,
                    image_path TEXT,
                    image_mime TEXT,
                    telegram_file_id TEXT,
                    author_telegram_id INTEGER,
                    author_username TEXT,
                    author_full_name TEXT,
                    telegram_message_id INTEGER,
                    is_deleted INTEGER DEFAULT 0,
                    edited_at DATETIME,
                    is_archived INTEGER DEFAULT 0,
                    is_summary INTEGER DEFAULT 0,
                    summary_source_ids TEXT,
                    is_addressed INTEGER DEFAULT 0,
                    author_is_bot INTEGER DEFAULT 0,
                    source_mode TEXT DEFAULT 'normal',
                    secretary_owner_telegram_id INTEGER,
                    secretary_source_chat_id INTEGER,
                    secretary_counterparty_id INTEGER,
                    secretary_reply_status TEXT,
                    reply_to_message_id INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS group_chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER UNIQUE NOT NULL,
                    chat_type TEXT NOT NULL,
                    chat_title TEXT,
                    is_banned INTEGER DEFAULT 0,
                    last_activity DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS secretary_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_telegram_id INTEGER UNIQUE NOT NULL,
                    business_connection_id TEXT,
                    owner_display_name TEXT,
                    enabled INTEGER DEFAULT 0,
                    response_mode TEXT DEFAULT 'draft',
                    system_prompt TEXT DEFAULT '',
                    save_history INTEGER DEFAULT 1,
                    ignore_bot_messages INTEGER DEFAULT 1,
                    media_stt_enabled INTEGER DEFAULT 0,
                    media_images_enabled INTEGER DEFAULT 0,
                    allowed_chats TEXT,
                    blocked_chats TEXT,
                    default_delay_seconds REAL DEFAULT 2.0,
                    burst_window_seconds REAL DEFAULT 2.0,
                    max_batch_messages INTEGER DEFAULT 10,
                    default_session_ttl_seconds INTEGER DEFAULT 3600,
                    close_after_reply INTEGER DEFAULT 0,
                    owner_message_behavior TEXT DEFAULT 'takeover',
                    turn_based_replies INTEGER DEFAULT 1,
                    last_activity DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS secretary_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_telegram_id INTEGER,
                    chat_id INTEGER,
                    status TEXT NOT NULL,
                    details TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS secretary_prompt_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_telegram_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS secretary_prompt_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_telegram_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(owner_telegram_id, name)
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS secretary_chat_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_telegram_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    response_mode TEXT,
                    system_prompt TEXT,
                    history_enabled INTEGER,
                    delay_seconds REAL,
                    burst_window_seconds REAL,
                    max_batch_messages INTEGER,
                    session_ttl_seconds INTEGER,
                    close_after_reply INTEGER,
                    owner_message_behavior TEXT,
                    turn_based_replies INTEGER,
                    allowed_mcp TEXT,
                    media_stt_enabled INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(owner_telegram_id, chat_id)
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS secretary_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_telegram_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    counterparty_id INTEGER,
                    status TEXT DEFAULT 'active',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    expires_at INTEGER,
                    closed_at INTEGER,
                    close_reason TEXT
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS secretary_pending_responses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_telegram_id INTEGER NOT NULL,
                    business_connection_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    session_id INTEGER,
                    reply_to_message_id INTEGER,
                    response_text TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS secretary_response_locks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_telegram_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    reply_to_message_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'claimed',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(owner_telegram_id, chat_id, reply_to_message_id)
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS secretary_business_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    business_connection_id TEXT UNIQUE NOT NULL,
                    owner_telegram_id INTEGER NOT NULL,
                    user_chat_id INTEGER,
                    is_enabled INTEGER DEFAULT 1,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_tool_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_name TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    actor_telegram_id INTEGER,
                    chat_id INTEGER,
                    source_mode TEXT,
                    status TEXT NOT NULL,
                    arguments_summary TEXT,
                    result_preview TEXT,
                    error TEXT,
                    duration_ms INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_server_status (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_name TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    details TEXT,
                    tools_count INTEGER DEFAULT 0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_access_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_name TEXT,
                    tool_name TEXT,
                    actor_telegram_id INTEGER,
                    chat_id INTEGER,
                    source_mode TEXT,
                    reason TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            user_columns = self._get_table_columns("users")
            user_additional_columns = {
                "preferences": "ALTER TABLE users ADD COLUMN preferences TEXT",
            }
            for column, alter_sql in user_additional_columns.items():
                if column not in user_columns:
                    try:
                        self.cursor.execute(alter_sql)
                        logger.info(f"Добавлена колонка '{column}' в таблицу users")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Не удалось добавить колонку '{column}': {e}")

            existing_columns = self._get_table_columns("messages")
            additional_columns = {
                "chat_id": "ALTER TABLE messages ADD COLUMN chat_id INTEGER",
                "chat_type": "ALTER TABLE messages ADD COLUMN chat_type TEXT",
                "chat_title": "ALTER TABLE messages ADD COLUMN chat_title TEXT",
                "telegram_message_id": "ALTER TABLE messages ADD COLUMN telegram_message_id INTEGER",
                "author_telegram_id": "ALTER TABLE messages ADD COLUMN author_telegram_id INTEGER",
                "author_username": "ALTER TABLE messages ADD COLUMN author_username TEXT",
                "author_full_name": "ALTER TABLE messages ADD COLUMN author_full_name TEXT",
                "is_deleted": "ALTER TABLE messages ADD COLUMN is_deleted INTEGER DEFAULT 0",
                "edited_at": "ALTER TABLE messages ADD COLUMN edited_at DATETIME",
                "is_archived": "ALTER TABLE messages ADD COLUMN is_archived INTEGER DEFAULT 0",
                "is_summary": "ALTER TABLE messages ADD COLUMN is_summary INTEGER DEFAULT 0",
                "summary_source_ids": "ALTER TABLE messages ADD COLUMN summary_source_ids TEXT",
                "content_type": "ALTER TABLE messages ADD COLUMN content_type TEXT",
                "image_path": "ALTER TABLE messages ADD COLUMN image_path TEXT",
                "image_mime": "ALTER TABLE messages ADD COLUMN image_mime TEXT",
                "telegram_file_id": "ALTER TABLE messages ADD COLUMN telegram_file_id TEXT",
                "is_addressed": "ALTER TABLE messages ADD COLUMN is_addressed INTEGER DEFAULT 0",
                "author_is_bot": "ALTER TABLE messages ADD COLUMN author_is_bot INTEGER DEFAULT 0",
                "source_mode": "ALTER TABLE messages ADD COLUMN source_mode TEXT DEFAULT 'normal'",
                "secretary_owner_telegram_id": "ALTER TABLE messages ADD COLUMN secretary_owner_telegram_id INTEGER",
                "secretary_source_chat_id": "ALTER TABLE messages ADD COLUMN secretary_source_chat_id INTEGER",
                "secretary_counterparty_id": "ALTER TABLE messages ADD COLUMN secretary_counterparty_id INTEGER",
                "secretary_session_id": "ALTER TABLE messages ADD COLUMN secretary_session_id INTEGER",
                "secretary_reply_status": "ALTER TABLE messages ADD COLUMN secretary_reply_status TEXT",
                "reply_to_message_id": "ALTER TABLE messages ADD COLUMN reply_to_message_id INTEGER",
            }

            secretary_columns = self._get_table_columns("secretary_profiles")
            secretary_additional_columns = {
                "business_connection_id": "ALTER TABLE secretary_profiles ADD COLUMN business_connection_id TEXT",
                "default_delay_seconds": "ALTER TABLE secretary_profiles ADD COLUMN default_delay_seconds REAL DEFAULT 2.0",
                "burst_window_seconds": "ALTER TABLE secretary_profiles ADD COLUMN burst_window_seconds REAL DEFAULT 2.0",
                "max_batch_messages": "ALTER TABLE secretary_profiles ADD COLUMN max_batch_messages INTEGER DEFAULT 10",
                "default_session_ttl_seconds": "ALTER TABLE secretary_profiles ADD COLUMN default_session_ttl_seconds INTEGER DEFAULT 3600",
                "close_after_reply": "ALTER TABLE secretary_profiles ADD COLUMN close_after_reply INTEGER DEFAULT 0",
                "owner_message_behavior": "ALTER TABLE secretary_profiles ADD COLUMN owner_message_behavior TEXT DEFAULT 'takeover'",
                "turn_based_replies": "ALTER TABLE secretary_profiles ADD COLUMN turn_based_replies INTEGER DEFAULT 1",
                "media_stt_enabled": "ALTER TABLE secretary_profiles ADD COLUMN media_stt_enabled INTEGER DEFAULT 0",
                "media_images_enabled": "ALTER TABLE secretary_profiles ADD COLUMN media_images_enabled INTEGER DEFAULT 0",
            }
            for column, alter_sql in secretary_additional_columns.items():
                if column not in secretary_columns:
                    try:
                        self.cursor.execute(alter_sql)
                        logger.info(f"Добавлена колонка '{column}' в таблицу secretary_profiles")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Не удалось добавить колонку '{column}': {e}")

            pending_columns = self._get_table_columns("secretary_pending_responses")
            pending_additional_columns = {
                "session_id": "ALTER TABLE secretary_pending_responses ADD COLUMN session_id INTEGER",
            }
            for column, alter_sql in pending_additional_columns.items():
                if column not in pending_columns:
                    try:
                        self.cursor.execute(alter_sql)
                        logger.info(f"Добавлена колонка '{column}' в таблицу secretary_pending_responses")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Не удалось добавить колонку '{column}': {e}")

            chat_settings_columns = self._get_table_columns("secretary_chat_settings")
            chat_settings_additional_columns = {
                "delay_seconds": "ALTER TABLE secretary_chat_settings ADD COLUMN delay_seconds REAL",
                "burst_window_seconds": "ALTER TABLE secretary_chat_settings ADD COLUMN burst_window_seconds REAL",
                "max_batch_messages": "ALTER TABLE secretary_chat_settings ADD COLUMN max_batch_messages INTEGER",
                "turn_based_replies": "ALTER TABLE secretary_chat_settings ADD COLUMN turn_based_replies INTEGER",
                "media_images_enabled": "ALTER TABLE secretary_chat_settings ADD COLUMN media_images_enabled INTEGER",
            }
            for column, alter_sql in chat_settings_additional_columns.items():
                if column not in chat_settings_columns:
                    try:
                        self.cursor.execute(alter_sql)
                        logger.info(f"Added column '{column}' to secretary_chat_settings")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Could not add column '{column}': {e}")

            for column, alter_sql in additional_columns.items():
                if column not in existing_columns:
                    try:
                        self.cursor.execute(alter_sql)
                        logger.info(f"Добавлена колонка '{column}' в таблицу messages")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Не удалось добавить колонку '{column}': {e}")

            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_secretary_context "
                "ON messages(source_mode, secretary_owner_telegram_id, secretary_source_chat_id)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_secretary_sessions_active "
                "ON secretary_sessions(owner_telegram_id, chat_id, status, expires_at)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_secretary_events_owner "
                "ON secretary_events(owner_telegram_id, created_at)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_secretary_business_connections_owner "
                "ON secretary_business_connections(owner_telegram_id)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_secretary_response_locks_key "
                "ON secretary_response_locks(owner_telegram_id, chat_id, reply_to_message_id)"
            )
            self.connection.commit()
            logger.info("Таблицы 'users' и 'messages' успешно созданы или обновлены.")
        except Exception as e:
            logger.error(f"Ошибка при создании таблиц: {e}")

    def _get_table_columns(self, table_name: str) -> Set[str]:
        try:
            self.cursor.execute(f"PRAGMA table_info({table_name})")
            columns = {row[1] for row in self.cursor.fetchall()}
            return columns
        except Exception as e:
            logger.error(f"Не удалось получить список колонок для таблицы {table_name}: {e}")
            return set()

    def _run_write(self, operation):
        with BaseDB._write_lock:
            try:
                return operation()
            except Exception:
                try:
                    self.connection.rollback()
                except Exception:
                    pass
                raise

    def close(self):
        self.connection.close()
