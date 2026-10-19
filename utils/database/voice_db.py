from typing import Any, Dict, List, Optional

from .base_db import BaseDB
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Храним только последние записи, чтобы таблица не росла бесконечно
MAX_TRANSCRIPTIONS = 2000
MAX_TEXT_LEN = 4000


class VoiceDB(BaseDB):
    def add_transcription(
        self,
        *,
        chat_id: Optional[int],
        chat_type: Optional[str],
        telegram_message_id: Optional[int],
        author_telegram_id: Optional[int],
        author_username: Optional[str],
        media_type: str,
        engine: Optional[str],
        duration_sec: Optional[float],
        status: str,
        text: str = "",
        error: str = "",
    ) -> bool:
        try:
            def operation():
                self.cursor.execute(
                    """
                    INSERT INTO voice_transcriptions (
                        chat_id, chat_type, telegram_message_id, author_telegram_id,
                        author_username, media_type, engine, duration_sec,
                        status, text, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chat_id, chat_type, telegram_message_id, author_telegram_id,
                        author_username, media_type, engine, duration_sec,
                        status, (text or "")[:MAX_TEXT_LEN], (error or "")[:1000],
                    ),
                )
                self.cursor.execute(
                    "DELETE FROM voice_transcriptions WHERE id <= "
                    "(SELECT MAX(id) FROM voice_transcriptions) - ?",
                    (MAX_TRANSCRIPTIONS,),
                )
                self.connection.commit()

            self._run_write(operation)
            return True
        except Exception as e:
            logger.error(f"Не удалось сохранить расшифровку: {e}")
            return False

    def list_transcriptions(
        self,
        limit: int = 200,
        status: Optional[str] = None,
        author_telegram_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM voice_transcriptions"
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if author_telegram_id is not None:
            where.append("author_telegram_id = ?")
            params.append(author_telegram_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        try:
            self.cursor.execute(sql, params)
            columns = [c[0] for c in self.cursor.description]
            return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
        except Exception as e:
            logger.error(f"Не удалось прочитать историю расшифровок: {e}")
            return []

    def clear_transcriptions(self) -> bool:
        try:
            def operation():
                self.cursor.execute("DELETE FROM voice_transcriptions")
                self.connection.commit()

            self._run_write(operation)
            return True
        except Exception as e:
            logger.error(f"Не удалось очистить историю расшифровок: {e}")
            return False

    def get_voice_stats(self) -> Dict[str, Any]:
        """Агрегаты по расшифровкам (SQL COUNT/SUM/GROUP BY, без загрузки строк)."""
        result: Dict[str, Any] = {
            "total": 0, "ok": 0, "empty": 0, "error": 0,
            "voice": 0, "video_note": 0, "duration_sec": 0.0,
            "engines": {}, "since": None,
        }
        try:
            self.cursor.execute(
                """
                SELECT COUNT(*),
                       COALESCE(SUM(status = 'ok'), 0),
                       COALESCE(SUM(status = 'empty'), 0),
                       COALESCE(SUM(status = 'error'), 0),
                       COALESCE(SUM(status = 'ok' AND media_type = 'voice'), 0),
                       COALESCE(SUM(status = 'ok' AND media_type = 'video_note'), 0),
                       COALESCE(SUM(CASE WHEN status = 'ok' THEN duration_sec END), 0),
                       MIN(created_at)
                FROM voice_transcriptions
                """
            )
            r = self.cursor.fetchone()
            (result["total"], result["ok"], result["empty"], result["error"],
             result["voice"], result["video_note"], result["duration_sec"], result["since"]) = r
            self.cursor.execute(
                """
                SELECT COALESCE(NULLIF(engine, ''), '—'), COUNT(*)
                FROM voice_transcriptions WHERE status = 'ok'
                GROUP BY 1 ORDER BY 2 DESC
                """
            )
            result["engines"] = {k: v for k, v in self.cursor.fetchall()}
        except Exception as e:
            logger.error(f"Не удалось получить статистику расшифровок: {e}")
        return result
