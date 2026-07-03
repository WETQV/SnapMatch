from PyQt6.QtWidgets import QVBoxLayout
from gui.admin_panel.admin_panel_base import AdminPanelBase
from gui.admin_panel.user_management import UserManagement
from gui.admin_panel.message_history import MessageHistory
from gui.admin_panel.server_control import ServerControl

class AdminPanel(AdminPanelBase):
    def __init__(self):
        super().__init__()

        # Инициализация модулей
        self.user_management = UserManagement()
        self.message_history = MessageHistory()
        self.server_control = ServerControl()

        # Создаём макеты (layouts) для вкладок
        self.users_tab.setLayout(QVBoxLayout())     # Добавляем макет для вкладки "Пользователи"
        self.history_tab.setLayout(QVBoxLayout())   # Добавляем макет для вкладки "История сообщений"
        self.stats_tab.setLayout(QVBoxLayout())     # Добавляем макет для вкладки "Статистика"

        # Добавление каждого компонента в соответствующую вкладку
        self.users_tab.layout().addWidget(self.user_management)
        self.history_tab.layout().addWidget(self.message_history)
        self.stats_tab.layout().addWidget(self.server_control)
