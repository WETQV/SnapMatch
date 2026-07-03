# utils/resource_manager.py
import os
import sys
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QFont, QColor
from PyQt6.QtCore import QDir
from utils.logger import setup_logger

logger = setup_logger(__name__)

def get_resource_path(relative_path):
    """
    Получает абсолютный путь к ресурсу.
    Работает как в режиме разработки, так и в скомпилированном exe.
    """
    try:
        # Если запущен как exe (PyInstaller)
        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            # Если запущен как скрипт
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        resource_path = os.path.join(base_path, relative_path)
        
        # Проверяем, существует ли файл
        if os.path.exists(resource_path):
            logger.debug(f"Найден ресурс: {resource_path}")
            return resource_path
        else:
            logger.debug(f"Ресурс не найден: {resource_path}")
            return None
            
    except Exception as e:
        logger.debug(f"Ошибка при получении пути к ресурсу {relative_path}: {e}")
        return None

def load_app_icon():
    """
    Загружает иконку приложения.
    Сначала пытается найти внешние файлы, затем использует встроенную системную иконку.
    """
    # Список возможных путей к иконкам (в порядке предпочтения)
    icon_paths = [
        "assets/icon3.ico",
        "assets/icon.ico",
        "assets/icon.png", 
        "assets/icon2.ico",
        "assets/snapmatch_icon.ico",
        "assets/snapmatch_icon.png",
        "icon3.ico",
        "icon.ico",
        "icon.png"
    ]
    
    # Пытаемся найти внешние иконки
    for icon_path in icon_paths:
        full_path = get_resource_path(icon_path)
        if full_path and os.path.exists(full_path):
            try:
                icon = QIcon(full_path)
                if not icon.isNull():
                    logger.info(f"Загружена иконка приложения: {full_path}")
                    return icon
            except Exception as e:
                logger.debug(f"Ошибка при загрузке иконки {full_path}: {e}")
                continue
    
    # Если внешние иконки не найдены, создаем простую встроенную
    try:
        # Создаем простую иконку используя Unicode символ
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(30, 144, 255))  # Синий фон
        
        # Рисуем символ
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        font = QFont("Segoe UI Symbol", 32, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        
        # Рисуем символ шестеренки в центре
        painter.drawText(16, 44, "⚙")
        painter.end()
        
        icon = QIcon(pixmap)
        logger.info("Создана встроенная иконка приложения")
        return icon
        
    except Exception as e:
        logger.warning(f"Ошибка при создании встроенной иконки: {e}")
    
    # В крайнем случае возвращаем None (будет использована системная иконка по умолчанию)
    logger.info("Используется системная иконка по умолчанию")
    return None

def load_splash_image():
    """
    Эта функция больше не используется, так как сплеш-скрин теперь создается программно.
    Оставлена для обратной совместимости.
    """
    logger.info("Splash изображения теперь создаются программно")
    return None

def ensure_assets_directory():
    """
    Убеждается, что папка для данных приложения существует.
    Теперь не создает папку assets, а создает папку для пользовательских данных.
    """
    try:
        app_data_path = get_app_data_path()
        if app_data_path and os.path.exists(app_data_path):
            logger.debug(f"Папка данных приложения: {app_data_path}")
            return True
        else:
            logger.warning("Не удалось создать папку данных приложения")
            return False
    except Exception as e:
        logger.error(f"Ошибка при проверке папки данных: {e}")
        return False

def get_app_data_path():
    """
    Возвращает путь к папке данных приложения в %APPDATA%/SnapMatch
    """
    try:
        if sys.platform == "win32":
            app_data = os.environ.get('APPDATA')
            if app_data:
                app_path = os.path.join(app_data, "SnapMatch")
                os.makedirs(app_path, exist_ok=True)
                return app_path
        
        # Для других ОС
        home = os.path.expanduser("~")
        app_path = os.path.join(home, ".snapmatch")
        os.makedirs(app_path, exist_ok=True)
        return app_path
        
    except Exception as e:
        logger.error(f"Ошибка при создании папки данных приложения: {e}")
        return os.getcwd()  # Возвращаем текущую папку как fallback 