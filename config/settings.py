# config/settings.py

import json
import os
import random
from utils.encryption import encryption

SETTINGS_FILE = 'config.json'
SYSTEM_PROMPT_HISTORY_FILE = 'system_prompt_history.json'
SYSTEM_PROMPT_TEMPLATES_FILE = 'system_prompt_templates.json'

DEFAULT_SECRETARY_MODE = {
    "enabled": False,
    "default_delay_seconds": 2.0,
    "default_burst_window_seconds": 2.0,
    "default_max_batch_messages": 10,
    "default_session_ttl_seconds": 3600,
    "allow_infinite_sessions": True,
    "suppress_model_unavailable_notice": True,
    "owners": [],
}

DEFAULT_RICH_MESSAGES = {
    "enabled": False,
    "format": "markdown",
    "fallback_to_legacy": True,
    "skip_entity_detection": False,
    "streaming_enabled": True,
    "stream_draft_interval_seconds": 0.8,
}


def default_secretary_mode():
    data = DEFAULT_SECRETARY_MODE.copy()
    data["owners"] = []
    return data


def default_rich_messages():
    return DEFAULT_RICH_MESSAGES.copy()


class SettingsManager:
    def __init__(self):
        if not os.path.exists(SETTINGS_FILE):
            self.settings = {
                "telegram_token": "",
                "database_path": "database.db",
                "log_file": "app.log",
                "temperature": 0.7,
                "max_tokens": 0,
                "presence_penalty": 0.0,
                "frequency_penalty": 0.0,
                "top_p": 0.95,
                "top_k": 40, 
                "repeat_penalty": 1.1,
                "seed": -1,
                "system_prompt": "",
                "default_context_length": 4096,
                "chat_system_notifications": True,
                "format_markdown": True,
                "format_html": True,
                "rich_messages": default_rich_messages(),
                "admin_telegram_ids": [],
                "telegram_menu": {
                    "enabled": True,
                    "allow_group_menu": True,
                    "colored_buttons_enabled": True,
                    "custom_emoji_ids": {},
                    "delete_menu_after_seconds": 300,
                    "require_confirm_for_dangerous_actions": True
                },
                "mcp": {
                    "enabled": False,
                    "limits": {
                        "tool_timeout_seconds": 30,
                        "max_tool_calls_per_request": 5,
                        "max_tool_result_chars": 12000
                    },
                    "servers": []
                },
                "audit_retention": {
                    "secretary_events_days": 90,
                    "secretary_events_max_per_owner": 2000,
                    "mcp_tool_calls_days": 90,
                    "mcp_tool_calls_max": 10000,
                    "mcp_access_audit_days": 90,
                    "mcp_access_audit_max": 10000
                },
                "placeholder_defaults": {
                    "model_name": "",
                    "user_name": ""
                },
                "load_balancing_strategy": "round_robin",
                "group_parallel_mode": False,
                "accept_bot_messages": True,
                "bot_access_policy": {
                    "mode": "all",
                    "allow_bot_ids": [],
                    "deny_bot_ids": [],
                    "apply_in_private": True,
                    "apply_in_groups": True,
                    "apply_in_secretary": False
                },
                "history_summary_enabled": True,
                "summary_trigger_ratio": 0.85,
                "summary_max_lines": 8,
                "summary_max_chars_per_line": 80,
                "summary_min_messages": 6,
                "max_summaries_in_prompt": 5,  # Максимум сводок в системном промпте
                "respond_only_on_mention": False,
                "reject_empty_mentions": True,
                "secretary_mode": default_secretary_mode(),
                "oled_mode": False,
                "stt_enabled": False,
                "stt_engine": "vosk",  # "vosk", "openai", "groq"
                "stt_model_path": "assets/models/stt/vosk",
                "stt_annotate": False,
                "stt_openai_key": "",
                "stt_openai_model": "whisper-1",
                "stt_groq_key": "",
                "stt_groq_model": "whisper-large-v3",
                "models": [
                    {
                        "id": "gpt-3.5-turbo",
                        "api_key": "",
                        "base_url": "https://api.openai.com/v1",
                        "weight": 1,
                        "supports_vision": False,
                        "reasoning_mode": "default",
                        "reasoning_provider": "auto",
                        "reasoning_budget_tokens": 0,
                        "reasoning_hide_internal": True,
                        "disable_sampling_for_reasoning": True,
                        "api_type": "openai"
                    }
                ]
            }
            self.save_settings()
        else:
            self.load_settings()
        
        if 'group_parallel_mode' not in self.settings:
            self.settings['group_parallel_mode'] = False
        if 'accept_bot_messages' not in self.settings:
            self.settings['accept_bot_messages'] = True
        self._ensure_bot_access_policy()
        if 'placeholder_defaults' not in self.settings:
            self.settings['placeholder_defaults'] = {"model_name": "", "user_name": ""}
        else:
            self.settings['placeholder_defaults'].setdefault('model_name', "")
            self.settings['placeholder_defaults'].setdefault('user_name', "")
        if 'admin_telegram_ids' not in self.settings:
            self.settings['admin_telegram_ids'] = []
        else:
            self.settings['admin_telegram_ids'] = self._normalize_telegram_id_list(
                self.settings.get('admin_telegram_ids')
            )
        self._ensure_telegram_menu_settings()
        self._ensure_mcp_settings()
        self._ensure_audit_retention_settings()
        migrated_prompt_storage = False
        if 'system_prompt_history' not in self.settings:
            self.settings['system_prompt_history'] = []
        history_migrated = self._migrate_legacy_prompt_history()
        templates_migrated = self._migrate_legacy_prompt_templates()
        if history_migrated or templates_migrated:
            self.save_settings()
        
        # Инициализируем параметры суммаризации если их нет
        if 'history_summary_enabled' not in self.settings:
            self.settings['history_summary_enabled'] = True
        if 'summary_trigger_ratio' not in self.settings:
            self.settings['summary_trigger_ratio'] = 0.85
        if 'summary_max_lines' not in self.settings:
            self.settings['summary_max_lines'] = 8
        if 'summary_max_chars_per_line' not in self.settings:
            self.settings['summary_max_chars_per_line'] = 80
        if 'summary_min_messages' not in self.settings:
            self.settings['summary_min_messages'] = 6
        if 'max_summaries_in_prompt' not in self.settings:
            self.settings['max_summaries_in_prompt'] = 5
        if 'respond_only_on_mention' not in self.settings:
            self.settings['respond_only_on_mention'] = False
        if 'reject_empty_mentions' not in self.settings:
            self.settings['reject_empty_mentions'] = True
        self._ensure_secretary_defaults()
        self._ensure_rich_messages_defaults()
        if 'oled_mode' not in self.settings:
            self.settings['oled_mode'] = False
        if 'stt_enabled' not in self.settings:
            self.settings['stt_enabled'] = False
        if 'stt_engine' not in self.settings:
            self.settings['stt_engine'] = "vosk"
        if 'stt_model_path' not in self.settings:
            self.settings['stt_model_path'] = "assets/models/stt/vosk"
        if 'stt_annotate' not in self.settings:
            self.settings['stt_annotate'] = False
        if 'stt_openai_key' not in self.settings:
            self.settings['stt_openai_key'] = ""
        if 'stt_openai_model' not in self.settings:
            self.settings['stt_openai_model'] = "whisper-1"
        if 'stt_groq_key' not in self.settings:
            self.settings['stt_groq_key'] = ""
        if 'stt_groq_model' not in self.settings:
            self.settings['stt_groq_model'] = "whisper-large-v3"
        
        # Инициализируем индекс для round-robin
        self.current_model_index = 0
        
        # Инициализируем счетчики загрузки моделей
        self.model_loads = {model["id"]: 0 for model in self.settings.get("models", [])}

        # Обновляем модели новыми полями при необходимости (миграция старых конфигов)
        valid_api_types = {"openai", "anthropic"}
        for model in self.settings.get("models", []):
            if 'supports_vision' not in model:
                model['supports_vision'] = False
            if 'reasoning_mode' not in model:
                if model.get('reasoning_enabled'):
                    legacy_effort = str(model.get('reasoning_effort') or 'medium').strip().lower()
                    model['reasoning_mode'] = 'off' if legacy_effort == 'none' else legacy_effort
                else:
                    model['reasoning_mode'] = 'default'
            if model.get('reasoning_mode') not in {'default', 'auto', 'off', 'minimal', 'low', 'medium', 'high', 'xhigh'}:
                model['reasoning_mode'] = 'default'
            if 'reasoning_provider' not in model:
                model['reasoning_provider'] = 'auto'
            if model.get('reasoning_provider') not in {'auto', 'openrouter', 'openai_compatible', 'anthropic_adaptive', 'anthropic_budget'}:
                model['reasoning_provider'] = 'auto'
            if 'reasoning_budget_tokens' not in model:
                model['reasoning_budget_tokens'] = 0
            if 'reasoning_hide_internal' not in model:
                model['reasoning_hide_internal'] = True
            if 'disable_sampling_for_reasoning' not in model:
                model['disable_sampling_for_reasoning'] = True
            if 'max_concurrent_requests' not in model:
                model['max_concurrent_requests'] = 1
            if 'context_window_size' not in model:
                model['context_window_size'] = self.settings.get('default_context_length', 4096)
            # Миграция: модели без api_type получают "openai" (обратная совместимость)
            if 'api_type' not in model or model['api_type'] not in valid_api_types:
                model['api_type'] = 'openai'

    @staticmethod
    def _normalize_telegram_id_list(value):
        if value is None:
            return []

        if isinstance(value, str):
            raw_items = value.replace('\n', ',').replace(';', ',').split(',')
        elif isinstance(value, (list, tuple, set)):
            raw_items = value
        else:
            raw_items = [value]

        normalized = []
        seen = set()
        for item in raw_items:
            text = str(item).strip()
            if not text:
                continue
            try:
                telegram_id = int(text)
            except (TypeError, ValueError):
                continue
            if telegram_id not in seen:
                normalized.append(telegram_id)
                seen.add(telegram_id)
        return normalized

    def _ensure_telegram_menu_settings(self):
        defaults = {
            "enabled": True,
            "allow_group_menu": True,
            "colored_buttons_enabled": True,
            "custom_emoji_ids": {},
            "delete_menu_after_seconds": 300,
            "require_confirm_for_dangerous_actions": True,
        }
        current = self.settings.get('telegram_menu')
        if not isinstance(current, dict):
            self.settings['telegram_menu'] = defaults
            return
        for key, value in defaults.items():
            current.setdefault(key, value)

    def _ensure_bot_access_policy(self):
        defaults = {
            "mode": "all",
            "allow_bot_ids": [],
            "deny_bot_ids": [],
            "apply_in_private": True,
            "apply_in_groups": True,
            "apply_in_secretary": False,
        }
        current = self.settings.get('bot_access_policy')
        if not isinstance(current, dict):
            self.settings['bot_access_policy'] = defaults
            return

        for key, value in defaults.items():
            current.setdefault(key, value)

        if str(current.get('mode', 'all')).strip().lower() not in {'all', 'off', 'allowlist', 'denylist'}:
            current['mode'] = 'all'
        else:
            current['mode'] = str(current.get('mode', 'all')).strip().lower()

        current['allow_bot_ids'] = self._normalize_telegram_id_list(current.get('allow_bot_ids'))
        current['deny_bot_ids'] = self._normalize_telegram_id_list(current.get('deny_bot_ids'))
        current['apply_in_private'] = bool(current.get('apply_in_private', True))
        current['apply_in_groups'] = bool(current.get('apply_in_groups', True))
        current['apply_in_secretary'] = bool(current.get('apply_in_secretary', False))

    def _ensure_mcp_settings(self):
        current = self.settings.get('mcp')
        if not isinstance(current, dict):
            self.settings['mcp'] = {"enabled": False, "servers": []}
            return
        current.setdefault('enabled', False)
        limits = current.setdefault('limits', {})
        if not isinstance(limits, dict):
            limits = {}
            current['limits'] = limits
        limits.setdefault('tool_timeout_seconds', 30)
        limits.setdefault('max_tool_calls_per_request', 5)
        limits.setdefault('max_tool_result_chars', 12000)
        if not isinstance(current.get('servers'), list):
            current['servers'] = []

    def _ensure_audit_retention_settings(self):
        defaults = {
            "secretary_events_days": 90,
            "secretary_events_max_per_owner": 2000,
            "mcp_tool_calls_days": 90,
            "mcp_tool_calls_max": 10000,
            "mcp_access_audit_days": 90,
            "mcp_access_audit_max": 10000,
        }
        current = self.settings.get('audit_retention')
        if not isinstance(current, dict):
            self.settings['audit_retention'] = defaults
            return
        for key, value in defaults.items():
            try:
                current[key] = max(0, int(current.get(key, value)))
            except (TypeError, ValueError):
                current[key] = value

    def _ensure_secretary_defaults(self):
        current = self.settings.get('secretary_mode')
        if not isinstance(current, dict):
            self.settings['secretary_mode'] = default_secretary_mode()
            return
        for key, value in DEFAULT_SECRETARY_MODE.items():
            current.setdefault(key, [] if isinstance(value, list) else value)
        if not isinstance(current.get('owners'), list):
            current['owners'] = []

    def _ensure_rich_messages_defaults(self):
        current = self.settings.get('rich_messages')
        if not isinstance(current, dict):
            self.settings['rich_messages'] = default_rich_messages()
            return
        for key, value in DEFAULT_RICH_MESSAGES.items():
            current.setdefault(key, value)

    def load_settings(self):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                encrypted_settings = json.load(f)
            # Расшифровываем настройки при загрузке
            self.settings = encryption.decrypt_config(encrypted_settings)
        except Exception as e:
            print(f"Ошибка при загрузке настроек: {e}")
            self.settings = {}

    def save_settings(self):
        try:
            settings_to_save = dict(self.settings)
            settings_to_save.pop('system_prompt_history', None)
            settings_to_save.pop('system_prompt_templates', None)
            # Шифруем настройки перед сохранением
            encrypted_settings = encryption.encrypt_config(settings_to_save)
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(encrypted_settings, f, indent=4, ensure_ascii=False)
            
            # АВТОМАТИЧЕСКИ ОБНОВЛЯЕМ ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ после сохранения
            self._update_global_vars()
            
        except Exception as e:
            print(f"Ошибка при сохранении настроек: {e}")

    def load_system_prompt_templates(self):
        try:
            if not os.path.exists(SYSTEM_PROMPT_TEMPLATES_FILE):
                return []
            with open(SYSTEM_PROMPT_TEMPLATES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception as e:
            print(f"Ошибка при загрузке шаблонов системного промпта: {e}")
        return []

    def save_system_prompt_templates(self, templates):
        try:
            with open(SYSTEM_PROMPT_TEMPLATES_FILE, 'w', encoding='utf-8') as f:
                json.dump(list(templates or []), f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка при сохранении шаблонов системного промпта: {e}")

    def load_system_prompt_history(self):
        try:
            if not os.path.exists(SYSTEM_PROMPT_HISTORY_FILE):
                return []
            with open(SYSTEM_PROMPT_HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception as e:
            print(f"Ошибка при загрузке истории системного промпта: {e}")
        return []

    def save_system_prompt_history(self, history):
        try:
            with open(SYSTEM_PROMPT_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(list(history or []), f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка при сохранении истории системного промпта: {e}")

    def _migrate_legacy_prompt_history(self):
        legacy_history = list(self.settings.get('system_prompt_history', []) or [])
        file_history = self.load_system_prompt_history()
        had_legacy_field = 'system_prompt_history' in self.settings

        if legacy_history and not file_history:
            self.save_system_prompt_history(legacy_history)
            file_history = legacy_history

        self.settings.pop('system_prompt_history', None)
        self._system_prompt_history_cache = list(file_history or [])
        return had_legacy_field

    def _migrate_legacy_prompt_templates(self):
        legacy_templates = list(self.settings.get('system_prompt_templates', []) or [])
        file_templates = self.load_system_prompt_templates()
        had_legacy_field = 'system_prompt_templates' in self.settings

        if legacy_templates and not file_templates:
            self.save_system_prompt_templates(legacy_templates)
            file_templates = legacy_templates

        self.settings.pop('system_prompt_templates', None)
        self._system_prompt_templates_cache = list(file_templates or [])
        return had_legacy_field

    def _update_global_vars(self):
        """Обновляет глобальные переменные после изменения настроек"""
        global TELEGRAM_TOKEN, DATABASE_PATH, LOG_FILE, TEMPERATURE, MAX_TOKENS
        global PRESENCE_PENALTY, FREQUENCY_PENALTY, OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_ID
        
        settings = self.get_settings()
        
        TELEGRAM_TOKEN = settings.get('telegram_token', '')
        DATABASE_PATH = settings.get('database_path', 'database.db')
        LOG_FILE = settings.get('log_file', 'app.log')
        TEMPERATURE = settings.get('temperature', 0.7)
        MAX_TOKENS = settings.get('max_tokens', 1024)
        PRESENCE_PENALTY = settings.get('presence_penalty', 0.0)
        FREQUENCY_PENALTY = settings.get('frequency_penalty', 0.0)
        # Добавляем обратно глобальные переменные для обратной совместимости
        OPENAI_API_KEY = settings.get('openai_api_key', '')
        OPENAI_BASE_URL = settings.get('openai_base_url', '')
        MODEL_ID = settings.get('model_id', '')

    def get_settings(self):
        # Для обратной совместимости добавляем старые поля
        settings_copy = self.settings.copy()
        settings_copy["system_prompt_history"] = self.load_system_prompt_history()
        settings_copy["system_prompt_templates"] = self.load_system_prompt_templates()
        
        # Если есть хотя бы одна модель, используем первую для обратной совместимости
        if "models" in settings_copy and settings_copy["models"]:
            first_model = settings_copy["models"][0]
            settings_copy["openai_api_key"] = first_model.get("api_key", "")
            settings_copy["openai_base_url"] = first_model.get("base_url", "")
            settings_copy["model_id"] = first_model.get("id", "")
        
        return settings_copy
    
    def get_model_settings(self, model_id=None):
        """Получить настройки конкретной модели или выбранной по стратегии балансировки"""
        models = self.settings.get("models", [])
        if not models:
            return None
        
        if model_id:
            # Если указан конкретный ID модели, ищем его
            for model in models:
                if model["id"] == model_id:
                    return model
            return None
        else:
            # Выбираем модель по стратегии балансировки
            strategy = self.settings.get("load_balancing_strategy", "round_robin")
            
            if strategy == "round_robin":
                # Round-robin: по очереди
                model = models[self.current_model_index]
                self.current_model_index = (self.current_model_index + 1) % len(models)
                return model
            
            elif strategy == "random_weighted":
                # Взвешенный случайный выбор
                total_weight = sum(model.get("weight", 1) for model in models)
                choice = random.uniform(0, total_weight)
                current_weight = 0
                for model in models:
                    current_weight += model.get("weight", 1)
                    if choice <= current_weight:
                        return model
                return models[0]  # На случай ошибки
            
            elif strategy == "least_used":
                # Наименее используемая модель
                least_used_model = min(models, key=lambda m: self.model_loads.get(m["id"], 0))
                self.model_loads[least_used_model["id"]] += 1
                return least_used_model
            
            else:
                # По умолчанию: первая модель
                return models[0]

    def update_settings(self, **kwargs):
        self.settings.update(kwargs)
        if 'admin_telegram_ids' in self.settings:
            self.settings['admin_telegram_ids'] = self._normalize_telegram_id_list(
                self.settings.get('admin_telegram_ids')
            )
        self._ensure_bot_access_policy()
        self._ensure_audit_retention_settings()
        self._ensure_secretary_defaults()
        self.save_settings()

    def reload_settings(self):
        self.load_settings()
        if 'admin_telegram_ids' not in self.settings:
            self.settings['admin_telegram_ids'] = []
        else:
            self.settings['admin_telegram_ids'] = self._normalize_telegram_id_list(
                self.settings.get('admin_telegram_ids')
            )
        self._ensure_telegram_menu_settings()
        self._ensure_mcp_settings()
        self._ensure_bot_access_policy()
        self._ensure_audit_retention_settings()
        self._ensure_secretary_defaults()
        # Обновляем счетчики загрузки моделей
        self.model_loads = {model["id"]: self.model_loads.get(model["id"], 0) 
                           for model in self.settings.get("models", [])}
        
        # АВТОМАТИЧЕСКИ ОБНОВЛЯЕМ ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ при перезагрузке
        self._update_global_vars()

    def validate_settings(self):
        """
        Проверяет валидность текущих настроек.
        Возвращает (is_valid: bool, errors: list[str])
        """
        errors = []
        
        # Проверяем telegram_token
        telegram_token = self.settings.get('telegram_token', '').strip()
        if not telegram_token:
            errors.append("Telegram токен не указан")
        elif len(telegram_token.split(':')) != 2:
            errors.append("Неверный формат Telegram токена (должен быть: BOT_ID:TOKEN)")
        
        # Проверяем модели
        models = self.settings.get('models', [])
        if not models:
            errors.append("Не добавлено ни одной модели")
        else:
            active_models = [m for m in models if m.get('active', True)]
            if not active_models:
                errors.append("Нет активных моделей")
            else:
                for i, model in enumerate(active_models):
                    model_id = model.get('id', '').strip()
                    api_key = model.get('api_key', '').strip() 
                    base_url = model.get('base_url', '').strip()
                    
                    if not model_id:
                        errors.append(f"Модель #{i+1}: не указан ID модели")
                    if not api_key:
                        errors.append(f"Модель #{i+1} ({model_id}): не указан API ключ")
                    if not base_url:
                        errors.append(f"Модель #{i+1} ({model_id}): не указан Base URL")
                    elif not (base_url.startswith('http://') or base_url.startswith('https://')):
                        errors.append(f"Модель #{i+1} ({model_id}): Base URL должен начинаться с http:// или https://")
                    
                    # Валидация типа API
                    api_type = model.get('api_type', 'openai')
                    valid_api_types = {'openai', 'anthropic'}
                    if api_type not in valid_api_types:
                        errors.append(
                            f"Модель #{i+1} ({model_id}): неизвестный тип API '{api_type}'. "
                            f"Допустимые: {', '.join(valid_api_types)}"
                        )
                    
                    # Валидация параметров
                    max_concurrent = model.get('max_concurrent_requests', 1)
                    context_window = model.get('context_window_size', 4096)
                    reasoning_budget = model.get('reasoning_budget_tokens', 0)
                    reasoning_mode = model.get('reasoning_mode', 'default')
                    reasoning_provider = model.get('reasoning_provider', 'auto')
                    
                    if not isinstance(max_concurrent, int) or max_concurrent < 1 or max_concurrent > 100:
                        errors.append(f"Модель #{i+1} ({model_id}): max_concurrent_requests должен быть целым числом от 1 до 100")
                    
                    if not isinstance(context_window, int) or context_window < 256:
                        errors.append(f"Модель #{i+1} ({model_id}): context_window_size должен быть целым числом минимум 256 токенов")
                    if not isinstance(reasoning_budget, int) or reasoning_budget < 0:
                        errors.append(f"Модель #{i+1} ({model_id}): reasoning_budget_tokens должен быть целым числом не меньше 0")
                    if reasoning_mode not in {'default', 'auto', 'off', 'minimal', 'low', 'medium', 'high', 'xhigh'}:
                        errors.append(f"Модель #{i+1} ({model_id}): неизвестный reasoning_mode '{reasoning_mode}'")
                    if reasoning_provider not in {'auto', 'openrouter', 'openai_compatible', 'anthropic_adaptive', 'anthropic_budget'}:
                        errors.append(f"Модель #{i+1} ({model_id}): неизвестный reasoning_provider '{reasoning_provider}'")
        
        return len(errors) == 0, errors

    def is_ready_for_bot(self):
        """
        Упрощенная проверка готовности для запуска бота.
        Возвращает True если настройки достаточны для запуска.
        """
        is_valid, _ = self.validate_settings()
        return is_valid

settings_manager = SettingsManager()
settings = settings_manager.get_settings()

TELEGRAM_TOKEN = settings.get('telegram_token', '')
DATABASE_PATH = settings.get('database_path', 'database.db')
LOG_FILE = settings.get('log_file', 'app.log')
TEMPERATURE = settings.get('temperature', 0.7)
MAX_TOKENS = settings.get('max_tokens', 1024)
PRESENCE_PENALTY = settings.get('presence_penalty', 0.0)
FREQUENCY_PENALTY = settings.get('frequency_penalty', 0.0)
# Добавляем обратно глобальные переменные для обратной совместимости
OPENAI_API_KEY = settings.get('openai_api_key', '')
OPENAI_BASE_URL = settings.get('openai_base_url', '')
MODEL_ID = settings.get('model_id', '')
