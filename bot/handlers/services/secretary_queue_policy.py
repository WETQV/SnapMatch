from typing import Any, Dict, Optional


def is_secretary_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False

    if payload.get("source_mode") == "secretary":
        return True

    request_context = payload.get("request_context")
    if isinstance(request_context, dict):
        return request_context.get("source_mode") == "secretary"

    return False


def suppress_model_unavailable_notice(payload: Any, settings: Optional[Dict] = None) -> bool:
    if not is_secretary_payload(payload):
        return False

    secretary_mode = (settings or {}).get("secretary_mode") or {}
    return bool(secretary_mode.get("suppress_model_unavailable_notice", True))
