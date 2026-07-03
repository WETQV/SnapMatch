# bot/handlers/services/text_cleaner.py
"""
Модуль для очистки текста от служебных символов и тегов.
Используется перед отправкой ответа пользователю.
"""

import re
from utils.logger import setup_logger

logger = setup_logger(__name__)


def clean_response(text):
    """
    Очищает текст ответа от служебных тегов и невидимых символов.
    Использует безопасное извлечение из JSON-оберток (Harmony format).
    """
    # Если текст пустой, сразу возвращаем заглушку
    if not text or text.strip() == "":
        return "Извините, не могу сформулировать ответ. Попробуйте перефразировать вопрос."
    
    # Очищаем от скрытых и невидимых Unicode-символов
    text = clean_hidden_characters(text)
    
    # 1. Удаляем мысли модели (<think>...)
    cleaned_text = re.sub(r'<think>[\s\S]*?</think>', '', text)
    cleaned_text = re.sub(r'</?think>', '', cleaned_text)

    # Удаляем сырой XML-подобный вызов инструмента, если модель напечатала его как текст.
    cleaned_text = re.sub(r'<tool_call\b[^>]*>[\s\S]*?</tool_call>', '', cleaned_text, flags=re.IGNORECASE)
    
    # 2. Удаляем служебные токены Harmony/Qwen (<|...|>)
    cleaned_text = re.sub(r'<\|.*?\|>', '', cleaned_text).strip()
    
    # 3. БЕЗОПАСНОЕ извлечение из JSON-обертки
    # Проверяем, не является ли ВЕСЬ текст техническим JSON-контейнером (Harmony format)
    if cleaned_text.startswith('{') and cleaned_text.endswith('}'):
        try:
            import json
            # Пробуем распарсить как JSON
            data = json.loads(cleaned_text)
            # Если это техническая обертка (есть ключ response)
            if isinstance(data, dict) and 'response' in data:
                # Если в словаре ТОЛЬКО один ключ 'response' — это точно техническая обертка
                if len(data) == 1:
                    logger.debug("Извлечен чистый текст из технической JSON-обертки")
                    cleaned_text = str(data['response'])
                else:
                    # Если ключей больше — значит это полезный JSON-контент, не трогаем
                    logger.debug("JSON содержит несколько ключей, расцениваем как полезный контент")
        except Exception:
            # Если это не валидный JSON или не обертка — оставляем как есть
            pass
    
    # 4. Финальная чистка пробелов
    cleaned_text = cleaned_text.strip()
    
    if not cleaned_text:
        return "Извините, не могу сформулировать ответ. Попробуйте перефразировать вопрос."
        
    return cleaned_text


def clean_hidden_characters(text):
    """
    Очищает текст от проблемных невидимых Unicode-символов.
    
    Args:
        text: Исходный текст
        
    Returns:
        Текст без управляющих и скрытых символов
    """
    if not text:
        return text
    
    # Список проблемных Unicode-диапазонов
    control_chars = [
        (0x0000, 0x0008),  # Управляющие символы
        (0x000B, 0x000C),  # Вертикальная табуляция, перевод страницы
        (0x000E, 0x001F),  # Управляющие символы
        (0x007F, 0x009F),  # Расширенные управляющие символы
        (0x00AD, 0x00AD),  # Мягкий перенос
        (0x061C, 0x061C),  # Арабский знак порядка букв
        (0x200B, 0x200F),  # Zero width space и другие невидимые форматирующие символы
        (0x2028, 0x202E),  # Line separator и другие направляющие символы
        (0x2060, 0x2064),  # Word joiner и другие невидимые форматирующие
        (0xFEFF, 0xFEFF),  # BOM (Byte Order Mark)
        (0xFFF9, 0xFFFC)   # Интерлинейные аннотации
    ]
    
    # Заменяем проблемные символы на пробелы
    result = []
    for char in text:
        code = ord(char)
        is_control = any(start <= code <= end for start, end in control_chars)
        result.append(' ' if is_control else char)
    
    cleaned = ''.join(result)
    
    # Если длина изменилась, логируем это
    if len(cleaned) != len(text):
        logger.debug(f"Удалены скрытые символы: было {len(text)}, стало {len(cleaned)}")
    
    return cleaned

