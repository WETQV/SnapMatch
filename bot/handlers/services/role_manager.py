# bot/handlers/services/role_manager.py
"""
Модуль для обеспечения правильного чередования ролей в истории сообщений.
Гарантирует совместимость с требованиями моделей (user/assistant/user/...).
"""

from typing import List, Dict, Optional
from copy import deepcopy
from utils.logger import setup_logger

logger = setup_logger(__name__)


def _merge_message_entries(target: Dict, source: Dict) -> Dict:
    """
    Объединяет два сообщения одной роли в одно единое сообщение.
    
    Args:
        target: Первое сообщение (базовое)
        source: Второе сообщение (добавляется к первому)
        
    Returns:
        Объединённое сообщение с совмещённым контентом
    """
    merged = deepcopy(target)

    content_a = merged.get('content')
    content_b = source.get('content')

    def to_parts(content):
        """Преобразует контент в список частей (для VLM)"""
        if isinstance(content, list):
            return [deepcopy(part) for part in content]
        if content is None or content == "":
            return []
        return [{'type': 'text', 'text': content}]

    if isinstance(content_a, list) or isinstance(content_b, list):
        merged_parts = to_parts(content_a) + to_parts(content_b)
        merged['content'] = merged_parts
    else:
        if content_a and content_b:
            merged['content'] = f"{content_a}\n\n{content_b}"
        else:
            merged['content'] = content_a or content_b

    # Переносим вложения, если они присутствуют в источнике
    if not merged.get('image_path') and source.get('image_path'):
        merged['image_path'] = source.get('image_path')
        merged['image_mime'] = source.get('image_mime')

    # Обновляем тип контента, если необходимо
    if merged.get('content_type') != source.get('content_type'):
        merged['content_type'] = merged.get('content_type') or source.get('content_type')

    # Объединяем вспомогательные флаги
    for flag in ('is_deleted', 'is_placeholder'):
        if source.get(flag):
            merged[flag] = source.get(flag)

    return merged


def ensure_alternating_roles(messages: List[Dict], system_message: Optional[Dict] = None) -> List[Dict]:
    """
    Обеспечивает чередование ролей в истории сообщений (user/assistant/user/...)
    для совместимости с LM Studio и другими моделями.
    
    Если подряд идут два сообщения одной роли, они объединяются в одно.
    
    Args:
        messages: Список сообщений (без system)
        system_message: Опциональное системное сообщение (добавляется в начало)
        
    Returns:
        Новая последовательность сообщений с правильным чередованием ролей
    """
    if not messages:
        return [deepcopy(system_message)] if system_message is not None else []

    result: List[Dict] = []
    if system_message is not None:
        result.append(deepcopy(system_message))

    for msg in messages:
        if not msg:
            continue
        role = msg.get('role')
        if role not in {'user', 'assistant'}:
            continue

        current = deepcopy(msg)

        if not result:
            result.append(current)
            continue

        last_role = result[-1].get('role')
        if last_role == role:
            # Объединяем два сообщения одной роли
            merged = _merge_message_entries(result[-1], current)
            result[-1] = merged
            logger.debug(f"Объединены два сообщения роли {role}")
        else:
            # Добавляем сообщение с альтернативной ролью
            result.append(current)

    logger.debug(
        "История сообщений после обеспечения чередования ролей: %s сообщений",
        len(result),
    )
    logger.debug(f"Последовательность ролей: {[m.get('role') for m in result]}")
    return result

