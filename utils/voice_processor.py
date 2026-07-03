# utils/voice_processor.py

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
    """Возвращает путь к ffmpeg.exe (встроенный или системный)."""
    candidates: list[Path] = []

    # PyInstaller: файлы лежат в _MEIPASS
    if getattr(sys, "_MEIPASS", None):
        candidates.append(Path(sys._MEIPASS) / "assets" / "ffmpeg" / "ffmpeg.exe")

    # Проектная структура: assets/ffmpeg/ffmpeg.exe рядом с кодом
    project_root = Path(__file__).resolve().parents[1]
    candidates.append(project_root / "assets" / "ffmpeg" / "ffmpeg.exe")

    # Репозиторий: приоритет ставим на полноценные сборки
    repo_root = project_root.parent
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

# Попытка импорта vosk (будет работать если библиотека установлена)
try:
    from vosk import Model, KaldiRecognizer
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False
    logger.warning("Библиотека Vosk не установлена. Локальный STT будет недоступен.")

class VoiceProcessor:
    def __init__(self):
        self.model = None
        self.current_model_path = None

    def _ensure_model_loaded(self):
        """Ленивая загрузка модели Vosk"""
        if not VOSK_AVAILABLE:
            raise RuntimeError("Библиотека vosk не установлена. Выполните: pip install vosk")

        settings = settings_manager.get_settings()
        model_path = settings.get('stt_model_path', 'assets/models/stt/vosk')

        if self.model is not None and self.current_model_path == model_path:
            return

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Модель Vosk не найдена по пути: {model_path}")

        logger.info(f"Загрузка модели Vosk из {model_path}...")
        try:
            self.model = Model(model_path)
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
        elif engine in ['openai', 'groq']:
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

    async def _transcribe_cloud(self, ogg_path: str, engine: str) -> str:
        """Распознавание через OpenAI или Groq API"""
        settings = settings_manager.get_settings()
        
        if engine == 'openai':
            api_key = settings.get('stt_openai_key')
            model = settings.get('stt_openai_model', 'whisper-1')
            base_url = "https://api.openai.com/v1"
        else: # groq
            api_key = settings.get('stt_groq_key')
            model = settings.get('stt_groq_model', 'whisper-large-v3-turbo')
            base_url = "https://api.groq.com/openai/v1"

        if not api_key:
            raise RuntimeError(f"Не указан API ключ для {engine} во вкладке 'Голос'.")

        # Для облачных API отправляем OGG напрямую (оба сервиса это поддерживают)
        # Используем aiohttp вместо httpx для совместимости с PyInstaller
        try:
            import aiohttp
            headers = {"Authorization": f"Bearer {api_key}"}
            url = f"{base_url}/audio/transcriptions"
            ssl_context = None

            # Читаем файл в память перед отправкой (чтобы избежать проблем с закрытием файла)
            with open(ogg_path, "rb") as f:
                file_data = f.read()
            
            async with aiohttp.ClientSession() as session:
                # aiohttp использует FormData для multipart/form-data
                form_data = aiohttp.FormData()
                form_data.add_field('file', file_data, filename=os.path.basename(ogg_path), content_type='audio/ogg')
                form_data.add_field('model', model)
                form_data.add_field('language', 'ru')
                
                try:
                    async with session.post(
                        url, 
                        data=form_data, 
                        headers=headers, 
                        ssl=ssl_context,
                        timeout=aiohttp.ClientTimeout(total=180.0)
                    ) as response:
                        # Явно проверяем статус перед закрытием контекста клиента
                        if response.status != 200:
                            error_msg = "Unknown error"
                            try:
                                error_data = await response.json()
                                error_detail = error_data.get('error', {})
                                error_msg = error_detail.get('message', str(error_detail))
                            except:
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
                startupinfo=startupinfo
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg conversion error: {e.stderr.decode()}")
            raise RuntimeError("Ошибка конвертации аудио. Пожалуйста, попробуйте позже.")
        except FileNotFoundError:
            raise RuntimeError("Системный компонент (FFmpeg) не найден. Обратитесь к администратору.")

        try:
            import wave
            wf = wave.open(wav_path, "rb")
            
            # Проверка формата WAV
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
                wf.close()
                raise RuntimeError("Неверный формат WAV после конвертации.")

            rec = KaldiRecognizer(self.model, wf.getframerate())
            rec.SetWords(True)

            results = []
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    pass # Промежуточные результаты нам не нужны
            
            final_result = json.loads(rec.FinalResult())
            text = final_result.get("text", "")
            
            wf.close()
            return text
        finally:
            # Чистим за собой временный WAV
            if os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except:
                    pass

voice_processor = VoiceProcessor()
