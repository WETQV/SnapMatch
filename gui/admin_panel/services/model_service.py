# gui/admin_panel/services/model_service.py
"""
Сервис для управления моделями.
Содержит бизнес-логику добавления, редактирования, удаления моделей,
отделённую от UI-кода settings_panel.py.
"""

from typing import Dict, List, Optional, Tuple
from config.settings import settings_manager
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ModelService:
    """Сервис управления конфигурацией моделей."""
    VALID_REASONING_MODES = {'default', 'auto', 'off', 'minimal', 'low', 'medium', 'high', 'xhigh'}
    VALID_REASONING_PROVIDERS = {'auto', 'openrouter', 'openai_compatible', 'anthropic_adaptive', 'anthropic_budget'}
    
    @staticmethod
    def get_all_models() -> List[Dict]:
        """Получает список всех моделей из конфига."""
        settings = settings_manager.get_settings()
        return settings.get('models', [])
    
    # Допустимые типы API
    VALID_API_TYPES = {'openai', 'anthropic'}

    @staticmethod
    def normalize_model_data(model_data: Dict) -> Dict:
        normalized = dict(model_data)

        mode = str(normalized.get('reasoning_mode') or '').strip().lower()
        if not mode:
            legacy_enabled = bool(normalized.get('reasoning_enabled', False))
            mode = str(normalized.get('reasoning_effort') or 'medium').strip().lower() if legacy_enabled else 'default'
        if mode == 'none':
            mode = 'off'
        if mode not in ModelService.VALID_REASONING_MODES:
            mode = 'default'

        provider = str(normalized.get('reasoning_provider') or 'auto').strip().lower()
        if provider not in ModelService.VALID_REASONING_PROVIDERS:
            provider = 'auto'

        try:
            budget = int(normalized.get('reasoning_budget_tokens') or 0)
        except (TypeError, ValueError):
            budget = 0

        normalized['reasoning_mode'] = mode
        normalized['reasoning_provider'] = provider
        normalized['reasoning_budget_tokens'] = max(0, budget)
        normalized['reasoning_hide_internal'] = True
        normalized['disable_sampling_for_reasoning'] = bool(
            normalized.get('disable_sampling_for_reasoning', True)
        )
        normalized.pop('reasoning_enabled', None)
        normalized.pop('reasoning_effort', None)
        return normalized

    @staticmethod
    def add_model(model_data: Dict) -> Tuple[bool, str]:
        """
        Добавляет новую модель в конфиг.
        
        Args:
            model_data: Данные модели (id, api_key, base_url, weight, active, api_type,
                        max_concurrent_requests, context_window_size, supports_vision)
            
        Returns:
            (успех, сообщение_об_ошибке_или_успеха)
        """
        model_data = ModelService.normalize_model_data(model_data)

        # Валидация обязательных полей
        if not model_data.get('id') or not model_data.get('api_key') or not model_data.get('base_url'):
            return False, "Все поля должны быть заполнены"
        
        # Валидация api_type
        api_type = model_data.get('api_type', 'openai')
        if api_type not in ModelService.VALID_API_TYPES:
            return False, f"Неизвестный тип API: {api_type}"
        
        # Проверка на дублирование ID
        models = settings_manager.settings.get('models', [])
        for existing_model in models:
            if existing_model.get('id') == model_data['id']:
                return False, f"Модель с ID '{model_data['id']}' уже существует"
        
        # Добавляем модель
        models.append(model_data)
        settings_manager.save_settings()
        
        logger.info(f"Добавлена новая модель: {model_data.get('id')}")
        return True, f"Модель '{model_data['id']}' добавлена успешно"
    
    @staticmethod
    def edit_model(row_index: int, model_data: Dict) -> Tuple[bool, str]:
        """
        Редактирует существующую модель.
        
        Args:
            row_index: Индекс модели в списке
            model_data: Новые данные модели
            
        Returns:
            (успех, сообщение)
        """
        model_data = ModelService.normalize_model_data(model_data)

        models = settings_manager.settings.get('models', [])
        
        if row_index >= len(models):
            return False, "Выбранная модель не найдена"
        
        # Валидация обязательных полей
        if not model_data.get('id') or not model_data.get('api_key') or not model_data.get('base_url'):
            return False, "Все поля должны быть заполнены"
        
        # Валидация api_type
        api_type = model_data.get('api_type', 'openai')
        if api_type not in ModelService.VALID_API_TYPES:
            return False, f"Неизвестный тип API: {api_type}"
        
        # Проверка на дублирование ID (кроме текущей модели)
        for i, model in enumerate(models):
            if i != row_index and model.get('id') == model_data['id']:
                return False, f"Модель с ID '{model_data['id']}' уже существует"
        
        # Обновляем модель
        old_id = models[row_index].get('id')
        models[row_index] = model_data
        settings_manager.save_settings()
        
        logger.info(f"Обновлена модель: {old_id} -> {model_data.get('id')}")
        return True, f"Модель '{model_data['id']}' обновлена успешно"
    
    @staticmethod
    def delete_model(row_index: int) -> Tuple[bool, str]:
        """
        Удаляет модель.
        
        Args:
            row_index: Индекс модели для удаления
            
        Returns:
            (успех, сообщение)
        """
        models = settings_manager.settings.get('models', [])
        
        if row_index >= len(models):
            return False, "Выбранная модель не найдена"
        
        # Проверка на последнюю модель
        if len(models) <= 1:
            return False, "Нельзя удалить последнюю модель. Должна остаться хотя бы одна модель."
        
        model_to_delete = models[row_index]
        model_id = model_to_delete.get('id', 'Unknown')
        
        # Удаляем модель
        del models[row_index]
        settings_manager.save_settings()
        
        logger.info(f"Удалена модель: {model_id}")
        return True, f"Модель '{model_id}' удалена успешно"
    
    @staticmethod
    def toggle_model_active(row_index: int, active: bool) -> Tuple[bool, str]:
        """
        Переключает статус активности модели.
        
        Args:
            row_index: Индекс модели
            active: Новый статус (активна/неактивна)
            
        Returns:
            (успех, сообщение)
        """
        models = settings_manager.settings.get('models', [])
        
        if row_index >= len(models):
            return False, "Модель не найдена"
        
        models[row_index]['active'] = active
        settings_manager.save_settings()
        
        model_id = models[row_index].get('id', 'Unknown')
        status_text = "активирована" if active else "деактивирована"
        logger.info(f"Модель {model_id} {status_text}")
        
        return True, f"Модель {status_text}"
    
    @staticmethod
    def get_model_by_id(model_id: str) -> Optional[Dict]:
        """Получает данные модели по ID."""
        models = ModelService.get_all_models()
        for model in models:
            if model.get('id') == model_id:
                return model
        return None

