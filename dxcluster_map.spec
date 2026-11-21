# -*- mode: python ; coding: utf-8 -*-
# Configurazione PyInstaller per DX Cluster Map (Windows).
# Produce una cartella "DXClusterMap" in dist/ (onedir: avvio più rapido
# e più affidabile del single-file con QtWebEngine).

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebChannel',
        'PySide6.QtMultimedia',
        'PySide6.QtTextToSpeech',
        'sgp4.api',
        'sgp4.wrapper',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL', 'PySide6.Qt3D*', 'PySide6.QtQuick*'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DXClusterMap',
    debug=False,
    strip=False,
    upx=False,
    console=False,          # app GUI: nessuna finestra terminale
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='DXClusterMap',
)
