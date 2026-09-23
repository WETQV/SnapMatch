# utils/encryption.py

import os
import json
import base64
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class ConfigEncryption:
    """Класс для шифрования конфиденциальных данных в конфигурации"""
    
    ENCRYPTED_FIELDS = [
        'telegram_token',
        'api_key',  # для моделей
        'openai_api_key',  # для обратной совместимости
        'stt_openai_key',
        'stt_groq_key',
        'stt_custom_key',
    ]
    
    def __init__(self):
        self.key = self._get_or_create_key()
        self.fernet = Fernet(self.key) if self.key else None
    
    def _get_or_create_key(self):
        """Получает или создаёт ключ шифрования"""
        legacy_key_file = Path('.encryption_key')
        configured_dir = os.environ.get("SNAPMATCH_DATA_DIR")
        if legacy_key_file.exists():
            key_file = legacy_key_file
        elif configured_dir:
            key_file = Path(configured_dir) / ".encryption_key"
        elif os.name == 'nt':
            key_file = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'SnapMatch' / '.encryption_key'
        else:
            data_home = Path(os.environ.get('XDG_DATA_HOME') or (Path.home() / '.local' / 'share'))
            key_file = data_home / 'snapmatch' / '.encryption_key'
        
        try:
            if key_file.exists():
                # Читаем существующий ключ
                with key_file.open('rb') as f:
                    key = f.read()
                Fernet(key)  # validate before accepting the key
                return key
            else:
                # Создаём новый ключ
                key_file.parent.mkdir(parents=True, exist_ok=True)
                key = Fernet.generate_key()
                with key_file.open('xb') as f:
                    f.write(key)
                if os.name != 'nt':
                    os.chmod(key_file, 0o600)
                return key
        except Exception as e:
            print(f"Ошибка при работе с ключом шифрования: {e}")
            return None
    
    def encrypt_value(self, value):
        """Шифрует значение"""
        if not value:
            return value
        if not self.fernet:
            raise RuntimeError("Ключ шифрования недоступен; секрет не сохранён")
        
        try:
            # Преобразуем в байты, шифруем и кодируем в base64
            encrypted = self.fernet.encrypt(value.encode())
            return f"ENC:{base64.b64encode(encrypted).decode()}"
        except Exception as e:
            raise RuntimeError("Не удалось зашифровать секрет") from e
    
    def decrypt_value(self, value):
        """Расшифровывает значение"""
        if not value or not isinstance(value, str):
            return value
        
        # Проверяем, что значение зашифровано
        if not value.startswith("ENC:"):
            return value
        if not self.fernet:
            raise RuntimeError("Ключ шифрования недоступен; секрет не расшифрован")
        
        try:
            # Убираем префикс и декодируем из base64
            encrypted_data = base64.b64decode(value[4:])
            decrypted = self.fernet.decrypt(encrypted_data)
            return decrypted.decode()
        except Exception as e:
            raise RuntimeError("Не удалось расшифровать секрет") from e
    
    def encrypt_config(self, config):
        """Шифрует чувствительные поля в конфигурации без мутации оригинала"""
        import copy
        encrypted_config = copy.deepcopy(config)
        
        # Шифруем основные поля
        for field in self.ENCRYPTED_FIELDS:
            if field in encrypted_config and encrypted_config[field]:
                encrypted_config[field] = self.encrypt_value(encrypted_config[field])
        
        # Шифруем API ключи в моделях
        if 'models' in encrypted_config:
            for model in encrypted_config['models']:
                if 'api_key' in model and model['api_key']:
                    model['api_key'] = self.encrypt_value(model['api_key'])
        
        return encrypted_config
    
    def decrypt_config(self, config):
        """Расшифровывает чувствительные поля в конфигурации без мутации оригинала"""
        import copy
        decrypted_config = copy.deepcopy(config)
        
        # Расшифровываем основные поля
        for field in self.ENCRYPTED_FIELDS:
            if field in decrypted_config:
                decrypted_config[field] = self.decrypt_value(decrypted_config[field])
        
        # Расшифровываем API ключи в моделях
        if 'models' in decrypted_config:
            for model in decrypted_config['models']:
                if 'api_key' in model:
                    model['api_key'] = self.decrypt_value(model['api_key'])
        
        return decrypted_config

# Глобальный экземпляр для использования
encryption = ConfigEncryption() 
