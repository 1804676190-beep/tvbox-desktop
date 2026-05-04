# -*- mode: python ; coding: utf-8 -*-
"""TVBox Desktop — PyInstaller 打包配置"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

block_cipher = None

# 收集 PyQt6 全部文件（DLL、插件、翻译等）
pyqt6_datas, pyqt6_binaries, pyqt6_hiddenimports = collect_all('PyQt6')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=pyqt6_binaries,
    datas=pyqt6_datas,
    hiddenimports=pyqt6_hiddenimports + [
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtNetwork',
        'mpv',
        'requests',
        'bs4',
        'lxml',
        'core',
        'core.models',
        'core.source_manager',
        'core.repository',
        'core.cloud_drive',
        'core.media_player',
        'core.spider_engine',
        'core.builtin_sources',
        'core.updater',
        'core.scraper',
        'core.web_video_extractor',
        'core.quark_drive',
        'ui',
        'ui.main_window',
        'ui.poster_wall',
        'ui.quark_login_dialog',
        'paste_link_converter',
        'qrcode',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'cv2',
        'torch',
        'tensorflow',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TVBox Desktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TVBox Desktop',
)
