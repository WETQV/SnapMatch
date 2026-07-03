# gui/admin_panel/handlers/log_handler.py
"""
Пользовательский обработчик логов для отображения в GUI.
Перехватывает логи и передаёт их в очередь для асинхронного отображения в QTextEdit.
"""

import logging
import queue
from PyQt6.QtGui import QTextCharFormat, QColor, QFont


class LogHandler(logging.Handler):
    """Обработчик логов для отображения в GUI через QTextEdit."""
    
    def __init__(self, max_logs: int = 1000):
        """
        Args:
            max_logs: Максимальное количество логов в очереди
        """
        super().__init__()
        self.log_queue = queue.Queue()
        self.max_logs = max_logs
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
        self.log_formats = {
            logging.DEBUG: QTextCharFormat(),
            logging.INFO: QTextCharFormat(),
            logging.WARNING: QTextCharFormat(),
            logging.ERROR: QTextCharFormat(),
            logging.CRITICAL: QTextCharFormat()
        }
        self.init_formats()
        
    def init_formats(self):
        """Инициализирует форматы для разных уровней логирования."""
        # DEBUG - серый
        self.log_formats[logging.DEBUG].setForeground(QColor("#757575"))
        
        # INFO - зеленый
        self.log_formats[logging.INFO].setForeground(QColor("#2E7D32"))
        
        # WARNING - оранжевый
        self.log_formats[logging.WARNING].setForeground(QColor("#FF8F00"))
        self.log_formats[logging.WARNING].setFontWeight(QFont.Weight.Bold)
        
        # ERROR - красный
        self.log_formats[logging.ERROR].setForeground(QColor("#D32F2F"))
        self.log_formats[logging.ERROR].setFontWeight(QFont.Weight.Bold)
        
        # CRITICAL - яркий красный с подчеркиванием
        self.log_formats[logging.CRITICAL].setForeground(QColor("#D50000"))
        self.log_formats[logging.CRITICAL].setFontWeight(QFont.Weight.Bold)
        self.log_formats[logging.CRITICAL].setFontUnderline(True)
    
    def emit(self, record: logging.LogRecord):
        """
        Переопределяет метод emit для добавления логов в очередь.
        
        Args:
            record: Запись логирования
        """
        try:
            msg = self.format(record)
            self.log_queue.put((record.levelno, msg))
            
            # Ограничиваем размер очереди
            if self.log_queue.qsize() > self.max_logs:
                self.log_queue.get()
        except Exception:
            self.handleError(record)
    
    def get_logs(self) -> list:
        """
        Возвращает все логи из очереди.
        
        Returns:
            Список кортежей (levelno, message)
        """
        logs = []
        while not self.log_queue.empty():
            logs.append(self.log_queue.get())
        return logs

