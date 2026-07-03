# bot/handlers/services/model_client_manager.py
"""
Модуль для управления клиентами моделей и работы с API.
Отвечает за инициализацию, выбор моделей и отправку запросов.
"""

import asyncio
import ipaddress
import json
import random
import re
import time
import sys
from typing import AsyncGenerator, Dict, List, Optional, Any
from urllib.parse import urlparse
import aiohttp

from config.settings import settings_manager
from utils import stats
from utils.logger import setup_logger
from utils.tokenizer import count_message_tokens, count_tokens
from utils.llm_response import TokenUsage
from .text_cleaner import clean_response
from .model_request_builder import build_model_request_params, has_reasoning_params, strip_reasoning_params
from .mcp_permissions import allowed_anthropic_tools_for_context, allowed_openai_tools_for_context, allowed_servers_for_context
from .mcp_registry import get_mcp_settings
from .mcp_runtime import McpRuntimeError, call_server_tool_async, is_mcp_sdk_available
from utils.database.database_manager import DatabaseManager

logger = setup_logger(__name__)

RAW_TOOL_CALL_RE = re.compile(r"<tool_call\b[^>]*>[\s\S]*?</tool_call>", re.IGNORECASE)
RAW_TOOL_FUNCTION_RE = re.compile(r"<function=([^>\s]+)>", re.IGNORECASE)
RAW_TOOL_PARAMETER_RE = re.compile(r"<parameter=([^>\s]+)>([\s\S]*?)</parameter>", re.IGNORECASE)

# Проверяем, запущены ли мы в PyInstaller bundle
IS_FROZEN = getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')

# Глобальное состояние для управления моделями
model_clients: Dict[str, Any] = {}  # Клиенты для каждой модели (теперь AiohttpOpenAIClient)
active_models: List[str] = []  # Список доступных моделей
model_capabilities: Dict[str, Dict[str, bool]] = {}  # Возможности каждой модели
model_usage_stats: Dict[str, Dict] = {}  # Статистика использования моделей
reasoning_disabled_runtime: Dict[str, str] = {}

# Lock для потокобезопасного доступа к счётчикам активных запросов (ленивая инициализация)
_pending_client_close_tasks: set[asyncio.Task] = set()
_model_stats_lock: Optional[asyncio.Lock] = None


def _track_client_close_task(task: asyncio.Task) -> None:
    _pending_client_close_tasks.add(task)

    def _on_done(done_task: asyncio.Task) -> None:
        _pending_client_close_tasks.discard(done_task)
        try:
            done_task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Model client delayed close failed: {e}")

    task.add_done_callback(_on_done)

def get_model_stats_lock() -> asyncio.Lock:
    """Возвращает Lock для статистики, создавая его в текущем event loop при необходимости."""
    global _model_stats_lock
    if _model_stats_lock is None:
        _model_stats_lock = asyncio.Lock()
    return _model_stats_lock


def reset_runtime_state():
    global _model_stats_lock
    _model_stats_lock = None
    reasoning_disabled_runtime.clear()
    for stats_entry in model_usage_stats.values():
        stats_entry["active_requests"] = 0


