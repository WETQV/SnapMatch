# utils/llm_response.py
"""
Единые структуры данных для ответов LLM и учёта токенов.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TokenUsage:
    """Единый формат информации о токенах, независимо от провайдера."""
    input_tokens: int = 0        # Сколько токенов ушло на промпт
    output_tokens: int = 0       # Сколько токенов в ответе
    total_tokens: int = 0        # Суммарно
    is_estimated: bool = False   # True если посчитано приблизительно (fallback)
    model: str = ""              # Какая модель использовалась
    provider: str = ""           # Какой провайдер (openai, anthropic, ollama...)
    
    def __post_init__(self):
        # Если total не указан, считаем сами
        if self.total_tokens == 0 and (self.input_tokens or self.output_tokens):
            self.total_tokens = self.input_tokens + self.output_tokens


@dataclass
class LLMResponse:
    """Результат вызова LLM — текст + метаданные об использовании."""
    content: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    success: bool = True
    error: Optional[str] = None
