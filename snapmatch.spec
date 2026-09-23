# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

# Local Vosk support is optional. Build it only when explicitly requested:
# SNAPMATCH_BUNDLE_VOSK=1 pyinstaller snapmatch.spec
bundle_vosk = os.environ.get('SNAPMATCH_BUNDLE_VOSK', '').strip().lower() in {'1', 'true', 'yes'}
datas, binaries, hiddenimports = [], [], []
if bundle_vosk:
    tmp_ret = collect_all('vosk')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Собираем все файлы для проблемных библиотек
tmp_ret = collect_all('httpx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('httpcore')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('h11')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('certifi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('openai')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('anyio')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Новые bot/secretary/MCP сценарии активно используют динамические импорты
# внутри aiogram, mcp и pydantic. Явно собираем их, чтобы PyInstaller не
# полагался только на статический анализ import graph.
tmp_ret = collect_all('aiogram')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# `mcp.cli` требует optional dependency `typer`, но SnapMatch использует MCP
# как runtime/client SDK. CLI в exe не нужен и ломает сборку без mcp[cli].
hiddenimports += collect_submodules(
    'mcp',
    filter=lambda name: not name.startswith('mcp.cli')
)
datas += copy_metadata('mcp')

for package_name in (
    'httpx_sse',
    'jsonschema',
    'starlette',
    'sse_starlette',
    'uvicorn',
    'jwt',
    'multipart',
    'python_multipart',
):
    try:
        tmp_ret = collect_all(package_name)
        datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    except Exception:
        pass

tmp_ret = collect_all('pydantic')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('pydantic_core')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('pydantic_settings')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Наши собственные скрытые импорты
# ПОРЯДОК ВАЖЕН! Config и utils должны быть загружены ПЕРВЫМИ
my_hiddenimports = [
    'config',
    'config.settings',
    'utils',
    'utils.logger',
    'utils.voice_processor',
    'utils.server_state',
    'utils.stats',
    'utils.encryption',
    'utils.resource_manager',
    'utils.history_manager',
    'utils.markdown_formatter',
    'utils.tokenizer',
    'utils.database',
    'utils.database.base_db',
    'utils.database.database_manager',
    'utils.database.message_db',
    'utils.database.mcp_db',
    'utils.database.secretary_db',
    'utils.database.user_db',
    'bot',
    'bot.handlers',
    'bot.handlers.queue_manager',
    'bot.handlers.message_handlers',
    'bot.handlers.menu_handlers',
    'bot.handlers.secretary_handlers',
    'bot.handlers.command_handlers',
    'bot.handlers.state_handlers',
    'bot.handlers.services',
    'bot.handlers.services.context_manager',
    'bot.handlers.services.context_snapshot',
    'bot.handlers.services.group_manager',
    'bot.handlers.services.image_processor',
    'bot.handlers.services.message_processor',
    'bot.handlers.services.model_client_manager',
    'bot.handlers.services.model_request_builder',
    'bot.handlers.services.menu_renderer',
    'bot.handlers.services.mcp_registry',
    'bot.handlers.services.mcp_runtime',
    'bot.handlers.services.mcp_permissions',
    'bot.handlers.services.prompt_manager',
    'bot.handlers.services.queue_processor',
    'bot.handlers.services.request_processor',
    'bot.handlers.services.role_manager',
    'bot.handlers.services.telegram_utils',
    'bot.handlers.services.text_cleaner',
    'gui',
    'gui.admin_panel',
    'gui.admin_panel.admin_panel_base',
    'gui.admin_panel.user_management',
    'gui.admin_panel.settings_panel',
    'gui.admin_panel.mcp_tab',
    'gui.admin_panel.secretary_tab',
    'gui.admin_panel.voice_settings_tab',
    'gui.admin_panel.extra_settings_tab',
    'gui.admin_panel.message_history',
    'gui.admin_panel.server_control',
    'gui.admin_panel.handlers',
    'gui.admin_panel.handlers.log_handler',
    'gui.admin_panel.services',
    'gui.admin_panel.services.model_service',
    'gui.admin_panel.services.stats_service',
    'gui.admin_panel.services.user_service',
    'gui.admin_dashboard',
    'gui.splash_screen',
    'aiohttp',
    'httpx',
    'httpcore',
    'h11',
    'sniffio',
    'anyio',
    'certifi',
    'wave',
    'json',
    'subprocess'
]
hiddenimports.extend(my_hiddenimports)

project_root = SPECPATH
repo_root = os.path.abspath(os.path.join(project_root, ".."))

extra_datas = [
    (os.path.join('assets', 'icon.svg'), 'assets'),
    (os.path.join('assets', 'icon3.ico'), 'assets'),
    (os.path.join('assets', 'icon3.png'), 'assets'),
    (os.path.join('assets', 'question_mark.png'), 'assets'),
]

excluded_modules = [
    'tests', 'test', 'matplotlib', 'numpy', 'pandas', 'scipy',
    'PIL', 'pillow', 'lxml', 'sqlalchemy', 'pytest', 'py',
    'pytz', 'cv2', 'sklearn', 'torch', 'tensorflow',
    'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets', 'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtNetwork',
]
if not bundle_vosk:
    # A globally installed Vosk must not leak into the lightweight build as
    # Python code without its native libraries.
    excluded_modules.append('vosk')

if bundle_vosk and os.name == 'nt':
    ffmpeg_candidates = [
        os.path.join(repo_root, 'ffmpeg-2026-01-26-git-fe0813d6e2-essentials_build', 'bin', 'ffmpeg.exe'),
        os.path.join(repo_root, 'ffmpeg-8.0.1-win64-static', 'bin', 'ffmpeg.exe'),
        os.path.join(repo_root, 'ffmpeg-8.0-audio-x86_64-w64-mingw32', 'ffmpeg-8.0-audio-x86_64-w64-mingw32', 'bin', 'ffmpeg.exe'),
    ]
    ffmpeg_path = next((path for path in ffmpeg_candidates if os.path.exists(path)), None)
    if ffmpeg_path:
        extra_datas.append((ffmpeg_path, os.path.join('assets', 'ffmpeg')))
    else:
        raise RuntimeError('Vosk build requires ffmpeg.exe in a supported sibling directory.')

if bundle_vosk:
    model_roots = [
        os.path.join(project_root, 'assets', 'models', 'stt', 'vosk'),
        os.path.join(repo_root, 'assets', 'models', 'stt', 'vosk'),
    ]
    vosk_model_path = None
    for model_root in model_roots:
        if not os.path.isdir(model_root):
            continue
        if os.path.isdir(os.path.join(model_root, 'am')) and os.path.isdir(os.path.join(model_root, 'conf')):
            vosk_model_path = model_root
            break
        for entry in sorted(os.listdir(model_root)):
            candidate = os.path.join(model_root, entry)
            if (
                os.path.isdir(candidate)
                and os.path.isdir(os.path.join(candidate, 'am'))
                and os.path.isdir(os.path.join(candidate, 'conf'))
            ):
                vosk_model_path = candidate
                break
        if vosk_model_path:
            break
    if vosk_model_path:
        extra_datas.append((vosk_model_path, os.path.join('assets', 'models', 'stt', 'vosk')))
    else:
        raise RuntimeError('Vosk build requires a local model with am and conf directories.')

version_file = 'version_info.txt' if sys.platform.startswith('win') and os.path.exists('version_info.txt') else None
icon_file = os.path.join('assets', 'icon3.ico') if os.path.exists(os.path.join(project_root, 'assets', 'icon3.ico')) else None

a = Analysis(
    ['main.py'],
    pathex=[project_root],
    binaries=binaries,
    datas=datas + extra_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    # PLY/pycparser stores grammar rules in docstrings. optimize=2 strips them
    # from bytecode and breaks MCP imports in the frozen app with YaccError.
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [('O', None, 'OPTION')],
    name='SnapMatch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=version_file,
    icon=icon_file,
)
