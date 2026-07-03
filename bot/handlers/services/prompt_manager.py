# bot/handlers/services/prompt_manager.py
"""
Сервис для управления и подготовки системных промптов.
Обрабатывает плейсхолдеры и валидирует промпты.
"""

import hashlib
import re
from typing import Dict, Tuple, List
from datetime import datetime

from utils.logger import setup_logger

logger = setup_logger(__name__)


def build_system_prompt_status(prompt: str, updated_at: str = "") -> str:
    prompt = prompt or ""
    if not prompt.strip():
        return "Промпт отключён. Запросы отправляются без пользовательского System Prompt."

    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    saved = updated_at or "время сохранения неизвестно"
    return (
        f"Активен: {len(prompt)} симв. · SHA {digest} · сохранён {saved} · "
        "применяется со следующего запроса"
    )


def prepare_system_prompt(
    prompt: str,
    model_id: str,
    user_data=None,
    chat_id=None,
    chat_type: str = None,
    chat_title: str = None,
    extra_placeholders: Dict[str, str] = None,
) -> str:
    """
    Подготавливает системный промпт с заменой плейсхолдеров.
    Универсальная функция без привязки к конкретным моделям.
    
    Поддерживаемые плейсхолдеры:
    {{model_name}} - название модели
    {{user_name}} - имя пользователя
    {{user_id}} - ID пользователя
    {{chat_id}} - ID чата
    {{char}} - универсальный персонаж (Assistant)
    {{user}} - универсальный пользователь (User)
    {{date}} - текущая дата
    {{time}} - текущее время
    """
    try:
        # Проверка на пустой промпт
        if not prompt or prompt.strip() == "":
            logger.info(f"Системный промпт пуст для модели {model_id}, модель будет работать без системного промпта")
            return None
        
        # Подготовка данных для замены плейсхолдеров
        now = datetime.now()
        
        # Базовые плейсхолдеры
        placeholders = {
            '{{model_name}}': model_id,
            '{{char}}': 'Assistant',
            '{{user}}': 'User',
            '{{date}}': now.strftime('%Y-%m-%d'),
            '{{time}}': now.strftime('%H:%M:%S'),
            '{{datetime}}': now.strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        # Добавляем пользовательские данные, если есть
        if user_data:
            placeholders.update({
                '{{user_name}}': user_data.get('first_name', 'User'),
                '{{user_id}}': str(user_data.get('telegram_id', '')),
            })
        
        if chat_id:
            placeholders['{{chat_id}}'] = str(chat_id)
        if chat_type:
            placeholders['{{chat_type}}'] = chat_type
        if chat_title:
            placeholders['{{chat_title}}'] = chat_title

        for key, value in (extra_placeholders or {}).items():
            placeholder = key if str(key).startswith('{{') else '{{' + str(key).strip('{}') + '}}'
            placeholders[placeholder] = str(value or "")

        try:
            from utils import server_state, stats
            placeholders['{{bot_name}}'] = (
                server_state.bot_full_name
                or server_state.bot_username
                or 'Assistant'
            )
            placeholders['{{pending_requests}}'] = str(stats.stats.get_pending_requests())
        except Exception:
            pass
        
        # Применяем дефолты из настроек
        try:
            from config.settings import settings_manager
            ph_defaults = settings_manager.get_settings().get('placeholder_defaults', {}) or {}
            if ph_defaults.get('model_name'):
                placeholders['{{model_name}}'] = ph_defaults.get('model_name')
        except Exception:
            pass

        # Заменяем плейсхолдеры
        processed_prompt = prompt
        for placeholder, value in placeholders.items():
            if placeholder in processed_prompt:
                processed_prompt = processed_prompt.replace(placeholder, value)
                logger.debug(f"Заменен плейсхолдер {placeholder} на {value}")
        
        # Логируем результат
        logger.debug(f"Обработанный системный промпт для модели {model_id}: {processed_prompt[:100]}...")
        
        return processed_prompt
        
    except Exception as e:
        logger.error(f"Ошибка при подготовке системного промпта: {e}")
        return None


def get_secretary_placeholders() -> Dict[str, str]:
    return {
        '{{owner_name}}': 'Имя владельца секретаря, от лица которого бот отвечает',
        '{{owner_id}}': 'Telegram ID владельца секретаря',
        '{{counterparty_name}}': 'Имя собеседника в secretary-чате, если доступно',
        '{{counterparty_id}}': 'Telegram ID собеседника в secretary-чате, если доступно',
        '{{secretary_chat_id}}': 'ID business/private чата, где работает секретарь',
    }


def get_available_placeholders(include_secretary: bool = False) -> Dict[str, str]:
    """
    Возвращает список всех доступных плейсхолдеров с их описанием.
    Полезно для отображения пользователю или в настройках.
    """
    placeholders = {
        '{{model_name}}': 'Название модели (если пусто — берём фактический ID активной модели)',
        '{{bot_name}}': 'Отображаемое имя бота (как его видят пользователи)',
        '{{user_name}}': 'Имя пользователя из Telegram профиля (подставляется автоматически)',
        '{{user_id}}': 'Telegram ID пользователя',
        '{{chat_id}}': 'ID текущего чата',
        '{{chat_type}}': 'Тип чата (private / group / supergroup)',
        '{{chat_title}}': 'Название группового чата (если доступно)',
        '{{char}}': 'Имя персонажа ассистента (по умолчанию Assistant)',
        '{{user}}': 'Имя персонажа пользователя (по умолчанию User)',
        '{{date}}': 'Текущая дата (ГГГГ-ММ-ДД)',
        '{{time}}': 'Текущее время (ЧЧ:ММ:СС)',
        '{{datetime}}': 'Текущие дата и время (ГГГГ-ММ-ДД ЧЧ:ММ:СС)',
        '{{pending_requests}}': 'Текущее количество запросов, ожидающих обработки',
    }
    if include_secretary:
        placeholders.update(get_secretary_placeholders())
        placeholders['{{user_name}}'] = 'В режиме секретаря: имя владельца. Для собеседника используйте {{counterparty_name}}'
        placeholders['{{user_id}}'] = 'В режиме секретаря: Telegram ID владельца. Для собеседника используйте {{counterparty_id}}'
    return placeholders


def validate_system_prompt(prompt: str, include_secretary: bool = False) -> Tuple[bool, List[str], List[str]]:
    """
    Проверяет системный промпт на потенциальные проблемы.
    
    Args:
        prompt: Системный промпт для проверки
        
    Returns:
        (is_valid, warnings, recommendations)
    """
    warnings = []
    recommendations = []
    
    # Пустой промпт теперь допустим - модель будет работать без системного промпта
    if not prompt or prompt.strip() == "":
        return True, [], ["Модель будет работать без системного промпта (это нормально)"]
    
    # Проверяем длину
    if len(prompt) > 2000:
        warnings.append(f"Длинный системный промпт ({len(prompt)} символов)")
        recommendations.append("Рассмотрите возможность сокращения промпта")
    
    # Проверяем неизвестные плейсхолдеры
    placeholders_in_prompt = re.findall(r'\{\{[^}]+\}\}', prompt)
    known_placeholders = set(get_available_placeholders(include_secretary=include_secretary).keys())
    
    unknown_placeholders = [p for p in placeholders_in_prompt if p not in known_placeholders]
    if unknown_placeholders:
        warnings.append(f"Неизвестные плейсхолдеры: {', '.join(unknown_placeholders)}")
        recommendations.append(f"Доступные плейсхолдеры: {', '.join(known_placeholders)}")
    
    # Проверяем потенциально проблемные инструкции
    problematic_patterns = [
        (r'ignore.{0,20}previous.{0,20}instruction', "Инструкции игнорирования могут вызвать проблемы"),
        (r'jailbreak|bypass|hack', "Инструкции обхода ограничений"),
        (r'act.{0,10}as.{0,10}developer.{0,10}mode', "Режим разработчика может быть нестабильным"),
    ]
    
    for pattern, warning_text in problematic_patterns:
        if re.search(pattern, prompt, re.IGNORECASE):
            warnings.append(warning_text)
            recommendations.append("Используйте более прямые и четкие инструкции")
    
    is_valid = len([w for w in warnings if 'Пустой' in w]) == 0
    return is_valid, warnings, recommendations

