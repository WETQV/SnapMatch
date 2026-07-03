# bot/handlers/services/__init__.py
"""
Services層 для обработки бизнес-логики обработки сообщений.
Эти модули отвечают за:
- Подготовку сообщений для моделей
- Управление контекстом и историей
- Работу с клиентами моделей
- Чистку текста и обработку изображений
- Обеспечение чередования ролей
- Обработку очереди и групп
"""

# Message and context processing
from .message_processor import prepare_model_messages, _sanitize_messages_for_log
from .text_cleaner import clean_response, clean_hidden_characters
from .role_manager import ensure_alternating_roles, _merge_message_entries
from .context_manager import adjust_history_for_context_limit, trim_messages_to_context_limit

# Model client management
from .model_client_manager import (
    init_model_clients,
    close_all_clients,
    get_response_from_model,
    select_model_for_request,
    get_model_usage_stats,
)

# Image processing
from .image_processor import build_image_data_url, redownload_image

# Prompt management
from .prompt_manager import prepare_system_prompt, get_available_placeholders, validate_system_prompt

# Request processing
from .request_processor import process_request

# Queue and group management
from .queue_processor import QueueProcessor
from .group_manager import GroupManager

__all__ = [
    # Message processing
    'prepare_model_messages',
    '_sanitize_messages_for_log',
    'clean_response',
    'clean_hidden_characters',
    'ensure_alternating_roles',
    '_merge_message_entries',
    'adjust_history_for_context_limit',
    'trim_messages_to_context_limit',
    # Model management
    'init_model_clients',
    'close_all_clients',
    'get_response_from_model',
    'select_model_for_request',
    'get_model_usage_stats',
    # Image
    'build_image_data_url',
    # Prompt
    'prepare_system_prompt',
    'get_available_placeholders',
    'validate_system_prompt',
    # Request
    'process_request',
    # Queue and groups
    'QueueProcessor',
    'GroupManager',
]

