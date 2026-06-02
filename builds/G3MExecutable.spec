# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import os, sys
from pathlib import Path

binaries_extra = []
# Support multiple VC runtime DLLs via VCREDIST_DLLS (pathsep-separated),
# and legacy single variable VCREDIST_DLL
vcredist_multi = os.getenv('VCREDIST_DLLS', '')
if vcredist_multi:
    for p in vcredist_multi.split(os.pathsep):
        p = p.strip()
        if p and os.path.exists(p):
            binaries_extra.append((p, '.'))
else:
    vcredist_dll = os.getenv('VCREDIST_DLL', '')
    if vcredist_dll and os.path.exists(vcredist_dll):
        binaries_extra.append((vcredist_dll, '.'))


datas_extra = []
debug_spec = os.getenv('G3M_SPEC_DEBUG', '').strip().lower() in {'1', 'true', 'yes', 'on'}
try:
    spec_path = Path(__file__).resolve()
except NameError:
    spec_path = None
if spec_path is not None:
    spec_dir = spec_path.parent
    project_root = None
    marker_names = ('builds', '.git', 'pyproject.toml')
    search_roots = (spec_dir,) + tuple(spec_dir.parents)
    for candidate in search_roots:
        if debug_spec:
            print(f"[spec debug] checking project root candidate: {candidate}")
        if any((candidate / marker).exists() for marker in marker_names):
            project_root = candidate
            break
    if project_root is None:
        project_root = spec_dir.parent
else:
    cwd = Path(os.getcwd()).resolve()
    project_root = cwd
    spec_dir = cwd / 'builds'
env_candidates = [
    os.path.join(project_root, 'src', '.env'),
    os.path.join(project_root, '.env'),
]
found_env_path = None
for env_path in env_candidates:
    if debug_spec:
        print(f"[spec debug] checking .env candidate: {env_path}")
    if os.path.exists(env_path):
        found_env_path = env_path
        datas_extra.append((env_path, 'src'))
        break
if found_env_path:
    print(f"Looking for .env: found at {found_env_path}")
else:
    print("WARNING: .env not found")

a = Analysis(
    ['../src/main.py'],
    pathex=['..'],
    binaries=binaries_extra,
    datas=[('../src', 'src')] + datas_extra,
    optimize=2,
    hiddenimports=[
        'psutil',
        'requests',
        'PyQt6',
        'PyQt6.sip',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtNetwork',
        'playsound3',
        'rarfile',
        'dotenv',
        'py7zr',
    ],
    excludes=[
        'PyQt6.QtQml',
        'PyQt6.QtQuick',
        'PyQt6.QtTest',
        'PyQt6.QtBluetooth',
        'PyQt6.QtNetworkAuth',
        'PyQt6.QtOpenGL',
        'PyQt6.QtOpenGLWidgets',
        'PyQt6.QtPositioning',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineQuick',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebChannel',
        'PyQt6.QtSensors',
        'PyQt6.QtSerialPort',
        'PyQt6.QtLocation',
        'PyQt6.QtMultimedia',
        'PyQt6.QtMultimediaWidgets',
        'PyQt6.QtPrintSupport',
        'PyQt6.QtSql',
        'PyQt6.QtSvgWidgets',
        'PyQt6.QtXml',
        'PyQt6.QtXmlPatterns',
        'PyQt6.QtDesigner',
        'PyQt6.QtHelp',
        'PyQt6.QtDBus',
        'PyQt6.Qt3DCore',
        'PyQt6.Qt3DRender',
        'PyQt6.Qt3DInput',
        'PyQt6.Qt3DExtras',
        'PyQt6.QtRemoteObjects',
        'PyQt6.QtNfc',
        'tkinter',
        'turtle',
        'curses',
        'readline',
        'sqlite3',
        'dbm',
        'gdbm',
        'pydoc',
        'pydoc_data',
        'doctest',
        'unittest',
        'test',
        'setuptools',
        'pip',
        'pdb',
        'profile',
        'pstats',
        'cProfile',
        'pickletools',
        'lib2to3',
        'ensurepip',
        'python_dotenv',
        'packaging',
        'venv',
        'wsgiref',
        'smtplib',
        'poplib',
        'imaplib',
        'nntplib',
        'telnetlib',
        'ftplib',
        'xmlrpc',
        'PIL',
        'PIL.Image',
        'PIL.ImageFile',
        'PIL._imaging',
        'antigravity',
        'cmd',
        'code',
        'colorsys',
        'compileall',
        'csv',
        'decimal',
        'difflib',
        'getopt',
        'idlelib',
        'mailbox',
        'optparse',
        'py_compile',
        'sched',
        'symtable',
        'tabnanny',
        'this',
        'timeit',
        'trace',
        'turtledemo',
        'wave',
        'zipapp',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name='G3M',
    icon='assets/icons/icon.ico',
    console=False,
    upx=True,
    upx_exclude=[],
)

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='G3M.app',
        icon='assets/icons/icon.icns',
        bundle_identifier='com.y114.g3m',
        info_plist={
            'CFBundleURLTypes': [
                {
                    'CFBundleURLName': 'G3M URL',
                    'CFBundleURLSchemes': ['g3m', 'deltahub']
                }
            ]
        }
    )

