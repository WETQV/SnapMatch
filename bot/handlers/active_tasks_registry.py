# bot/handlers/active_tasks_registry.py
import asyncio
from typing import Set

# Реестр активных задач asyncio.Task для отслеживания всех выполняемых запросов.
# Использование отдельного модуля позволяет избежать циклических импортов
# между queue_manager и queue_processor.
active_tasks: Set[asyncio.Task] = set()
