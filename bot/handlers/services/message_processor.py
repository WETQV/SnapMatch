# bot/handlers/services/message_processor.py
"""
Модуль для подготовки сообщений перед отправкой в модель.
Валидирует структуру, обрабатывает изображения, применяет плейсхолдеры.
"""

import os
from typing import List, Dict, Optional
from utils.logger import setup_logger
from .image_processor import build_image_data_url

logger = setup_logger(__name__)

# Константы для плейсхолдеров
LEGACY_IMAGE_PLACEHOLDER = "[изображение пользователя]"
ROLE_PLACEHOLDER_TEXT = "[нет ответа — служебный плейсхолдер]"


def prepare_model_messages(messages: List[Dict], supports_vision: bool) -> List[Dict]:
    """
    Подготавливает сообщения для отправки в модель с валидацией.
    
    Функция:
    - Валидирует роли сообщений (должны быть: system, user, assistant)
    - Обрабатывает изображения для VLM-моделей
    - Применяет плейсхолдеры для пустых сообщений
    - Пропускает неправильные сообщения с логированием
    
    Args:
        messages: Список сообщений для подготовки
        supports_vision: Поддерживает ли модель визуальные данные (VLM)
        
    Returns:
        Список подготовленных сообщений для модели
    """
    prepared = []
    valid_roles = {'system', 'user', 'assistant'}
    
    for msg in messages:
        # Валидация роли сообщения
        role = msg.get('role')
        if role not in valid_roles:
            logger.warning(f"Пропущено сообщение с недопустимой ролью: {role}")
            continue
        
        # Валидация содержимого
        text_content = msg.get('content', '') or ''
        image_path = msg.get('image_path')
        image_mime = msg.get('image_mime')
        
        if msg.get('was_image_placeholder'):
            logger.debug(
                "Сообщение %s помечено как плейсхолдер изображения (chat_id=%s)",
                msg.get('telegram_message_id'),
                msg.get('chat_id'),
            )

        # Если сообщение только с изображением, но без текста — добавляем плейсхолдер
        if not text_content and not image_path and msg.get('content_type') in {'image', 'image_ref'}:
            text_content = LEGACY_IMAGE_PLACEHOLDER
            msg['content'] = text_content
            msg['was_image_placeholder'] = True
            logger.debug(
                "Добавлен плейсхолдер для пустого изображения в истории (message_id=%s)",
                msg.get('telegram_message_id'),
            )

        # Пропускаем пустые сообщения (кроме system и плейсхолдеров)
        # Плейсхолдеры с content='...' нужны для правильного чередования ролей
        is_placeholder = msg.get('is_placeholder', False)
        if not text_content and not image_path and role != 'system' and not is_placeholder:
            logger.debug(f"Пропущено пустое сообщение с ролью {role}")
            continue
        
        # Для system сообщений и плейсхолдеров разрешаем пустой контент
        if role == 'system' and not text_content:
            text_content = ''  # Пустой system промпт допустим
        elif is_placeholder:
            # Плейсхолдеры всегда имеют единый текст
            text_content = ROLE_PLACEHOLDER_TEXT
            msg['content'] = text_content
        
        # Логируем плейсхолдеры для отладки
        if is_placeholder:
            logger.debug(f"Обработка плейсхолдера: role={role}, content={text_content}")
        
        # Обработка изображений для VLM-моделей
        if supports_vision and image_path:
            parts = []
            
            # Проверяем, есть ли изображение как основной контент (content_type = 'image')
            has_image_content = msg.get('content_type') == 'image'
            
            if has_image_content:
                # Это сообщение с изображением от пользователя
                # Добавляем маркер чтобы модель понимала что фото прислал пользователь, а не она
                if text_content:
                    # Добавляем маркер + текст пользователя
                    parts.append({'type': 'text', 'text': f"[Изображение пользователя]: {text_content}"})
                else:
                    # Только маркер, текста нет
                    parts.append({'type': 'text', 'text': LEGACY_IMAGE_PLACEHOLDER})
            else:
                # Обычное текстовое сообщение (возможно с референсом на изображение)
                if text_content:
                    parts.append({'type': 'text', 'text': text_content})
            
            # Добавляем само изображение
            data_url = build_image_data_url(image_path, image_mime)
            if data_url:
                parts.append({'type': 'image_url', 'image_url': {'url': data_url}})
            
            if parts:
                prepared.append({'role': role, 'content': parts})
        else:
            prepared.append({'role': role, 'content': text_content})
    
    # Проверяем что есть хотя бы одно сообщение
    if not prepared:
        logger.warning("Нет валидных сообщений для отправки в модель")
        return []
    
    return prepared


def _sanitize_messages_for_log(messages: List[Dict]) -> List[Dict]:
    """
    Скрывает base64-данные изображений в логах для читаемости.
    
    Args:
        messages: Список сообщений для санитизации
        
    Returns:
        Список сообщений с замаскированными данными изображений
    """
    sanitized = []
    for msg in messages:
        content = msg.get('content')
        if isinstance(content, list):
            clean_content = []
            for part in content:
                if part.get('type') == 'image_url':
                    clean_content.append({'type': 'image_url', 'image_url': {'url': '[base64 omitted]'}})
                else:
                    clean_content.append(part)
            sanitized.append({'role': msg.get('role'), 'content': clean_content})
        else:
            sanitized.append(msg)
    return sanitized