def _parse_base_url(base_url: str):
    parsed = urlparse((base_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Invalid model base_url: {base_url}")
    return parsed


def _is_local_url(base_url: str) -> bool:
    """
    Определяет, является ли URL локальным (LM Studio, Ollama и т.д.).
    Используется для решения: отключать SSL или нет.
    
    Локальные адреса работают по HTTP без сертификатов,
    поэтому для них SSL проверку отключаем.
    Внешние API (OpenAI, Claude, OpenRouter) используют HTTPS с валидными сертификатами.
    """
    parsed = _parse_base_url(base_url)
    hostname = (parsed.hostname or "").strip().lower()

    if hostname == "localhost":
        return True

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False

    return address.is_loopback or address.is_private or address.is_unspecified


def _detect_provider(base_url: str, api_type: str = "openai") -> str:
    if api_type == "anthropic":
        return "anthropic"

    try:
        parsed = _parse_base_url(base_url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except Exception:
        return "openai_compatible"

    if "openrouter.ai" in host:
        return "openrouter"
    if "api.openai.com" in host:
        return "openai"
    if "chutes.ai" in host:
        return "chutes"
    if host == "localhost" and port == 11434:
        return "ollama"
    if host in {"127.0.0.1", "localhost"} and port == 1234:
        return "lmstudio"
    if _is_local_url(base_url):
        return "openai_compatible_local"
    return "openai_compatible"


STREAM_USAGE_PROVIDERS = {
    "openai",
    "openrouter",
    # LM Studio официально поддерживает stream_options.include_usage
    # на OpenAI-compatible endpoints, поэтому usage можно забирать
    # из финального стрим-чанка, а не только считать локально.
    "lmstudio",
}


def _extract_usage_totals(usage: Any, provider: str = "") -> tuple[Optional[int], Optional[int], Optional[int]]:
    if usage is None:
        return None, None, None

    if isinstance(usage, dict):
        usage_dict = usage
    else:
        usage_dict = {
            key: getattr(usage, key)
            for key in dir(usage)
            if not key.startswith("_") and not callable(getattr(usage, key))
        }

    prompt_tokens = usage_dict.get("prompt_tokens")
    completion_tokens = usage_dict.get("completion_tokens")
    total_tokens = usage_dict.get("total_tokens")

    if prompt_tokens is None:
        prompt_tokens = usage_dict.get("input_tokens")
    if completion_tokens is None:
        completion_tokens = usage_dict.get("output_tokens")

    if provider == "anthropic":
        cache_read = usage_dict.get("cache_read_input_tokens") or 0
        cache_creation = usage_dict.get("cache_creation_input_tokens") or 0
        if prompt_tokens is not None:
            prompt_tokens = prompt_tokens + cache_read + cache_creation

    if prompt_tokens is None:
        prompt_tokens = usage_dict.get("prompt_eval_count")
    if completion_tokens is None:
        completion_tokens = usage_dict.get("eval_count")

    if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

    return prompt_tokens, completion_tokens, total_tokens


def _record_usage(response, messages=None, response_text=None, model_id=None):
    """
    Записывает использование токенов в глобальную статистику.
    Если API не вернул данные, использует локальный токенизатор для оценки.
    """
    try:
        usage_recorded = False
        provider = ""
        if response is not None:
            provider = getattr(response, "provider", "") or ""
        
        # 1. Пробуем получить точные данные от API
        if response is not None:
            usage = getattr(response, 'usage', None)
            prompt_tokens, completion_tokens, _ = _extract_usage_totals(usage, provider=provider)
            
            if prompt_tokens is not None and prompt_tokens > 0:
                stats.stats.add_input_tokens(prompt_tokens)
                usage_recorded = True
            if completion_tokens is not None and completion_tokens > 0:
                stats.stats.add_output_tokens(completion_tokens)
                usage_recorded = True
            
            if usage_recorded:
                logger.debug(
                    "Токены получены от API (%s): +%s вход, +%s выход",
                    provider or "unknown",
                    prompt_tokens or 0,
                    completion_tokens or 0,
                )
        
        # 2. Fallback: если API не вернул токены (или вернул 0), считаем сами
        if not usage_recorded and (messages or response_text):
            in_tokens = 0
            out_tokens = 0
            
            if messages:
                in_tokens = count_message_tokens(messages, model_id=model_id)
                stats.stats.add_input_tokens(in_tokens)
            
            if response_text:
                out_tokens = count_tokens(response_text, model_id=model_id)
                stats.stats.add_output_tokens(out_tokens)
            
            logger.debug(f"Токены посчитаны локально (fallback): +{in_tokens} вход, +{out_tokens} выход")
        elif not usage_recorded:
            logger.warning("Не удалось зафиксировать использование токенов: нет данных от API и нет текста для fallback")
    except Exception as e:
        logger.error(f"Критическая ошибка при записи статистики токенов: {e}", exc_info=True)


class AiohttpOpenAIClient:
    """
    Легковесная замена AsyncOpenAI на базе aiohttp.
    Решает проблемы с httpx в PyInstaller и работает быстрее.
    
    Ключевые особенности:
    - Переиспользует одну ClientSession (connection pooling, HTTP keep-alive)
    - Умная работа с SSL: отключён для локальных серверов, включён для внешних API
    - Корректное закрытие сессии через close()
    """
    def __init__(self, api_key: str, base_url: str):
        parsed_base_url = _parse_base_url(base_url)
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.provider = _detect_provider(base_url, api_type="openai")
        self._last_stream_usage = None
        
        # Автоматическое исправление для популярных API (например, Chutes), 
        # если пользователь забыл добавить /v1 в конфигурацию
        if "chutes.ai" in self.base_url and not self.base_url.endswith("/v1"):
            self.base_url += "/v1"
            
        self.chat = self.Chat(self)
        
        # Определяем, локальный ли это сервер
        self.is_local = _is_local_url(base_url)
        if not self.is_local and parsed_base_url.scheme != "https":
            raise ValueError(f"External model APIs must use https:// ({base_url})")
        
        # SSL: отключаем только для локальных серверов (LM Studio, Ollama по HTTP)
        # Для внешних API (OpenAI, Claude, OpenRouter) — SSL включён (None = дефолтное поведение aiohttp)
        if self.is_local and parsed_base_url.scheme == "http":
            self.ssl_context = False
            logger.info(f"SSL отключён для локального сервера: {base_url}")
        else:
            self.ssl_context = None  # None = aiohttp использует системные сертификаты
            logger.info(f"SSL включён для внешнего API: {base_url}")
        
        # Сессия создаётся лениво при первом запросе (lazy initialization)
        # Это нужно потому, что ClientSession должна создаваться внутри event loop
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """
        Возвращает переиспользуемую ClientSession.
        Создаёт при первом вызове (lazy init внутри event loop).
        Пересоздаёт, если предыдущая сессия была закрыта.
        """
        if self._session is None or self._session.closed:
            # Таймауты: 30 сек на подключение, 120 сек на чтение ответа (LLM могут думать долго)
            timeout = aiohttp.ClientTimeout(
                total=300,       # Общий лимит на запрос
                connect=30,      # Лимит на установку соединения
                sock_read=120,   # Лимит на чтение данных из сокета
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._session
    
    async def close(self):
        """Закрывает HTTP-сессию. Вызывать при остановке бота или переинициализации моделей."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            logger.debug(f"Закрыта HTTP-сессия для {self.base_url}")

    class Chat:
        def __init__(self, client):
            self.completions = self.Completions(client)

        class Completions:
            def __init__(self, client):
                self.client = client

            async def create(self, **kwargs):
                url = self.client.base_url
                if not url.endswith('/chat/completions'):
                    url = f"{url}/chat/completions"
                
                # Фильтруем None значения
                data = {k: v for k, v in kwargs.items() if v is not None}
                
                session = await self.client._get_session()
                
                # По просьбе пользователя: для Chutes.ai увеличиваем кол-во попыток до 12, 
                # так как инфраструктура часто перегружена (429 maximum capacity)
                is_chutes = "chutes.ai" in self.client.base_url
                max_attempts = 12 if is_chutes else 3
                
                try:
                    for attempt_idx in range(max_attempts):
                        attempt_num = attempt_idx + 1
                        try:
                            # Логируем только повторные попытки или если это дебаг
                            if attempt_num > 1:
                                logger.info(f"Повторный запрос к {self.client.base_url} (Попытка {attempt_num}/{max_attempts})...")

                            async with session.post(
                                url, 
                                json=data, 
                                ssl=self.client.ssl_context,
                            ) as response:
                                if response.status != 200:
                                    error_text = await response.text()
                                    
                                    # Логика повторов для специфичных ошибок Chutes
                                    if is_chutes:
                                        # 429 (Infrastructure is at maximum capacity) или 404 (No matching cord)
                                        is_retryable = response.status == 429 or (response.status == 404 and "No matching cord" in error_text)
                                        if is_retryable and attempt_idx < max_attempts - 1:
                                            # Экспоненциальная задержка: 1.5, 2.25, 3.37... но не более 10 сек
                                            wait_time = min(1.5 ** attempt_idx + random.uniform(0.1, 0.5), 10)
                                            logger.warning(f"Chutes error {response.status}. Ждем {wait_time:.1f}с перед попыткой {attempt_num + 1}/{max_attempts}...")
                                            await asyncio.sleep(wait_time)
                                            continue
                                            
                                    # Стандартная логика для 404 cord error (если не Chutes или если попытки кончились)
                                    if response.status == 404 and "No matching cord" in error_text:
                                        raise Exception(f"Chutes API: No matching cord — check balance/model name. Error: {error_text}")
                                    
                                    raise Exception(f"API Error {response.status}: {error_text}")
                                
                                result = await response.json()
                                return AiohttpOpenAIClient.MockResponse(
                                    result,
                                    provider=self.client.provider,
                                )
                        except aiohttp.ClientSSLError as e:
                            raise e
                        except Exception as e:
                            if attempt_idx < max_attempts - 1:
                                wait_time = 1.0 if not is_chutes else min(1.5 ** attempt_idx, 5)
                                logger.debug(f"Ошибка запроса {self.client.base_url}, попытка {attempt_num}/{max_attempts}: {e}")
                                await asyncio.sleep(wait_time)
                                continue
                            raise Exception(f"Ошибка при запросе к {self.client.base_url} после {max_attempts} попыток: {e}") from e
                
                except aiohttp.ClientSSLError as ssl_err:
                    raise Exception(
                        f"SSL verification failed for {self.client.base_url}: {ssl_err}"
                    ) from ssl_err
                except aiohttp.ClientError as e:
                    # Сетевые ошибки (таймаут, отказ соединения и т.д.)
                    raise Exception(
                        f"Ошибка соединения с {self.client.base_url}: {e}"
                    ) from e

            async def create_stream(self, **kwargs) -> AsyncGenerator[str, None]:
                """SSE-стриминг: yield-ит куски текста по мере поступления от модели."""
                url = self.client.base_url
                if not url.endswith('/chat/completions'):
                    url = f"{url}/chat/completions"
                    
                data = {k: v for k, v in kwargs.items() if v is not None}
                data['stream'] = True
                self.client._last_stream_usage = None

                if self.client.provider in STREAM_USAGE_PROVIDERS:
                    data['stream_options'] = {"include_usage": True}

                session = await self.client._get_session()
                is_chutes = "chutes.ai" in self.client.base_url
                max_attempts = 12 if is_chutes else 3
                
                for attempt_idx in range(max_attempts):
                    attempt_num = attempt_idx + 1
                    try:
                        if attempt_num > 1:
                            logger.info(f"Повторный запрос (стриминг) к {self.client.base_url} (Попытка {attempt_num}/{max_attempts})...")

                        async with session.post(
                            url,
                            json=data,
                            ssl=self.client.ssl_context,
                        ) as response:
                            if response.status != 200:
                                error_text = await response.text()
                                
                                if is_chutes:
                                    is_retryable = response.status == 429 or (response.status == 404 and "No matching cord" in error_text)
                                    if is_retryable and attempt_idx < max_attempts - 1:
                                        wait_time = min(1.5 ** attempt_idx + random.uniform(0.1, 0.5), 10)
                                        logger.warning(f"Chutes error {response.status} (streaming). Ждем {wait_time:.1f}с перед попыткой {attempt_num + 1}/{max_attempts}...")
                                        await asyncio.sleep(wait_time)
                                        continue

                                if response.status == 404 and "No matching cord" in error_text:
                                    raise Exception(f"Chutes API: No matching cord — check balance/model name. Error: {error_text}")
                                    
                                raise Exception(f"API Error {response.status}: {error_text}")
                                
                            async for raw_line in response.content:
                                line = raw_line.decode('utf-8', errors='replace').rstrip('\n').rstrip('\r')
                                if not line.startswith('data:'):
                                    continue
                                payload = line[len('data:'):].strip()
                                if payload == '[DONE]':
                                    break
                                try:
                                    chunk = json.loads(payload)
                                    if chunk.get('usage'):
                                        self.client._last_stream_usage = chunk.get('usage')
                                    delta = chunk.get('choices', [{}])[0].get('delta', {})
                                    token = delta.get('content')
                                    if token:
                                        yield token
                                except (json.JSONDecodeError, IndexError, KeyError):
                                    continue
                        # Успешно завершили генератор
                        break
                    except aiohttp.ClientSSLError:
                        raise # SSL ошибки вверх
                    except Exception as e:
                        if attempt_idx < max_attempts - 1:
                            wait_time = 1.0 if not is_chutes else min(1.5 ** attempt_idx, 5)
                            await asyncio.sleep(wait_time)
                            continue
                        raise Exception(
                            f"Ошибка соединения (стриминг) после {max_attempts} попыток с {self.client.base_url}: {e}"
                        ) from e

    class MockResponse:
        """Имитирует структуру ответа OpenAI."""
        def __init__(self, data, provider: str = ""):
            self.data = data
            self.provider = provider
            self.choices = [self.Choice(c) for c in data.get('choices', [])]
            self.usage = self.Usage(data)

        class Choice:
            def __init__(self, data):
                self.message = self.Message(data.get('message', {}))

            class Message:
                def __init__(self, data):
                    self.content = data.get('content')
                    self.tool_calls = data.get('tool_calls') or []

        class Usage:
            def __init__(self, data):
                usage_data = data.get('usage', {}) if isinstance(data, dict) else {}

                self.prompt_tokens = usage_data.get('prompt_tokens')
                self.completion_tokens = usage_data.get('completion_tokens')
                self.total_tokens = usage_data.get('total_tokens')
                self.input_tokens = usage_data.get('input_tokens')
                self.output_tokens = usage_data.get('output_tokens')
                self.cache_read_input_tokens = usage_data.get('cache_read_input_tokens')
                self.cache_creation_input_tokens = usage_data.get('cache_creation_input_tokens')

                if self.prompt_tokens is None:
                    self.prompt_tokens = data.get('prompt_eval_count')
                if self.completion_tokens is None:
                    self.completion_tokens = data.get('eval_count')
                if self.total_tokens is None and (
                    self.prompt_tokens is not None or self.completion_tokens is not None
                ):
                    self.total_tokens = (self.prompt_tokens or 0) + (self.completion_tokens or 0)


class AiohttpAnthropicClient:
    """
    Клиент для Anthropic-compatible API (Claude).
    
    Anthropic использует другой формат запросов и ответов:
    - Эндпоинт: /v1/messages (не /chat/completions)
    - Авторизация: x-api-key (не Bearer token)
    - System prompt передаётся отдельным полем, а не как message с role=system
    - max_tokens — обязательный параметр
    - Ответ: content[0].text (не choices[0].message.content)
    
    Возвращает MockResponse в формате OpenAI для совместимости с get_response_from_model().
    """

    # Актуальная версия API Anthropic
    ANTHROPIC_API_VERSION = "2023-06-01"

    def __init__(self, api_key: str, base_url: str):
        parsed_base_url = _parse_base_url(base_url)
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.provider = _detect_provider(base_url, api_type="anthropic")
        self.is_local = _is_local_url(base_url)
        if not self.is_local and parsed_base_url.scheme != "https":
            raise ValueError(f"External model APIs must use https:// ({base_url})")
        
        if self.is_local and parsed_base_url.scheme == "http":
            self.ssl_context = False
            logger.info(f"[Anthropic] SSL отключён для локального сервера: {base_url}")
        else:
            self.ssl_context = None
            logger.info(f"[Anthropic] SSL включён для внешнего API: {base_url}")
        
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Возвращает переиспользуемую ClientSession с заголовками Anthropic."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=300, connect=30, sock_read=120)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.ANTHROPIC_API_VERSION,
                    "Content-Type": "application/json",
                },
            )
        return self._session
    
    async def close(self):
        """Закрывает HTTP-сессию."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            logger.debug(f"[Anthropic] Закрыта HTTP-сессия для {self.base_url}")

    @staticmethod
    def _convert_messages_to_anthropic(messages: List[Dict]) -> tuple:
        """
        Конвертирует сообщения из формата OpenAI в формат Anthropic.
        
        OpenAI: [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        Anthropic: system="...", messages=[{"role": "user", "content": "..."}]
        
        Returns:
            (system_prompt: str, messages: list) — system отдельно, сообщения без system
        """
        system_parts = []
        anthropic_messages = []
        
        for msg in messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            
            if role == 'system':
                # Anthropic: system prompt передаётся отдельным полем
                if isinstance(content, str):
                    system_parts.append(content)
                continue
            
            if role == 'assistant' or role == 'user':
                # Конвертируем контент (может быть строкой или списком для VLM)
                if isinstance(content, list):
                    # Multimodal: конвертируем image_url из формата OpenAI в формат Anthropic
                    anthropic_content = []
                    for part in content:
                        if part.get('type') == 'text':
                            anthropic_content.append({"type": "text", "text": part.get('text', '')})
                        elif part.get('type') in {'tool_use', 'tool_result'}:
                            anthropic_content.append(part)
                        elif part.get('type') == 'image_url':
                            image_url = part.get('image_url', {}).get('url', '')
                            if image_url.startswith('data:'):
                                # data:image/jpeg;base64,... → Anthropic формат
                                try:
                                    header, b64_data = image_url.split(',', 1)
                                    media_type = header.split(':')[1].split(';')[0]
                                    anthropic_content.append({
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": media_type,
                                            "data": b64_data,
                                        }
                                    })
                                except (ValueError, IndexError):
                                    logger.warning(f"Не удалось разобрать base64 изображение для Anthropic")
                            else:
                                # URL изображения
                                anthropic_content.append({
                                    "type": "image",
                                    "source": {"type": "url", "url": image_url}
                                })
                    anthropic_messages.append({"role": role, "content": anthropic_content})
                else:
                    anthropic_messages.append({"role": role, "content": str(content)})
        
        system_prompt = "\n\n".join(system_parts) if system_parts else ""
        return system_prompt, anthropic_messages

    async def create_message(self, **kwargs) -> 'AiohttpOpenAIClient.MockResponse':
        """
        Отправляет запрос к Anthropic API и возвращает MockResponse в формате OpenAI.
        
        Принимает параметры в формате OpenAI (messages, model, temperature, max_tokens и т.д.),
        конвертирует в формат Anthropic, отправляет, и конвертирует ответ обратно.
        """
        messages = kwargs.get('messages', [])
        model = kwargs.get('model', '')
        temperature = kwargs.get('temperature', 0.7)
        max_tokens = kwargs.get('max_tokens', 4096)  # Anthropic требует max_tokens
        
        # Конвертируем сообщения
        system_prompt, anthropic_messages = self._convert_messages_to_anthropic(messages)
        
        # Формируем тело запроса Anthropic
        data = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens if max_tokens and max_tokens > 0 else 4096,
            "temperature": temperature,
        }
        
        # system — только если не пустой
        if system_prompt:
            data["system"] = system_prompt
        
        # top_p (Anthropic поддерживает)
        if 'top_p' in kwargs and kwargs['top_p'] is not None:
            data["top_p"] = kwargs['top_p']
        if 'thinking' in kwargs and kwargs['thinking']:
            data["thinking"] = kwargs['thinking']
        if 'output_config' in kwargs and kwargs['output_config']:
            data["output_config"] = kwargs['output_config']
        if 'tools' in kwargs and kwargs['tools']:
            data["tools"] = kwargs['tools']
        if 'tool_choice' in kwargs and kwargs['tool_choice']:
            data["tool_choice"] = kwargs['tool_choice']
        
        url = f"{self.base_url}/v1/messages"
        session = await self._get_session()
        
        try:
            async with session.post(url, json=data, ssl=self.ssl_context) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Anthropic API Error {response.status}: {error_text}")
                
                result = await response.json()
                
                # Конвертируем ответ Anthropic → формат OpenAI MockResponse
                return self._convert_response_to_openai(result)
                
        except aiohttp.ClientSSLError as ssl_err:
            raise Exception(
                f"[Anthropic] SSL verification failed for {self.base_url}: {ssl_err}"
            ) from ssl_err
        except aiohttp.ClientError as e:
            raise Exception(f"[Anthropic] Ошибка соединения с {self.base_url}: {e}") from e

    @staticmethod
    def _convert_response_to_openai(anthropic_data: dict) -> 'AiohttpOpenAIClient.MockResponse':
        """
        Конвертирует ответ Anthropic в формат OpenAI MockResponse.
        
        Anthropic: { content: [{ type: "text", text: "..." }], usage: { input_tokens, output_tokens } }
        OpenAI:    { choices: [{ message: { content: "..." } }], usage: { prompt_tokens, completion_tokens } }
        """
        # Извлекаем текст из content blocks
        content_blocks = anthropic_data.get('content', [])
        text_parts = []
        for block in content_blocks:
            if block.get('type') == 'text':
                text_parts.append(block.get('text', ''))
        
        response_text = "\n".join(text_parts) if text_parts else ""
        
        # Конвертируем usage
        anthropic_usage = anthropic_data.get('usage', {})
        
        # Собираем в формат OpenAI
        openai_format = {
            'choices': [{
                'message': {
                    'content': response_text,
                }
            }],
            'usage': {
                'prompt_tokens': anthropic_usage.get('input_tokens'),
                'completion_tokens': anthropic_usage.get('output_tokens'),
            }
        }
        
        response = AiohttpOpenAIClient.MockResponse(openai_format, provider="anthropic")
        response.raw_anthropic = anthropic_data
        return response


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Допустимые типы API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUPPORTED_API_TYPES = {"openai", "anthropic"}


async def close_all_clients():
    """Close current and previously scheduled model client HTTP sessions."""
    for model_id, client in list(model_clients.items()):
        try:
            if hasattr(client, "close"):
                await client.close()
        except Exception as e:
            logger.warning(f"Model client close failed for {model_id}: {e}")

    if _pending_client_close_tasks:
        done, pending = await asyncio.wait(list(_pending_client_close_tasks), timeout=5)
        for task in done:
            try:
                task.result()
            except Exception as e:
                logger.warning(f"Model client delayed close failed: {e}")
        for task in pending:
            task.cancel()
            _pending_client_close_tasks.discard(task)
    logger.info("All model client HTTP sessions are closed")


def _close_old_clients_sync():
    """Close old clients before synchronous model client reinitialization."""
    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    for model_id, client in list(model_clients.items()):
        try:
            if not hasattr(client, "close"):
                continue
            if loop and loop.is_running():
                _track_client_close_task(loop.create_task(client.close()))
            else:
                asyncio.run(client.close())
        except Exception as e:
            logger.debug(f"Failed to close old model client {model_id}: {e}")

def init_model_clients():
    """
    Инициализирует клиенты для всех активных моделей.
    Вызывается при запуске бота и после изменения конфигурации.
    """
    global model_clients, active_models
    
    # Закрываем старые клиенты перед переинициализацией
    _close_old_clients_sync()
    
    model_capabilities.clear()
    
    # ПРИНУДИТЕЛЬНО ПЕРЕЗАГРУЖАЕМ НАСТРОЙКИ
    settings_manager.reload_settings()
    settings = settings_manager.get_settings()
    logger.info(f"Перезагружены настройки при инициализации моделей: temperature={settings.get('temperature')}")
    
    models = settings.get('models', [])
    
    # Очищаем список активных моделей и клиентов
    active_models.clear()
    model_clients.clear()
    
    for model in models:
        model_id = model.get('id')
        # Проверяем, что модель активна (по умолчанию - True)
        is_active = model.get('active', True)
        if model_id and model.get('base_url') and is_active:
            try:
                base_url = model.get('base_url', '')
                api_key = model.get('api_key', '')
                model_capabilities[model_id] = {'supports_vision': model.get('supports_vision', False)}
                
                # Создаём клиент нужного типа на основе api_type
                api_type = model.get('api_type', 'openai')
                
                if api_type == 'anthropic':
                    model_clients[model_id] = AiohttpAnthropicClient(
                        api_key=api_key,
                        base_url=base_url,
                    )
                else:
                    # openai — дефолтный тип (LM Studio, Ollama, OpenAI, OpenRouter и др.)
                    model_clients[model_id] = AiohttpOpenAIClient(
                        api_key=api_key,
                        base_url=base_url,
                    )
                
                location = 'локальная' if _is_local_url(base_url) else 'внешняя'
                logger.info(
                    f"Инициализирована модель: {model_id} "
                    f"(тип={api_type}, {location}, {base_url})"
                )
                
                # Инициализируем статистику для новой модели, если её ещё нет
                if model_id not in model_usage_stats:
                    model_usage_stats[model_id] = {
                        "requests": 0, 
                        "errors": 0, 
                        "active_requests": 0
                    }
                # Сбрасываем счетчик активных запросов при перезапуске
                else:
                    model_usage_stats[model_id]["active_requests"] = 0
                
                # Добавляем модель в список активных
                active_models.append(model_id)
            except Exception as e:
                logger.error(f"Ошибка инициализации модели {model_id}: {e}")
        else:
            model_capabilities.pop(model_id, None)
    
    # Если нет активных моделей, выводим предупреждение
    if not active_models:
        logger.warning("Внимание! Не найдено активных моделей для обработки запросов.")


def has_active_vlm_model(sync_if_needed: bool = True) -> bool:
    """
    Проверяет, есть ли среди активных моделей те, что поддерживают изображения.

    Args:
        sync_if_needed: Перезагрузить конфигурацию, если активных моделей ещё нет,
            но по настройкам ожидаются VLM модели.
    """
    try:
        if any(model_capabilities.get(mid, {}).get('supports_vision') for mid in active_models):
            return True

        if not sync_if_needed:
            return False

        settings = settings_manager.get_settings()
        expected_vlm = any(
            model.get('active', True) and model.get('supports_vision', False)
            for model in settings.get('models', [])
        )
        if expected_vlm:
            logger.info("Обнаружены VLM-модели в настройках, но они не активированы в рантайме. Перезагружаем клиенты моделей...")
            init_model_clients()
            return any(model_capabilities.get(mid, {}).get('supports_vision') for mid in active_models)
    except Exception as exc:
        logger.error(f"Ошибка при проверке активных VLM-моделей: {exc}")
    return False


def select_model_for_request(
    requires_vision: bool = False,
    eligible_model_ids: Optional[List[str]] = None,
    min_context_window_size: Optional[int] = None,
) -> Optional[str]:
    """
    Выбирает подходящую модель для обработки запроса согласно стратегии балансировки.
    
    Args:
        requires_vision: Требуется ли поддержка изображений (VLM)
        eligible_model_ids: Если задан, выбирать только среди этих моделей (после vision-фильтра).
        min_context_window_size: Если задан, выбирать только модели с context_window_size >= этого значения.
        
    Returns:
        ID выбранной модели или None если нет подходящих
    """
    # ВСЕГДА ПОЛУЧАЕМ СВЕЖИЕ НАСТРОЙКИ
    settings = settings_manager.get_settings()
    strategy = settings.get("load_balancing_strategy", "round_robin")
    logger.debug(f"Используем стратегию балансировки: {strategy}")
    
    # Используем только активные модели из глобального списка
    if not active_models:
        return None
    
    # Получаем конфиги моделей для проверки лимитов
    models_config = {m.get('id'): m for m in settings.get('models', [])}
    
    if requires_vision:
        capable_models = [m for m in active_models if model_capabilities.get(m, {}).get('supports_vision')]
        if not capable_models:
            logger.warning("Нет доступных VLM-моделей для обработки изображения")
            return None
    else:
        capable_models = active_models.copy()

    if eligible_model_ids is not None:
        eligible_set = set(eligible_model_ids)
        capable_models = [m for m in capable_models if m in eligible_set]

    if min_context_window_size is not None:
        default_context_length = settings.get('default_context_length', 4096)
        capable_models = [
            m for m in capable_models
            if models_config.get(m, {}).get('context_window_size', default_context_length) >= min_context_window_size
        ]

    if not capable_models:
        logger.debug("Нет подходящих моделей после применения ограничений (eligible/min_context).")
        return None

    # Проверяем все модели на статус "бездействия"
    # Теперь также проверяем, есть ли место для новых запросов
    idle_models = []
    models_with_space = []  # Модели, которые ещё могут взять запросы
    
    for model_id in capable_models:
        model_stats = model_usage_stats.get(model_id, {"requests": 0, "errors": 0, "active_requests": 0})
        model_config = models_config.get(model_id, {})
        
        # Получаем лимит для этой модели
        max_concurrent = model_config.get('max_concurrent_requests', 1)
        active_requests = model_stats.get("active_requests", 0)
        
        # Проверяем, есть ли место для нового запроса
        has_space = active_requests < max_concurrent
        
        if has_space:
            models_with_space.append(model_id)
            
        # Проверяем, полностью ли свободна модель
        is_idle = active_requests == 0
        if is_idle:
            idle_models.append(model_id)
    
    # Приоритет 1: Полностью свободные модели (без активных запросов)
    if idle_models:
        logger.debug(f"Найдены свободные модели: {idle_models}")
        if strategy == "round_robin" and len(idle_models) > 1:
            # Используем round-robin только среди свободных моделей
            selected_model = idle_models[0]
            active_models.remove(selected_model)
            active_models.append(selected_model)
            logger.debug(f"Стратегия round_robin: выбрана свободная модель {selected_model}")
            return selected_model
        else:
            # Используем первую свободную модель
            logger.debug(f"Выбрана свободная модель {idle_models[0]}")
            return idle_models[0]
    
    # Приоритет 2: Модели с местом для нового запроса
    if models_with_space:
        logger.debug(f"Найдены модели с местом: {models_with_space}")
        
        if strategy == "round_robin":
            # Используем round-robin среди моделей с местом
            selected_model = models_with_space[0]
            try:
                active_models.remove(selected_model)
                active_models.append(selected_model)
            except ValueError:
                pass  # На случай, если модель уже в конце
            logger.debug(f"Стратегия round_robin: выбрана модель {selected_model} (место доступно)")
            return selected_model
        
        elif strategy == "random_weighted":
            # Взвешенный выбор среди моделей с местом
            weighted_models = []
            total_weight = 0
            for model_id in models_with_space:
                weight = models_config.get(model_id, {}).get("weight", 1)
                weighted_models.append((model_id, weight))
                total_weight += weight
            
            if weighted_models:
                choice = random.uniform(0, total_weight)
                current_weight = 0
                for model_id, weight in weighted_models:
                    current_weight += weight
                    if choice <= current_weight:
                        logger.debug(f"Стратегия random_weighted: выбрана модель {model_id}")
                        return model_id
            return models_with_space[0]
        
        elif strategy == "least_used":
            # Выбираем модель с наименьшей нагрузкой (в процентах от лимита)
            # Это справедливее, чем просто по количеству запросов
            best_model = None
            best_ratio = float('inf')
            
            for model_id in models_with_space:
                model_stats = model_usage_stats.get(model_id, {})
                model_config = models_config.get(model_id, {})
                
                active = model_stats.get("active_requests", 0)
                max_concurrent = model_config.get('max_concurrent_requests', 1)
                
                # Считаем процент занятости
                usage_ratio = active / max_concurrent if max_concurrent > 0 else float('inf')
                
                logger.debug(f"Модель {model_id}: {active}/{max_concurrent} (заполнено на {usage_ratio*100:.1f}%)")
                
                if usage_ratio < best_ratio:
                    best_ratio = usage_ratio
                    best_model = model_id
            
            if best_model:
                logger.debug(f"Стратегия least_used: выбрана модель {best_model} (заполнено на {best_ratio*100:.1f}%)")
                return best_model
    
    # Приоритет 3: Если нет моделей с местом — возвращаем None
    # process_queue() будет крутить запрос обратно в очередь
    logger.warning(f"Нет моделей с доступным местом! Активные модели полностью заняты.")
    return None


def get_model_usage_stats() -> Dict[str, Dict]:
    """
    Возвращает статистику использования моделей.
    
    Returns:
        Словарь с информацией о каждой модели (количество запросов, ошибок, активных запросов)
    """
    # Возвращаем копию статистики с дополнительной информацией
    stats_copy = {}
    for model_id, stat in model_usage_stats.items():
        stats_copy[model_id] = stat.copy()
        # Добавляем статус модели
        stats_copy[model_id]["is_idle"] = stat.get("active_requests", 0) == 0
        stats_copy[model_id]["is_active"] = model_id in active_models
    
    return stats_copy


def _extract_tool_calls(response) -> List[Dict]:
    try:
        if not response or not response.choices:
            return []
        tool_calls = getattr(response.choices[0].message, "tool_calls", []) or []
        return [call for call in tool_calls if isinstance(call, dict)]
    except Exception:
        return []


def _strip_raw_tool_call_blocks(text: str) -> str:
    if not text:
        return ""
    return RAW_TOOL_CALL_RE.sub("", text).strip()


def _coerce_raw_tool_argument(value: str) -> Any:
    value = (value or "").strip()
    if value == "":
        return ""
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in {"null", "none"}:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def _extract_raw_text_tool_calls(text: str) -> List[Dict]:
    """Парсит XML-подобные tool_call блоки, которые некоторые модели печатают как текст."""
    calls = []
    for index, block_match in enumerate(RAW_TOOL_CALL_RE.finditer(text or "")):
        block = block_match.group(0)
        function_match = RAW_TOOL_FUNCTION_RE.search(block)
        if not function_match:
            continue
        function_name = function_match.group(1).strip()
        if "__" not in function_name:
            continue
        arguments = {}
        for param_name, param_value in RAW_TOOL_PARAMETER_RE.findall(block):
            arguments[param_name.strip()] = _coerce_raw_tool_argument(param_value)
        calls.append({
            "id": f"raw_tool_call_{index + 1}",
            "function": {
                "name": function_name,
                "arguments": json.dumps(arguments, ensure_ascii=False),
            },
        })
    return calls


async def _resolve_raw_text_tool_calls(
    *,
    response_text: str,
    current_params: Dict,
    completion_params: Dict,
    settings: Dict,
    request_context: Dict,
    perform_request,
) -> tuple[Any, Optional[Dict]]:
    raw_tool_calls = _extract_raw_text_tool_calls(response_text)
    if not raw_tool_calls:
        return None, None

    logger.warning(
        "Модель вернула MCP tool_call как обычный текст; выполняем распознанные вызовы: %s",
        [call.get("function", {}).get("name") for call in raw_tool_calls],
    )
    tool_messages = await _execute_mcp_tool_calls(raw_tool_calls, settings, request_context or {})
    if not tool_messages:
        return None, None

    result_lines = []
    for message in tool_messages:
        tool_name = message.get("name") or "tool"
        result_lines.append(f"{tool_name}:\n{message.get('content') or ''}")

    visible_text = _strip_raw_tool_call_blocks(response_text)
    final_params = dict(completion_params)
    final_params["messages"] = (
        current_params.get("messages", completion_params.get("messages", []))
        + [{
            "role": "assistant",
            "content": visible_text or "Я запросил данные через инструмент.",
        }]
        + [{
            "role": "user",
            "content": (
                "Результаты MCP-инструментов:\n\n"
                + "\n\n".join(result_lines)
                + "\n\nСформулируй обычный ответ пользователю. "
                "Не печатай XML, tool_call, function или служебные теги."
            ),
        }]
    )
    final_params.pop("tool_choice", None)
    final_params.pop("tools", None)
    response = await perform_request(final_params)
    return response, final_params


def _assistant_tool_call_message(response, tool_calls: Optional[List[Dict]] = None) -> Dict:
    message = response.choices[0].message
    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": tool_calls if tool_calls is not None else (getattr(message, "tool_calls", []) or []),
    }


async def _execute_mcp_tool_calls(tool_calls: List[Dict], settings: Dict, request_context: Dict) -> List[Dict]:
    servers = allowed_servers_for_context(settings, request_context)
    server_by_name = {server.get("name"): server for server in servers}
    mcp_settings = get_mcp_settings(settings)
    limits = mcp_settings.get("limits") or {}
    max_calls = int(limits.get("max_tool_calls_per_request", 5) or 5)
    timeout_seconds = int(limits.get("tool_timeout_seconds", 30) or 30)
    max_result_chars = int(limits.get("max_tool_result_chars", 12000) or 12000)
    tool_messages = []
    db = DatabaseManager()

    try:
        for index, call in enumerate(tool_calls):
            call_id = call.get("id") or ""
            function = call.get("function") or {}
            function_name = function.get("name") or ""
            arguments_raw = function.get("arguments") or "{}"
            if index >= max_calls:
                logger.warning("MCP tool call limit reached: max=%s", max_calls)
                db.mcp.add_access_denied(
                    server_name="",
                    tool_name=function_name,
                    request_context=request_context,
                    reason="max_tool_calls_per_request exceeded",
                )
                continue
            if "__" not in function_name:
                db.mcp.add_access_denied(
                    server_name="",
                    tool_name=function_name,
                    request_context=request_context,
                    reason="invalid tool function name",
                )
                continue
            server_name, tool_name = function_name.split("__", 1)
            server = server_by_name.get(server_name)
            if not server:
                logger.warning("MCP tool denied or unknown server: %s", server_name)
                db.mcp.add_access_denied(
                    server_name=server_name,
                    tool_name=tool_name,
                    request_context=request_context,
                    reason="server denied or unknown",
                )
                continue
            try:
                arguments = json.loads(arguments_raw) if isinstance(arguments_raw, str) else dict(arguments_raw)
            except Exception:
                arguments = {}
            if server_name == "weather-open-meteo" and tool_name == "forecast":
                tool_name = "weather_forecast"
            if server_name == "weather-open-meteo" and tool_name == "geocoding":
                arguments = _normalize_geocoding_arguments(arguments)
            started_at = time.monotonic()
            try:
                if server_name == "weather-open-meteo" and tool_name == "geocoding":
                    result_text, arguments = await _call_geocoding_with_recovery(
                        server,
                        arguments,
                        timeout_seconds=timeout_seconds,
                    )
                else:
                    result_text = await call_server_tool_async(
                        server,
                        tool_name,
                        arguments,
                        timeout_seconds=timeout_seconds,
                    )
                if _is_mcp_error_result(result_text):
                    status = "failed"
                    error_text = result_text[:1000]
                else:
                    status = "completed"
                    error_text = ""
            except McpRuntimeError as e:
                status = "failed"
                error_text = str(e)
                result_text = f"MCP error: {e}"
            except Exception as e:
                logger.warning("MCP tool call failed: server=%s tool=%s error=%s", server_name, tool_name, e)
                status = "failed"
                error_text = str(e)
                result_text = f"MCP tool call failed: {e}"

            duration_ms = int((time.monotonic() - started_at) * 1000)
            if len(result_text) > max_result_chars:
                result_text = result_text[:max_result_chars] + "\n...[truncated]"
                logger.warning("MCP tool result truncated: server=%s tool=%s max_chars=%s", server_name, tool_name, max_result_chars)
            db.mcp.add_tool_call(
                server_name=server_name,
                tool_name=tool_name,
                request_context=request_context,
                status=status,
                arguments=arguments,
                result_preview=result_text,
                error=error_text,
                duration_ms=duration_ms,
            )

            tool_messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": function_name,
                "content": result_text,
            })
    finally:
        db.close()

    return tool_messages


