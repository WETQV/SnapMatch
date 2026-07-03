# utils/stats.py

import threading

class ThreadSafeStats:
    """Потокобезопасный класс для хранения статистики"""
    def __init__(self):
        self._wait_times = []
        self._response_times = []
        self._session_request_count = 0
        self._context_truncated_count = 0
        self._input_tokens_total = 0
        self._output_tokens_total = 0
        self._pending_requests = 0
        self._lock = threading.Lock()
    
    def add_wait_time(self, time):
        with self._lock:
            self._wait_times.append(time)
    
    def add_response_time(self, time):
        with self._lock:
            self._response_times.append(time)
    
    def increment_request_count(self):
        with self._lock:
            self._session_request_count += 1
            return self._session_request_count
    
    def get_wait_times(self):
        with self._lock:
            return self._wait_times.copy()
    
    def get_response_times(self):
        with self._lock:
            return self._response_times.copy()
    
    def get_request_count(self):
        with self._lock:
            return self._session_request_count

    # Новые методы для учёта обрезаний контекста
    def increment_context_truncated(self):
        with self._lock:
            self._context_truncated_count += 1
            return self._context_truncated_count

    def get_context_truncated_count(self):
        with self._lock:
            return self._context_truncated_count

    def get_context_truncated_ratio(self):
        with self._lock:
            total = self._session_request_count or 1
            return (self._context_truncated_count / total) * 100.0
    
    def reset(self):
        with self._lock:
            self._wait_times.clear()
            self._response_times.clear()
            self._session_request_count = 0
            self._context_truncated_count = 0
            self._input_tokens_total = 0
            self._output_tokens_total = 0
            self._pending_requests = 0

    # Токены
    def add_input_tokens(self, n: int):
        if n is None:
            return
        with self._lock:
            self._input_tokens_total += max(0, int(n))

    def add_output_tokens(self, n: int):
        if n is None:
            return
        with self._lock:
            self._output_tokens_total += max(0, int(n))

    def get_input_tokens_total(self) -> int:
        with self._lock:
            return self._input_tokens_total

    def get_output_tokens_total(self) -> int:
        with self._lock:
            return self._output_tokens_total

    # Очередь запросов
    def increment_pending_requests(self) -> int:
        with self._lock:
            self._pending_requests += 1
            return self._pending_requests

    def decrement_pending_requests(self) -> int:
        with self._lock:
            self._pending_requests = max(0, self._pending_requests - 1)
            return self._pending_requests

    def get_pending_requests(self) -> int:
        with self._lock:
            return self._pending_requests

# Создаём единственный экземпляр для использования во всём приложении
stats = ThreadSafeStats()

# Для обратной совместимости
wait_times = stats.get_wait_times()
response_times = stats.get_response_times()
session_request_count = stats.get_request_count()
