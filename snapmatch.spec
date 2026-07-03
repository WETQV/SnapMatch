import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

def collect_package(name, required=False):
    try:
        return collect_all(name)
    except Exception:
        if required:
            raise
        return [], [], []

def add_existing_data(items, source, target):
    if os.path.exists(source):
        items.append((source, target))

datas, binaries, hiddenimports = collect_package('vosk')

for package_name in (
    'httpx',
    'httpcore',
    'h11',
    'certifi',
    'openai',
    'anyio',
    'aiogram',
    'pydantic',
    'pydantic_core',
    'pydantic_settings',
):
    package_datas, package_binaries, package_hiddenimports = collect_package(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

hiddenimports += collect_submodules('mcp', filter=lambda name: not name.startswith('mcp.cli'))
try:
    datas += copy_metadata('mcp')
except Exception:
    pass

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
    package_datas, package_binaries, package_hiddenimports = collect_package(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

hiddenimports += [
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
    'bot.handlers.secretary_runtime',
    'bot.handlers.command_handlers',
    'bot.handlers.state_handlers',
    'bot.handlers.services',
    'bot.handlers.services.access_control',
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
    'bot.handlers.services.rich_message_sender',
    'bot.handlers.services.role_manager',
    'bot.handlers.services.secretary_debounce_manager',
    'bot.handlers.services.secretary_intake',
    'bot.handlers.services.secretary_queue_adapter',
    'bot.handlers.services.secretary_queue_policy',
    'bot.handlers.services.secretary_response',
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
    'wave',
    'json',
    'subprocess',
]

project_root = SPECPATH
repo_root = os.path.abspath(os.path.join(project_root, '..'))
app_datas = []
for path, target in (
    (os.path.join(project_root, 'assets', 'icon.svg'), 'assets'),
    (os.path.join(project_root, 'assets', 'icon3.ico'), 'assets'),
    (os.path.join(project_root, 'assets', 'icon3.png'), 'assets'),
    (os.path.join(project_root, 'assets', 'question_mark.png'), 'assets'),
):
    add_existing_data(app_datas, path, target)

for ffmpeg_path in (
    os.path.join(repo_root, 'ffmpeg-2026-01-26-git-fe0813d6e2-essentials_build', 'bin', 'ffmpeg.exe'),
    os.path.join(repo_root, 'ffmpeg-8.0.1-win64-static', 'bin', 'ffmpeg.exe'),
    os.path.join(repo_root, 'ffmpeg-8.0-audio-x86_64-w64-mingw32', 'ffmpeg-8.0-audio-x86_64-w64-mingw32', 'bin', 'ffmpeg.exe'),
):
    if os.path.exists(ffmpeg_path):
        app_datas.append((ffmpeg_path, os.path.join('assets', 'ffmpeg')))
        break

version_file = 'version_info.txt' if sys.platform.startswith('win') and os.path.exists('version_info.txt') else None
icon_file = os.path.join('assets', 'icon3.ico') if os.path.exists(os.path.join(project_root, 'assets', 'icon3.ico')) else None

a = Analysis(
    ['main.py'],
    pathex=[project_root],
    binaries=binaries,
    datas=datas + app_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tests', 'test', 'matplotlib', 'numpy', 'pandas', 'scipy',
        'PIL', 'pillow', 'lxml', 'sqlalchemy', 'pytest', 'py',
        'pytz', 'cv2', 'sklearn', 'torch', 'tensorflow',
        'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets', 'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtNetwork',
    ],
    noarchive=False,
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
