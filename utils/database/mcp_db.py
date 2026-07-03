import json
from typing import Any, Dict, List, Optional

from .base_db import BaseDB
from utils.logger import setup_logger

logger = setup_logger(__name__)


class McpDB(BaseDB):
    def add_tool_call(
        self,
        *,
        server_name: str,
        tool_name: str,
        request_context: Optional[Dict[str, Any]] = None,
        status: str,
        arguments: Optional[Dict[str, Any]] = None,
        result_preview: str = "",
        error: str = "",
        duration_ms: Optional[int] = None,
    ) -> bool:
        context = request_context or {}
        arguments_summary = self._summarize_arguments(arguments or {})
        try:
            def operation():
                self.cursor.execute(
                    """
                    INSERT INTO mcp_tool_calls (
                        server_name,
                        tool_name,
                        actor_telegram_id,
                        chat_id,
                        source_mode,
                        status,
                        arguments_summary,
                        result_preview,
                        error,
                        duration_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        server_name,
                        tool_name,
                        context.get("actor_telegram_id"),
                        context.get("chat_id"),
                        context.get("source_mode"),
                        status,
                        arguments_summary,
                        self._truncate(result_preview, 1200),
                        self._truncate(error, 1200),
                        duration_ms,
                    ),
                )
                self.connection.commit()

            self._run_write(operation)
            self.prune_tool_calls()
            return True
        except Exception as e:
            logger.error(f"Ошибка записи MCP tool call audit: {e}")
            return False

    def add_access_denied(
        self,
        *,
        server_name: str = "",
        tool_name: str = "",
        request_context: Optional[Dict[str, Any]] = None,
        reason: str,
    ) -> bool:
        context = request_context or {}
        try:
            def operation():
                self.cursor.execute(
                    """
                    INSERT INTO mcp_access_audit (
                        server_name,
                        tool_name,
                        actor_telegram_id,
                        chat_id,
                        source_mode,
                        reason
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        server_name,
                        tool_name,
                        context.get("actor_telegram_id"),
                        context.get("chat_id"),
                        context.get("source_mode"),
                        reason,
                    ),
                )
                self.connection.commit()

            self._run_write(operation)
            self.prune_access_audit()
            return True
        except Exception as e:
            logger.error(f"Ошибка записи MCP access audit: {e}")
            return False

    def upsert_server_status(
        self,
        *,
        server_name: str,
        status: str,
        details: str = "",
        tools_count: int = 0,
    ) -> bool:
        try:
            def operation():
                self.cursor.execute(
                    """
                    INSERT INTO mcp_server_status (server_name, status, details, tools_count)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(server_name) DO UPDATE SET
                        status = excluded.status,
                        details = excluded.details,
                        tools_count = excluded.tools_count,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (server_name, status, self._truncate(details, 1200), int(tools_count or 0)),
                )
                self.connection.commit()

            self._run_write(operation)
            return True
        except Exception as e:
            logger.error(f"Ошибка записи MCP server status: {e}")
            return False

    def list_server_statuses(self) -> List[Dict[str, Any]]:
        try:
            self.cursor.execute("SELECT * FROM mcp_server_status ORDER BY updated_at DESC")
            rows = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка чтения MCP server statuses: {e}")
            return []

    def list_tool_calls(self, limit: int = 50, server_name: str = "") -> List[Dict[str, Any]]:
        try:
            query = "SELECT * FROM mcp_tool_calls"
            params = []
            if server_name:
                query += " WHERE server_name = ?"
                params.append(server_name)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            self.cursor.execute(query, tuple(params))
            rows = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка чтения MCP tool calls: {e}")
            return []

    def list_access_denials(self, limit: int = 50, server_name: str = "") -> List[Dict[str, Any]]:
        try:
            query = "SELECT * FROM mcp_access_audit"
            params = []
            if server_name:
                query += " WHERE server_name = ?"
                params.append(server_name)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            self.cursor.execute(query, tuple(params))
            rows = self.cursor.fetchall()
            return [dict(zip([column[0] for column in self.cursor.description], row)) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка чтения MCP access audit: {e}")
            return []

    def prune_tool_calls(self) -> int:
        try:
            from config.settings import settings_manager

            retention = settings_manager.get_settings().get("audit_retention", {}) or {}
            days = int(retention.get("mcp_tool_calls_days", 90) or 0)
            max_rows = int(retention.get("mcp_tool_calls_max", 10000) or 0)
            return self._prune_table(
                "mcp_tool_calls",
                days=days,
                max_rows=max_rows,
                date_column="created_at",
            )
        except Exception as e:
            logger.error(f"Ошибка очистки MCP tool call audit: {e}")
            return 0

    def prune_access_audit(self) -> int:
        try:
            from config.settings import settings_manager

            retention = settings_manager.get_settings().get("audit_retention", {}) or {}
            days = int(retention.get("mcp_access_audit_days", 90) or 0)
            max_rows = int(retention.get("mcp_access_audit_max", 10000) or 0)
            return self._prune_table(
                "mcp_access_audit",
                days=days,
                max_rows=max_rows,
                date_column="created_at",
            )
        except Exception as e:
            logger.error(f"Ошибка очистки MCP access audit: {e}")
            return 0

    def _prune_table(self, table_name: str, *, days: int, max_rows: int, date_column: str = "created_at") -> int:
        allowed_tables = {"mcp_tool_calls", "mcp_access_audit"}
        if table_name not in allowed_tables:
            return 0
        try:
            def operation():
                deleted = 0
                if days > 0:
                    self.cursor.execute(
                        f"DELETE FROM {table_name} WHERE {date_column} < datetime('now', ?)",
                        (f"-{days} days",),
                    )
                    deleted += self.cursor.rowcount
                if max_rows > 0:
                    self.cursor.execute(
                        f"""
                        DELETE FROM {table_name}
                        WHERE id NOT IN (
                            SELECT id FROM {table_name}
                            ORDER BY {date_column} DESC, id DESC
                            LIMIT ?
                        )
                        """,
                        (max_rows,),
                    )
                    deleted += self.cursor.rowcount
                self.connection.commit()
                return deleted

            return int(self._run_write(operation) or 0)
        except Exception as e:
            logger.error(f"Ошибка очистки таблицы {table_name}: {e}")
            return 0

    @staticmethod
    def _truncate(value: Any, limit: int) -> str:
        text = str(value or "")
        return text if len(text) <= limit else text[:limit] + "...[truncated]"

    @staticmethod
    def _summarize_arguments(arguments: Dict[str, Any]) -> str:
        summary = {
            "keys": sorted(str(key) for key in arguments.keys()),
            "count": len(arguments),
        }
        return json.dumps(summary, ensure_ascii=False)
