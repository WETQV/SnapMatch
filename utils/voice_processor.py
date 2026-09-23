# utils/voice_processor.py

import asyncio
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from utils.logger import setup_logger
from config.settings import settings_manager

logger = setup_logger(__name__)

STT_NOISE_PATTERNS = [
    re.compile(r"^\s*субтитры\s+сделал\s+.+$", re.IGNORECASE),
    re.compile(r"^\s*subtitles?\s+by\s+.+$", re.IGNORECASE),
]


def _clean_transcribed_text(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def _looks_like_suspicious_stt_result(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return any(pattern.match(cleaned) for pattern in STT_NOISE_PATTERNS)


def resolve_ffmpeg_path() -> str | None:
    """Return a bundled or system FFmpeg executable when Vosk needs one."""
    candidates: list[Path] = []
    executable = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    # PyInstaller: файлы лежат в _MEIPASS
    if getattr(sys, "_MEIPASS", None):
        candidates.append(Path(sys._MEIPASS) / "assets" / "ffmpeg" / executable)

    # Проектная структура: assets/ffmpeg/ffmpeg.exe рядом с кодом
    project_root = Path(__file__).resolve().parents[1]
    candidates.append(project_root / "assets" / "ffmpeg" / executable)

    # Репозиторий: приоритет ставим на полноценные сборки
    repo_root = project_root.parent
    if os.name == 'nt':
    # 1. Новая essentials сборка (самая надежная)
        candidates.append(repo_root / "ffmpeg-2026-01-26-git-fe0813d6e2-essentials_build" / "bin" / "ffmpeg.exe")
    # 2. Стандартный путь (если переименовали)
        candidates.append(repo_root / "ffmpeg-8.0.1-win64-static" / "bin" / "ffmpeg.exe")
    # 3. Аудио-сборка (только как последний шанс, хотя она может не подойти)
        candidates.append(repo_root / "ffmpeg-8.0-audio-x86_64-w64-mingw32" / "ffmpeg-8.0-audio-x86_64-w64-mingw32" / "bin" / "ffmpeg.exe")

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return shutil.which("ffmpeg")

class VoiceProcessor:
    def __init__(self):
        self.model = None
        self.current_model_path = None
        self._vosk_module = None
        self._vosk_import_error = None

    def _load_vosk_module(self):
        """Import Vosk only when the local engine is actually selected."""
        if self._vosk_module is not None:
            return self._vosk_module
        try:
            self._vosk_module = importlib.import_module("vosk")
            return self._vosk_module
        except Exception as e:
            self._vosk_import_error = e
            logger.warning("Vosk недоступен: %s", e)
            raise RuntimeError(
                "Vosk не установлен или его нативная библиотека не загрузилась. "
                "Установите локальные STT-зависимости либо выберите openai, groq или custom."
            ) from e

    def _ensure_model_loaded(self):
        """Ленивая загрузка модели Vosk"""
        vosk_module = self._load_vosk_module()

        settings = settings_manager.get_settings()
        configured_model_path = settings.get('stt_model_path', 'assets/models/stt/vosk')
        model_path = Path(configured_model_path).expanduser()
        if not model_path.is_absolute() and getattr(sys, "_MEIPASS", None):
            bundled_model_path = Path(sys._MEIPASS) / model_path
            if bundled_model_path.exists():
                model_path = bundled_model_path
        model_path = str(model_path)

        if self.model is not None and self.current_model_path == model_path:
            return

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Модель Vosk не найдена по пути: {model_path}")

        logger.info(f"Загрузка модели Vosk из {model_path}...")
        try:
            self.model = vosk_module.Model(model_path)
            self.current_model_path = model_path
            logger.info("Модель Vosk успешно загружена.")
        except Exception as e:
            logger.error(f"Ошибка при загрузке модели Vosk: {e}")
            raise

    async def transcribe_voice(self, ogg_path: str) -> str:
        """Конвертирует медиа в нужный формат и распознает текст."""
        return await self.transcribe_media(ogg_path)

    async def transcribe_media(self, media_path: str) -> str:
        """Распознает аудио из голосовых сообщений, кружочков и других медиа."""
        settings = settings_manager.get_settings()
        if not settings.get('stt_enabled', False):
            return ""

        engine = settings.get('stt_engine', 'vosk')
        
        if engine == 'vosk':
            text = await self._transcribe_vosk(media_path)
        elif engine in ['openai', 'groq', 'custom']:
            text = await self._transcribe_cloud(media_path, engine)
        else:
            text = ""

        cleaned = _clean_transcribed_text(text)
        if _looks_like_suspicious_stt_result(cleaned):
            logger.info(
                "STT вернул подозрительно шаблонный текст, но результат сохранён: [length=%s]",
                len(cleaned),
            )
        return cleaned

    async def _transcribe_cloud(self, media_path: str, engine: str) -> str:
        """Распознавание через OpenAI-совместимый transcription API."""
        settings = settings_manager.get_settings()
        
        if engine == 'openai':
            api_key = settings.get('stt_openai_key')
            model = settings.get('stt_openai_model', 'whisper-1')
            base_url = "https://api.openai.com/v1"
        elif engine == 'groq':
            api_key = settings.get('stt_groq_key')
            model = settings.get('stt_groq_model', 'whisper-large-v3-turbo')
            base_url = "https://api.groq.com/openai/v1"
        else:
            api_key = settings.get('stt_custom_key') or ""
            model = settings.get('stt_custom_model', 'whisper-1')
            base_url = str(settings.get('stt_custom_base_url') or '').rstrip('/')

        if not base_url.startswith(('http://', 'https://')):
            raise RuntimeError("Base URL STT должен начинаться с http:// или https://")

        if engine != 'custom' and not api_key:
            raise RuntimeError(f"Не указан API ключ для {engine} во вкладке 'Голос'.")

        # Для облачных API отправляем OGG напрямую (оба сервиса это поддерживают)
        # Используем aiohttp вместо httpx для совместимости с PyInstaller
        try:
            import aiohttp
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            url = f"{base_url}/audio/transcriptions"
            max_upload_bytes = max(1, int(settings.get('stt_max_upload_mb', 25) or 25)) * 1024 * 1024

            if os.path.getsize(media_path) > max_upload_bytes:
                raise RuntimeError("Аудиофайл превышает настроенный лимит STT.")
            with open(media_path, "rb") as f:
                file_data = f.read()
            
            async with aiohttp.ClientSession() as session:
                # aiohttp использует FormData для multipart/form-data
                form_data = aiohttp.FormData()
                import mimetypes
                content_type = mimetypes.guess_type(media_path)[0] or 'application/octet-stream'
                form_data.add_field('file', file_data, filename=os.path.basename(media_path), content_type=content_type)
                form_data.add_field('model', model)
                form_data.add_field('language', 'ru')
                
                try:
                    async with session.post(
                        url, 
                        data=form_data, 
                        headers=headers, 
                        timeout=aiohttp.ClientTimeout(total=180.0)
                    ) as response:
                        # Явно проверяем статус перед закрытием контекста клиента
                        if response.status != 200:
                            error_msg = "Unknown error"
                            try:
                                error_data = await response.json()
                                error_detail = error_data.get('error', {})
                                error_msg = error_detail.get('message', str(error_detail))
                            except Exception:
                                pass
                            raise RuntimeError(f"Ошибка API {engine}: {error_msg}")
                        
                        result = await response.json()
                        return result.get("text", "")
                except aiohttp.ClientSSLError as ssl_err:
                    raise RuntimeError(f"SSL verification failed for {base_url}: {ssl_err}") from ssl_err
        except ImportError:
            raise RuntimeError("Библиотека aiohttp не установлена. Выполните: pip install aiohttp")
        except Exception as e:
            logger.error(f"Ошибка при обращении к {engine} API: {e}")
            raise

    async def _transcribe_vosk(self, media_path: str) -> str:
        return await asyncio.wait_for(asyncio.to_thread(self._transcribe_vosk_sync, media_path), timeout=300)

    def _transcribe_vosk_sync(self, media_path: str) -> str:
        self._ensure_model_loaded()

        wav_path = str(Path(media_path).with_suffix(".wav"))
        ffmpeg_path = resolve_ffmpeg_path()

        if not ffmpeg_path:
            raise RuntimeError("FFmpeg не найден. Проверьте assets/ffmpeg или PATH.")
        
        # Конвертация через FFmpeg
        try:
            # -ar 16000 (частота дискретизации 16кГц для Vosk)
            # -ac 1 (моно)
            # Добавляем флаги для подавления окна консоли на Windows
            startupinfo = None
            if os.name == 'nt':
                import subprocess
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0 # SW_HIDE

            command = [
                ffmpeg_path, '-y', '-i', media_path,
                '-ar', '16000', '-ac', '1', wav_path
            ]
            
            subprocess.run(
                command, 
                check=True, 
                capture_output=True, 
                startupinfo=startupinfo,
                timeout=180,
            )
            import wave
            with wave.open(wav_path, "rb") as wf:
                if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
                    raise RuntimeError("Неверный формат WAV после конвертации.")

                vosk_module = self._load_vosk_module()
                rec = vosk_module.KaldiRecognizer(self.model, wf.getframerate())
                rec.SetWords(True)
                while True:
                    data = wf.readframes(4000)
                    if not data:
                        break
                    rec.AcceptWaveform(data)
                return json.loads(rec.FinalResult()).get("text", "")
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else str(e.stderr or "")
            logger.error("FFmpeg conversion error: %s", stderr)
            raise RuntimeError("Ошибка конвертации аудио. Пожалуйста, попробуйте позже.") from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("FFmpeg не успел обработать аудио за отведённое время.") from e
        except FileNotFoundError as e:
            raise RuntimeError("Системный компонент (FFmpeg) не найден. Обратитесь к администратору.") from e
        finally:
            # Чистим за собой временный WAV
            if os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception:
                    pass

voice_processor = VoiceProcessor()
