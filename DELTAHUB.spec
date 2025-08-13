# -*- mode: python ; coding: utf-8 -*-
# Универсальный spec: одна точка входа, все ассеты внутри
# Запускается:  pyinstaller -y DELTAHUB.spec

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

a = Analysis(
    ['main.py', 'launcher.py', 'helpers.py'],
    pathex=['.'],
    binaries=binaries_extra,
    datas=[('assets', 'assets'), ('lang', 'lang')],
    hiddenimports=[
        'psutil',
        'packaging',
        'requests',
        'PyQt6',
        'playsound3',
        'secrets_embed',
        'rarfile',
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
    icon='assets/icon.ico',
    console=False,
    upx=False,
)

# На macOS формируем .app бандл из exe
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='DELTAHUB.app',
        icon='assets/icon.icns',
        bundle_identifier='com.y114.deltahub'
    )