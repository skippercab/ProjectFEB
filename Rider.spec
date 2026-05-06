# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Rider.app — self-contained macOS bundle
import os
from pathlib import Path

project_dir = Path(SPECPATH)
src_dir = project_dir / 'src'
build_venv = project_dir / '.venv_build'
site_packages = build_venv / 'lib' / 'python3.12' / 'site-packages'

# ── Data files bundled into the app ──────────────────────────────────────────
datas = [
    # CustomTkinter UI assets (themes, images, fonts)
    (str(site_packages / 'customtkinter'), 'customtkinter'),
    # App assets
    (str(project_dir / 'img'), 'img'),
    (str(project_dir / 'font'), 'font'),
    (str(project_dir / 'config'), 'config'),
    (str(project_dir / 'template'), 'template'),
]

# ── Hidden imports that PyInstaller misses via static analysis ────────────────
hiddenimports = [
    'customtkinter',
    'PIL._tkinter_finder',
    'PIL.ImageTk',
    'tkinter',
    'tkinter.ttk',
    'tkinter.filedialog',
    'tkinter.messagebox',
    '_tkinter',
    'cryptography',
    'cryptography.hazmat',
    'cryptography.hazmat.primitives',
    'cryptography.hazmat.backends',
    'cryptography.hazmat.backends.openssl',
    'cryptography.fernet',
    'lxml',
    'lxml.etree',
    'lxml._elementpath',
    'xmltodict',
    'loguru',
    'fuzzywuzzy',
    'Levenshtein',
    'pandas',
    'requests',
    'dotenv',
    'packaging',
    'packaging.version',
    'packaging.specifiers',
    'packaging.requirements',
]

a = Analysis(
    [str(src_dir / 'main.py')],
    pathex=[str(src_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project_dir / 'pyi_runtime_hook.py')],
    excludes=['faster_whisper', 'torch', 'torchaudio', 'numpy.testing', 'pytest'],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Rider',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Rider',
)

app = BUNDLE(
    coll,
    name='Rider.app',
    icon=str(project_dir / 'img' / 'icon.icns'),
    bundle_identifier='com.projectfeb.rider',
    version='2.0.0',
    info_plist={
        'CFBundleName': 'Rider',
        'CFBundleDisplayName': 'Rider',
        'CFBundleShortVersionString': '2.0.0',
        'CFBundleVersion': '2.0.0',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
        'LSMinimumSystemVersion': '12.0',
        'NSHumanReadableCopyright': '© 2026 ProjectFEB',
        'LSApplicationCategoryType': 'public.app-category.music',
    },
)
