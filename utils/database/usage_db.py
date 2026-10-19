from typing import Any, Dict, List, Optional

from .base_db import BaseDB
from utils.logger import setup_logger

logger = setup_logger(__name__)

MAX_ROWS = 50000
PRUNE_EVERY = 500


class UsageDB(BaseDB):
    """Учёт токенов по моделям (таблица token_usage)."""

    _inserts = 0

    def add_usage(self, model_id: Optional[str], input_tokens: int, output_tokens: int) -> bool:
        input_tokens = max(0, int(input_tokens or 0))
        output_tokens = max(0, int(output_tokens or 0))
        if not input_tokens and not output_tokens:
            return False
        try:
            def operation():
                self.cursor.execute(
                    "INSERT INTO token_usage (model_id, input_tokens, output_tokens) VALUES (?, ?, ?)",
                    (str(model_id) if model_id else None, input_tokens, output_tokens),
                )
                self.connection.commit()

            self._run_write(operation)
            UsageDB._inserts += 1
            if UsageDB._inserts % PRUNE_EVERY == 0:
                self._prune()
            return True
        except Exception as e:
            logger.error(f"Ошибка записи учёта токенов: {e}")
            return False

    def _prune(self) -> None:
        try:
            def operation():
                self.cursor.execute(
                    "DELETE FROM token_usage WHERE id <= (SELECT MAX(id) FROM token_usage) - ?", (MAX_ROWS,)
                )
                self.connection.commit()

            self._run_write(operation)
        except Exception as e:
            logger.warning(f"Не удалось почистить token_usage: {e}")

    def get_usage_by_model(self, top: int = 8) -> Dict[str, Any]:
        """Токены и запросы по моделям; строки без model_id (старые записи) идут отдельной группой."""
        result: Dict[str, Any] = {"models": [], "total_in": 0, "total_out": 0, "requests": 0}
        try:
            self.cursor.execute(
                """
                SELECT model_id, COUNT(*), COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0)
                FROM token_usage
                GROUP BY model_id
                ORDER BY 3 + 4 DESC
                """
            )
            rows: List[Dict[str, Any]] = [
                {"model": r[0], "requests": r[1], "input": r[2], "output": r[3]}
                for r in self.cursor.fetchall()
            ]
            result["total_in"] = sum(r["input"] for r in rows)
            result["total_out"] = sum(r["output"] for r in rows)
            result["requests"] = sum(r["requests"] for r in rows)
            result["models"] = rows[: int(top)]
            result["more"] = max(0, len(rows) - int(top))
        except Exception as e:
            logger.error(f"Не удалось получить токены по моделям: {e}")
        return result
