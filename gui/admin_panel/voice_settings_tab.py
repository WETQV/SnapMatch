# gui/admin_panel/voice_settings_tab.py

import importlib.util
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox, QLabel, QFileDialog, QSizePolicy,
)
from PyQt6.QtCore import Qt
from config.settings import settings_manager
from gui.async_worker import run_in_background
from gui.design.dialogs import ask, inform, warn
from gui.admin_panel.ui_common import BadgeSlot, field, vertical_scroll
from gui.design import FxButton, FxComboBox, SwitchRow, card, label, page_header, primary
from utils.logger import setup_logger
from utils.openai_models import (
    DEFAULT_STT_MODEL, LEGACY_REMOVAL_DATE, OPENAI_BASE_URL, fallback_models, get_stt_models, is_legacy_stt_model,
)
from utils.voice_processor import resolve_ffmpeg_path

logger = setup_logger(__name__)

class VoiceSettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Несохранённые ввод по движкам: {движок: (ключ, модель, base_url)}
        self._engine_drafts = {}
        self._active_engine = None
        self._models_request = 0
        self._asked_migration = False
        self._init_ui()

    def _init_ui(self):
        settings = settings_manager.get_settings()

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        # Заголовок экрана с кнопкой сохранения
        save_btn_top = primary("Сохранить", "mdi6.content-save-outline")
        save_btn_top.setToolTip("Сохранить настройки голоса\nЗаписывает движок, ключи, модель и путь к модели Vosk.")
        save_btn_top.clicked.connect(self.save_settings)
        layout.addLayout(page_header("Голос", "Распознавание голосовых сообщений и кружочков", save_btn_top))

        # Карточка основных настроек STT
        self.stt_group, stt_lay = card()
        stt_lay.addWidget(label("Распознавание речи (STT)", "h2"))

        self.cb_stt_enabled = SwitchRow("Включить поддержку голосовых и кружочков", settings.get('stt_enabled', False))
        self.cb_stt_enabled.setToolTip(
            "Поддержка голосовых\nВключает или выключает обработку голосовых сообщений и кружочков ботом."
        )
        stt_lay.addWidget(self.cb_stt_enabled)

        self.combo_engine = FxComboBox()
        self.combo_engine.addItems(["vosk", "openai", "groq", "custom"])
        self.combo_engine.setCurrentText(settings.get('stt_engine', 'vosk'))
        self.combo_engine.currentTextChanged.connect(self._on_engine_changed)
        self.combo_engine.setToolTip(
            "Движок распознавания\n"
            "Выберите движок для распознавания речи:\n"
            "• vosk: Работает полностью локально, требует скачивания модели.\n"
            "• openai: Использует Whisper API от OpenAI. Высокая точность, платно.\n"
            "• groq: Использует Whisper через Groq API. Очень быстро, есть бесплатные лимиты.\n"
            "• custom: Ваш локальный или удалённый OpenAI-совместимый STT endpoint."
        )
        stt_lay.addLayout(field("ДВИЖОК", self.combo_engine))
        layout.addWidget(self.stt_group)

        # Карточка облачных решений (OpenAI / Groq / custom)
        self.cloud_group, cloud_lay = card()
        cloud_lay.addWidget(label("Настройки облачного STT", "h2"))

        self.le_cloud_key = QLineEdit()
        self.le_cloud_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.le_cloud_key.setToolTip("API ключ\nКлюч для выбранного облачного сервиса.")
        cloud_lay.addLayout(field("API КЛЮЧ", self.le_cloud_key))

        # Редактируемый список: для OpenAI подгружается из /models, ручной ввод сохраняется
        self.le_cloud_model = FxComboBox()
        self.le_cloud_model.setEditable(True)
        self.le_cloud_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.le_cloud_model.setToolTip(
            "Модель\nНазвание модели для распознавания (gpt-transcribe для OpenAI, whisper-large-v3 для Groq).\n"
            "Для OpenAI список подгружается с сервера; можно ввести своё имя."
        )
        self.le_cloud_model.editTextChanged.connect(self._update_model_note)
        cloud_lay.addLayout(field("МОДЕЛЬ", self.le_cloud_model))
        self.lbl_model_note = BadgeSlot("", "error")
        self.lbl_model_note.setVisible(False)
        cloud_lay.addWidget(self.lbl_model_note)

        self.le_custom_base_url = QLineEdit()
        self.le_custom_base_url.setPlaceholderText("http://localhost:8000/v1")
        self.le_custom_base_url.setToolTip("Base URL\nOpenAI-совместимого сервера; нужен POST /audio/transcriptions.")
        self.le_custom_base_url.setObjectName("mono")
        self.lbl_custom_base_url = label("BASE URL", "sectionLabel")
        cloud_lay.addWidget(self.lbl_custom_base_url)
        cloud_lay.addWidget(self.le_custom_base_url)
        layout.addWidget(self.cloud_group)

        # Карточка локального Vosk
        self.vosk_group, vosk_lay = card()
        vosk_lay.addWidget(label("Настройки Vosk (локально)", "h2"))

        # Одна строка-подсказка, только если пакет vosk не установлен
        self.lbl_vosk_missing = BadgeSlot("Vosk не установлен: pip install vosk (см. requirements-local-stt.txt)", "error")
        vosk_lay.addWidget(self.lbl_vosk_missing)

        # Проверка FFmpeg: статус — бейдж, а не текст с галочкой
        self.lbl_ffmpeg_status = BadgeSlot("Проверка FFmpeg...", "idle")
        ffmpeg_row = QHBoxLayout()
        ffmpeg_row.addWidget(self.lbl_ffmpeg_status)
        ffmpeg_row.addStretch()
        btn_ffmpeg_help = FxButton("Как установить FFmpeg")
        btn_ffmpeg_help.setToolTip("Установка FFmpeg\nПодсказка по установке FFmpeg для вашей системы.")
        btn_ffmpeg_help.clicked.connect(self._show_ffmpeg_help)
        ffmpeg_row.addWidget(btn_ffmpeg_help)
        vosk_lay.addWidget(label("СТАТУС FFMPEG", "sectionLabel"))
        vosk_lay.addLayout(ffmpeg_row)

        self.lbl_model_status = BadgeSlot("Проверка модели...", "idle")
        btn_download = FxButton("Скачать модели")
        btn_download.setToolTip("Скачать модели\nПерейти на сайт alphacephei.com для выбора и загрузки моделей Vosk.")
        btn_download.clicked.connect(self._download_vosk_models)
        model_row = QHBoxLayout()
        model_row.addWidget(self.lbl_model_status)
        model_row.addStretch()
        model_row.addWidget(btn_download)
        vosk_lay.addWidget(label("СТАТУС МОДЕЛИ", "sectionLabel"))
        vosk_lay.addLayout(model_row)

        path_row = QHBoxLayout()
        self.lbl_path = QLabel(settings.get('stt_model_path', 'assets/models/stt/vosk'))
        self.lbl_path.setObjectName("mono")
        # Длинный путь не должен растягивать окно: метка сжимается, полный путь — в подсказке
        self.lbl_path.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_path.setToolTip(self.lbl_path.text())
        btn_browse = FxButton("Обзор...")
        btn_browse.setToolTip("Папка модели\nВыберите каталог распакованной модели Vosk.")
        btn_browse.clicked.connect(self._browse_model_path)
        path_row.addWidget(self.lbl_path, 1)
        path_row.addWidget(btn_browse)
        vosk_lay.addWidget(label("ПУТЬ К МОДЕЛИ", "sectionLabel"))
        vosk_lay.addLayout(path_row)

        btn_refresh = FxButton("Проверить наличие модели")
        btn_refresh.setToolTip("Проверить модель\nЗапустить повторную проверку файлов модели в указанной папке.")
        btn_refresh.clicked.connect(self._check_model_exists)
        refresh_row = QHBoxLayout()
        refresh_row.addWidget(btn_refresh)
        refresh_row.addStretch()
        vosk_lay.addLayout(refresh_row)
        layout.addWidget(self.vosk_group)

        # Справка
        self.info_group, info_lay = card()
        info_lay.addWidget(label("Справка", "h2"))
        self.info_label = label("", "muted")
        self.info_label.setWordWrap(True)
        self.info_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        info_lay.addWidget(self.info_label)
        layout.addWidget(self.info_group)

        layout.addStretch()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(vertical_scroll(content))

        # Начальное обновление видимости и справки
        self._on_engine_changed(self.combo_engine.currentText())
        self._check_model_exists()

    def _on_engine_changed(self, engine):
        self.vosk_group.setVisible(engine == "vosk")
        self.lbl_vosk_missing.setVisible(importlib.util.find_spec("vosk") is None)
        self.cloud_group.setVisible(engine in ["openai", "groq", "custom"])
        self.le_custom_base_url.setVisible(engine == "custom")
        if self.lbl_custom_base_url:
            self.lbl_custom_base_url.setVisible(engine == "custom")
        
        # Запоминаем несохранённый ввод предыдущего облачного движка
        self._stash_current_engine()
        self._active_engine = engine

        settings = settings_manager.get_settings()
        if engine in ("openai", "groq", "custom"):
            defaults = {
                "openai": ('stt_openai_key', 'stt_openai_model', DEFAULT_STT_MODEL),
                "groq": ('stt_groq_key', 'stt_groq_model', 'whisper-large-v3-turbo'),
                "custom": ('stt_custom_key', 'stt_custom_model', 'whisper-1'),
            }[engine]
            draft = self._engine_drafts.get(engine)
            if draft is not None:
                key, model, base_url = draft
            else:
                key = settings.get(defaults[0], '')
                model = settings.get(defaults[1], defaults[2])
                base_url = settings.get('stt_custom_base_url', 'http://localhost:8000/v1')
            self.le_cloud_key.setText(key)
            self.le_cloud_model.setEditText(model)
            if engine == "openai":
                self._load_openai_models(key)
            else:
                self._models_request += 1
                self._set_model_items([])
            if engine == "custom":
                self.le_custom_base_url.setText(base_url)
            self._update_help_text(engine)
        else:  # vosk
            self._update_help_text("vosk")
            
        if engine == "vosk":
            self._check_ffmpeg()

    # ───────── список моделей OpenAI ─────────
    def _set_model_items(self, entries):
        """Подставляет список моделей, не трогая введённый текст."""
        combo = self.le_cloud_model
        text = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems([e["id"] for e in entries])
        combo.setEditText(text)
        combo.blockSignals(False)

    def _load_openai_models(self, api_key):
        """Сразу запасной список, затем в фоне актуальный (кэш 24 ч или GET /models)."""
        self._models_request += 1
        request = self._models_request
        self._set_model_items(fallback_models())
        self._update_model_note()

        def apply(entries):
            if request == self._models_request and self._active_engine == "openai":
                self._set_model_items(entries)

        run_in_background(get_stt_models, OPENAI_BASE_URL, api_key.strip(), on_done=apply, on_error=lambda _e: None)

    def _update_model_note(self, *_):
        model = self.le_cloud_model.currentText().strip()
        show = self._active_engine == "openai" and is_legacy_stt_model(model)
        self.lbl_model_note.setVisible(show)
        if show:
            self.lbl_model_note.set(
                f"Модель устарела (отключение {LEGACY_REMOVAL_DATE:%d.%m.%Y}), заменится на {DEFAULT_STT_MODEL}", "error"
            )

    def _stash_current_engine(self):
        engine = self._active_engine
        if engine in ("openai", "groq", "custom"):
            self._engine_drafts[engine] = (
                self.le_cloud_key.text(),
                self.le_cloud_model.currentText(),
                self.le_custom_base_url.text(),
            )

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
                "OpenAI — облачное распознавание речи через OpenAI API\n\n"
                "Требования:\n"
                "• Укажите API ключ от OpenAI (https://platform.openai.com/api-keys)\n"
                "• Модель: 'gpt-transcribe' (по умолчанию). whisper-1 и gpt-4o-*transcribe устарели, отключение 26.02.2027\n"
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
            ),
            "custom": (
                "Свой STT-сервер — локальный или удалённый интерфейс с OpenAI-совместимым "
                "POST /audio/transcriptions. Укажите Base URL, имя модели и ключ, если сервер его требует. "
                "Аудио отправляется напрямую; Vosk и FFmpeg не нужны."
            ),
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
        if ask(self, "Загрузка моделей Vosk", msg):
            import webbrowser
            webbrowser.open("https://alphacephei.com/vosk/models")

    def _check_ffmpeg(self):
        ffmpeg_path = resolve_ffmpeg_path()
        if ffmpeg_path:
            self.lbl_ffmpeg_status.set("Установлен", "ok")
        else:
            self.lbl_ffmpeg_status.set("Не найден (нужен только для Vosk)", "error")

    def _show_ffmpeg_help(self):
        import sys
        if sys.platform == "win32":
            msg = (
                "Для обработки голосовых сообщений и кружочков нужен FFmpeg.\n\n"
                "1. В сборке он лежит в assets/ffmpeg/ffmpeg.exe.\n"
                "2. В режиме разработки можно положить ffmpeg.exe в папку проекта\n"
                "   или добавить FFmpeg в PATH системы.\n\n"
                "Открыть сайт загрузки?"
            )
            url = "https://www.gyan.dev/ffmpeg/builds/"
        else:
            msg = (
                "Для обработки голосовых сообщений и кружочков нужен FFmpeg.\n\n"
                "Установите его пакетным менеджером и перезапустите приложение:\n"
                "  Debian/Ubuntu:  sudo apt install ffmpeg\n"
                "  Fedora:         sudo dnf install ffmpeg\n"
                "  Arch:           sudo pacman -S ffmpeg\n\n"
                "Открыть сайт FFmpeg?"
            )
            url = "https://ffmpeg.org/download.html"
        if ask(self, "Установка FFmpeg", msg):
            import webbrowser
            webbrowser.open(url)

    def _browse_model_path(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Выберите папку с моделью Vosk", self.lbl_path.text())
        if dir_path:
            self.lbl_path.setText(dir_path)
            self.lbl_path.setToolTip(dir_path)
            self._check_model_exists()

    def _check_model_exists(self):
        path = self.lbl_path.text()
        if os.path.exists(path) and any(os.path.isdir(os.path.join(path, d)) for d in os.listdir(path) if d in ['am', 'graph', 'ivector']):
            self.lbl_model_status.set("Модель найдена", "ok")
        elif os.path.exists(os.path.join(path, "am")): # упрощенная проверка
            self.lbl_model_status.set("Модель найдена", "ok")
        else:
            self.lbl_model_status.set("Модель не найдена или неверная структура", "error")

    def save_settings(self):
        settings = settings_manager.get_settings()
        engine = self.combo_engine.currentText()
        
        settings['stt_enabled'] = self.cb_stt_enabled.isChecked()
        settings['stt_engine'] = engine
        settings['stt_model_path'] = self.lbl_path.text()
        
        self._stash_current_engine()
        # Значения других облачных движков, введённые до переключения, тоже сохраняем
        for other, (okey, omodel, _url) in self._engine_drafts.items():
            if other in ("openai", "groq") and other != engine:
                settings[f'stt_{other}_key'] = okey.strip()
                settings[f'stt_{other}_model'] = omodel.strip()

        if engine == "openai":
            model = self.le_cloud_model.currentText().strip() or DEFAULT_STT_MODEL
            if is_legacy_stt_model(model) and not self._asked_migration:
                self._asked_migration = True
                if ask(self, "Устаревшая модель",
                       f"Модель {model} будет отключена {LEGACY_REMOVAL_DATE:%d.%m.%Y}.\n"
                       f"Заменить на {DEFAULT_STT_MODEL} сейчас?", yes="Заменить"):
                    model = DEFAULT_STT_MODEL
                    self.le_cloud_model.setEditText(model)
            settings['stt_openai_key'] = self.le_cloud_key.text().strip()
            settings['stt_openai_model'] = model
        elif engine == "groq":
            settings['stt_groq_key'] = self.le_cloud_key.text().strip()
            settings['stt_groq_model'] = self.le_cloud_model.currentText().strip()
        elif engine == "custom":
            base_url = self.le_custom_base_url.text().strip().rstrip('/')
            if not base_url.startswith(('http://', 'https://')):
                warn(self, "Ошибка", "Base URL должен начинаться с http:// или https://")
                return
            if not self.le_cloud_model.currentText().strip():
                warn(self, "Ошибка", "Укажите имя STT-модели")
                return
            settings['stt_custom_key'] = self.le_cloud_key.text().strip()
            settings['stt_custom_model'] = self.le_cloud_model.currentText().strip()
            settings['stt_custom_base_url'] = base_url

        try:
            settings_manager.update_settings(**settings)
        except Exception as exc:
            logger.error("Не удалось сохранить настройки голоса: %s", exc)
            warn(self, "Ошибка", "Не удалось сохранить настройки голоса.")
            return
        logger.info("Настройки голоса сохранены")
        inform(self, "Сохранено", "Настройки голоса сохранены.")
