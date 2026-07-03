# gui/admin_panel/services/__init__.py
"""
Services層 для GUI админ-панели.
Отвечают за бизнес-логику управления пользователями, статистикой и моделями,
отделённую от UI-компонентов PyQt.
"""

from .model_service import ModelService
from .user_service import UserService
from .stats_service import StatsService

__all__ = [
    'ModelService',
    'UserService',
    'StatsService',
]

