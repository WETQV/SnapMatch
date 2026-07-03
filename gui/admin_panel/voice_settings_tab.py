# gui/admin_panel/voice_settings_tab.py

import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QGroupBox, QFormLayout, QCheckBox, QComboBox, QLabel, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt
from config.settings import settings_manager
from utils.logger import setup_logger
from utils.voice_processor import resolve_ffmpeg_path

logger = setup_logger(__name__)

class VoiceSettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()

        # Верхняя панель с кнопкой сохранения
        top_bar = QHBoxLayout()
        save_btn_top = QPushButton("Сохранить настройки голоса")
        save_btn_top.clicked.connect(self.save_settings)
        top_bar.addStretch()
        top_bar.addWidget(save_btn_top)
        layout.addLayout(top_bar)

        settings = settings_manager.get_settings()

        # Группа основных настроек STT
        stt_group = QGroupBox("Распознавание речи (STT)")
        stt_form = QFormLayout()

        self.cb_stt_enabled = QCheckBox("Включить поддержку голосовых и кружочков")
        self.cb_stt_enabled.setChecked(settings.get('stt_enabled', False))
        self.cb_stt_enabled.setToolTip("Включает или выключает обработку голосовых сообщений и кружочков ботом.")
        stt_form.addRow("Статус:", self.cb_stt_enabled)

        self.combo_engine = QComboBox()
        self.combo_engine.addItems(["vosk", "openai", "groq"])
        self.combo_engine.setCurrentText(settings.get('stt_engine', 'vosk'))
        self.combo_engine.currentTextChanged.connect(self._on_engine_changed)
        self.combo_engine.setToolTip(
            "Выберите движок для распознавания речи:\n"
            "• vosk: Работает полностью локально, требует скачивания модели.\n"
            "• openai: Использует Whisper API от OpenAI. Высокая точность, платно.\n"
            "• groq: Использует Whisper через Groq API. Очень быстро, есть бесплатные лимиты."
        )
        stt_form.addRow("Движок:", self.combo_engine)

        stt_group.setLayout(stt_form)
        layout.addWidget(stt_group)

        # Группа для облачных решений (OpenAI / Groq)
        self.cloud_group = QGroupBox("Настройки облачного STT")
        cloud_form = QFormLayout()

        self.le_cloud_key = QLineEdit()
        self.le_cloud_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.le_cloud_key.setToolTip("API ключ для выбранного облачного сервиса.")
        cloud_form.addRow("API Ключ:", self.le_cloud_key)

        self.le_cloud_model = QLineEdit()
        self.le_cloud_model.setToolTip("Название модели для распознавания (например, whisper-1 для OpenAI или whisper-large-v3 для Groq).")
        cloud_form.addRow("Модель:", self.le_cloud_model)

        self.cloud_group.setLayout(cloud_form)
        layout.addWidget(self.cloud_group)

        # Группа для локального Vosk
        self.vosk_group = QGroupBox("Настройки Vosk (Локально)")
        vosk_form = QFormLayout()

        # 🆕 Проверка FFmpeg
        self.lbl_ffmpeg_status = QLabel("Проверка FFmpeg...")
        ffmpeg_layout = QHBoxLayout()
        ffmpeg_layout.addWidget(self.lbl_ffmpeg_status)
        vosk_form.addRow("Статус FFmpeg:", ffmpeg_layout)

        self.lbl_model_status = QLabel("Проверка модели...")
        btn_download = QPushButton("Скачать модели")
        btn_download.setFixedWidth(150)
        btn_download.setToolTip("Перейти на сайт alphacephei.com для выбора и загрузки моделей Vosk.")
        btn_download.clicked.connect(self._download_vosk_models)
        
        model_status_layout = QHBoxLayout()
        model_status_layout.addWidget(self.lbl_model_status)
        model_status_layout.addStretch()
        model_status_layout.addWidget(btn_download)
        vosk_form.addRow("Статус модели:", model_status_layout)

        path_layout = QHBoxLayout()
        self.lbl_path = QLabel(settings.get('stt_model_path', 'assets/models/stt/vosk'))
        btn_browse = QPushButton("Обзор...")
        btn_browse.clicked.connect(self._browse_model_path)
        path_layout.addWidget(self.lbl_path, 1)
        path_layout.addWidget(btn_browse)
        vosk_form.addRow("Путь к модели:", path_layout)

        btn_refresh = QPushButton("Проверить наличие модели")
        btn_refresh.setFixedWidth(200)
        btn_refresh.setToolTip("Запустить повторную проверку файлов модели в указанной папке.")
        btn_refresh.clicked.connect(self._check_model_exists)
        vosk_form.addRow("", btn_refresh)

        self.vosk_group.setLayout(vosk_form)
        layout.addWidget(self.vosk_group)

        # Инфо-панель
        self.info_group = QGroupBox("Справка")
        self.info_layout = QVBoxLayout()
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.info_layout.addWidget(self.info_label)
        self.info_group.setLayout(self.info_layout)
        layout.addWidget(self.info_group)

        layout.addStretch()
        self.setLayout(layout)
        
        # Начальное обновление видимости и справки
        self._on_engine_changed(self.combo_engine.currentText())
        self._check_model_exists()

    def _on_engine_changed(self, engine):
        self.vosk_group.setVisible(engine == "vosk")
        self.cloud_group.setVisible(engine in ["openai", "groq"])
        
        settings = settings_manager.get_settings()
        if engine == "openai":
            self.le_cloud_key.setText(settings.get('stt_openai_key', ''))
            self.le_cloud_model.setText(settings.get('stt_openai_model', 'whisper-1'))
            self._update_help_text("openai")
        elif engine == "groq":
            self.le_cloud_key.setText(settings.get('stt_groq_key', ''))
            self.le_cloud_model.setText(settings.get('stt_groq_model', 'whisper-large-v3-turbo'))
            self._update_help_text("groq")
        else:  # vosk
            self._update_help_text("vosk")
            
        self._check_ffmpeg()

    def _update_help_text(self, engine):
        """Обновляет текст справки в зависимости от выбранного движка"""
        help_texts = {
            "vosk": (
                "Vosk — локальное распознавание речи (работает без интернета)\n\n"
                "Требования:\n"
                "• Скачайте модель с alphacephei.com/vosk/models (рекомендуется vosk-model-small-ru-0.22 — 45 МБ)\n"
                "• Распакуйте папку так, чтобы внутри были подпапки 'am', 'conf', 'graph' и др.\n"
                "• Укажите путь к этой папке в настройке 'Путь к модели'\n"
                "• FFmpeg должен быть установлен\n\n"
                "Плюсы: полная приватность, нет интернета, бесплатно\n"
                "Минусы: требует скачивания модели, занимает место"
            ),
            "openai": (
                "OpenAI Whisper — облачное распознавание речи через OpenAI API\n\n"
                "Требования:\n"
                "• Укажите API ключ от OpenAI (https://platform.openai.com/api-keys)\n"
                "• Модель: 'whisper-1' (по умолчанию)\n"
                "• Требуется интернет-соединение\n"
                "• Требуется активная подписка на OpenAI (платная услуга)\n\n"
                "Плюсы: высочайшая точность, поддержка 100+ языков\n"
                "Минусы: платно, требует интернета, данные отправляются на серверы OpenAI"
            ),
            "groq": (
                "Groq Whisper — быстрое облачное распознавание через Groq API\n\n"
                "Требования:\n"
                "• Укажите API ключ от Groq (https://console.groq.com/keys)\n"
                "• Модели: 'whisper-large-v3' (точнее) или 'whisper-large-v3-turbo' (быстрее)\n"
                "• Требуется интернет-соединение\n"
                "• Бесплатные лимиты: 100 минут в день (free tier)\n\n"
                "Плюсы: очень быстро (189x speed), многоязычный, есть бесплатный лимит\n"
                "Минусы: требует интернета, лимиты на бесплатном тарифе"
            )
        }
        
        self.info_label.setText(help_texts.get(engine, ""))

    def _download_vosk_models(self):
        msg = (
            "Для работы локального распознавания (Vosk) нужны языковые модели.\n\n"
            "1. Перейдите на сайт alphacephei.com/vosk/models.\n"
            "2. Выберите подходящую модель (например, 'vosk-model-small-ru-0.22' — 45 Мб).\n"
            "3. Скачайте, распакуйте и укажите путь к папке в настройках.\n\n"
            "Открыть сайт со списком моделей?"
        )
        reply = QMessageBox.question(
            self, "Загрузка моделей Vosk", msg, 
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            import webbrowser
            webbrowser.open("https://alphacephei.com/vosk/models")

    def _check_ffmpeg(self):
        ffmpeg_path = resolve_ffmpeg_path()
        if ffmpeg_path:
            self.lbl_ffmpeg_status.setText("✅ Установлен")
            self.lbl_ffmpeg_status.setStyleSheet("color: #4CAF50;")
        else:
            self.lbl_ffmpeg_status.setText("❌ Не найден (нужен для ГС и кружочков)")
            self.lbl_ffmpeg_status.setStyleSheet("color: #F44336;")

    def _show_ffmpeg_help(self):
        msg = (
            "Для обработки голосовых сообщений и кружочков нужен FFmpeg.\n\n"
            "1. В сборке он лежит в assets/ffmpeg/ffmpeg.exe.\n"
            "2. В режиме разработки можно положить ffmpeg.exe в папку проекта\n"
            "   или добавить FFmpeg в PATH системы.\n\n"
            "Открыть сайт загрузки?"
        )
        reply = QMessageBox.question(self, "Установка FFmpeg", msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            import webbrowser
            webbrowser.open("https://www.gyan.dev/ffmpeg/builds/")

    def _browse_model_path(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Выберите папку с моделью Vosk", self.lbl_path.text())
        if dir_path:
            self.lbl_path.setText(dir_path)
            self._check_model_exists()

    def _check_model_exists(self):
        path = self.lbl_path.text()
        # 🆕 Создаем папку, если её нет
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
                logger.info(f"Создана директория для моделей: {path}")
            except Exception as e:
                logger.error(f"Не удалось создать директорию {path}: {e}")

        if os.path.exists(path) and any(os.path.isdir(os.path.join(path, d)) for d in os.listdir(path) if d in ['am', 'graph', 'ivector']):
            self.lbl_model_status.setText("✅ Модель найдена")
            self.lbl_model_status.setStyleSheet("color: #4CAF50;")
        elif os.path.exists(os.path.join(path, "am")): # упрощенная проверка
            self.lbl_model_status.setText("✅ Модель найдена")
            self.lbl_model_status.setStyleSheet("color: #4CAF50;")
        else:
            self.lbl_model_status.setText("❌ Модель не найдена или неверная структура")
            self.lbl_model_status.setStyleSheet("color: #F44336;")

    def save_settings(self):
        settings = settings_manager.get_settings()
        engine = self.combo_engine.currentText()
        
        settings['stt_enabled'] = self.cb_stt_enabled.isChecked()
        settings['stt_engine'] = engine
        settings['stt_model_path'] = self.lbl_path.text()
        
        if engine == "openai":
            settings['stt_openai_key'] = self.le_cloud_key.text().strip()
            settings['stt_openai_model'] = self.le_cloud_model.text().strip()
        elif engine == "groq":
            settings['stt_groq_key'] = self.le_cloud_key.text().strip()
            settings['stt_groq_model'] = self.le_cloud_model.text().strip()

        settings_manager.update_settings(**settings)
        logger.info("Настройки голоса сохранены")
        QMessageBox.information(self, "Сохранено", "Настройки голоса сохранены.")
