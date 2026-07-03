# gui/admin_panel/services/stats_service.py
"""
Сервис для работы со статистикой.
Отвечает за сбор и форматирование данных статистики,
отделённый от UI-кода user_management.py.
"""

from pathlib import Path
from typing import Dict, List, Optional
from utils import stats
from utils.logger import setup_logger
from utils.session_stats_storage import SESSION_STATS_FILE, migrate_legacy_session_stats

logger = setup_logger(__name__)

class StatsService:
    """Сервис для работы с статистикой использования бота."""
    
    @staticmethod
    def get_wait_times() -> List[float]:
        """Получает список времён ожидания запросов."""
        try:
            return stats.stats.get_wait_times() if hasattr(stats, 'stats') else []
        except Exception as e:
            logger.error(f"Ошибка при получении времён ожидания: {e}")
            return []
    
    @staticmethod
    def get_response_times() -> List[float]:
        """Получает список времён ответа."""
        try:
            return stats.stats.get_response_times() if hasattr(stats, 'stats') else []
        except Exception as e:
            logger.error(f"Ошибка при получении времён ответа: {e}")
            return []
    
    @staticmethod
    def get_average_wait_time() -> float:
        """Вычисляет среднее время ожидания."""
        try:
            wt = StatsService.get_wait_times()
            return (sum(wt) / len(wt)) if wt else 0.0
        except Exception as e:
            logger.error(f"Ошибка при вычислении среднего времени ожидания: {e}")
            return 0.0
    
    @staticmethod
    def get_average_response_time() -> float:
        """Вычисляет среднее время ответа."""
        try:
            rt = StatsService.get_response_times()
            return (sum(rt) / len(rt)) if rt else 0.0
        except Exception as e:
            logger.error(f"Ошибка при вычислении среднего времени ответа: {e}")
            return 0.0
    
    @staticmethod
    def get_request_count() -> int:
        """Получает общее количество запросов за сеанс."""
        try:
            return stats.stats.get_request_count() if hasattr(stats, 'stats') else 0
        except Exception:
            return 0
    
    @staticmethod
    def get_pending_requests() -> int:
        """Получает количество запросов, ожидающих обработки."""
        try:
            return stats.stats.get_pending_requests() if hasattr(stats, 'stats') else 0
        except Exception:
            return 0
    
    @staticmethod
    def get_input_tokens_total() -> int:
        """Получает общее количество входных токенов."""
        try:
            return stats.stats.get_input_tokens_total() if hasattr(stats, 'stats') else 0
        except Exception:
            return 0
    
    @staticmethod
    def get_output_tokens_total() -> int:
        """Получает общее количество выходных токенов."""
        try:
            return stats.stats.get_output_tokens_total() if hasattr(stats, 'stats') else 0
        except Exception:
            return 0

    @staticmethod
    def get_context_truncated_count() -> int:
        """Получает количество обрезаний контекста."""
        try:
            return stats.stats.get_context_truncated_count() if hasattr(stats, 'stats') else 0
        except Exception:
            return 0

    @staticmethod
    def get_context_truncated_ratio() -> float:
        """Получает процент запросов с обрезанным контекстом."""
        try:
            return stats.stats.get_context_truncated_ratio() if hasattr(stats, 'stats') else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def reset() -> None:
        """Сбрасывает статистику сеанса."""
        try:
            if hasattr(stats, 'stats'):
                stats.stats.reset()
            logger.info("Статистика сеанса сброшена")
        except Exception as e:
            logger.error(f"Ошибка при сбросе статистики: {e}")
    
    @staticmethod
    def get_compact_stats_string(total_users: int, online_users: int) -> str:
        """
        Возвращает компактную строку статистики для вывода.
        Включает: онлайн, запросы, в очереди, токены.
        
        Args:
            total_users: Общее количество пользователей
            online_users: Количество онлайн пользователей
            
        Returns:
            Форматированная строка статистики
        """
        avg_wait = StatsService.get_average_wait_time()
        avg_response = StatsService.get_average_response_time()
        request_count = StatsService.get_request_count()
        pending = StatsService.get_pending_requests()
        
        # Получаем токены
        input_tokens = StatsService.get_input_tokens_total()
        output_tokens = StatsService.get_output_tokens_total()
        total_tokens = input_tokens + output_tokens
        
        # Форматируем время красиво
        wait_str = StatsService._format_time(avg_wait)
        response_str = StatsService._format_time(avg_response)
        
        # Форматируем токены (K для тысяч)
        if total_tokens >= 1000:
            tokens_str = f"{total_tokens/1000:.1f}K"
        else:
            tokens_str = str(total_tokens)
        
        parts = [
            f"О: {online_users}/{total_users}",
            f"З: {request_count}",
            f"Оч: {pending}",
            f"Т: {tokens_str}",
        ]
        
        return " | ".join(parts)

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Форматирует время в удобочитаемый вид."""
        if seconds < 1.0:
            return f"{seconds * 1000:.0f}мс"
        elif seconds < 60.0:
            return f"{seconds:.1f}с"
        else:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}м {secs:.0f}с"

    @staticmethod
    def get_all_current_stats() -> Dict:
        """
        Возвращает все текущие данные статистики в виде словаря.
        Удобно для передачи в UI.
        """
        request_count = StatsService.get_request_count()
        input_tokens = StatsService.get_input_tokens_total()
        output_tokens = StatsService.get_output_tokens_total()
        
        return {
            "request_count": request_count,
            "pending_requests": StatsService.get_pending_requests(),
            "avg_wait_time": StatsService.get_average_wait_time(),
            "avg_response_time": StatsService.get_average_response_time(),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "context_truncated": StatsService.get_context_truncated_count(),
            "context_truncated_ratio": StatsService.get_context_truncated_ratio(),
        }
    
    @staticmethod
    def get_full_stats_text(total_users: int, online_users: int) -> str:
        """
        Возвращает полный текст статистики для диалога.
        
        Args:
            total_users: Общее количество пользователей
            online_users: Количество онлайн пользователей
            
        Returns:
            Форматированный текст со всей статистикой
        """
        data = StatsService.get_all_current_stats()
        
        avg_wait_str = StatsService._format_time(data["avg_wait_time"])
        avg_response_str = StatsService._format_time(data["avg_response_time"])
        
        return f"""Статистика текущего сеанса

  Пользователи онлайн:       {online_users}
  Всего пользователей:       {total_users}

  Запросов за сеанс:         {data['request_count']}
  В очереди:                 {data['pending_requests']}

  Среднее ожидание:          {avg_wait_str}
  Среднее время ответа:      {avg_response_str}

  Входные токены (prompt):   {data['input_tokens']:,}
  Выходные токены (compl.):  {data['output_tokens']:,}
  Всего токенов:             {data['total_tokens']:,}

  Обрезаний контекста:       {data['context_truncated']}"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ИСТОРИЯ СЕАНСОВ (чтение session_stats.txt)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def get_session_stats_path() -> Path:
        """Возвращает путь к файлу истории сеансов."""
        return migrate_legacy_session_stats()

    @staticmethod
    def session_stats_exist() -> bool:
        """Проверяет, существует ли файл истории сеансов."""
        return migrate_legacy_session_stats().exists()

    @staticmethod
    def get_past_sessions(limit: int = 10) -> List[Dict]:
        """
        Читает файл session_stats.txt и парсит последние N сеансов.
        
        Args:
            limit: Максимальное количество последних сеансов
            
        Returns:
            Список словарей с данными сеансов (от новых к старым)
        """
        session_stats_file = migrate_legacy_session_stats()
        if not session_stats_file.exists():
            return []
        
        try:
            text = session_stats_file.read_text(encoding='utf-8')
            blocks = text.strip().split('\n\n')
            
            sessions = []
            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                
                session = StatsService._parse_session_block(block)
                if session:
                    sessions.append(session)
            
            # Возвращаем последние N, от новых к старым
            return list(reversed(sessions[-limit:]))
        
        except Exception as e:
            logger.error(f"Ошибка при чтении истории сеансов: {e}")
            return []

    @staticmethod
    def _parse_session_block(block: str) -> Optional[Dict]:
        """Парсит один блок сеанса из текстового файла."""
        try:
            lines = [line.strip() for line in block.split('\n') if line.strip()]
            if len(lines) < 3:
                return None
            
            session: Dict = {}
            
            for line in lines:
                if line.startswith("Сеанс с "):
                    # Парсим: "Сеанс с 2025-09-19 19:01:46 по 2025-09-19 19:12:38"
                    parts = line.replace("Сеанс с ", "").split(" по ")
                    if len(parts) == 2:
                        session["start"] = parts[0].strip()
                        session["end"] = parts[1].strip()
                elif line.startswith("Продолжительность сеанса:"):
                    session["duration"] = line.split(":", 1)[1].strip()
                elif line.startswith("Количество запросов за сеанс:"):
                    try:
                        session["requests"] = int(line.split(":")[1].strip())
                    except ValueError:
                        session["requests"] = 0
                elif line.startswith("Среднее ожидание:"):
                    session["avg_wait"] = line.split(":")[1].strip()
                elif line.startswith("Среднее время ответа:"):
                    session["avg_response"] = line.split(":")[1].strip()
            
            # Пропускаем пустые / невалидные блоки
            if "start" not in session:
                return None
            
            return session
        
        except Exception as e:
            logger.debug(f"Ошибка при парсинге блока сеанса: {e}")
            return None

    @staticmethod
    def get_total_sessions_count() -> int:
        """Возвращает общее количество сохранённых сеансов."""
        session_stats_file = migrate_legacy_session_stats()
        if not session_stats_file.exists():
            return 0
        try:
            text = session_stats_file.read_text(encoding='utf-8')
            blocks = [b.strip() for b in text.strip().split('\n\n') if b.strip()]
            return len(blocks)
        except Exception:
            return 0
