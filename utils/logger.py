# utils/logger.py

import logging
import os
from logging.handlers import RotatingFileHandler

_configured_log_file = None


def configure_file_logging(log_file):
    """Attach one rotating file handler to the root logger."""
    global _configured_log_file
    if not log_file:
        return
    target = os.path.abspath(log_file)
    if _configured_log_file == target:
        return
    os.makedirs(os.path.dirname(target) or os.getcwd(), exist_ok=True)
    root = logging.getLogger()
    handler = RotatingFileHandler(target, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    _configured_log_file = target

def setup_logger(name=None, level=logging.INFO, log_file=None):
    # Создаём кастомный логгер
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Проверяем, есть ли уже обработчики, чтобы избежать дублирования
    if not logger.handlers:
        # Создаём обработчик вывода в консоль
        ch = logging.StreamHandler()
        ch.setLevel(level)
        # Задаём формат логов для консоли
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        # Создаём обработчик записи в файл, если указан
        if log_file:
            fh = logging.FileHandler(log_file)
            fh.setLevel(level)
            formatter_file = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
            fh.setFormatter(formatter_file)
            logger.addHandler(fh)

    return logger