def _normalize_geocoding_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(arguments or {})
    if normalized.get("format"):
        normalized["format"] = str(normalized["format"]).strip().lower()
    if normalized.get("countryCode"):
        normalized["countryCode"] = str(normalized["countryCode"]).strip().upper()
    try:
        normalized["count"] = max(1, min(int(normalized.get("count") or 5), 100))
    except (TypeError, ValueError):
        normalized["count"] = 5
    return normalized


def _geocoding_name_candidates(name: str) -> List[str]:
    original = str(name or "").strip()
    if not original:
        return []
    candidates = [original]
    lower = original.lower()

    if lower.endswith(("е", "а")) and len(original) > 3:
        candidates.append(original[:-1])
    if lower.endswith("пе") and len(original) > 3:
        candidates.append(original[:-1] + "а")
    if lower.endswith("ве") and len(original) > 3:
        candidates.append(original[:-1] + "а")
    if lower.endswith("ы") and len(original) > 3:
        candidates.append(original[:-1] + "а")
    if lower.endswith("и") and len(original) > 3:
        candidates.extend((original[:-1] + "а", original[:-1] + "я"))

    unique = []
    seen = set()
    for candidate in candidates:
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _geocoding_has_results(result_text: str) -> bool:
    try:
        data = json.loads(result_text)
        return bool(isinstance(data, dict) and data.get("results"))
    except Exception:
        return False


