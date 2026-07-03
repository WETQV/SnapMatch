from typing import Any, Dict, List

from utils.logger import setup_logger

logger = setup_logger(__name__)

REASONING_MODES = {"default", "auto", "off", "minimal", "low", "medium", "high", "xhigh"}
REASONING_PROVIDERS = {"auto", "openrouter", "openai_compatible", "anthropic_adaptive", "anthropic_budget"}
OPENAI_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high"}
OPENROUTER_REASONING_EFFORTS = {"minimal", "low", "medium", "high"}
REASONING_PAYLOAD_KEYS = {"reasoning", "reasoning_effort", "thinking", "output_config"}


def build_model_request_params(
    *,
    model_id: str,
    messages: List[Dict],
    settings: Dict[str, Any],
    model_settings: Dict[str, Any],
    is_anthropic: bool,
) -> Dict[str, Any]:
    max_tokens = settings.get('max_tokens', 0) or 0

    params: Dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": settings.get('temperature', 0.7),
        "top_p": settings.get('top_p', 0.95),
    }

    if is_anthropic:
        params["max_tokens"] = max_tokens if max_tokens and max_tokens > 0 else 4096
    else:
        params["presence_penalty"] = settings.get('presence_penalty', 0.0)
        params["frequency_penalty"] = settings.get('frequency_penalty', 0.0)
        if max_tokens and max_tokens > 0:
            params["max_tokens"] = max_tokens

    reasoning_params = build_reasoning_params(
        model_settings,
        is_anthropic=is_anthropic,
        model_id=model_id,
        max_tokens=int(params.get("max_tokens") or 0),
    )
    if reasoning_params:
        params.update(reasoning_params)
        filter_generation_params_for_reasoning(params, model_settings)

    return params


def build_reasoning_params(
    model_settings: Dict[str, Any],
    *,
    is_anthropic: bool,
    model_id: str,
    max_tokens: int,
) -> Dict[str, Any]:
    mode = _normalize_reasoning_mode(model_settings)
    provider = _normalize_reasoning_provider(model_settings)

    if mode == "default":
        logger.debug("Reasoning mode for model %s: default, no explicit params sent", model_id)
        return {}

    if provider == "auto":
        provider = _detect_reasoning_provider(model_settings, is_anthropic=is_anthropic)

    logger.debug("Reasoning mode for model %s: %s (%s)", model_id, mode, provider)

    if provider == "openrouter":
        params = _build_openrouter_reasoning(mode, model_settings)
    elif provider == "openai_compatible":
        params = _build_openai_compatible_reasoning(mode)
    elif provider == "anthropic_adaptive":
        params = _build_anthropic_adaptive_reasoning(mode)
    elif provider == "anthropic_budget":
        params = _build_anthropic_budget_reasoning(mode, model_settings, model_id=model_id, max_tokens=max_tokens)
    else:
        params = {}

    if params:
        logger.info("Explicit reasoning applied: model_id=%s provider=%s mode=%s", model_id, provider, mode)
    else:
        logger.debug("Reasoning skipped for model %s: mode=%s provider=%s", model_id, mode, provider)
    return params


def filter_generation_params_for_reasoning(
    params: Dict[str, Any],
    model_settings: Dict[str, Any],
) -> None:
    if not model_settings.get("disable_sampling_for_reasoning", True):
        return
    for key in ("temperature", "top_p"):
        params.pop(key, None)


def strip_reasoning_params(params: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(params)
    for key in REASONING_PAYLOAD_KEYS:
        cleaned.pop(key, None)
    return cleaned


def has_reasoning_params(params: Dict[str, Any]) -> bool:
    return any(key in params for key in REASONING_PAYLOAD_KEYS)


def _normalize_reasoning_mode(model_settings: Dict[str, Any]) -> str:
    legacy_enabled = bool(model_settings.get("reasoning_enabled", False))
    raw_mode = model_settings.get("reasoning_mode")
    if not raw_mode:
        raw_mode = model_settings.get("reasoning_effort") if legacy_enabled else "default"
    mode = str(raw_mode or "default").strip().lower()
    if mode == "none":
        mode = "off"
    return mode if mode in REASONING_MODES else "default"


def _normalize_reasoning_provider(model_settings: Dict[str, Any]) -> str:
    provider = str(model_settings.get("reasoning_provider") or "auto").strip().lower()
    return provider if provider in REASONING_PROVIDERS else "auto"


def _detect_reasoning_provider(model_settings: Dict[str, Any], *, is_anthropic: bool) -> str:
    if is_anthropic:
        return "anthropic_budget" if int(model_settings.get("reasoning_budget_tokens") or 0) > 0 else "anthropic_adaptive"

    base_url = str(model_settings.get("base_url") or "").lower()
    if "openrouter.ai" in base_url:
        return "openrouter"
    if "api.openai.com" in base_url:
        return "openai_compatible"
    return ""


def _build_openrouter_reasoning(mode: str, model_settings: Dict[str, Any]) -> Dict[str, Any]:
    if mode == "auto":
        return {"reasoning": {"enabled": True, "exclude": True}}
    if mode == "off":
        return {"reasoning": {"enabled": False, "exclude": True}}

    budget = int(model_settings.get("reasoning_budget_tokens") or 0)
    if budget > 0:
        return {"reasoning": {"max_tokens": budget, "exclude": True}}

    effort = "high" if mode == "xhigh" else mode
    if effort not in OPENROUTER_REASONING_EFFORTS:
        effort = "medium"
    return {"reasoning": {"effort": effort, "exclude": True}}


def _build_openai_compatible_reasoning(mode: str) -> Dict[str, Any]:
    if mode == "auto":
        return {}
    effort = "none" if mode == "off" else ("high" if mode == "xhigh" else mode)
    if effort not in OPENAI_REASONING_EFFORTS:
        effort = "medium"
    return {"reasoning_effort": effort}


def _build_anthropic_adaptive_reasoning(mode: str) -> Dict[str, Any]:
    if mode == "off":
        return {}
    effort = "high" if mode == "xhigh" else mode
    if effort == "auto":
        return {"thinking": {"type": "adaptive", "display": "omitted"}}
    if effort not in {"minimal", "low", "medium", "high"}:
        effort = "medium"
    return {
        "thinking": {"type": "adaptive", "display": "omitted"},
        "output_config": {"effort": effort},
    }


def _build_anthropic_budget_reasoning(
    mode: str,
    model_settings: Dict[str, Any],
    *,
    model_id: str,
    max_tokens: int,
) -> Dict[str, Any]:
    if mode == "off":
        return {}
    budget = int(model_settings.get("reasoning_budget_tokens") or 0)
    if budget < 1024:
        logger.warning("Thinking budget skipped for %s because budget_tokens is below 1024", model_id)
        return {}
    if max_tokens and budget >= max_tokens:
        logger.warning("Thinking budget skipped for %s because max_tokens is too low", model_id)
        return {}
    return {"thinking": {"type": "enabled", "budget_tokens": budget, "display": "omitted"}}
