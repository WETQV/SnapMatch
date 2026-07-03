# bot/handlers/services/context_manager.py
"""
Модуль для управления контекстом и историей сообщений.
Отвечает за сокращение истории по лимитам контекста модели.
"""

from typing import List, Dict, Tuple
from utils.logger import setup_logger
from utils.tokenizer import count_tokens, count_message_tokens

logger = setup_logger(__name__)


def adjust_history_for_context_limit(messages: List[Dict], model_id: str, settings: Dict) -> Tuple[List[Dict], Dict]:
    """
    Проверяет и при необходимости сокращает историю по лимиту токенов модели.
    
    Args:
        messages: Список сообщений для проверки
        model_id: ID модели для определения лимитов
        settings: Глобальные настройки приложения
        
    Returns:
        Кортеж (сокращённые_сообщения, context_info_dict)
        context_info содержит: status, estimated_tokens, limit, message для пользователя
    """
    # Получаем лимит контекста для модели
    models = settings.get('models', [])
    default_context_length = settings.get('default_context_length', 4096)
    model_context_length = default_context_length
    for model in models:
        if model.get('id') == model_id:
            # Используем новое имя поля: context_window_size
            model_context_length = model.get('context_window_size', default_context_length)
            break

    max_tokens = settings.get('max_tokens', 0) or 0
    # Если max_tokens не задан (0), резерв определяем автоматически (50% окна, минимум 512)
    if max_tokens and max_tokens > 0:
        reserved_for_response = min(max_tokens, int(model_context_length * 0.5))
        if max_tokens > reserved_for_response:
            logger.info(f"max_tokens={max_tokens} превышает половину окна контекста {model_context_length}. Ограничиваем резерв до {reserved_for_response}.")
    else:
        # Увеличиваем резерв до 50% для надежности (вместо 25%)
        # Это гарантирует, что модель не будет обрезана посередине ответа
        reserved_for_response = max(512, int(model_context_length * 0.5))
        logger.debug(f"max_tokens не задан. Автоматический резерв под ответ: {reserved_for_response} токенов")
    
    # Добавляем буфер безопасности для компенсации ошибок подсчёта
    safety_buffer = max(256, int(model_context_length * 0.1))
    available_context = max(256, model_context_length - reserved_for_response - safety_buffer)

    # Подсчет токенов
    total_tokens = count_message_tokens(messages, model_id=model_id)
    logger.debug(f"Анализ контекста для модели {model_id}: {total_tokens}/{available_context} токенов")

    context_info = {
        'estimated_tokens': total_tokens,
        'limit': available_context,
        'model_context_length': model_context_length,
        'reserved_for_response': reserved_for_response
    }

    # Если влезает — оценим статус и вернем как есть
    if total_tokens <= available_context:
        usage_percent = (total_tokens / available_context) * 100 if available_context else 0
        if usage_percent <= 70:
            context_info['status'] = 'ok'
            context_info['message'] = None
        elif usage_percent <= 90:
            context_info['status'] = 'warning'
            # Не показываем сообщение пользователю - логируем только
            logger.debug(f"Контекст заполнен на {usage_percent:.1f}% ({total_tokens}/{available_context} токенов)")
            context_info['message'] = None
        else:
            context_info['status'] = 'warning'
            # Не показываем сообщение пользователю - логируем только
            logger.debug(f"Почти достигнут лимит контекста: {usage_percent:.1f}% ({total_tokens}/{available_context} токенов)")
            context_info['message'] = None
        return messages, context_info

    # Не обрабатываем system сообщения здесь - они будут добавлены позже
    # Просто работаем с user/assistant сообщениями
    system_msg = None
    start_index = 0
    if messages and messages[0].get('role') == 'system':
        # Сохраняем system для подсчёта токенов, но не добавляем в результат
        system_msg = messages[0]
        start_index = 1

    system_tokens = count_tokens(system_msg['content'], model_id=model_id) if system_msg else 0
    budget = max(0, available_context - system_tokens)

    kept_reversed = []
    used = 0
    removed_count = 0
    # Идем с конца, набираем, строго соблюдая чередование ролей
    seq = messages[start_index:]
    if not seq:
        seq_reversed = []
        expected_role = None
    else:
        seq_reversed = list(reversed(seq))
        expected_role = seq_reversed[0].get('role')

    for msg in seq_reversed:
        role = msg.get('role')
        # Пропускаем system сообщения - они обрабатываются отдельно
        if role == 'system':
            continue
        if expected_role is not None and role != expected_role:
            # пропускаем, чтобы сохранить правильное чередование
            removed_count += 1
            continue
        msg_tokens = count_tokens(msg.get('content', ''), model_id=model_id)
        if used + msg_tokens <= budget or not kept_reversed:
            kept_reversed.append(msg)
            used += msg_tokens
            # Меняем ожидаемую роль (user <-> assistant)
            if expected_role == 'user':
                expected_role = 'assistant'
            elif expected_role == 'assistant':
                expected_role = 'user'
        else:
            removed_count += 1

    # НЕ добавляем system в результат - он будет добавлен позже в ensure_alternating_roles
    truncated_messages = list(reversed(kept_reversed))

    # Убрано добавление assistant в начало - это нарушает порядок ролей
    # Если нет assistant в истории - это нормально, модель начнет с user
    # Не нужно принудительно добавлять assistant, это создаст нарушение чередования

    # Финальная проверка
    final_tokens = count_message_tokens(truncated_messages, model_id=model_id)
    if final_tokens > available_context:
        # В редком случае — жестко укорачиваем самый старый из оставшихся
        while truncated_messages and final_tokens > available_context:
            # Не удаляем system; удаляем второе сообщение, если есть
            idx = 1 if system_msg and len(truncated_messages) > 1 else 0
            if idx >= len(truncated_messages):
                break
            removed = truncated_messages.pop(idx)
            removed_count += 1
            final_tokens = count_message_tokens(truncated_messages, model_id=model_id)

    # Убран двойной вызов ensure_alternating_roles()
    # Чередование ролей обеспечивается ОДИН РАЗ после всех операций с контекстом (в process_request)
    # Здесь только сохраняем порядок сообщений

    context_info['status'] = 'truncated' if removed_count > 0 else 'ok'
    context_info['removed_messages'] = removed_count
    context_info['estimated_tokens'] = final_tokens
    # Сообщение для пользователя не отправляем, чтобы не спамить
    context_info['message'] = None

    # Если даже после сокращения не влезает — критическая ситуация
    if final_tokens > available_context:
        context_info['status'] = 'critical'
        # Убрано пугающее сообщение, только логирование
        context_info['message'] = None
        logger.error(f"Критическое переполнение контекста: {final_tokens}/{available_context} токенов после обрезки")

    return truncated_messages, context_info


