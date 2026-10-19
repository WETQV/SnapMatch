"""Список STT-моделей OpenAI: запрос GET {base_url}/models, дисковый кэш, запасной список, устаревание.

Без сторонних зависимостей (aiohttp уже есть в проекте). Ключ API не пишется ни в кэш, ни в лог.
Модуль не импортирует config.settings, чтобы settings мог безопасно использовать миграцию отсюда.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import time
from typing import Any, Dict, Iterable, List, Optional

from utils.app_paths import get_user_data_dir
from utils.logger import setup_logger

logger = setup_logger(__name__)

OPENAI_BASE_URL = "https://api.openai.com/v1"
CACHE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_STT_MODEL = "gpt-transcribe"

# Дата отключения старых STT-моделей OpenAI (https://developers.openai.com/api/docs/deprecations)
LEGACY_REMOVAL_DATE = datetime.date(2027, 2, 26)
LEGACY_STT_MODELS = frozenset({
    "whisper-1",
    "gpt-4o-transcribe",
    "gpt-4o-mini-transcribe",
    "gpt-4o-transcribe-diarize",
})

FALLBACK_MODEL_IDS = (
    "gpt-transcribe",
    "gpt-live-transcribe",
    "whisper-1",
    "gpt-4o-transcribe",
    "gpt-4o-mini-transcribe",
)


def _cache_path() -> str:
    return str(get_user_data_dir() / "cache" / "openai_stt_models.json")


def _entry(model_id: str, shutdown_date: Optional[str] = None) -> Dict[str, Any]:
    if not shutdown_date and model_id in LEGACY_STT_MODELS:
        shutdown_date = LEGACY_REMOVAL_DATE.isoformat()
    return {"id": model_id, "shutdown_date": shutdown_date or None, "deprecated": bool(shutdown_date)}


def fallback_models() -> List[Dict[str, Any]]:
    return [_entry(m) for m in FALLBACK_MODEL_IDS]


def is_stt_model_id(model_id: str) -> bool:
    low = str(model_id).lower()
    return "transcribe" in low or "whisper" in low


def filter_stt_models(raw_models: Iterable[Any]) -> List[Dict[str, Any]]:
    """Оставляет модели распознавания речи; помечает устаревшие (shutdown_date из API или известный список)."""
    result: Dict[str, Dict[str, Any]] = {}
    for item in raw_models or []:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id or not is_stt_model_id(model_id):
            continue
        shutdown = item.get("shutdown_date")
        result[model_id] = _entry(model_id, str(shutdown) if shutdown else None)
    # Новые модели сверху, устаревшие внизу, внутри групп по имени
    return sorted(result.values(), key=lambda e: (e["deprecated"], e["id"]))


# ───────────────────────── кэш ─────────────────────────
def _read_cache(base_url: str, ttl: float = CACHE_TTL_SECONDS, now: Optional[float] = None,
                allow_stale: bool = False) -> Optional[List[Dict[str, Any]]]:
    try:
        with open(_cache_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        entry = data.get(base_url.rstrip("/"))
        if not isinstance(entry, dict) or not isinstance(entry.get("models"), list):
            return None
        age = (time.time() if now is None else now) - float(entry.get("ts", 0))
        if age > ttl and not allow_stale:
            return None
        return entry["models"]
    except Exception:
        return None


def _write_cache(base_url: str, models: List[Dict[str, Any]], now: Optional[float] = None) -> None:
    path = _cache_path()
    try:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        data[base_url.rstrip("/")] = {"ts": time.time() if now is None else now, "models": models}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as exc:
        logger.warning("Не удалось записать кэш моделей STT: %s", type(exc).__name__)


# ───────────────────────── сеть ─────────────────────────
async def fetch_models_async(base_url: str, api_key: str, timeout: float = 10.0) -> List[Dict[str, Any]]:
    """GET {base_url}/models -> отфильтрованный список STT-моделей. Бросает исключение при ошибке."""
    import aiohttp

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{base_url.rstrip('/')}/models", headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            payload = await response.json()
    return filter_stt_models(payload.get("data", []) if isinstance(payload, dict) else [])


async def get_stt_models_async(base_url: str = OPENAI_BASE_URL, api_key: str = "",
                               force: bool = False) -> List[Dict[str, Any]]:
    """Кэш (24 ч) -> сеть -> устаревший кэш -> запасной список. Никогда не бросает исключение."""
    base_url = (base_url or OPENAI_BASE_URL).rstrip("/")
    if not force:
        cached = _read_cache(base_url)
        if cached:
            return cached
    if api_key:
        try:
            models = await fetch_models_async(base_url, api_key)
            if models:
                _write_cache(base_url, models)
                return models
        except Exception as exc:  # текст исключения aiohttp может содержать URL, но не ключ
            logger.warning("Не удалось получить список моделей STT: %s", type(exc).__name__)
    return _read_cache(base_url, allow_stale=True) or fallback_models()


def get_stt_models(base_url: str = OPENAI_BASE_URL, api_key: str = "", force: bool = False) -> List[Dict[str, Any]]:
    """Синхронная обёртка для фонового потока GUI (gui.async_worker.run_in_background). Не вызывать из GUI-потока."""
    try:
        return asyncio.run(get_stt_models_async(base_url, api_key, force))
    except Exception as exc:
        logger.warning("Список моделей STT недоступен: %s", type(exc).__name__)
        return fallback_models()


# ───────────────────────── устаревание и миграция ─────────────────────────
def is_legacy_stt_model(model: str) -> bool:
    return str(model or "").strip() in LEGACY_STT_MODELS


def effective_openai_stt_model(model: str, today: Optional[datetime.date] = None) -> str:
    """Модель, с которой реально ходить в api.openai.com: после даты отключения подставляется gpt-transcribe."""
    model = str(model or "").strip() or DEFAULT_STT_MODEL
    if is_legacy_stt_model(model) and (today or datetime.date.today()) >= LEGACY_REMOVAL_DATE:
        return DEFAULT_STT_MODEL
    return model


def migrate_stt_settings(settings: Dict[str, Any], today: Optional[datetime.date] = None) -> bool:
    """Меняет settings['stt_openai_model'] на gpt-transcribe, только если старая модель уже отключена.

    До даты отключения сохранённое значение не трогаем (оно рабочее). stt_custom_model и stt_groq_model
    не меняются никогда. Возвращает True, если значение изменено.
    """
    current = settings.get("stt_openai_model")
    new = effective_openai_stt_model(current, today)
    if current and new != current:
        settings["stt_openai_model"] = new
        return True
    return False
