# utils/logger.py

import logging

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
