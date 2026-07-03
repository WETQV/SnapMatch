from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget

class ServerControl(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        self.status_label = QLabel('Сервер остановлен')
        self.start_button = QPushButton('Запустить сервер')
        self.stop_button = QPushButton('Остановить сервер')

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.status_label)
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

        # Привязка событий
        self.start_button.clicked.connect(self.start_server)
        self.stop_button.clicked.connect(self.stop_server)

    def start_server(self):
        # Логика запуска сервера
        self.status_label.setText('Сервер запущен')

    def stop_server(self):
        # Логика остановки сервера
        self.status_label.setText('Сервер остановлен')
