import re
from typing import Optional, List, Dict, Any
import importlib
import unicodedata

_ENCODER_CACHE: Dict[str, object] = {}

def _guess_encoding_name(model_id: Optional[str], encoding_name: Optional[str]) -> str:
    if encoding_name:
        return encoding_name

    model_name = (model_id or "").lower()
    if model_name.startswith(("gpt-4o", "o1", "o3", "o4")):
        return "o200k_base"
    return "cl100k_base"


def _load_tiktoken_encoder(encoding_name: str, model_id: Optional[str] = None):
    try:
        import tiktoken  # type: ignore
        if model_id:
            try:
                return tiktoken.encoding_for_model(model_id)
            except Exception:
                pass
        return tiktoken.get_encoding(encoding_name)
    except Exception:
        return None

def _load_hf_tokenizer(model_id: str):
    """
    Динамическая загрузка transformers во избежание попадания всей библиотеки в билд.
    """
    try:
        transformers = importlib.import_module("transformers")  # type: ignore
        AutoTokenizer = getattr(transformers, "AutoTokenizer", None)
        if AutoTokenizer is None:
            return None
        return AutoTokenizer.from_pretrained(model_id)
    except Exception:
        return None

def count_tokens(
    text: Any,
    model_id: Optional[str] = None,
    encoding_name: Optional[str] = None,
    allow_hf_tokenizer: bool = True,
) -> int:
    """
    Возвращает количество токенов для заданного текста или списка частей (Vision).
    """
    if not text:
        return 0

    # Обработка мультимодальных сообщений (список частей)
    if isinstance(text, list):
        total = 0
        for part in text:
            if isinstance(part, dict):
                if part.get('type') == 'text':
                    total += count_tokens(
                        part.get('text', ''),
                        model_id,
                        encoding_name,
                        allow_hf_tokenizer=allow_hf_tokenizer,
                    )
                elif part.get('type') == 'image_url':
                    # Усредненная оценка для изображений (у OpenAI это ~85-170+ токенов)
                    total += 85 
            elif isinstance(part, str):
                total += count_tokens(
                    part,
                    model_id,
                    encoding_name,
                    allow_hf_tokenizer=allow_hf_tokenizer,
                )
        return total

    # Принудительно приводим к строке, если пришло что-то иное
    if not isinstance(text, str):
        text = str(text)

    # 1. tiktoken
    encoding_key = _guess_encoding_name(model_id, encoding_name)
    encoder = _ENCODER_CACHE.get(encoding_key)
    if encoder is None:
        encoder = _load_tiktoken_encoder(encoding_key, model_id=model_id)
        if encoder is not None:
            _ENCODER_CACHE[encoding_key] = encoder
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception:
            pass

    # 2. HF tokenizer
    if allow_hf_tokenizer and model_id:
        hf_key = f"hf::{model_id}"
        hf_tok = _ENCODER_CACHE.get(hf_key)
        if hf_tok is None:
            hf_tok = _load_hf_tokenizer(model_id)
            if hf_tok is not None:
                _ENCODER_CACHE[hf_key] = hf_tok
        if hf_tok is not None:
            try:
                return len(hf_tok.encode(text))
            except Exception:
                pass

    # 3. Эвристика
    return _heuristic_token_count(text)

def _heuristic_token_count(text: str) -> int:
    # Базовая оценка: ~0.75 токена на слово для кириллицы/латиницы
    words = len(re.findall(r"[\w\-]+", text, flags=re.UNICODE))
    base = int(words * 0.75)

    # Бонус за символы пунктуации и спецсимволы
    punct = sum(1 for ch in text if unicodedata.category(ch)[0] in {"P", "S"})
    bonus = int(punct * 0.5)

    # Бонус за длину (для длинных строк)
    length_bonus = int(len(text) * 0.05)

    # Кодовые блоки и inline-код
    code_blocks = len(re.findall(r"```[\s\S]*?```", text))
    inline_code = len(re.findall(r"`[^`\n]+?`", text))
    code_bonus = code_blocks * 50 + inline_code * 5

    return max(1, base + bonus + length_bonus + code_bonus)

def count_message_tokens(messages: List[Dict], model_id: Optional[str] = None, encoding_name: Optional[str] = None) -> int:
    """Считает токены для списка сообщений, поддерживая Vision формат."""
    if not messages:
        return 0

    model_name = (model_id or "").lower()
    if model_name.startswith("gpt-3.5"):
        tokens_per_message = 4
        tokens_per_name = -1
    else:
        tokens_per_message = 3
        tokens_per_name = 1

    total = 0
    for msg in messages:
        total += tokens_per_message
        # Считаем контент сообщения (может быть str или list)
        total += count_tokens(msg.get("content", ""), model_id, encoding_name)
        if msg.get("role"):
            total += count_tokens(msg.get("role", ""), model_id, encoding_name)
        if msg.get("name"):
            total += count_tokens(msg.get("name", ""), model_id, encoding_name)
            total += tokens_per_name

    total += 3
    return total