def check_context_overflow_and_notify(context_info: Dict) -> str:
    """
    Проверяет статус контекста и возвращает сообщение для пользователя, если нужно.
    
    Args:
        context_info: Информация о контексте из adjust_history_for_context_limit
        
    Returns:
        Сообщение для пользователя или None если ничего не нужно отправлять
    """
    if context_info['status'] in ['warning', 'critical']:
        return context_info['message']
    return None


def _calculate_available_context(settings: Dict, model_id: str) -> int:
    """Вспомогательная функция для расчёта доступного контекста."""
    models = settings.get('models', [])
    default_context_length = settings.get('default_context_length', 4096)
    model_context_length = default_context_length
    for model in models:
        if model.get('id') == model_id:
            model_context_length = model.get('context_window_size', default_context_length)
            break

    max_tokens = settings.get('max_tokens', 0) or 0
    if max_tokens and max_tokens > 0:
        reserved_for_response = min(max_tokens, int(model_context_length * 0.5))
    else:
        reserved_for_response = max(512, int(model_context_length * 0.5))

    safety_buffer = max(256, int(model_context_length * 0.1))
    available_context = max(256, model_context_length - reserved_for_response - safety_buffer)
    return available_context


def trim_messages_to_context_limit(messages: List[Dict], model_id: str, settings: Dict) -> tuple:
    """
    Финальное сокращение сообщений если они ещё превышают лимит после объединения ролей.
    
    Args:
        messages: Список сообщений после объединения
        model_id: ID модели
        settings: Глобальные настройки
        
    Returns:
        Кортеж (сокращённые_сообщения, был_ли_сокращен_флаг)
    """
    if not messages:
        return messages, False

    from copy import deepcopy
    available_context = _calculate_available_context(settings, model_id)
    system_msg = None
    trimmed = [deepcopy(msg) for msg in messages]

    if trimmed and trimmed[0].get('role') == 'system':
        system_msg = trimmed[0]
        body = trimmed[1:]
    else:
        body = trimmed

    def compose_sequence(body_msgs):
        if system_msg:
            return [system_msg] + body_msgs
        return body_msgs

    sequence = compose_sequence(body)
    total_tokens = count_message_tokens(sequence, model_id=model_id)
    trimmed_any = False

    while body and total_tokens > available_context:
        removed = body.pop(0)
        trimmed_any = True
        logger.debug(
            "Удалено сообщение %s (role=%s) при финальном сокращении контекста",
            removed.get('id'),
            removed.get('role'),
        )
        sequence = compose_sequence(body)
        total_tokens = count_message_tokens(sequence, model_id=model_id)

    if trimmed_any:
        logger.warning(
            "Контекст сокращён после объединения ролей: %s сообщений осталось, %s токенов",
            len(sequence),
            total_tokens,
        )

    return sequence, trimmed_any

