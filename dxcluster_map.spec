# -*- mode: python ; coding: utf-8 -*-
# Configurazione PyInstaller per DX Cluster Map (Windows).
# Produce una cartella "DXClusterMap" in dist/ (onedir: avvio più rapido
# e più affidabile del single-file con QtWebEngine).
#
# Per tenere il pacchetto piccolo (~120 MB invece di ~250) vengono esclusi:
#  - la directory QML e i moduli QtQuick3D/3D/Charts/Pdf/Multimedia... non
#    usati dall'app (la mappa è HTML/JS, i suoni usano il player di sistema)
#  - le traduzioni di Qt e le localizzazioni di WebEngine tranne en-US e it
#  - i devtools di WebEngine
# La lista delle librerie Qt mantenute è la chiusura delle dipendenze di
# QtWebEngineCore (verificata con ldd): Quick/Qml/OpenGL sono necessarie
# perché WebEngine le usa internamente.
import re

# Moduli Python (binding) da tenere: tutto il resto di PySide6/*.abi3 viene
# scartato perché l'app non li importa.
# Nota: QtPrintSupport serve perché QtWebEngineCore lo importa internamente,
# anche se l'app non stampa.
KEEP_BINDINGS = {
    "qtcore", "qtgui", "qtwidgets", "qtnetwork", "qtprintsupport",
    "qtwebenginecore", "qtwebenginewidgets", "qtwebchannel",
    "qttexttospeech",
}

# Librerie Qt necessarie a WebEngine e ai widget (verificate via ldd).
# Su Linux servono anche i backend di piattaforma: senza Qt6XcbQpa il plugin
# xcb userebbe il Qt di sistema, con una versione diversa (e non funzionerebbe).
KEEP_QT_LIBS = {
    "qt6core", "qt6gui", "qt6widgets", "qt6network", "qt6opengl",
    "qt6openglwidgets", "qt6svg", "qt6dbus", "qt6printsupport",
    "qt6qml", "qt6qmlmeta", "qt6qmlmodels", "qt6qmlworkerscript",
    "qt6quick", "qt6quickwidgets", "qt6quickshapes", "qt6shadertools",
    "qt6positioning", "qt6webchannel",
    "qt6webenginecore", "qt6webenginewidgets",
    "qt6texttospeech",
    "qt6xcbqpa", "qt6waylandclient",
    "icudata", "icui18n", "icuuc",
}

# Formati FFmpeg di QtMultimedia (pesanti e inutilizzati: i WAV si giocano
# con winsound/paplay). Vengono rimossi anche i relativi .dll/.so.
DROP_PREFIXES = (
    "avcodec", "avformat", "avutil", "swresample", "swscale",
    "avdevice", "avfilter", "postproc",
)

# Sottodirectory di PySide6/Qt da non includere per niente.
DROP_DIRS = (
    "/qt/qml/",
    "/qt/plugins/qmltooling/",
    "/qt/plugins/multimedia/",
)

# Librerie di sistema che PyInstaller copia dal sistema di build: è meglio
# usare quelle della distribuzione. In particolare libstdc++ di Ubuntu 22.04,
# più vecchia di quella richiesta dalla Mesa dei sistemi recenti, faceva
# fallire l'avvio su X11 con "Could not initialize GLX".
DROP_SYSTEM_LIBS = {"libstdc++.so.6", "libgcc_s.so.1"}


def _stem(path: str) -> str:
    """Basename senza estensione e senza suffissi di versione (es. libQt6Core.so.6 -> qt6core)."""
    name = re.split(r"[/\\]", path)[-1]
    stem = re.sub(r"\.(so|dll|pyd)(\.\d+)*$", "", name, flags=re.IGNORECASE)
    stem = stem.lower()
    if stem.endswith(".abi3"):
        stem = stem[: -len(".abi3")]
    if stem.startswith("lib"):
        stem = stem[3:]
    return stem


def _keep(entry) -> bool:
    """Filtra una voce di a.binaries: entry = (dest, src, kind)."""
    dest = entry[0].replace("\\", "/").lower()
    if any(d in dest for d in DROP_DIRS):
        return False
    raw = re.split(r"[/\\]", dest)[-1]
    stem = _stem(dest)
    if raw in DROP_SYSTEM_LIBS:
        return False
    if "pyside" in stem or "shiboken" in stem:
        return True
    if dest.startswith("pyside6/") and (".abi3" in raw or raw.endswith(".pyd")):
        # binding PySide6: tienilo solo se l'app lo usa davvero.
        # Attenzione: i .pyd della stdlib (_socket, _ssl, ...) non sono binding
        # e devono restare.
        return stem in KEEP_BINDINGS
    if stem.startswith(DROP_PREFIXES):
        return False
    if stem.startswith("icu"):
        return True   # dati i18n: necessari, nomi diversi per piattaforma
    if stem.startswith("qt6"):
        return stem in KEEP_QT_LIBS
    return True


def _keep_data(entry) -> bool:
    """Filtra una voce di a.datas: scarta QML, traduzioni e devtools."""
    dest = entry[0].replace("\\", "/").lower()
    if any(d in dest for d in DROP_DIRS):
        return False
    if "qtwebengine_devtools_resources.pak" in dest:
        return False
    if "/qt/translations/" in dest:
        # tieni solo le localizzazioni di WebEngine in inglese e italiano
        return dest.endswith(("qtwebengine_locales/en-us.pak",
                              "qtwebengine_locales/it.pak"))
    return True


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('installer/icon.png', '.')],
    hiddenimports=[
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebChannel',
        'PySide6.QtTextToSpeech',
        'sgp4.api',
        'sgp4.wrapper',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL',
              'PySide6.QtMultimedia*', 'PySide6.QtQml*', 'PySide6.QtQuick*',
              'PySide6.Qt3D*', 'PySide6.QtQuick3D*', 'PySide6.Qt5Compat*',
              'PySide6.QtGraphs*', 'PySide6.QtCharts*', 'PySide6.QtPdf*',
              'PySide6.QtOpenGL*', 'PySide6.QtRemoteObjects*',
              'PySide6.QtSerialPort*', 'PySide6.QtBluetooth*',
              'PySide6.QtNfc*', 'PySide6.QtSensors*', 'PySide6.QtTest*',
              'PySide6.QtHelp*', 'PySide6.QtUiTools*', 'PySide6.QtDesigner*',
              'PySide6.QtSql*', 'PySide6.QtScxml*', 'PySide6.QtStateMachine*',
              'PySide6.QtLocation*', 'PySide6.QtDataVisualization*',
              'PySide6.QtWebSockets*'],
    noarchive=False,
)

# Applica i filtri dopo l'analisi: PyInstaller trascina comunque le librerie
# Qt collegate da WebEngine (Quick/Qml), ma qui eliminiamo tutto il resto.
a.binaries = [entry for entry in a.binaries if _keep(entry)]
a.datas = [entry for entry in a.datas if _keep_data(entry)]

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
    icon='installer/dxcluster_map.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='DXClusterMap',
)
