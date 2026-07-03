# bot/handlers/services/image_processor.py
"""
Модуль для работы с изображениями.
Отвечает за кодирование изображений и подготовку data URL для отправки в модель.
"""

import base64
import mimetypes
import os
from pathlib import Path
from typing import Optional
from uuid import uuid4
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Директория для загрузок
UPLOADS_DIR = Path("assets") / "uploads"


def build_image_data_url(path: str, mime: Optional[str]) -> Optional[str]:
    """
    Преобразует файл изображения в data URL для отправки в VLM-модель.
    
    Args:
        path: Путь к файлу изображения
        mime: MIME-тип изображения (если неизвестен, определяется автоматически)
        
    Returns:
        Data URL в формате 'data:image/jpeg;base64,...' или None при ошибке
    """
    try:
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode('utf-8')
        mime_type = mime or mimetypes.guess_type(path)[0] or "image/jpeg"
        return f"data:{mime_type};base64,{encoded}"
    except FileNotFoundError:
        logger.warning(f"Файл изображения не найден: {path}")
        return None
    except Exception as exc:
        logger.error(f"Не удалось подготовить изображение {path}: {exc}")
        return None


async def redownload_image(
    bot,
    telegram_file_id: str,
    mime: Optional[str] = None,
) -> Optional[dict]:
    """
    Перескачивает изображение от Telegram по file_id.
    Используется когда локальный файл был удалён для экономии места.
    
    Args:
        bot: Экземпляр бота aiogram
        telegram_file_id: Идентификатор файла в Telegram
        mime: MIME-тип изображения (определяется автоматически, если не передан)
        
    Returns:
        dict с ключами:
        - path: путь к сохранённому файлу
        - mime: MIME тип изображения
        Или None при ошибке
    """
    try:
        file = await bot.get_file(telegram_file_id)
        download_stream = await bot.download_file(file.file_path)
        
        # Читаем данные
        from io import BytesIO
        if isinstance(download_stream, BytesIO):
            data = download_stream.getvalue()
        else:
            data = download_stream.read()
        
        # Определяем MIME и расширение
        mime_type = mime or mimetypes.guess_type(file.file_path)[0] or "image/jpeg"
        suffix = Path(file.file_path).suffix or mimetypes.guess_extension(mime_type) or ".jpg"
        
        # Сохраняем файл
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid4().hex}{suffix}"
        target_path = UPLOADS_DIR / filename
        
        with open(target_path, "wb") as f:
            f.write(data)
        
        logger.info(f"Изображение перескачано по file_id: {target_path}")
        return {"path": str(target_path), "mime": mime_type}
        
    except Exception as exc:
        logger.error(f"Не удалось перескачать изображение {telegram_file_id}: {exc}")
        return None


def ensure_image_available(
    path: Optional[str],
    mime: Optional[str],
    telegram_file_id: Optional[str],
    bot,
) -> Optional[str]:
    """
    Проверяет доступность изображения и перескачивает при необходимости.
    
    Args:
        path: Путь к файлу изображения
        mime: MIME-тип изображения
        telegram_file_id: Идентификатор файла в Telegram (для перескачивания)
        bot: Экземпляр бота aiogram
        
    Returns:
        Путь к доступному файлу или None
    """
    # Если файл существует - возвращаем сразу
    if path and os.path.exists(path):
        return path
    
    # Файл удалён, пробуем перескачать
    if telegram_file_id and bot:
        logger.info(f"Локальный файл {path} не найден, пробуем перескачать по file_id")
        result = None
        
        # Проблема: redownload async, а эта функция sync
        # Для синхронного использования нужно вызывать через run_until_complete
        # Это заглушка - реальная логика должна быть в async контексте
        logger.warning("Синхронный redownload не поддерживается, используйте async версию")
        return None
    
    logger.warning(f"Изображение недоступно: файл {path} удалён, telegram_file_id={telegram_file_id}")
    return None

