# utils/history_manager.py

"""
Менеджер истории сообщений: отвечает за суммаризацию, архивирование и адаптацию контекста
для групповых и приватных чатов с учётом токенов.
"""

from typing import List, Dict, Optional, Tuple
from utils.logger import setup_logger
from utils.tokenizer import count_tokens, count_message_tokens
from utils.database.database_manager import DatabaseManager
import re

logger = setup_logger(__name__)

IMPORTANT_KEYWORDS_RE = re.compile(
    r"\b(итог|результ|решил|решен|важн|план|договор|сделаем|делаем|ошибк|проблем|вопрос)\b",
    re.IGNORECASE,
)


class HistorySummarizer:
    """Класс для суммаризации и управления историей сообщений."""
    
    # Параметры по умолчанию
    DEFAULT_SUMMARY_TRIGGER_RATIO = 0.85  # Начинать суммаризацию при 85% заполнении контекста
    DEFAULT_SUMMARY_MAX_LINES = 8  # Максимум строк в одной сводке (базовое значение)
    DEFAULT_SUMMARY_MAX_CHARS_PER_LINE = 80  # Максимум символов на строку в сводке (базовое значение)
    DEFAULT_MAX_SUMMARIES_IN_PROMPT = 5  # Максимум сводок в системном промпте
    DEFAULT_MIN_MESSAGES_FOR_SUMMARY = 6  # Минимум сообщений перед суммаризацией
    SUMMARY_TOKEN_BUDGET_PER_LINE = 48  # Примерный бюджет токенов на строку сводки
    
    # Адаптивные коэффициенты для разных размеров контекста
    MIN_CONTEXT_FOR_ADAPTIVE = 2048  # Минимальный контекст для адаптации
    BASE_CONTEXT_SIZE = 4096  # Базовый размер контекста для расчётов
    
    def __init__(self, model_id: str, settings: Dict):
        """
        Инициализирует суммаризатор.
        
        Args:
            model_id: ID модели для подсчёта токенов
            settings: Словарь настроек приложения
        """
        self.model_id = model_id
        self.settings = settings
        self.db = DatabaseManager()
        self.summary_enabled = settings.get('history_summary_enabled', True)
        self.trigger_ratio = settings.get('summary_trigger_ratio', self.DEFAULT_SUMMARY_TRIGGER_RATIO)
        self.max_summary_lines = settings.get('summary_max_lines', self.DEFAULT_SUMMARY_MAX_LINES)
        self.max_chars_per_line = settings.get('summary_max_chars_per_line', self.DEFAULT_SUMMARY_MAX_CHARS_PER_LINE)
        self.max_summaries_in_prompt = settings.get('max_summaries_in_prompt', self.DEFAULT_MAX_SUMMARIES_IN_PROMPT)
        self.min_messages_for_summary = settings.get('summary_min_messages', self.DEFAULT_MIN_MESSAGES_FOR_SUMMARY)
    
    def _calculate_adaptive_params(self, available_context: int) -> Tuple[int, int]:
        """
        Рассчитывает адаптивные параметры сводки на основе размера контекста.
        
        Args:
            available_context: Доступный размер контекста в токенах
            
        Returns:
            (max_lines, max_chars_per_line) - адаптивные параметры сводки
        """
        if available_context < self.MIN_CONTEXT_FOR_ADAPTIVE:
            # Для маленьких контекстов используем базовые значения
            return self.max_summary_lines, self.max_chars_per_line
        
        # Коэффициент масштабирования относительно базового контекста (4096)
        scale_factor = available_context / self.BASE_CONTEXT_SIZE
        
        # Адаптируем количество строк (минимум базовое, максимум в 2 раза больше)
        adaptive_lines = max(
            self.max_summary_lines,
            min(int(self.max_summary_lines * scale_factor), self.max_summary_lines * 2)
        )
        
        # Адаптируем длину строки (минимум базовое, максимум в 1.5 раза больше)
        adaptive_chars = max(
            self.max_chars_per_line,
            min(int(self.max_chars_per_line * scale_factor), int(self.max_chars_per_line * 1.5))
        )
        
        return adaptive_lines, adaptive_chars
    
    def _calculate_adaptive_trigger_ratio(self, available_context: int) -> float:
        """
        Рассчитывает адаптивный порог триггера на основе размера контекста.
        
        Для больших контекстов можно триггерить раньше (больше места для сводок).
        Для маленьких контекстов - позже (меньше места).
        
        Args:
            available_context: Доступный размер контекста в токенах
            
        Returns:
            Адаптивный порог триггера (0.0-1.0)
        """
        if available_context < self.MIN_CONTEXT_FOR_ADAPTIVE:
            # Для маленьких контекстов используем базовый порог
            return self.trigger_ratio
        
        # Для больших контекстов можно триггерить раньше
        # Больше контекст = больше места для сводок = можно начинать раньше
        scale_factor = available_context / self.BASE_CONTEXT_SIZE
        
        # Адаптируем порог: для больших контекстов снижаем до 0.75, для маленьких оставляем 0.85
        if scale_factor >= 2.0:  # Контекст >= 8192
            adaptive_ratio = 0.75
        elif scale_factor >= 1.5:  # Контекст >= 6144
            adaptive_ratio = 0.78
        elif scale_factor >= 1.2:  # Контекст >= 4915
            adaptive_ratio = 0.80
        else:
            adaptive_ratio = self.trigger_ratio
        
        return adaptive_ratio
    
    def should_summarize(self, total_tokens: int, available_context: int) -> bool:
        """
        Проверяет, нужно ли начинать суммаризацию контекста.
        
        Args:
            total_tokens: Текущее количество токенов в истории
            available_context: Доступный размер контекста в токенах
            
        Returns:
            True если нужно начинать суммаризацию
        """
        if not self.summary_enabled:
            return False
        
        # Используем адаптивный порог триггера
        adaptive_trigger = self._calculate_adaptive_trigger_ratio(available_context)
        usage_ratio = total_tokens / available_context if available_context > 0 else 0
        
        logger.debug(
            f"Проверка суммаризации: {total_tokens}/{available_context} токенов "
            f"({usage_ratio:.1%}), порог={adaptive_trigger:.1%}"
        )
        
        return usage_ratio >= adaptive_trigger
    
    def _score_message(self, message: Dict) -> int:
        """
        Вычисляет "важность" сообщения для включения в сводку.
        Чем выше результат, тем важнее сообщение.
        """
        if message.get('is_summary') or message.get('is_placeholder'):
            return 0
        
        content = (message.get('content') or '').strip()
        if not content:
            return 0
        
        score = 0
        role = (message.get('role') or '').lower()
        
        if role == 'assistant':
            score += 4
        elif role == 'user':
            score += 1
        
        if message.get('is_addressed'):
            score += 2
        
        if '@' in content:
            score += 1
        if '?' in content:
            score += 1
        if '!' in content:
            score += 1
        
        if IMPORTANT_KEYWORDS_RE.search(content):
            score += 2
        
        token_estimate = count_tokens(content, model_id=self.model_id)
        score += min(token_estimate // 40, 3)
        
        return score
    
    def _select_summary_candidates(self, messages: List[Dict], max_lines: int) -> List[Tuple[int, Dict]]:
        """
        Отбирает сообщения для сводки с учётом важности.
        Возвращает список кортежей (index, message) в хронологическом порядке.
        """
        scored = []
        for idx, msg in enumerate(messages):
            score = self._score_message(msg)
            if score <= 0:
                continue
            scored.append((score, idx, msg))
        
        if not scored:
            fallback = [
                (idx, msg)
                for idx, msg in enumerate(messages)
                if not msg.get('is_summary') and (msg.get('content') or '').strip()
            ]
            return fallback[:max(max_lines, 1)]
        
        scored.sort(key=lambda item: (-item[0], item[1]))
        top = scored[:max(max_lines, 1)]
        top.sort(key=lambda item: item[1])
        return [(item[1], item[2]) for item in top]
    
    def _format_summary_line(self, message: Dict, max_chars: int) -> str:
        """Формирует строку сводки в виде маркера."""
        content = (message.get('content') or '').strip()
        if not content:
            return ""
        
        content_clean = re.sub(r'\s+', ' ', content).strip()
        preview = self._truncate_text(content_clean, max_chars)
        
        role = (message.get('role') or '').lower()
        if role == 'assistant':
            prefix = "Бот"
        else:
            author = (
                message.get('author_full_name')
                or message.get('author_username')
                or (f"user_{message.get('author_telegram_id')}" if message.get('author_telegram_id') else "Участник")
            )
            prefix = f"Bot {author}" if message.get('author_is_bot') else str(author)
        
        return f"- {prefix}: {preview}"
    
    def build_summary(self, messages: List[Dict], available_context: Optional[int] = None) -> Tuple[str, List[int]]:
        """
        Строит краткую сводку из списка сообщений.
        
        Args:
            messages: Список сообщений для суммаризации
            available_context: Доступный размер контекста в токенах (для адаптации размера сводки)
            
        Returns:
            Кортеж (summary_text, included_ids), где summary_text — текст сводки,
            included_ids — список ID сообщений, попавших в неё
        """
        if not messages:
            return "", []
        
        # Используем адаптивные параметры если доступен размер контекста
        if available_context is not None:
            max_lines, max_chars = self._calculate_adaptive_params(available_context)
        else:
            max_lines, max_chars = self.max_summary_lines, self.max_chars_per_line
        
        selected_entries = self._select_summary_candidates(messages, max_lines)
        summary_lines = []
        included_message_ids = []
        token_budget = max(max_lines, 1) * self.SUMMARY_TOKEN_BUDGET_PER_LINE
        used_tokens = 0
        
        for _, msg in selected_entries:
            line = self._format_summary_line(msg, max_chars)
            if not line:
                continue
            
            line_tokens = count_tokens(line, model_id=self.model_id)
            if summary_lines and used_tokens + line_tokens > token_budget:
                logger.debug(
                    "Останавливаем формирование сводки: достигнут лимит токенов (%s/%s)",
                    used_tokens,
                    token_budget,
                )
                break
            
            summary_lines.append(line)
            used_tokens += line_tokens
            msg_id = msg.get('id')
            if msg_id is not None:
                included_message_ids.append(msg_id)
            
            if len(summary_lines) >= max_lines:
                break
        
        # Fallback: если ничего не выбрали (например, короткие реплики), берём первые осмысленные сообщения
        if not summary_lines:
            fallback_entries = [
                (idx, msg)
                for idx, msg in enumerate(messages)
                if not msg.get('is_summary') and (msg.get('content') or '').strip()
            ][:max_lines]
            for _, msg in fallback_entries:
                line = self._format_summary_line(msg, max_chars)
                if line:
                    summary_lines.append(line)
                    msg_id = msg.get('id')
                    if msg_id is not None:
                        included_message_ids.append(msg_id)
        
        # Убираем дубли ID (могут появиться при fallback)
        if included_message_ids:
            included_message_ids = list(dict.fromkeys(included_message_ids))
        
        summary_text = "\n".join(summary_lines)
        
        if available_context is not None:
            logger.debug(
                "Создана адаптивная сводка: %s строк (макс %s), %s символов/строка, контекст=%s токенов, сообщения=%s",
                len(summary_lines),
                max_lines,
                max_chars,
                available_context,
                included_message_ids,
            )
        
        return summary_text, included_message_ids
    
    def _truncate_text(self, text: str, max_chars: int) -> str:
        """Обрезает текст до максимальной длины."""
        if len(text) <= max_chars:
            return text
        return text[:max_chars - 3].rstrip() + "..."
    
    def archive_and_summarize(
        self, 
        chat_id: int, 
        user_id: int, 
        messages_to_archive: List[Dict],
        available_context: Optional[int] = None
    ) -> Optional[Dict]:
        """
        Архивирует старые сообщения и создаёт сводку.
        
        Args:
            chat_id: ID чата
            user_id: ID пользователя (для приватных чатов)
            messages_to_archive: Список сообщений для архивирования
            available_context: Доступный размер контекста в токенах (для адаптации размера сводки)
            
        Returns:
            Словарь с данными новой сводки или None при ошибке
        """
        if not messages_to_archive:
            return None
        
        try:
            # Строим сводку с адаптивными параметрами
            summary_text, highlighted_ids = self.build_summary(messages_to_archive, available_context)
            if not summary_text:
                logger.warning(f"Не удалось построить сводку для чата {chat_id}")
                return None
            
            # Сохраняем сводку в БД как сообщение
            source_ids = ','.join(str(msg['id']) for msg in messages_to_archive)
            
            # 🔧 ИСПРАВЛЕНО: Сохраняем сводку с role='assistant' но с пометкой is_summary
            # Это позволяет не нарушать чередование user/assistant
            # В процессе подготовки сообщений сводка будет обработана особым образом
            self.db.messages.add_message(
                user_id=user_id,
                role='assistant',  # Используем assistant чтобы не нарушать чередование
                content=f"[Сводка истории]\n{summary_text}",
                chat_id=chat_id,
                chat_type='supergroup' if chat_id < 0 else 'private',
                chat_title=None,
                author_telegram_id=None,
                author_username=None,
                author_full_name='[Сводка истории]',
                is_summary=1,
                summary_source_ids=source_ids
            )
            
            # Получаем ID новой сводки
            # 🔧 ИСПРАВЛЕНО: Используем правильный доступ к курсору через DatabaseManager
            self.db.messages.cursor.execute(
                "SELECT id FROM messages WHERE is_summary = 1 AND summary_source_ids = ? ORDER BY id DESC LIMIT 1",
                (source_ids,)
            )
            result = self.db.messages.cursor.fetchone()
            summary_id = result[0] if result else None
            
            # Архивируем исходные сообщения
            message_ids = [msg['id'] for msg in messages_to_archive]
            archived_count = self.db.messages.archive_messages_by_ids(message_ids)
            
            logger.info(
                f"Создана сводка для чата {chat_id}: {len(message_ids)} сообщений архивировано, "
                f"сводка сохранена (ID={summary_id})"
            )
            if highlighted_ids:
                logger.debug(
                    "Сводка %s включает ключевые сообщения: %s",
                    summary_id,
                    highlighted_ids,
                )
            
            # 🔧 ИСПРАВЛЕНО: Возвращаем сводку как assistant с пометкой is_summary
            # Это позволяет не нарушать чередование user/assistant
            # При подготовке к отправке модели сводка будет обработана особым образом
            return {
                'role': 'assistant',
                'content': f"[Сводка истории]\n{summary_text}",
                'id': summary_id,
                'is_summary': 1,
                'content_type': 'text',
                'summary_id': summary_id,
                'archived_count': archived_count,
                'source_ids': message_ids,
                'highlight_ids': highlighted_ids,
            }
            
        except Exception as e:
            logger.error(f"Ошибка при архивировании и суммаризации для чата {chat_id}: {e}")
            return None
    
    def ensure_context_fits(
        self,
        chat_id: int,
        user_id: int,
        messages: List[Dict],
        available_context: int
    ) -> Tuple[List[Dict], Dict]:
        """
        Проверяет контекст и применяет суммаризацию если нужно.
        
        Args:
            chat_id: ID чата
            user_id: ID пользователя
            messages: Список сообщений
            available_context: Доступный размер контекста в токенах
            
        Returns:
            (обновленный список сообщений, информация о выполненной суммаризации)
        """
        total_tokens = count_message_tokens(messages, model_id=self.model_id)
        summary_info = {
            'initial_tokens': total_tokens,
            'initial_message_count': len(messages),
            'summarized': False,
            'summary_created': False
        }
        
        # Если контекст влезает, просто возвращаем
        if total_tokens <= available_context:
            summary_info['status'] = 'ok'
            return messages, summary_info
        
        # Если суммаризация отключена, просто обрезаем
        if not self.summary_enabled:
            summary_info['status'] = 'truncated_no_summary'
            return messages, summary_info
        
        # Проверяем, нужна ли суммаризация
        if not self.should_summarize(total_tokens, available_context):
            summary_info['status'] = 'truncated_no_trigger'
            return messages, summary_info

        # Минимальное количество сообщений для суммаризации (игнорируем системные и сводки)
        non_summary_messages = [
            msg for msg in messages
            if not msg.get('is_summary') and msg.get('role') in {'user', 'assistant'}
        ]
        summary_info['non_summary_message_count'] = len(non_summary_messages)
        if len(non_summary_messages) < self.min_messages_for_summary:
            summary_info['status'] = 'too_few_messages'
            logger.debug(
                "Пропускаем суммаризацию (сообщений недостаточно): %s < %s",
                len(non_summary_messages),
                self.min_messages_for_summary,
            )
            return messages, summary_info
        
        logger.info(
            f"Инициирована суммаризация для чата {chat_id}: "
            f"{total_tokens}/{available_context} токенов (ratio={total_tokens/available_context:.1%})"
        )
        
        # Выделяем сообщения для архивирования (адаптивно в зависимости от размера контекста)
        system_msg = None
        start_idx = 0
        if messages and messages[0].get('role') == 'system':
            system_msg = messages[0]
            start_idx = 1
        
        user_messages = messages[start_idx:]
        
        # 🔧 ИСПРАВЛЕНО: Адаптивный порог архивирования
        # Для больших контекстов можно архивировать больше сообщений (до 50%)
        # Для маленьких контекстов - меньше (30%)
        if available_context >= 8192:  # Большой контекст
            archive_ratio = 0.5  # 50% сообщений
        elif available_context >= 4096:  # Средний контекст
            archive_ratio = 0.4  # 40% сообщений
        else:  # Маленький контекст
            archive_ratio = 0.33  # 33% сообщений (как было)
        
        archive_threshold = max(3, int(len(user_messages) * archive_ratio))
        messages_to_archive = user_messages[:archive_threshold]
        
        logger.debug(
            f"Архивирование: {len(messages_to_archive)} из {len(user_messages)} сообщений "
            f"({archive_ratio:.1%}), контекст={available_context} токенов"
        )
        
        # 🔧 ИСПРАВЛЕНО: Исключаем уже существующие сводки из архивирования
        messages_to_archive = [m for m in messages_to_archive if not m.get('is_summary')]
        
        # Исключаем фиктивные сообщения и записи без ID
        messages_to_archive = [m for m in messages_to_archive if m.get('id') is not None]
        
        if not messages_to_archive:
            summary_info['status'] = 'truncated_no_archive'
            return messages, summary_info
        
        # Проверяем, не являются ли все сообщения для архивирования ассистентом
        non_assistant_count = sum(1 for m in messages_to_archive if m.get('role') != 'assistant')
        if non_assistant_count == 0 and len(messages_to_archive) > 1:
            # Оставляем последнее сообщение ассистента, берём старые user сообщения
            messages_to_archive = messages_to_archive[:-1]
        
        if not messages_to_archive:
            summary_info['status'] = 'truncated_no_archive'
            return messages, summary_info
        
        # Архивируем и создаём сводку с передачей размера контекста для адаптации
        archive_result = self.archive_and_summarize(chat_id, user_id, messages_to_archive, available_context)
        
        if archive_result:
            # Обновляем список сообщений: вместо старых - сводка
            remaining_messages = user_messages[archive_threshold:]
            
            # 🔧 ИСПРАВЛЕНО: Сводка добавляется в начало, но НЕ нарушает чередование
            # Если есть system_msg, сводка идёт после него
            # Если сводка role='assistant', то следующий должен быть user
            # Проверяем первый элемент remaining_messages
            if system_msg:
                # Если есть system, добавляем сводку после него
                new_messages = [system_msg, archive_result]
            else:
                # Если нет system, начинаем со сводки
                new_messages = [archive_result]
            
            # Добавляем оставшиеся сообщения
            new_messages.extend(remaining_messages)
            
            summary_info['summarized'] = True
            summary_info['summary_created'] = True
            summary_info['archived_count'] = archive_result['archived_count']
            summary_info['status'] = 'summarized'
            summary_info['highlight_ids'] = archive_result.get('highlight_ids', [])
            
            new_total_tokens = count_message_tokens(new_messages, model_id=self.model_id)
            summary_info['final_tokens'] = new_total_tokens
            summary_info['final_message_count'] = len(new_messages)
            
            logger.info(
                f"Суммаризация завершена для чата {chat_id}: "
                f"{total_tokens} -> {new_total_tokens} токенов, "
                f"{len(messages)} -> {len(new_messages)} сообщений"
            )
            
            return new_messages, summary_info
        else:
            summary_info['status'] = 'summarize_failed'
            logger.warning(f"Не удалось создать сводку для чата {chat_id}")
            return messages, summary_info
    
    def close(self):
        """Закрывает соединение с БД."""
        self.db.close()


# Кэш суммаризаторов по моделям
_summarizers_cache = {}


def get_history_summarizer(model_id: str, settings: Dict) -> HistorySummarizer:
    """Получает или создаёт суммаризатор для модели."""
    if model_id not in _summarizers_cache:
        _summarizers_cache[model_id] = HistorySummarizer(model_id, settings)
    return _summarizers_cache[model_id]


def reset_history_cache(model_id: Optional[str] = None) -> None:
    """Сбрасывает кэш суммаризаторов (полностью или для конкретной модели)."""
    if model_id:
        _summarizers_cache.pop(model_id, None)
    else:
        _summarizers_cache.clear()
