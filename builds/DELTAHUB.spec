# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import os, sys

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
try:
    spec_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    spec_dir = os.path.join(os.getcwd(), 'builds')
project_root = os.path.dirname(spec_dir)
secrets_embed_path = os.path.join(project_root, 'secrets_embed.py')
if os.path.exists(secrets_embed_path):
    datas_extra.append((secrets_embed_path, '.'))

a = Analysis(
    ['../src/main.py'],
    pathex=['..'],
    binaries=binaries_extra,
    datas=[('../src', 'src')] + datas_extra,
    hiddenimports=[
        'psutil',
        'packaging',
        'requests',
        'PyQt6',
        'PyQt6.sip',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtNetwork',
        'playsound3',
        'secrets_embed',
        'rarfile',
        'dotenv',
        'py7zr',
        'PIL',
        'PIL.Image',
    ],
    excludes=[
        'PyQt6.QtQml',
        'PyQt6.QtQuick',
        'PyQt6.QtTest',
        'PyQt6.QtBluetooth',
        'PyQt6.QtNetworkAuth',
        'PyQt6.QtOpenGLWidgets',
        'PyQt6.QtPositioning',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineQuick',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtSensors',
        'PyQt6.QtSerialPort',
        'PyQt6.QtLocation'
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name='DELTAHUB',
    icon='../src/assets/icons/icon.ico',
    console=False,
    upx=False,
)

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='DELTAHUB.app',
        icon='../src/assets/icons/icon.icns',
        bundle_identifier='com.y114.deltahub',
        info_plist={
            'CFBundleURLTypes': [
                {
                    'CFBundleURLName': 'DELTAHUB URL',
                    'CFBundleURLSchemes': ['deltahub']
                }
            ]
        }
    )