def _is_mcp_error_result(result_text: str) -> bool:
    normalized = str(result_text or "").strip().lower()
    return normalized.startswith("error:") or normalized.startswith("mcp error:")


async def _call_geocoding_with_recovery(
    server: Dict[str, Any],
    arguments: Dict[str, Any],
    *,
    timeout_seconds: int,
) -> tuple[str, Dict[str, Any]]:
    candidates = _geocoding_name_candidates(arguments.get("name"))
    if not candidates:
        result = await call_server_tool_async(
            server,
            "geocoding",
            arguments,
            timeout_seconds=timeout_seconds,
        )
        return result, arguments

    last_result = ""
    last_arguments = arguments
    for candidate in candidates:
        candidate_arguments = dict(arguments)
        candidate_arguments["name"] = candidate
        last_arguments = candidate_arguments
        last_result = await call_server_tool_async(
            server,
            "geocoding",
            candidate_arguments,
            timeout_seconds=timeout_seconds,
        )
        if _geocoding_has_results(last_result):
            if candidate != candidates[0]:
                logger.info(
                    "Open-Meteo geocoding recovered location name: %s -> %s",
                    candidates[0],
                    candidate,
                )
            return last_result, candidate_arguments
    return last_result, last_arguments


def _extract_anthropic_tool_uses(response) -> List[Dict]:
    raw = getattr(response, "raw_anthropic", None) or {}
    blocks = raw.get("content") or []
    return [block for block in blocks if isinstance(block, dict) and block.get("type") == "tool_use"]


