"""Просмотр загрузочного экрана SnapMatch: запуск из корня проекта `python tools/preview_splash.py`.

Окно с кнопкой «Показать ещё раз» — сплеш можно смотреть сколько угодно раз.
Статусы имитируют реальную загрузку из main.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import QTimer

from gui.splash_screen import SplashScreen

STEPS = [
    (400, "Подготовка…", 0.05),
    (500, "Проверка настроек…", 0.25),
    (600, "Запуск бота…", 0.5),
    (700, "Загрузка интерфейса…", 0.75),
    (500, "Готово", 1.0),
]


class Preview(QWidget):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.splash = None
        self.setWindowTitle("Превью загрузочного экрана")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Нажмите кнопку, чтобы показать экран загрузки"))
        self.button = QPushButton("Показать ещё раз")
        self.button.clicked.connect(self.play)
        layout.addWidget(self.button)
        self.resize(320, 110)
        QTimer.singleShot(300, self.play)

    def play(self) -> None:
        if self.splash is not None:
            return
        self.button.setEnabled(False)
        self.splash = SplashScreen(self.app)
        self.splash.show()
        self.splash.finished.connect(self._done)
        delay = 0
        for step_ms, text, progress in STEPS:
            delay += step_ms
            QTimer.singleShot(delay, lambda t=text, p=progress: self._step(t, p))
        QTimer.singleShot(delay + 100, lambda: self.splash and self.splash.finish_and_wait())

    def _step(self, text: str, progress: float) -> None:
        if self.splash:
            self.splash.set_status(text, progress)

    def _done(self) -> None:
        self.splash = None
        self.button.setEnabled(True)


if __name__ == "__main__":
    qapp = QApplication(sys.argv)
    window = Preview(qapp)
    window.show()
    sys.exit(qapp.exec())
