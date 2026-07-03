# utils/encryption.py

import os
import json
import base64
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
    ]
    
    def __init__(self):
        self.key = self._get_or_create_key()
        self.fernet = Fernet(self.key) if self.key else None
    
    def _get_or_create_key(self):
        """Получает или создаёт ключ шифрования"""
        key_file = '.encryption_key'
        
        try:
            if os.path.exists(key_file):
                # Читаем существующий ключ
                with open(key_file, 'rb') as f:
                    return f.read()
            else:
                # Создаём новый ключ
                key = Fernet.generate_key()
                with open(key_file, 'wb') as f:
                    f.write(key)
                return key
        except Exception as e:
            print(f"Ошибка при работе с ключом шифрования: {e}")
            return None
    
    def encrypt_value(self, value):
        """Шифрует значение"""
        if not self.fernet or not value:
            return value
        
        try:
            # Преобразуем в байты, шифруем и кодируем в base64
            encrypted = self.fernet.encrypt(value.encode())
            return f"ENC:{base64.b64encode(encrypted).decode()}"
        except Exception as e:
            print(f"Ошибка при шифровании: {e}")
            return value
    
    def decrypt_value(self, value):
        """Расшифровывает значение"""
        if not self.fernet or not value or not isinstance(value, str):
            return value
        
        # Проверяем, что значение зашифровано
        if not value.startswith("ENC:"):
            return value
        
        try:
            # Убираем префикс и декодируем из base64
            encrypted_data = base64.b64decode(value[4:])
            decrypted = self.fernet.decrypt(encrypted_data)
            return decrypted.decode()
        except Exception as e:
            print(f"Ошибка при расшифровке: {e}")
            return value
    
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