def _anthropic_assistant_tool_message(response, tool_uses: Optional[List[Dict]] = None) -> Dict:
    raw = getattr(response, "raw_anthropic", None) or {}
    content = raw.get("content") or []
    if tool_uses is not None:
        selected_ids = {item.get("id") for item in tool_uses}
        content = [
            block
            for block in content
            if not isinstance(block, dict)
            or block.get("type") != "tool_use"
            or block.get("id") in selected_ids
        ]
    return {
        "role": "assistant",
        "content": content,
    }


async def _execute_anthropic_mcp_tool_uses(tool_uses: List[Dict], settings: Dict, request_context: Dict) -> List[Dict]:
    openai_style_calls = []
    for tool_use in tool_uses:
        openai_style_calls.append({
            "id": tool_use.get("id") or "",
            "function": {
                "name": tool_use.get("name") or "",
                "arguments": json.dumps(tool_use.get("input") or {}, ensure_ascii=False),
            },
        })

    tool_messages = await _execute_mcp_tool_calls(openai_style_calls, settings, request_context)
    result_blocks = []
    for message in tool_messages:
        result_blocks.append({
            "type": "tool_result",
            "tool_use_id": message.get("tool_call_id") or "",
            "content": [{"type": "text", "text": message.get("content") or ""}],
        })
    return result_blocks


