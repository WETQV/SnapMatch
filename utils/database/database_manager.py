from config.settings import settings_manager

from .message_db import MessageDB
from .mcp_db import McpDB
from .secretary_db import SecretaryDB
from .user_db import UserDB


class DatabaseManager:
    def __init__(self):
        self._users = None
        self._messages = None
        self._mcp = None
        self._secretary = None
        self.settings_manager = settings_manager

    @property
    def users(self) -> UserDB:
        if self._users is None:
            self._users = UserDB()
        return self._users

    @property
    def messages(self) -> MessageDB:
        if self._messages is None:
            self._messages = MessageDB()
        return self._messages

    @property
    def secretary(self) -> SecretaryDB:
        if self._secretary is None:
            self._secretary = SecretaryDB()
        return self._secretary

    @property
    def mcp(self) -> McpDB:
        if self._mcp is None:
            self._mcp = McpDB()
        return self._mcp

    def close(self):
        if self._users is not None:
            self._users.close()
            self._users = None
        if self._messages is not None:
            self._messages.close()
            self._messages = None
        if self._secretary is not None:
            self._secretary.close()
            self._secretary = None
        if self._mcp is not None:
            self._mcp.close()
            self._mcp = None
