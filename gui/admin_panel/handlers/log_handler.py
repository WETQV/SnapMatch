# gui/admin_panel/handlers/log_handler.py
"""
Пользовательский обработчик логов для отображения в GUI.
Перехватывает логи и передаёт их в очередь для асинхронного отображения в QTextEdit.
Цвета форматов берутся из токенов дизайн-системы, поэтому читаются во всех темах.
"""

import logging
import queue
from PyQt6.QtGui import QTextCharFormat, QColor, QFont

from gui.design import current_tokens


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
        """Пересоздаёт форматы уровней из текущих токенов темы (можно вызывать при смене темы)."""
        t = current_tokens()
        if not t:
            return

        def fmt(role: str, bold: bool = False) -> QTextCharFormat:
            f = QTextCharFormat()
            f.setForeground(QColor(t[role]))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            return f

        self.log_formats[logging.DEBUG] = fmt("text_muted")
        self.log_formats[logging.INFO] = fmt("accent")
        self.log_formats[logging.WARNING] = fmt("warning", bold=True)
        self.log_formats[logging.ERROR] = fmt("danger", bold=True)
        critical = fmt("danger", bold=True)
        critical.setFontUnderline(True)
        self.log_formats[logging.CRITICAL] = critical
    
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