async def get_response_from_model(
    messages: List[Dict], 
    settings: Dict, 
    model_id: str, 
    supports_vision: bool = False,
    request_context: Optional[Dict] = None,
) -> str:
    """
    Получает ответ от модели через AiohttpOpenAIClient.
    """
    # Get model settings
    temperature = settings.get('temperature', 0.7)
    max_tokens = settings.get('max_tokens', 0) or 0
    presence_penalty = settings.get('presence_penalty', 0.0)
    frequency_penalty = settings.get('frequency_penalty', 0.0)
    top_p = settings.get('top_p', 0.95)
    top_k = settings.get('top_k', 40)
    repeat_penalty = settings.get('repeat_penalty', 1.1)
    seed = settings.get('seed', -1)

    logger.info(
        "Отправляем запрос к модели %s с настройками: temperature=%s, max_tokens=%s, top_p=%s, top_k=%s, "
        "presence_penalty=%s, frequency_penalty=%s",
        model_id,
        temperature,
        'auto' if not max_tokens else max_tokens,
        top_p,
        top_k,
        presence_penalty,
        frequency_penalty,
    )

    client = model_clients.get(model_id)
    if not client:
        model_settings = next((m for m in settings.get('models', []) if m.get('id') == model_id), None)
        if not model_settings:
            raise ValueError(f"Настройки для модели {model_id} не найдены")

        base_url = model_settings.get('base_url', '')
        api_key = model_settings.get('api_key', '')
        api_type = model_settings.get('api_type', 'openai')
        
        if api_type == 'anthropic':
            client = AiohttpAnthropicClient(api_key=api_key, base_url=base_url)
            logger.info(f"Создан AiohttpAnthropicClient on-the-fly для модели: {model_id}")
        else:
            client = AiohttpOpenAIClient(api_key=api_key, base_url=base_url)
            logger.info(f"Создан AiohttpOpenAIClient on-the-fly для модели: {model_id}")
        model_clients[model_id] = client

    model_settings = next((m for m in settings.get('models', []) if m.get('id') == model_id), {})

    # Определяем тип клиента для маршрутизации запроса
    is_anthropic = isinstance(client, AiohttpAnthropicClient)
    completion_params = build_model_request_params(
        model_id=model_id,
        messages=messages,
        settings=settings,
        model_settings=model_settings,
        is_anthropic=is_anthropic,
    )
    if model_id in reasoning_disabled_runtime and has_reasoning_params(completion_params):
        completion_params = strip_reasoning_params(completion_params)
        logger.debug(
            "Reasoning skipped for %s because it is disabled until reload: %s",
            model_id,
            reasoning_disabled_runtime[model_id],
        )
    if request_context and is_mcp_sdk_available():
        if is_anthropic:
            anthropic_tools = allowed_anthropic_tools_for_context(settings, request_context)
            if anthropic_tools:
                completion_params["tools"] = anthropic_tools
        else:
            openai_tools = allowed_openai_tools_for_context(settings, request_context)
            if openai_tools:
                completion_params["tools"] = openai_tools
                completion_params["tool_choice"] = "auto"

    async def _perform_request(params):
        try:
            if is_anthropic:
                return await client.create_message(**params)
            else:
                return await client.chat.completions.create(**params)
        except Exception as exc:
            error_text = str(exc).lower()
            unsupported_param_error = (
                "unexpected keyword" in error_text
                or "unrecognized" in error_text
                or "unsupported" in error_text
                or "unknown parameter" in error_text
            )
            if unsupported_param_error and has_reasoning_params(params):
                logger.warning("Reasoning params rejected for %s, retrying without reasoning: %s", model_id, exc)
                no_reasoning_params = strip_reasoning_params(params)
                if is_anthropic:
                    response = await client.create_message(**no_reasoning_params)
                else:
                    response = await client.chat.completions.create(**no_reasoning_params)
                reasoning_disabled_runtime[model_id] = str(exc)
                logger.info("Runtime reasoning disabled for model %s until reload", model_id)
                return response
            # Если ошибка о неподдерживаемых параметрах - пробуем с минимумом
            if unsupported_param_error:
                logger.warning(f"Модель {model_id} не поддерживает часть параметров: {exc}")
                basic_params = {
                    "model": model_id,
                    "messages": params["messages"],
                    "temperature": temperature,
                }
                if is_anthropic:
                    basic_params["max_tokens"] = max_tokens if max_tokens and max_tokens > 0 else 4096
                    return await client.create_message(**basic_params)
                else:
                    basic_params["presence_penalty"] = presence_penalty
                    basic_params["frequency_penalty"] = frequency_penalty
                    if max_tokens and max_tokens > 0:
                        basic_params["max_tokens"] = max_tokens
                    return await client.chat.completions.create(**basic_params)
            raise

    # (Вынесено выше на уровень модуля)

    # Если это Chutes.ai, то клиент сам сделает 12 попыток.
    # Поэтому на уровне этого метода достаточно 1 попытки, если это Chutes,
    # и 2 попытки (включая один перезапуск) для всех остальных случаев.
    # Проверяем URL в клиенте (если он уже создан)
    is_chutes = False
    if client and hasattr(client, 'base_url'):
        is_chutes = "chutes.ai" in client.base_url.lower()
    else:
        # Если клиент еще не создан, ищем в настройках по model_id
        model_settings = next((m for m in settings.get('models', []) if m.get('id') == model_id), None)
        if model_settings:
            is_chutes = "chutes.ai" in model_settings.get('base_url', '').lower()

    max_attempts = 1 if is_chutes else 2
    
    for attempt in range(max_attempts):
        current_params = dict(completion_params)
        try:
            logger.debug(f"Отправка запроса к модели {model_id} (попытка {attempt + 1}/{max_attempts})")
            
            messages_for_log = _sanitize_messages_for_log(current_params["messages"]) if supports_vision else current_params["messages"]
            endpoint = "/v1/messages" if is_anthropic else "/v1/chat/completions"
            logger.debug(
                "Отправляем запрос: POST %s, сообщений: %d",
                endpoint,
                len(current_params.get("messages", [])),
            )

            response = await _perform_request(current_params)
            mcp_limits = get_mcp_settings(settings).get("limits") or {}
            max_tool_calls = int(mcp_limits.get("max_tool_calls_per_request", 5) or 5)
            executed_tool_calls = 0
            used_mcp_tools = False

            while executed_tool_calls < max_tool_calls:
                if not is_anthropic:
                    tool_calls = _extract_tool_calls(response)
                    if not tool_calls:
                        break
                    remaining = max_tool_calls - executed_tool_calls
                    selected_calls = tool_calls[:remaining]
                    tool_messages = await _execute_mcp_tool_calls(
                        selected_calls,
                        settings,
                        request_context or {},
                    )
                    if not tool_messages:
                        break
                    executed_tool_calls += len(selected_calls)
                    used_mcp_tools = True
                    next_params = dict(current_params)
                    next_params["messages"] = (
                        list(current_params.get("messages") or [])
                        + [_assistant_tool_call_message(response, selected_calls)]
                        + tool_messages
                    )
                    response = await _perform_request(next_params)
                    current_params = next_params
                    continue

                tool_uses = _extract_anthropic_tool_uses(response)
                if not tool_uses:
                    break
                remaining = max_tool_calls - executed_tool_calls
                selected_uses = tool_uses[:remaining]
                tool_result_blocks = await _execute_anthropic_mcp_tool_uses(
                    selected_uses,
                    settings,
                    request_context or {},
                )
                if not tool_result_blocks:
                    break
                executed_tool_calls += len(selected_uses)
                used_mcp_tools = True
                next_params = dict(current_params)
                next_params["messages"] = (
                    list(current_params.get("messages") or [])
                    + [_anthropic_assistant_tool_message(response, selected_uses)]
                    + [{"role": "user", "content": tool_result_blocks}]
                )
                response = await _perform_request(next_params)
                current_params = next_params

            still_requests_tool = bool(
                _extract_anthropic_tool_uses(response)
                if is_anthropic
                else _extract_tool_calls(response)
            )
            if used_mcp_tools and still_requests_tool:
                logger.warning(
                    "MCP tool call limit reached for model %s: %s",
                    model_id,
                    max_tool_calls,
                )
                final_params = dict(current_params)
                final_params.pop("tool_choice", None)
                final_params.pop("tools", None)
                final_params["messages"] = list(current_params.get("messages") or []) + [{
                    "role": "user",
                    "content": (
                        "Лимит вызовов инструментов исчерпан. Сформулируй лучший возможный "
                        "ответ по уже полученным результатам, без новых tool calls."
                    ),
                }]
                response = await _perform_request(final_params)
                current_params = final_params

            raw_response_text = ""
            try:
                raw_response_text = (response.choices[0].message.content or "").strip()
            except Exception:
                raw_response_text = ""
            if raw_response_text and RAW_TOOL_CALL_RE.search(raw_response_text):
                resolved_response, resolved_params = await _resolve_raw_text_tool_calls(
                    response_text=raw_response_text,
                    current_params=current_params,
                    completion_params=completion_params,
                    settings=settings,
                    request_context=request_context or {},
                    perform_request=_perform_request,
                )
                if resolved_response is not None and resolved_params is not None:
                    response = resolved_response
                    current_params = resolved_params

            _record_usage(
                response, 
                messages=current_params.get("messages"), 
                response_text=(response.choices[0].message.content if response and response.choices else None),
                model_id=model_id
            )

            response_text = (response.choices[0].message.content or "").strip()
            if not response_text:
                logger.warning(
                    "Модель %s вернула пустой ответ (попытка %s/%s)",
                    model_id,
                    attempt + 1,
                    max_attempts,
                )
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.2)
                    continue
                return "Извините, модель вернула пустой ответ. Пожалуйста, повторите ваш запрос."

            logger.debug(f"Сырой ответ от модели {model_id} (первые 100 символов): {response_text[:100]}...")
            cleaned_response = clean_response(response_text)
            if RAW_TOOL_CALL_RE.search(cleaned_response):
                stripped_response = _strip_raw_tool_call_blocks(cleaned_response)
                if stripped_response:
                    logger.warning("Из ответа модели %s удалён сырой MCP tool_call блок", model_id)
                    cleaned_response = stripped_response
                else:
                    logger.warning("Ответ модели %s состоял только из сырого MCP tool_call блока", model_id)
                    return (
                        "Извините, не получилось корректно выполнить инструмент. "
                        "Пожалуйста, повторите запрос."
                    )

            normalized_response = cleaned_response.strip().lower()
            placeholder_match = normalized_response in {
                '[нет ответа — служебный плейсхолдер]'.lower(),
                '...',
                '…'
            }

            if placeholder_match:
                logger.warning(
                    "Модель %s вернула служебный плейсхолдер вместо ответа", model_id
                )
                if attempt < max_attempts - 1:
                    reminder_message = {
                        "role": "system",
                        "content": (
                            "Прошлый ответ был пустым/служебным. Сформулируй новый полноценно, без "
                            "цитирования плейсхолдеров."
                        ),
                    }
                    completion_params = dict(completion_params)
                    completion_params["messages"] = completion_params["messages"] + [reminder_message]
                    await asyncio.sleep(0.2)
                    continue
                return (
                    "Извините, ответ не сформирован. Пожалуйста, повторите вопрос или перефразируйте его."
                )

            if not cleaned_response or cleaned_response.strip() == "":
                logger.warning(f"Ответ от модели {model_id} стал пустым после очистки")
                if response_text:
                    logger.info("Возвращаем исходный неочищенный текст, поскольку очистка привела к пустому результату")
                    return response_text
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.2)
                    continue
                return "Извините, не могу сформулировать ответ. Пожалуйста, повторите ваш запрос."

            return cleaned_response

        except Exception as e:
            logger.error(f"Ошибка при запросе к модели {model_id}: {e}")

            if attempt < max_attempts - 1:
                logger.warning(
                    "Повторная попытка запроса к модели %s после ошибки: %s",
                    model_id,
                    e,
                )
                await asyncio.sleep(0.2)
                continue

            return f"Извините, произошла ошибка при обращении к модели {model_id}. Попробуйте ещё раз позже."

    return "Извините, модель вернула пустой ответ. Пожалуйста, повторите ваш запрос."


async def stream_from_model(
    messages: List[Dict],
    settings: Dict,
    model_id: str,
) -> AsyncGenerator[str, None]:
    """
    Async-генератор: получает куски текста от модели через SSE-стриминг.

    Только для OpenAI-совместимых клиентов (AiohttpOpenAIClient).
    Для Anthropic вызывает RuntimeError — проверяй is_anthropic_client() заранее.
    """
    client = model_clients.get(model_id)
    if client is None:
        # Попытка создать клиент на лету
        model_settings = next((m for m in settings.get('models', []) if m.get('id') == model_id), None)
        if not model_settings:
            raise ValueError(f"Настройки для модели {model_id} не найдены")
        api_type = model_settings.get('api_type', 'openai')
        if api_type == 'anthropic':
            raise RuntimeError("Стриминг не поддерживается для Anthropic-клиента")
        client = AiohttpOpenAIClient(
            api_key=model_settings.get('api_key', ''),
            base_url=model_settings.get('base_url', ''),
        )
        model_clients[model_id] = client

    if isinstance(client, AiohttpAnthropicClient):
        raise RuntimeError("Стриминг не поддерживается для Anthropic-клиента")

    temperature = settings.get('temperature', 0.7)
    max_tokens = settings.get('max_tokens', 0) or 0
    presence_penalty = settings.get('presence_penalty', 0.0)
    frequency_penalty = settings.get('frequency_penalty', 0.0)
    top_p = settings.get('top_p', 0.95)

    model_settings = next((m for m in settings.get('models', []) if m.get('id') == model_id), {})
    params = build_model_request_params(
        model_id=model_id,
        messages=messages,
        settings=settings,
        model_settings=model_settings,
        is_anthropic=False,
    )
    if model_id in reasoning_disabled_runtime and has_reasoning_params(params):
        params = strip_reasoning_params(params)

    logger.info("Запускаем SSE-стриминг для модели %s", model_id)
    full_response_content = []

    try:
        async for chunk in client.chat.completions.create_stream(**params):
            full_response_content.append(chunk)
            yield chunk
    except Exception as exc:
        error_text = str(exc).lower()
        unsupported_param_error = (
            "unexpected keyword" in error_text
            or "unrecognized" in error_text
            or "unsupported" in error_text
            or "unknown parameter" in error_text
        )
        if unsupported_param_error and has_reasoning_params(params):
            logger.warning("Reasoning params rejected for streaming %s, retrying without reasoning: %s", model_id, exc)
            reasoning_disabled_runtime[model_id] = str(exc)
            params = strip_reasoning_params(params)
            full_response_content.clear()
            async for chunk in client.chat.completions.create_stream(**params):
                full_response_content.append(chunk)
                yield chunk
        else:
            raise
        
    # По завершении стриминга записываем статистику (т.к. стриминг часто не возвращает usage в чанках)
    try:
        total_text = "".join(full_response_content)
        stream_usage = getattr(client, "_last_stream_usage", None)
        if stream_usage:
            response_stub = type(
                "StreamUsageResponse",
                (),
                {
                    "usage": stream_usage,
                    "provider": getattr(client, "provider", ""),
                },
            )()
            _record_usage(
                response_stub,
                messages=messages,
                response_text=total_text,
                model_id=model_id,
            )
        else:
            # Для стриминга используем fallback-подсчет, если провайдер не прислал usage
            _record_usage(None, messages=messages, response_text=total_text, model_id=model_id)
    except Exception as e:
        logger.warning(f"Ошибка подсчета токенов после стриминга: {e}")


def is_anthropic_client(model_id: str) -> bool:
    """Возвращает True если клиент модели — Anthropic (не поддерживает стриминг)."""
    client = model_clients.get(model_id)
    return isinstance(client, AiohttpAnthropicClient)


def _sanitize_messages_for_log(messages: List[Dict]) -> List[Dict]:
    """Скрывает base64-данные изображений в логах для читаемости."""
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
