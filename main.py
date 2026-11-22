import logging
import os

from version import __version__

log = logging.getLogger(__name__)
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QIcon, QPalette, QColor, QDesktopServices, QFont, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QSplitter, QStatusBar, QSystemTrayIcon, QVBoxLayout,
    QWidget, QStackedWidget, QPushButton, QFormLayout, QToolButton, QWidgetAction,
    QSlider, QDialog, QTextEdit, QSpinBox, QDialogButtonBox, QScrollArea, QFrame,
    QDockWidget, QMessageBox, QFileDialog
)

from adif_log import (AdifLog, NEW_BAND, NEW_CALL, NEW_COUNTRY, WORKED,
                      default_adif_path)
from alerts_audio import AlertSounds
from geo import (maidenhead_to_latlon, haversine_km, initial_bearing,
                 maidenhead_square_center, sunrise_sunset)
from map_view import MapView, valid_call
from models import BANDS, parse_alert_entries, spot_matches_alert
from providers.spothole import SpotholeProvider
from satellite_passes_dialog import SatellitePassesDialog
from solar_dashboard import SolarDashboard
from satellite_provider import SatelliteProvider, SatelliteTLE
from spot_list import SpotList
from wsjtx_listener import WSJTXListener
from psk_provider import PSKReporterProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

CONTINENTS = [
    ("Tutti", None), ("Europa", "EU"), ("Nord America", "NA"),
    ("Sud America", "SA"), ("Asia", "AS"), ("Africa", "AF"),
    ("Oceania", "OC"), ("Antartide", "AN"),
]

class MainWindow(QMainWindow):
    REFRESH_MS = 60_000
    ALERT_CHECK_MS = 10_000
    SOLAR_REFRESH_MS = 30 * 60 * 1000
    SATELLITE_REFRESH_MS = 6 * 60 * 60 * 1000
    SPOT_TTL_SECONDS = 30 * 60
    MAX_SPOTS_IN_MEMORY = 1000

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"DX Cluster Map v{__version__}")
        self.resize(1400, 850)

        # --- Stato ---
        self.provider = SpotholeProvider()
        self.sat_provider = SatelliteProvider()
        self.all_spots = []
        self.current_mode = None
        self.current_continent = None
        self._map_ready = False   # True quando la pagina Leaflet è pronta
        self.last_refresh_ts = None
        self._notified_ids = set()
        self.current_spot_detail = None
        self.distance_unit = "km"

        # Log ADIF per worked-before e avvisi sonori/vocali
        self.adif = AdifLog()
        self.adif_path = (QSettings().value("log/adif_path", "", type=str)
                          or default_adif_path())
        self.alert_sounds = AlertSounds(self)
        self.passes_dialog = None

        # Sorgente dati: "cluster" (Spothole), "wsjtx" (UDP locale) o "pskr"
        self.data_source = "cluster"
        self.wsjtx_listener = None
        self.wsjtx_last_status = {}
        self.pskr_provider = PSKReporterProvider(
            QSettings().value("user/pskr_receiver", "IZ0FIU", type=str))
        self.pskr_timer = QTimer(self)
        self.pskr_timer.setInterval(10 * 60 * 1000)  # ~1 query ogni 10 min (limite PSKR)
        self.pskr_timer.timeout.connect(self._on_pskr_timer)
        self._pskr_backoff_min = 0  # minuti extra prima del prossimo polling
        
        # Stato satelliti
        self.all_tles = []
        self.sat_checkboxes = {}
        self.selected_sats = set()

        # Stato locator
        self.user_lat = None
        self.user_lng = None
        self._last_applied_locator = ""
        self.locator_status_label = QLabel("")
        self.locator_status_label.setStyleSheet("color: #888; font-size: 11px;")

        # --- Banner di errore ---
        self.error_banner = QLabel()
        self.error_banner.setStyleSheet(
            "background-color: #dc3545; color: white; padding: 8px; "
            "font-weight: bold; border-radius: 4px;"
        )
        self.error_banner.setAlignment(Qt.AlignCenter)
        self.error_banner.hide()

        # --- Tray Icon ---
        self.tray_icon = QSystemTrayIcon(QIcon.fromTheme("utilities-system-monitor"), self)
        self.tray_icon.setToolTip("DX Cluster Map")
        self.tray_menu = QMenu()
        exit_action = QAction("Esci", self)
        exit_action.triggered.connect(QApplication.instance().quit)
        self.tray_menu.addAction(exit_action)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()

        # --- Mappa ---
        self.map = MapView()

        # --- Dock: Spot (sinistro) e Dettaglio (destro) ---
        self.dock_spot = QDockWidget("Spot", self)
        self.dock_spot.setObjectName("dockSpot")
        self.dock_spot.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.page_list = self._build_list_page()
        self.dock_spot.setWidget(self.page_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_spot)

        self.dock_detail = QDockWidget("Dettaglio stazione", self)
        self.dock_detail.setObjectName("dockDetail")
        self.dock_detail.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.page_detail = self._build_detail_page()
        self.dock_detail.setWidget(self.page_detail)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_detail)
        self.dock_detail.hide()

        # --- Layout principale: banner errori + barra filtri + mappa ---
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.error_banner)
        main_layout.addWidget(self._build_filter_bar())
        main_layout.addWidget(self.map, 1)

        self.setCentralWidget(main_widget)
        self._build_menus()
        self.setStatusBar(QStatusBar())
        self._build_statusbar()

        # --- Ripristino impostazioni e Connessioni ---
        self._restore_settings()
        self._connect_signals()

        # --- Timer ---
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.REFRESH_MS)

        self.second_timer = QTimer(self)
        self.second_timer.timeout.connect(self._update_status)
        self.second_timer.start(1000)

        self.alert_timer = QTimer(self)
        self.alert_timer.timeout.connect(self._check_alerts)
        self.alert_timer.start(self.ALERT_CHECK_MS)

        # Ricarica automatica del log ADIF quando il file cambia (WSJT-X lo
        # aggiorna a ogni QSO registrato).
        self.adif_timer = QTimer(self)
        self.adif_timer.timeout.connect(self._check_adif_changed)
        self.adif_timer.start(60_000)

        self.solar_timer = QTimer(self)
        self.solar_timer.timeout.connect(self._update_solar)
        self.solar_timer.start(self.SOLAR_REFRESH_MS)
        QTimer.singleShot(1000, self._update_solar)

        self.sat_timer = QTimer(self)
        self.sat_timer.timeout.connect(self._update_satellites)
        self.sat_timer.start(self.SATELLITE_REFRESH_MS)
        QTimer.singleShot(2000, self._update_satellites)

        self.map.loadFinished.connect(self._on_map_loaded)

    # ---------- Costruzione UI ----------
    def _build_list_page(self):
        """Contenuto del dock Spot: dashboard solare + lista spot."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)

        self.solar_dashboard = SolarDashboard()
        layout.addWidget(self.solar_dashboard)

        self.spot_list = SpotList()
        layout.addWidget(self.spot_list, 1)
        return page

    def _labeled_field(self, text, widget):
        """Campo con etichetta sopra il controllo: la barra si spiega da sola."""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        v.addWidget(label)
        v.addWidget(widget)
        return box

    def _build_filter_bar(self):
        """Barra di filtri rapida sopra la mappa, con etichette esplicite."""
        bar = QWidget()
        bar.setObjectName("filterBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 4, 8, 6)
        h.setSpacing(8)

        # Sorgente dati (41): Cluster, WSJT-X o PSK Reporter
        self.source_combo = QComboBox()
        self.source_combo.addItem("Cluster (Spothole)", userData="cluster")
        self.source_combo.addItem("WSJT-X (UDP locale)", userData="wsjtx")
        self.source_combo.addItem("PSK Reporter (ricezioni)", userData="pskr")
        self.source_combo.setMinimumWidth(170)
        self.source_combo.setToolTip(
            "Cluster: dati Spothole — WSJT-X: decodifiche via UDP locale — "
            "PSK Reporter: le tue ricezioni caricate da WSJT-X (richiede la spunta "
            "\"Abilita rilevamento PSK Reporter\" in WSJT-X)"
        )
        h.addWidget(self._labeled_field("Modalità operativa", self.source_combo))

        # Filtro Bande
        self.band_btn = QToolButton()
        self.band_btn.setText("Tutte")
        self.band_btn.setPopupMode(QToolButton.InstantPopup)
        self.band_btn.setToolTip("Bande da mostrare sulla mappa")
        self.band_menu = QMenu(self.band_btn)

        action_all = self.band_menu.addAction("Seleziona tutte")
        action_all.triggered.connect(self._select_all_bands)
        action_none = self.band_menu.addAction("Deseleziona tutte")
        action_none.triggered.connect(self._select_no_bands)
        self.band_menu.addSeparator()

        widget_cb = QWidget()
        layout_cb = QVBoxLayout(widget_cb)
        layout_cb.setContentsMargins(5, 5, 5, 5)
        layout_cb.setSpacing(2)

        self.band_checkboxes = {}
        for name, _low, _high in BANDS:
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_band_selection_changed)
            layout_cb.addWidget(cb)
            self.band_checkboxes[name] = cb

        widget_action = QWidgetAction(self.band_menu)
        widget_action.setDefaultWidget(widget_cb)
        self.band_menu.addAction(widget_action)
        self.band_btn.setMenu(self.band_menu)
        h.addWidget(self._labeled_field("Bande", self.band_btn))

        # Menu Satelliti (inizialmente vuoto, si popola dopo il fetch)
        self.sat_btn = QToolButton()
        self.sat_btn.setText("Nessuno")
        self.sat_btn.setPopupMode(QToolButton.InstantPopup)
        self.sat_btn.setToolTip("Satelliti da mostrare sulla mappa")
        self.sat_menu = QMenu(self.sat_btn)
        self.sat_btn.setMenu(self.sat_menu)
        h.addWidget(self._labeled_field("Satelliti", self.sat_btn))

        # Filtro Modo
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Tutti", userData=None)
        self.mode_combo.addItem("CW", userData="CW")
        self.mode_combo.addItem("Fonia", userData="PHONE")
        self.mode_combo.addItem("Digitale", userData="DIGITAL")
        self.mode_combo.setMinimumWidth(110)
        h.addWidget(self._labeled_field("Modi", self.mode_combo))

        # Filtro Continente
        self.cont_combo = QComboBox()
        for label, code in CONTINENTS:
            self.cont_combo.addItem(label, userData=code)
        self.cont_combo.setMinimumWidth(130)
        h.addWidget(self._labeled_field("Spot da", self.cont_combo))

        # Target locator (16): analisi della rotta
        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText("es. KM04")
        self.target_edit.setMaxLength(6)
        self.target_edit.setFixedWidth(110)
        self.target_edit.setToolTip("Locator di destinazione per l'analisi della rotta")
        self.target_info = QLabel("")
        self.target_info.setStyleSheet("color: #888; font-size: 11px;")
        self.target_info.setWordWrap(False)
        tgt_box = QWidget()
        tgt_h = QHBoxLayout(tgt_box)
        tgt_h.setContentsMargins(0, 0, 0, 0)
        tgt_h.setSpacing(6)
        tgt_h.addWidget(self.target_edit)
        tgt_h.addWidget(self.target_info)
        h.addWidget(self._labeled_field("Rotta verso", tgt_box))

        # Alert
        self.alert_edit = QLineEdit()
        self.alert_edit.setPlaceholderText("nominativi, separati da virgola")
        self.alert_edit.setFixedWidth(190)
        self.alert_edit.setToolTip("Evidenzia ed avvisa per questi nominativi (Ctrl+F)")
        h.addWidget(self._labeled_field("Avvisi", self.alert_edit))

        h.addStretch(1)
        self.source_status_label = QLabel("")
        self.source_status_label.setStyleSheet("color: #888; font-size: 11px;")
        h.addWidget(self.source_status_label)
        self._build_settings_dialog()
        return bar

    def _build_settings_dialog(self):
        """Dialogo ⚙ Impostazioni: stazione, log ADIF, avvisi, sorgenti."""
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("Impostazioni")
        form = QFormLayout(self.settings_dialog)

        form.addRow(QLabel("Stazione"))
        self.locator_edit = QLineEdit()
        self.locator_edit.setPlaceholderText("es. JN45")
        self.locator_edit.setMaxLength(6)
        form.addRow("Locator:", self.locator_edit)
        form.addRow(self.locator_status_label)

        self.callsign_edit = QLineEdit()
        self.callsign_edit.setMaxLength(16)
        self.callsign_edit.setPlaceholderText("es. IZ0FIU")
        self.callsign_edit.setToolTip(
            "Il tuo nominativo: serve a riconoscere le stazioni che ti chiamano "
            "e a personalizzare gli avvisi vocali")
        form.addRow("Nominativo:", self.callsign_edit)

        self.unit_combo = QComboBox()
        self.unit_combo.addItem("km", userData="km")
        self.unit_combo.addItem("miglia", userData="mi")
        form.addRow("Unità distanza:", self.unit_combo)

        form.addRow(QLabel("Log ADIF (worked-before)"))
        adif_row = QWidget()
        adif_layout = QHBoxLayout(adif_row)
        adif_layout.setContentsMargins(0, 0, 0, 0)
        self.adif_path_edit = QLineEdit()
        self.adif_path_edit.setPlaceholderText("es. ~/.local/share/WSJT-X/wsjtx_log.adi")
        self.adif_path_edit.setToolTip(
            "Log ADIF di WSJT-X: gli spot già a log vengono marcati B4 e i "
            "nuovi DXCC/bande sono evidenziati")
        adif_layout.addWidget(self.adif_path_edit, 1)
        self.adif_browse_btn = QPushButton("Sfoglia…")
        self.adif_browse_btn.clicked.connect(self._browse_adif)
        adif_layout.addWidget(self.adif_browse_btn)
        form.addRow("File ADIF:", adif_row)

        self.adif_status_label = QLabel("")
        self.adif_status_label.setStyleSheet("color: #8d9099; font-size: 11px;")
        self.adif_status_label.setWordWrap(True)
        form.addRow(self.adif_status_label)

        form.addRow(QLabel("Avvisi"))
        self.sound_cb = QCheckBox("Segnale sonoro")
        self.voice_cb = QCheckBox("Voce (sintesi vocale)")
        form.addRow(self.sound_cb)
        form.addRow(self.voice_cb)

        audio_row = QWidget()
        audio_layout = QHBoxLayout(audio_row)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.addWidget(QLabel("Volume:"))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setToolTip("Volume degli avvisi sonori")
        audio_layout.addWidget(self.volume_slider, 1)
        self.audio_test_btn = QPushButton("Prova")
        self.audio_test_btn.clicked.connect(self._test_audio)
        audio_layout.addWidget(self.audio_test_btn)
        form.addRow(audio_row)

        form.addRow(QLabel("Sorgenti"))
        self.pskr_edit = QLineEdit()
        self.pskr_edit.setMaxLength(16)
        self.pskr_edit.setText(QSettings().value("user/pskr_receiver", "IZ0FIU", type=str))
        self.pskr_edit.setToolTip(
            "Nominativo ricevitore per la sorgente \"PSK Reporter\":\n"
            "le ricezioni caricate da WSJT-X con questa spunta attiva"
        )
        form.addRow("Nominativo PSK Reporter:", self.pskr_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(QSettings().value("source/wsjtx_port", 2237, type=int))
        self.port_spin.setToolTip(
            "Porta UDP su cui l'app riceve le decodifiche di WSJT-X\n"
            "(Settings > Reporting > UDP Server di WSJT-X)"
        )
        form.addRow("Porta UDP WSJT-X:", self.port_spin)

        self.relay_edit = QLineEdit()
        self.relay_edit.setPlaceholderText("127.0.0.1:2238")
        self.relay_edit.setToolTip(
            "Inoltra a questi destinatari ogni datagramma ricevuto da WSJT-X,\n"
            "inalterato (host:porta, separati da virgola).\n"
            "Serve quando WSJT-X invia all'app ma un altro programma\n"
            "(es. WavelogGate) deve continuare a ricevere gli stessi dati:\n"
            "quel programma va però spostato su una porta diversa."
        )
        self.relay_edit.setText(QSettings().value("source/relay_targets", "", type=str))
        form.addRow("Inoltra a:", self.relay_edit)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._apply_settings)
        btns.rejected.connect(self._cancel_settings)
        form.addRow(btns)

    def _build_menus(self):
        mb = self.menuBar()

        # File
        m_file = mb.addMenu("&File")
        act_stats = QAction("📊 Statistiche", self)
        act_stats.triggered.connect(self._show_statistics)
        m_file.addAction(act_stats)
        act_reload_adif = QAction("🔄 Ricarica log ADIF", self)
        act_reload_adif.setShortcut(QKeySequence("F9"))
        act_reload_adif.triggered.connect(lambda: self._load_adif(notify=True))
        m_file.addAction(act_reload_adif)
        m_file.addSeparator()
        act_quit = QAction("Esci", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(QApplication.instance().quit)
        m_file.addAction(act_quit)

        # Vista
        m_view = mb.addMenu("&Vista")
        self.theme_cb = QCheckBox("Tema scuro")
        self.legend_cb = QCheckBox("Legenda sulla mappa")
        self.heat_cb = QCheckBox("Heatmap")
        self.heat_cb.setToolTip("Densità di spot per quadrato griglia (26)")
        self.grayline_cb = QCheckBox("Grayline")
        self.grayline_cb.setChecked(True)
        for cb in (self.theme_cb, self.legend_cb, self.heat_cb, self.grayline_cb):
            self._add_menu_widget(m_view, cb)
        m_view.addSeparator()
        act_fullmap = QAction("Solo mappa (F11)", self)
        act_fullmap.triggered.connect(self._toggle_full_map)
        m_view.addAction(act_fullmap)

        # Filtri
        m_filters = mb.addMenu("&Filtri")
        self.new_spots_cb = QCheckBox("Solo spot nuovi")
        self._add_menu_widget(m_filters, self.new_spots_cb)
        age_widget = QWidget()
        ah = QHBoxLayout(age_widget)
        ah.setContentsMargins(8, 2, 8, 2)
        ah.addWidget(QLabel("Età max \u00abnuovi\u00bb:"))
        # Slider età massima spot (10): da 1 a 30 minuti
        self.age_slider = QSlider(Qt.Horizontal)
        self.age_slider.setRange(1, 30)
        self.age_slider.setValue(5)
        self.age_slider.setToolTip("Età massima degli spot \"nuovi\" (minuti)")
        ah.addWidget(self.age_slider, 1)
        self.age_label = QLabel("5m")
        ah.addWidget(self.age_label)
        self._add_menu_widget(m_filters, age_widget)
        m_filters.addSeparator()
        act_alerts = QAction("🔔 Modifica alert… (Ctrl+F)", self)
        act_alerts.triggered.connect(self._focus_alert_edit)
        m_filters.addAction(act_alerts)
        m_filters.addSeparator()
        self.sound_action = QAction("🔔 Avvisi sonori", self)
        self.sound_action.setCheckable(True)
        self.sound_action.toggled.connect(self._on_sound_action_toggled)
        m_filters.addAction(self.sound_action)
        self.voice_action = QAction("🗣 Voce negli avvisi", self)
        self.voice_action.setCheckable(True)
        self.voice_action.toggled.connect(self._on_voice_action_toggled)
        m_filters.addAction(self.voice_action)

        # Satelliti
        m_sat = mb.addMenu("🛰 &Satelliti")
        act_sat_all = QAction("Seleziona tutti", self)
        act_sat_all.triggered.connect(self._select_all_sats)
        act_sat_none = QAction("Deseleziona tutti", self)
        act_sat_none.triggered.connect(self._select_no_sats)
        m_sat.addAction(act_sat_all)
        m_sat.addAction(act_sat_none)
        m_sat.addSeparator()
        act_sat_pick = QAction("Cerca e seleziona…", self)
        act_sat_pick.triggered.connect(self._open_sat_menu)
        m_sat.addAction(act_sat_pick)
        m_sat.addSeparator()
        act_sat_passes = QAction("📈 Passaggi e polar plot…", self)
        act_sat_passes.setShortcut(QKeySequence("F10"))
        act_sat_passes.triggered.connect(self._open_passes_dialog)
        m_sat.addAction(act_sat_passes)

        # Impostazioni
        m_settings = mb.addMenu("&Impostazioni")
        act_settings = QAction("⚙ Apri impostazioni…", self)
        act_settings.triggered.connect(self._open_settings)
        m_settings.addAction(act_settings)

        # Aiuto
        m_help = mb.addMenu("&Aiuto")
        act_about = QAction("Informazioni", self)
        act_about.triggered.connect(self._show_about)
        m_help.addAction(act_about)

    def _add_menu_widget(self, menu, widget):
        """Inserisce un widget (checkbox, slider…) dentro un menu."""
        action = QWidgetAction(menu)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def _open_sat_menu(self):
        self.sat_btn.showMenu()

    def _build_statusbar(self):
        self.status_adif = QLabel("Log ADIF: —")
        self.status_adif.setStyleSheet("color: #8d9099;")
        self.status_adif.setToolTip("QSO caricati dal log ADIF per il worked-before")
        self.statusBar().addPermanentWidget(self.status_adif)
        self.status_relay = QLabel("")
        self.status_relay.setStyleSheet("color: #888;")
        self.statusBar().addPermanentWidget(self.status_relay)
        self.status_utc = QLabel("")
        self.status_utc.setStyleSheet("color: #4fc3f7; font-weight: bold;")
        self.statusBar().addPermanentWidget(self.status_utc)
        relay = QSettings().value("source/relay_targets", "", type=str)
        if relay:
            self.status_relay.setText(f"Ponte → {relay}")

    def _show_about(self):
        QMessageBox.about(
            self, "Informazioni",
            f"<b>DX Cluster Map</b> v{__version__}<br>"
            "Spot radioamatoriali su mappa.<br>"
            "Sorgenti: Spothole, WSJT-X (UDP), PSK Reporter.<br>"
            "Satelliti: elementi orbitali CelesTrak (aggiornati ogni 6 h).<br>"
            "<small>IZ0FIU — <a href='https://github.com/IZ0FIU/dxcluster-map'>"
            "github.com/IZ0FIU/dxcluster-map</a></small>")

    def _build_detail_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.lbl_dx_call = QLabel("—")
        font = QFont()
        font.setPointSize(18)
        font.setBold(True)
        font.setFamily("Monospace")
        self.lbl_dx_call.setFont(font)
        form.addRow("Stazione DX:", self.lbl_dx_call)

        self.lbl_country = QLabel("—")
        form.addRow("Nazione:", self.lbl_country)

        self.lbl_freq = QLabel("—")
        form.addRow("Frequenza:", self.lbl_freq)

        self.lbl_mode = QLabel("—")
        form.addRow("Modo:", self.lbl_mode)

        self.lbl_log = QLabel("—")
        self.lbl_log.setStyleSheet("font-weight: bold;")
        form.addRow("Log ADIF:", self.lbl_log)

        self.lbl_spotter = QLabel("—")
        form.addRow("Spotter:", self.lbl_spotter)

        self.lbl_time = QLabel("—")
        form.addRow("Ora (UTC):", self.lbl_time)

        self.lbl_distance = QLabel("—")
        self.lbl_distance.setStyleSheet("color: #0a5; font-weight: bold;")
        form.addRow("Distanza:", self.lbl_distance)

        self.lbl_comment = QLabel("—")
        self.lbl_comment.setWordWrap(True)
        form.addRow("Commento:", self.lbl_comment)

        layout.addLayout(form)
        layout.addSpacing(20)

        self.btn_qrz = QPushButton("Cerca su QRZ.com")
        self.btn_qrz.setStyleSheet(
            "padding: 8px; background-color: #ffb02e; color: #111; "
            "font-weight: bold; border: none; border-radius: 6px;")
        self.btn_qrz.clicked.connect(self._open_qrz)
        layout.addWidget(self.btn_qrz)

        # Condivisione spot (23)
        self.btn_copy = QPushButton("📋 Copia info spot")
        self.btn_copy.setToolTip("Copia le informazioni dello spot negli appunti (23)")
        self.btn_copy.clicked.connect(self._copy_spot_info)
        layout.addWidget(self.btn_copy)

        layout.addStretch(1)
        return page



    # ---------- Logica Filtro Bande ----------
    def _get_selected_bands(self):
        return [name for name, cb in self.band_checkboxes.items() if cb.isChecked()]

    def _select_all_bands(self):
        for cb in self.band_checkboxes.values():
            cb.setChecked(True)

    def _select_no_bands(self):
        for cb in self.band_checkboxes.values():
            cb.setChecked(False)

    def _on_band_selection_changed(self):
        selected = self._get_selected_bands()
        
        if len(selected) == len(BANDS):
            self.band_btn.setText("Tutte")
        elif len(selected) == 0:
            self.band_btn.setText("Nessuna")
        elif len(selected) <= 2:
            self.band_btn.setText(", ".join(selected))
        else:
            self.band_btn.setText(f"{len(selected)} bande")
        
        QSettings().setValue("filters/bands", selected)
        QSettings().remove("filters/band")
        self._apply_filter()

    # ---------- Logica Satelliti ----------
    def _populate_sat_menu(self, tles):
        self.sat_menu.clear()
        self.sat_checkboxes.clear()

        saved_sats = QSettings().value("filters/satellites", ["ISS (ZARYA)", "SO-50"], type=list)
        # QSettings può restituire una stringa singola ("ISS (ZARYA)") invece
        # di una lista: normalizziamo, altrimenti nessuna spunta viene salvata.
        if isinstance(saved_sats, str):
            saved_sats = [saved_sats]
        saved_sats = {str(x) for x in (saved_sats or [])}
        if not saved_sats:
            # Chiave @Invalid() (lista vuota salvata in passato): QSettings
            # restituisce [] ignorando il default → usa ISS come default.
            saved_sats = {"ISS (ZARYA)"}
            QSettings().setValue("filters/satellites", sorted(saved_sats))

        # Ordine alfabetico per facilitare la ricerca
        tles = sorted(tles, key=lambda t: t.name.lower())

        action_all = self.sat_menu.addAction("Seleziona tutti")
        action_all.triggered.connect(self._select_all_sats)
        action_none = self.sat_menu.addAction("Deseleziona tutte")
        action_none.triggered.connect(self._select_no_sats)
        self.sat_menu.addSeparator()

        # Campo di ricerca per nome
        self.sat_filter_edit = QLineEdit()
        self.sat_filter_edit.setPlaceholderText("cerca satellite…")
        self.sat_filter_edit.setClearButtonEnabled(True)
        filter_action = QWidgetAction(self.sat_menu)
        filter_action.setDefaultWidget(self.sat_filter_edit)
        self.sat_menu.addAction(filter_action)

        # Elenco scorrevole dei satelliti
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(5, 5, 5, 5)
        v.setSpacing(2)
        self.sat_checkboxes = {}
        for tle in tles:
            cb = QCheckBox(tle.name)
            cb.blockSignals(True)   # evita 96 chiamate a update durante il popolamento
            cb.setChecked(tle.name in saved_sats)
            cb.blockSignals(False)
            cb.stateChanged.connect(self._on_sat_selection_changed)
            v.addWidget(cb)
            self.sat_checkboxes[tle.name] = cb
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(container)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(420)
        scroll.setFrameShape(QFrame.NoFrame)

        self.sat_filter_edit.textChanged.connect(self._filter_sat_menu)

        widget_action = QWidgetAction(self.sat_menu)
        widget_action.setDefaultWidget(scroll)
        self.sat_menu.addAction(widget_action)

        self._on_sat_selection_changed()

    def _filter_sat_menu(self, text):
        """Nasconde i satelliti che non corrispondono al testo cercato."""
        text = text.strip().lower()
        for name, cb in self.sat_checkboxes.items():
            cb.setVisible(text in name.lower())

    def _get_selected_sats(self):
        return {name for name, cb in self.sat_checkboxes.items() if cb.isChecked()}

    def _select_all_sats(self):
        for cb in self.sat_checkboxes.values():
            cb.setChecked(True)

    def _select_no_sats(self):
        for cb in self.sat_checkboxes.values():
            cb.setChecked(False)

    def _on_sat_selection_changed(self):
        selected = self._get_selected_sats()
        self.selected_sats = selected
        
        if len(selected) == 0:
            self.sat_btn.setText("Nessuno")
        elif len(selected) == len(self.sat_checkboxes) and len(selected) > 0:
            self.sat_btn.setText("Tutti")
        elif len(selected) <= 2:
            self.sat_btn.setText(", ".join(selected))
        else:
            self.sat_btn.setText(f"{len(selected)} satelliti")
            
        # Non salvare liste vuote: QSettings le scrive come @Invalid() e alla
        # lettura successiva restituisce None/[] ignorando il default.
        if selected:
            QSettings().setValue("filters/satellites", sorted(selected))
        self.map.update_satellites(self.all_tles, self.selected_sats)

    def _update_satellites(self):
        tles = self.sat_provider.fetch_tles()
        if tles:
            self.all_tles = tles
            if not self.sat_checkboxes:
                self._populate_sat_menu(tles)
            elif getattr(self, "_map_ready", False):
                # Aggiorna la mappa solo se la pagina è pronta, altrimenti
                # la chiamata JS andrebbe persa (la ripeterà _on_map_loaded)
                self.map.update_satellites(self.all_tles, self.selected_sats)

    # ---------- Logica Master-Detail ----------
    def _show_spot_details(self, spot):
        self.current_spot_detail = spot
        self.lbl_dx_call.setText(spot.dx_call)
        self.lbl_country.setText(spot.country or "Sconosciuta")
        self.lbl_freq.setText(f"{spot.freq_khz:.1f} kHz ({spot.band})")
        self.lbl_mode.setText(spot.mode)

        status = self.adif.status_for(
            spot.dx_call, spot.band, getattr(spot, "country", None))
        log_labels = {
            NEW_COUNTRY: ("NUOVO — entità mai lavorata", "#ffb02e"),
            NEW_BAND: ("NUOVA BANDA", "#5fd38d"),
            NEW_CALL: ("nuovo nominativo", "#6aa9ff"),
            WORKED: ("già a log (B4)", "#777a82"),
        }
        log_text, log_color = log_labels.get(status, ("—", "#8d9099"))
        self.lbl_log.setText(log_text)
        self.lbl_log.setStyleSheet(f"color: {log_color}; font-weight: bold;")
        spotter_text = spot.spotter or "—"
        spotter_country = getattr(spot, "spotter_country", None)
        if spotter_country:
            flag = getattr(spot, "spotter_flag", None) or ""
            spotter_text = f"{flag} {spotter_text}\n{spotter_country}".strip()
        self.lbl_spotter.setText(spotter_text)
        self.lbl_time.setText(spot.timestamp.strftime("%H:%M UTC"))
        
        if self.user_lat is not None and spot.has_coords:
            dist = haversine_km(self.user_lat, self.user_lng, spot.lat, spot.lng)
            az = initial_bearing(self.user_lat, self.user_lng, spot.lat, spot.lng)
            
            if self.distance_unit == "mi":
                dist = dist * 0.621371
                unit_str = "mi"
            else:
                unit_str = "km"
                
            self.lbl_distance.setText(f"{dist:.0f} {unit_str} — az {az:.0f}°")
        else:
            self.lbl_distance.setText("Locator non impostato")

        self.lbl_comment.setTextFormat(Qt.PlainText)
        self.lbl_comment.setText((spot.comment or "Nessun commento")[:200])
        self.dock_detail.show()
        self.dock_detail.raise_()

    def _back_to_list(self):
        self.dock_detail.hide()
        self.dock_spot.show()
        self.dock_spot.raise_()

    def _open_qrz(self):
        if not self.current_spot_detail:
            return
        call = (self.current_spot_detail.dx_call or "").strip().upper()
        # Sicurezza (3): i nominativi arrivano da una API esterna; apriamo QRZ
        # solo se il nominativo è plausibile, per non costruire URL arbitrari.
        if valid_call(call):
            QDesktopServices.openUrl(QUrl(f"https://www.qrz.com/db/{call}"))
        else:
            self.statusBar().showMessage(f"Nominativo non valido, link QRZ bloccato: {call!r}", 5000)

    # ---------- Ripristino e Connessioni ----------
    def _restore_settings(self):
        settings = QSettings()
        
        old_band = settings.value("filters/band", "", type=str)
        saved_bands = settings.value("filters/bands", None)
        
        if saved_bands is not None:
            if isinstance(saved_bands, str):
                saved_bands = [saved_bands]
        elif old_band:
            saved_bands = [old_band]
        else:
            saved_bands = [name for name, _, _ in BANDS]
            
        for name, cb in self.band_checkboxes.items():
            cb.blockSignals(True)
            cb.setChecked(name in saved_bands)
            cb.blockSignals(False)
        self._on_band_selection_changed()
            
        saved_mode = settings.value("filters/mode", "", type=str)
        if saved_mode:
            idx = self.mode_combo.findData(saved_mode)
            if idx >= 0: self.mode_combo.setCurrentIndex(idx)
            self.current_mode = saved_mode
            
        saved_continent = settings.value("filters/continent", "", type=str)
        if saved_continent:
            idx = self.cont_combo.findData(saved_continent)
            if idx >= 0: self.cont_combo.setCurrentIndex(idx)
            self.current_continent = saved_continent
            
        saved_locator = settings.value("user/locator", "", type=str)
        if saved_locator:
            self.locator_edit.setText(saved_locator)
            self._last_applied_locator = saved_locator.upper()
            try:
                self.user_lat, self.user_lng = maidenhead_to_latlon(saved_locator)
                self.locator_status_label.setText(f"Locator: {saved_locator.upper()}")
            except ValueError: pass
            
        saved_alerts = settings.value("alerts/list", "", type=str)
        if saved_alerts:
            self.alert_edit.setText(saved_alerts)

        saved_call = settings.value("user/callsign", "", type=str)
        self.callsign_edit.setText(saved_call)

        saved_adif = settings.value("log/adif_path", "", type=str)
        if saved_adif:
            self.adif_path = saved_adif
        self.adif_path_edit.setText(self.adif_path)

        sound_on = settings.value("alerts/sound_enabled", True, type=bool)
        voice_on = settings.value("alerts/voice_enabled", True, type=bool)
        volume = settings.value("alerts/volume", 70, type=int)
        self.sound_cb.setChecked(sound_on)
        self.voice_cb.setChecked(voice_on)
        self.volume_slider.setValue(max(0, min(100, volume)))
        self.alert_sounds.set_volume(max(0, min(100, volume)) / 100.0)
        self.sound_action.setChecked(sound_on)
        self.voice_action.setChecked(voice_on)
            
        saved_theme = settings.value("ui/dark_theme", False, type=bool)
        self.theme_cb.setChecked(saved_theme)
        self._apply_theme(saved_theme)

        saved_new_spots = settings.value("filters/new_spots", False, type=bool)
        self.new_spots_cb.setChecked(saved_new_spots)

        saved_minutes = settings.value("filters/new_minutes", 5, type=int)
        self.age_slider.blockSignals(True)
        self.age_slider.setValue(max(1, min(30, saved_minutes)))
        self.age_slider.blockSignals(False)
        self.age_label.setText(f"{self.age_slider.value()}m")

        saved_legend = settings.value("ui/map_legend", False, type=bool)
        self.legend_cb.setChecked(saved_legend)

        saved_heat = settings.value("ui/heatmap", False, type=bool)
        self.heat_cb.setChecked(saved_heat)

        # Geometria finestra e dock (14)
        geo = settings.value("ui/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        state = settings.value("ui/dock_state")
        if state is not None:
            self.restoreState(state)
        
        saved_unit = settings.value("ui/distance_unit", "km", type=str)
        idx = self.unit_combo.findData(saved_unit)
        if idx >= 0: self.unit_combo.setCurrentIndex(idx)
        self.distance_unit = saved_unit
        self.map.set_distance_unit(self.distance_unit)

        # Sorgente dati salvata (41): cluster o wsjtx
        saved_source = settings.value("source/data_source", "cluster", type=str)
        idx = self.source_combo.findData(saved_source)
        if idx >= 0: self.source_combo.setCurrentIndex(idx)
        self.data_source = self.source_combo.currentData() or "cluster"
        self._activate_source(self.data_source)

        # Log ADIF per worked-before (se configurato o trovato automaticamente)
        self._load_adif()

    def _connect_signals(self):
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.cont_combo.currentIndexChanged.connect(self._on_continent_changed)
        self.locator_edit.editingFinished.connect(self._on_locator_changed)
        self.alert_edit.editingFinished.connect(self._on_alerts_changed)
        self.grayline_cb.toggled.connect(self.map.toggle_grayline)
        self.theme_cb.toggled.connect(self._on_theme_toggled)
        self.new_spots_cb.toggled.connect(self._on_new_spots_toggled)
        self.age_slider.valueChanged.connect(self._on_age_changed)
        self.legend_cb.toggled.connect(self._on_legend_toggled)
        self.heat_cb.toggled.connect(self._on_heat_toggled)
        self.target_edit.editingFinished.connect(self._on_target_changed)
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        self.port_spin.valueChanged.connect(self._on_wsjtx_port_changed)
        self.spot_list.spot_selected.connect(self._on_spot_selected)
        self.sound_cb.toggled.connect(self._on_sound_toggled)
        self.voice_cb.toggled.connect(self._on_voice_toggled)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.adif_path_edit.editingFinished.connect(self._on_adif_path_changed)

        # --- Scorciatoie (15) ---
        QShortcut(QKeySequence("F5"), self, activated=self.refresh)
        QShortcut(QKeySequence("Escape"), self, activated=self._on_escape)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_alert_edit)
        QShortcut(QKeySequence("F11"), self, activated=self._toggle_full_map)

    # ---------- Eventi ----------
    def _update_solar(self):
        self.solar_dashboard.refresh()

    def _show_error(self, message):
        self.error_banner.setText(f"⚠️ {message}")
        self.error_banner.show()

    def _hide_error(self):
        self.error_banner.hide()

    def _on_theme_toggled(self, checked):
        QSettings().setValue("ui/dark_theme", checked)
        self._apply_theme(checked)
        
    def _on_unit_changed(self, _index):
        self.distance_unit = self.unit_combo.currentData()
        QSettings().setValue("ui/distance_unit", self.distance_unit)
        self.map.set_distance_unit(self.distance_unit)
        if self.current_spot_detail:
            self._show_spot_details(self.current_spot_detail)

    def _on_new_spots_toggled(self, checked):
        QSettings().setValue("filters/new_spots", checked)
        self._apply_filter()

    def _on_age_changed(self, value):
        self.age_label.setText(f"{value}m")
        QSettings().setValue("filters/new_minutes", value)
        self._apply_filter()

    # --- Mappa a schermo intero (8): nasconde i dock ---
    def _toggle_full_map(self):
        docks_visible = self.dock_spot.isVisible() or self.dock_detail.isVisible()
        if docks_visible:
            self.dock_spot.hide()
            self.dock_detail.hide()
        else:
            self.dock_spot.show()
        self.map.setFocus()

    def _on_escape(self):
        if self.dock_detail.isVisible():
            self._back_to_list()
        elif not (self.dock_spot.isVisible() or self.dock_detail.isVisible()):
            self._toggle_full_map()

    def _focus_alert_edit(self):
        self.dock_spot.show()
        self.alert_edit.setFocus()
        self.alert_edit.selectAll()

    # ---------- Copia info spot (23) ----------
    def _copy_spot_info(self):
        s = self.current_spot_detail
        if not s:
            return
        lines = [
            f"DX: {s.dx_call} — {s.freq_khz:.1f} kHz ({s.band}, {s.mode})",
            f"Spotter: {s.spotter}",
            f"Ora: {s.timestamp:%d/%m/%Y %H:%M} UTC",
        ]
        if s.country:
            lines.append(f"Nazione: {s.country}")
        if self.user_lat is not None and s.has_coords:
            dist = haversine_km(self.user_lat, self.user_lng, s.lat, s.lng)
            az = initial_bearing(self.user_lat, self.user_lng, s.lat, s.lng)
            if self.distance_unit == "mi":
                dist *= 0.621371
            lines.append(f"Distanza: {dist:.0f} — az {az:.0f}°")
        if s.comment:
            lines.append(f"Commento: {s.comment[:120]}")
        if valid_call((s.dx_call or "").strip().upper()):
            lines.append(f"QRZ: https://www.qrz.com/db/{s.dx_call.strip().upper()}")
        QApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage("Informazioni spot copiate negli appunti", 3000)

    # ---------- Statistiche (19) ----------
    def _show_statistics(self):
        from collections import Counter

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.SPOT_TTL_SECONDS)
        spots = [s for s in self.all_spots if s.timestamp >= cutoff]

        by_band = Counter(s.band for s in spots)
        by_spotter = Counter(s.spotter.upper() for s in spots if s.spotter)
        by_country = Counter(s.country for s in spots if s.country)
        by_mode = Counter(s.mode_category for s in spots)

        lines = [f"Spot in memoria (ultimi {self.SPOT_TTL_SECONDS // 60} minuti): {len(spots)}", ""]

        lines.append("— Per banda —")
        for band, n in sorted(by_band.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {band}: {n}")
        lines.append("")
        lines.append("— Per modo —")
        for mode, n in sorted(by_mode.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {mode}: {n}")
        lines.append("")
        lines.append("— Top 5 spotter —")
        for name, n in by_spotter.most_common(5):
            lines.append(f"  {name}: {n} spot")
        lines.append("")
        lines.append("— Top 5 nazioni DX —")
        for name, n in by_country.most_common(5):
            lines.append(f"  {name}: {n} spot")

        if self.adif.loaded:
            lines.append("")
            lines.append("— Log ADIF (worked-before) —")
            lines.append(f"  {self.adif.total_qsos} QSO nel log")
            lines.append(f"  {len(self.adif.worked_countries)} entità DXCC lavorate")
            lines.append(f"  {len(self.adif.worked_calls)} nominativi diversi")
            if self.adif.path:
                lines.append(f"  File: {self.adif.path}")

        dlg = QDialog(self)
        dlg.setWindowTitle("Statistiche sessione")
        lay = QVBoxLayout(dlg)
        text = QTextEdit()
        text.setPlainText("\n".join(lines))
        text.setReadOnly(True)
        lay.addWidget(text)
        dlg.resize(360, 480)
        dlg.show()

    def _on_legend_toggled(self, checked):
        QSettings().setValue("ui/map_legend", checked)
        self.map.toggle_legend(checked)

    def _on_heat_toggled(self, checked):
        QSettings().setValue("ui/heatmap", checked)
        self.map.toggle_heat(checked)
        self._apply_filter()

    def _update_heat(self, filtered):
        """Heatmap per quadrato griglia (26): un punto per centro del quadrato
        4 caratteri di ogni spot. Peso minimo 0.5: sotto 0.2 il layer non
        visualizza quasi nulla, quindi partiamo da una base visibile."""
        counts = {}
        for s in filtered:
            if not s.has_coords:
                continue
            key = maidenhead_square_center(s.lat, s.lng)
            counts[key] = counts.get(key, 0) + 1
        points = [[c[0], c[1], min(0.5 + 0.1 * v, 1.0)] for c, v in counts.items()]
        self.map.update_heat(points)

    def _apply_theme(self, is_dark):
        app = QApplication.instance()
        if is_dark:
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor(53, 53, 53))
            palette.setColor(QPalette.WindowText, Qt.white)
            palette.setColor(QPalette.Base, QColor(25, 25, 25))
            palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
            palette.setColor(QPalette.ToolTipBase, Qt.black)
            palette.setColor(QPalette.ToolTipText, Qt.white)
            palette.setColor(QPalette.Text, Qt.white)
            palette.setColor(QPalette.Button, QColor(53, 53, 53))
            palette.setColor(QPalette.ButtonText, Qt.white)
            palette.setColor(QPalette.BrightText, Qt.red)
            palette.setColor(QPalette.Link, QColor(42, 130, 218))
            palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
            palette.setColor(QPalette.HighlightedText, Qt.black)
            app.setPalette(palette)
            # Tema scuro "dashboard": antracite + accento ambra (9)
            app.setStyleSheet("""
                QMainWindow, QDialog, QWidget { color: #e8e8ea; background: #1e1f24; }
                QLineEdit, QComboBox QAbstractItemView {
                    background: #26272d; color: #e8e8ea;
                    border: 1px solid #45474d; border-radius: 6px; padding: 3px 6px;
                    selection-background-color: #ffb02e; selection-color: #111;
                }
                QComboBox { background: #2b2d33; color: #e8e8ea;
                            border: 1px solid #45474d; border-radius: 6px; padding: 3px 8px; }
                QComboBox::drop-down { border: none; width: 20px; }
                QComboBox QAbstractItemView {
                    background: #26272d; border: 1px solid #45474d;
                    selection-background-color: #ffb02e; selection-color: #111;
                }
                QTableWidget {
                    background: #26272d; alternate-background-color: #2b2d33;
                    color: #d6d7db; gridline-color: #2e3036; border: none;
                }
                QTableWidget::item:selected { background: rgba(255,176,46,0.20); color: #fff; }
                QHeaderView::section {
                    background: #232529; color: #9a9ca3; border: none;
                    padding: 4px 6px; font-size: 10px; letter-spacing: 0.5px;
                }
                QMenu { background: #26272d; color: #e8e8ea; border: 1px solid #45474d; }
                QMenu::item:selected { background: #ffb02e; color: #111; }
                QMenu::separator { height: 1px; background: #3a3c42; margin: 3px 6px; }
                QMenuBar { background: #20222a; color: #c9cace; }
                QMenuBar::item:selected { background: #33363f; border-radius: 4px; }
                QStatusBar { background: #191b20; color: #9a9ca3; }
                QDockWidget { color: #9a9ca3; font-size: 11px; }
                QDockWidget::title {
                    background: #2b2d33; padding: 5px 10px;
                    border-bottom: 1px solid #34363c; text-transform: uppercase;
                }
                QToolButton {
                    background: #2b2d33; color: #e8e8ea; border: 1px solid #45474d;
                    border-radius: 6px; padding: 4px 10px;
                }
                QToolButton:hover { border-color: #ffb02e; }
                QPushButton {
                    background: #2b2d33; color: #e8e8ea; border: 1px solid #45474d;
                    border-radius: 6px; padding: 5px 12px;
                }
                QPushButton:hover { border-color: #ffb02e; }
                QScrollBar:vertical, QScrollBar:horizontal {
                    background: #232529; width: 10px; height: 10px; border: none;
                }
                QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                    background: #45474d; border-radius: 5px; min-height: 20px; min-width: 20px;
                }
                QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
                QCheckBox { color: #c9cace; spacing: 6px; }
                #fieldLabel { color: #8d9099; font-size: 10px; margin-left: 2px; }
                QToolTip { background: #26272d; color: #eee; border: 1px solid #45474d; }
                #filterBar { background: #232529; border-bottom: 1px solid #34363c; }
            """)
        else:
            app.setPalette(app.style().standardPalette())
            app.setStyleSheet("")
        if hasattr(self, 'map'):
            self.map.set_theme(is_dark)

    def showEvent(self, event):
        super().showEvent(event)
        if self.windowHandle():
            self.windowHandle().screenChanged.connect(self._on_screen_changed)
        if self.screen():
            self.screen().geometryChanged.connect(self._update_layout_orientation)
            QTimer.singleShot(100, self._update_layout_orientation)

    def closeEvent(self, event):
        # Salvataggio geometria + stato dock (14) e stop del listener WSJT-X
        settings = QSettings()
        settings.setValue("ui/geometry", self.saveGeometry())
        settings.setValue("ui/dock_state", self.saveState())
        if self.wsjtx_listener is not None:
            self.wsjtx_listener.stop()
        super().closeEvent(event)

    def _on_screen_changed(self, screen):
        self._update_layout_orientation()
        try:
            self.screen().geometryChanged.disconnect(self._update_layout_orientation)
        except (TypeError, RuntimeError): pass
        self.screen().geometryChanged.connect(self._update_layout_orientation)

    def _update_layout_orientation(self):
        """In verticale (schermo ruotato) sposta il dock spot sotto la mappa."""
        screen = self.screen()
        if not screen: return
        geo = screen.geometry()
        is_portrait = geo.height() > geo.width()
        if is_portrait:
            self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_spot)
        else:
            self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_spot)

    def _on_map_loaded(self, ok):
        if not ok: return
        self._map_ready = True
        self.map.toggle_grayline(self.grayline_cb.isChecked())
        self.map.set_user_location(self.user_lat, self.user_lng)
        self.map.set_theme(self.theme_cb.isChecked())
        self.map.set_distance_unit(self.distance_unit)
        self.map.toggle_legend(self.legend_cb.isChecked())
        self.map.toggle_heat(self.heat_cb.isChecked())
        # I satelliti scaricati PRIMA del caricamento della pagina andavano
        # persi (la chiamata JS finiva su una pagina non pronta): ripetiamola.
        if self.all_tles:
            self.map.update_satellites(self.all_tles, self.selected_sats)
        self.refresh()

    def _on_mode_changed(self, _index):
        self.current_mode = self.mode_combo.currentData()
        QSettings().setValue("filters/mode", self.current_mode or "")
        self._apply_filter()

    def _on_continent_changed(self, _index):
        self.current_continent = self.cont_combo.currentData()
        QSettings().setValue("filters/continent", self.current_continent or "")
        self._apply_filter()

    def _on_locator_changed(self):
        text = self.locator_edit.text().strip().upper()
        if text == self._last_applied_locator: return
        self._last_applied_locator = text
        settings = QSettings()
        if not text:
            self.user_lat = self.user_lng = None
            self.locator_status_label.setText("")
            settings.remove("user/locator")
        else:
            try:
                self.user_lat, self.user_lng = maidenhead_to_latlon(text)
                self.locator_status_label.setText(f"Locator: {text}")
                settings.setValue("user/locator", text)
            except ValueError as e:
                self.user_lat = self.user_lng = None
                self.locator_status_label.setText(f"⚠ {e}")
                settings.remove("user/locator")
        self.map.set_user_location(self.user_lat, self.user_lng)
        self._apply_filter()

    def _on_alerts_changed(self):
        text = self.alert_edit.text().strip()
        QSettings().setValue("alerts/list", text)
        self._apply_filter()

    # ---------- Log ADIF / worked-before ----------
    def _load_adif(self, notify: bool = False):
        """(Ri)carica il log ADIF e aggiorna lista, dettaglio e stato."""
        path = (self.adif_path_edit.text().strip() or self.adif_path
                or default_adif_path())
        self.adif_path = path
        if path:
            QSettings().setValue("log/adif_path", path)
            self.adif_path_edit.setText(path)

        ok = self.adif.load(path)
        if ok:
            self.adif_status_label.setText(self.adif.summary())
            self.status_adif.setText(f"Log ADIF: {self.adif.total_qsos} QSO")
            self.status_adif.setToolTip(self.adif.summary())
        else:
            if not path:
                msg = ("Nessun log ADIF configurato: indica il file wsjtx_log.adi "
                       "per attivare B4 e i badge NUOVO/BANDA.")
            else:
                msg = f"⚠ {self.adif.error}"
            self.adif_status_label.setText(msg)
            self.status_adif.setText("Log ADIF: —")
            self.status_adif.setToolTip(msg)

        self.spot_list.set_adif_log(self.adif)
        self._apply_filter()
        if self.current_spot_detail:
            self._show_spot_details(self.current_spot_detail)

        if notify:
            if ok:
                self.statusBar().showMessage(
                    f"Log ADIF ricaricato: {self.adif.total_qsos} QSO", 4000)
            else:
                self.statusBar().showMessage(
                    f"Log ADIF non caricato: {self.adif.error}", 6000)

    def _check_adif_changed(self):
        """Ricarica il log se WSJT-X lo ha aggiornato (mtime cambiato)."""
        path = self.adif_path_edit.text().strip()
        if not path or not os.path.isfile(path):
            return
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return
        if self.adif.mtime is None or mtime > self.adif.mtime + 1e-6:
            self._load_adif()
            if self.adif.loaded:
                self.statusBar().showMessage(
                    f"Log ADIF aggiornato: {self.adif.total_qsos} QSO", 3000)

    def _on_adif_path_changed(self):
        text = self.adif_path_edit.text().strip()
        if text == self.adif_path and self.adif.loaded:
            return
        self.adif_path = text
        QSettings().setValue("log/adif_path", text)
        self._load_adif(notify=True)

    def _browse_adif(self):
        start = (self.adif_path_edit.text().strip()
                 or os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(
            self, "Scegli il log ADIF di WSJT-X", start,
            "Log ADIF (*.adi *.adif);;Tutti i file (*)")
        if path:
            self.adif_path_edit.setText(path)
            self._on_adif_path_changed()

    # ---------- Avvisi sonori e vocali ----------
    def _my_callsign(self) -> str:
        """Nominativo dell'operatore (impostazione dedicata o ricevitore PSKR)."""
        return (QSettings().value("user/callsign", "", type=str).strip().upper()
                or QSettings().value("user/pskr_receiver", "", type=str).strip().upper())

    def _sound_enabled(self) -> bool:
        return QSettings().value("alerts/sound_enabled", True, type=bool)

    def _voice_enabled(self) -> bool:
        return QSettings().value("alerts/voice_enabled", True, type=bool)

    @staticmethod
    def _band_spoken(band: str) -> str:
        band = (band or "").strip()
        return f"{band[:-1]} metri" if band.endswith("m") else band

    def _on_sound_toggled(self, checked):
        QSettings().setValue("alerts/sound_enabled", checked)
        if hasattr(self, "sound_action"):
            self.sound_action.blockSignals(True)
            self.sound_action.setChecked(checked)
            self.sound_action.blockSignals(False)

    def _on_voice_toggled(self, checked):
        QSettings().setValue("alerts/voice_enabled", checked)
        if hasattr(self, "voice_action"):
            self.voice_action.blockSignals(True)
            self.voice_action.setChecked(checked)
            self.voice_action.blockSignals(False)

    def _on_sound_action_toggled(self, checked):
        QSettings().setValue("alerts/sound_enabled", checked)
        if hasattr(self, "sound_cb"):
            self.sound_cb.blockSignals(True)
            self.sound_cb.setChecked(checked)
            self.sound_cb.blockSignals(False)

    def _on_voice_action_toggled(self, checked):
        QSettings().setValue("alerts/voice_enabled", checked)
        if hasattr(self, "voice_cb"):
            self.voice_cb.blockSignals(True)
            self.voice_cb.setChecked(checked)
            self.voice_cb.blockSignals(False)

    def _on_volume_changed(self, value):
        QSettings().setValue("alerts/volume", value)
        self.alert_sounds.set_volume(value / 100.0)

    def _test_audio(self):
        self.alert_sounds.test(self.voice_cb.isChecked())

    def _notify_alert(self, spot, others: int = 0):
        """Suono e voce per uno spot che corrisponde agli avvisi."""
        if self._sound_enabled():
            status = self.adif.status_for(
                spot.dx_call, spot.band, getattr(spot, "country", None))
            self.alert_sounds.play("new_country" if status == NEW_COUNTRY else "alert")
        if self._voice_enabled():
            text = (f"Nominativo {spot.dx_call}, banda "
                    f"{self._band_spoken(spot.band)}, {spot.mode}")
            if others:
                text += f", e altri {others} spot"
            self.alert_sounds.speak(text)

    def _notify_calling(self, spot):
        """Qualcuno ci sta chiamando (decodifica WSJT-X col nostro nominativo)."""
        if self._sound_enabled():
            self.alert_sounds.play("calling")
        if self._voice_enabled():
            self.alert_sounds.speak(f"{spot.dx_call} ti sta chiamando")
        self.tray_icon.showMessage(
            "📞 Ti sta chiamando",
            f"{spot.dx_call} — {spot.freq_khz:.1f} kHz ({spot.band}, {spot.mode})",
            QSystemTrayIcon.MessageIcon.Information, 6000)

    def _open_passes_dialog(self):
        if self.passes_dialog is None:
            self.passes_dialog = SatellitePassesDialog(self)
        self.passes_dialog.show()
        self.passes_dialog.raise_()
        self.passes_dialog.activateWindow()

    # ---------- Target locator (16) ----------
    def _on_target_changed(self):
        text = self.target_edit.text().strip().upper()
        settings = QSettings()
        if not text:
            self.target_info.setText("")
            settings.remove("user/target_locator")
            self.map.clear_route()
            return
        try:
            t_lat, t_lng = maidenhead_to_latlon(text)
        except ValueError as e:
            self.target_info.setText(f"⚠ {e}")
            return
        settings.setValue("user/target_locator", text)

        parts = [f"Target {text}"]
        if self.user_lat is not None:
            dist = haversine_km(self.user_lat, self.user_lng, t_lat, t_lng)
            az = initial_bearing(self.user_lat, self.user_lng, t_lat, t_lng)
            if self.distance_unit == "mi":
                dist *= 0.621371; unit = "mi"
            else:
                unit = "km"
            parts.append(f"distanza {dist:.0f} {unit}, az {az:.0f}°")

        rise, set_ = sunrise_sunset(t_lat, t_lng)
        if rise is None and set_ is None:
            parts.append("sole sempre su/giù (zona polare)")
        else:
            if rise is not None and set_ is not None:
                now = datetime.now(timezone.utc)
                is_day = rise <= now <= set_ if rise < set_ else (now >= rise or now <= set_)
                tag = "☀ giorno" if is_day else "🌙 notte"
                parts.append(f"alba {rise:%H:%M}, tramonto {set_:%H:%M} UTC ({tag})")

        self.target_info.setText(" — ".join(parts))
        self.map.show_route(t_lat, t_lng)

    def _on_spot_selected(self, spot):
        self.map.focus_on(spot.id)
        self._show_spot_details(spot)

    # ---------- Dati e Alert ----------
    def _get_alert_entries(self) -> list:
        """Voci alert estese: prefissi, '*' e filtro @banda (20)."""
        return parse_alert_entries(self.alert_edit.text())

    def _check_alerts(self):
        alert_entries = self._get_alert_entries()
        if not alert_entries: return
        new_alerts = []
        for s in self.all_spots:
            if spot_matches_alert(s, alert_entries) and s.id not in self._notified_ids:
                new_alerts.append(s)
                self._notified_ids.add(s.id)
        if new_alerts:
            first = new_alerts[0]
            msg = f"{first.dx_call} su {first.freq_khz:.1f} kHz ({first.band}, {first.mode})"
            if len(new_alerts) > 1: msg += f" e altri {len(new_alerts)-1} spot"
            self.tray_icon.showMessage("🚨 DX Alert!", msg, QSystemTrayIcon.MessageIcon.Information, 5000)
            self._notify_alert(first, len(new_alerts) - 1)

    # ---------- Sorgente dati: Cluster o WSJT-X (41) ----------
    def _on_source_changed(self, _index):
        source = self.source_combo.currentData() or "cluster"
        QSettings().setValue("source/data_source", source)
        self._activate_source(source)

    def _activate_source(self, source):
        self.data_source = source
        # Ferma tutto ciò che non è la sorgente scelta
        if hasattr(self, "timer"):
            self.timer.stop()
        self._stop_wsjtx_listener()
        if self.data_source == "wsjtx":
            self._start_wsjtx_listener()
            self.source_status_label.setText(
                f"WSJT-X in ascolto su UDP :{self.port_spin.value()} — in attesa di decodifiche…"
            )
            self._prune_spots()
            self._apply_filter()
        elif self.data_source == "pskr":
            self.pskr_provider.receiver_callsign = QSettings().value(
                "user/pskr_receiver", "IZ0FIU", type=str)
            self.source_status_label.setText(
                f"PSK Reporter: ricezioni di {self.pskr_provider.receiver_callsign} "
                "(aggiornamento ogni 10 minuti)…"
            )
            self._on_pskr_timer()
            self.pskr_timer.start()
        else:  # cluster
            self.source_status_label.setText("")
            if hasattr(self, "timer"):
                self.timer.start(self.REFRESH_MS)
                self.refresh()

    def _on_pskr_timer(self):
        spots, error = self.pskr_provider.fetch(minutes=30)
        if error:
            if "rate limit" in error.lower():
                # Backoff progressivo: +10 min per ogni 429 (max 40 min).
                # Il timer regolare resta fermo: scheduliamo la ripresa
                # manualmente per allungare l'intervallo.
                self._pskr_backoff_min = min(40, max(10, self._pskr_backoff_min + 10))
                self.pskr_timer.stop()
                QTimer.singleShot(self._pskr_backoff_min * 60 * 1000, self._pskr_resume)
                self.source_status_label.setStyleSheet("color: #e3a008; font-size: 11px;")
                self.source_status_label.setText(
                    f"⚠ PSK Reporter: rate limit (429) — riprovo tra {self._pskr_backoff_min} minuti")
                return
            self.source_status_label.setStyleSheet("color: #dc3545; font-size: 11px;")
            self.source_status_label.setText(f"⚠ PSK Reporter: {error}")
            return
        # Successo: azzera il backoff
        self._pskr_backoff_min = 0
        self.source_status_label.setStyleSheet("color: #888; font-size: 11px;")
        if spots:
            self._prune_spots()
            known = {s.id for s in self.all_spots}
            fresh = [s for s in spots if s.id not in known]
            self.all_spots.extend(fresh)
            if len(self.all_spots) > self.MAX_SPOTS_IN_MEMORY:
                self.all_spots.sort(key=lambda s: s.timestamp, reverse=True)
                self.all_spots = self.all_spots[: self.MAX_SPOTS_IN_MEMORY]
            self.last_refresh_ts = time.monotonic()
            self.source_status_label.setText(
                f"PSK Reporter: {len(self.all_spots)} ricezioni di "
                f"{self.pskr_provider.receiver_callsign} (aggiorno ogni 10 minuti)"
            )
            self._apply_filter()
        else:
            self.source_status_label.setText(
                f"PSK Reporter: nessuna ricezione negli ultimi 30 minuti "
                f"(controlla la spunta \"Abilita rilevamento PSK Reporter\" in WSJT-X "
                f"e l'attività della banda)"
            )

    def _pskr_resume(self):
        """Riprende il polling regolare dopo un backoff (429)."""
        if self.data_source == "pskr":
            self.pskr_timer.start()
            self._on_pskr_timer()

    @staticmethod
    def _parse_relay_targets(text: str):
        """"127.0.0.1:2238, 10.0.0.5:2237" -> [(host, porta), ...]"""
        targets = []
        for part in (text or "").replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            host, _sep, port = part.rpartition(":")
            if not host or not port.isdigit():
                continue
            targets.append((host.strip(), int(port)))
        return targets

    def _on_relay_changed(self):
        QSettings().setValue("source/relay_targets", self.relay_edit.text().strip())
        # Riavvia il listener per applicare i nuovi destinatari
        if self.data_source == "wsjtx":
            self._stop_wsjtx_listener()
            self._start_wsjtx_listener()
            self.source_status_label.setText(
                f"WSJT-X in ascolto su UDP :{self.port_spin.value()} — in attesa di decodifiche…"
            )

    # ---------- Dialogo Impostazioni ----------
    def _open_settings(self):
        self.settings_dialog.show()

    def _apply_settings(self):
        """OK: applica e salva stazione, log ADIF, avvisi e sorgenti."""
        self._on_locator_changed()
        self._on_relay_changed()
        self._on_wsjtx_port_changed(self.port_spin.value())
        self._on_unit_changed(self.unit_combo.currentIndex())

        call = self.callsign_edit.text().strip().upper()
        QSettings().setValue("user/callsign", call)
        QSettings().setValue("alerts/sound_enabled", self.sound_cb.isChecked())
        QSettings().setValue("alerts/voice_enabled", self.voice_cb.isChecked())
        QSettings().setValue("alerts/volume", self.volume_slider.value())
        self.alert_sounds.set_volume(self.volume_slider.value() / 100.0)

        new_adif = self.adif_path_edit.text().strip()
        if new_adif != self.adif_path:
            self.adif_path = new_adif
            QSettings().setValue("log/adif_path", new_adif)
            self._load_adif(notify=True)

        pskr = self.pskr_edit.text().strip().upper()
        QSettings().setValue("user/pskr_receiver", pskr)
        self.pskr_provider.receiver_callsign = pskr
        if self.wsjtx_listener is not None:
            self.wsjtx_listener.my_call = self._my_callsign()
        if self.data_source == "pskr":
            self._on_pskr_timer()   # aggiorna subito con il nuovo nominativo
        self.settings_dialog.accept()

    def _cancel_settings(self):
        """Annulla: ripristina i valori salvati nei campi."""
        s = QSettings()
        self.locator_edit.setText(s.value("user/locator", "", type=str))
        self.callsign_edit.setText(s.value("user/callsign", "", type=str))
        self.pskr_edit.setText(s.value("user/pskr_receiver", "IZ0FIU", type=str))
        self.relay_edit.setText(s.value("source/relay_targets", "", type=str))
        self.port_spin.setValue(s.value("source/wsjtx_port", 2237, type=int))
        self.adif_path_edit.setText(s.value("log/adif_path", "", type=str))
        for widget in (self.sound_cb, self.voice_cb, self.volume_slider):
            widget.blockSignals(True)
        self.sound_cb.setChecked(s.value("alerts/sound_enabled", True, type=bool))
        self.voice_cb.setChecked(s.value("alerts/voice_enabled", True, type=bool))
        self.volume_slider.setValue(s.value("alerts/volume", 70, type=int))
        for widget in (self.sound_cb, self.voice_cb, self.volume_slider):
            widget.blockSignals(False)
        idx = self.unit_combo.findData(s.value("ui/distance_unit", "km", type=str))
        if idx >= 0:
            self.unit_combo.setCurrentIndex(idx)
        self.settings_dialog.reject()

    def _start_wsjtx_listener(self):
        port = self.port_spin.value()
        targets = self._parse_relay_targets(self.relay_edit.text())
        self.wsjtx_listener = WSJTXListener(
            port, relay_targets=targets, my_call=self._my_callsign())
        if targets:
            log.info("Ponte UDP: inoltro verso %s", ", ".join(f"{h}:{p}" for h, p in targets))
        self.wsjtx_listener.decode_received.connect(self._on_wsjtx_decode)
        self.wsjtx_listener.status_received.connect(self._on_wsjtx_status)
        self.wsjtx_listener.listening_changed.connect(
            self._on_wsjtx_listening, Qt.QueuedConnection)

    def _stop_wsjtx_listener(self):
        if self.wsjtx_listener is not None:
            try:
                self.wsjtx_listener.decode_received.disconnect()
                self.wsjtx_listener.status_received.disconnect()
                self.wsjtx_listener.listening_changed.disconnect()
            except (TypeError, RuntimeError):
                pass
            self.wsjtx_listener.stop()
            self.wsjtx_listener.deleteLater()
            self.wsjtx_listener = None

    def _on_wsjtx_port_changed(self, value):
        QSettings().setValue("source/wsjtx_port", value)
        # Riavvia il listener se siamo in modalità WSJT-X
        if self.data_source == "wsjtx":
            self._stop_wsjtx_listener()
            self._start_wsjtx_listener()
            self.source_status_label.setText(
                f"WSJT-X in ascolto su UDP :{value} — in attesa di decodifiche…"
            )

    def _on_wsjtx_listening(self, ok, err=""):
        if ok:
            self.source_status_label.setStyleSheet("color: #888; font-size: 11px;")
            self.source_status_label.setText(
                f"WSJT-X in ascolto su UDP :{self.port_spin.value()} — in attesa di decodifiche…"
            )
        else:
            self.source_status_label.setStyleSheet("color: #dc3545; font-size: 11px; font-weight: bold;")
            self.source_status_label.setText(
                f"❌ Porta UDP {self.port_spin.value()} occupata da un altro programma "
                f"({err}). Chiudi l'altro programma oppure cambia porta qui e in WSJT-X "
                f"(Settings > Reporting > UDP Server)."
            )

    def _on_wsjtx_decode(self, spot):
        """Nuova decodifica FT8/FT4/JT... via UDP (41)."""
        self._prune_spots()
        if len(self.all_spots) >= self.MAX_SPOTS_IN_MEMORY:
            self.all_spots.sort(key=lambda s: s.timestamp, reverse=True)
            self.all_spots = self.all_spots[: self.MAX_SPOTS_IN_MEMORY - 1]
        self.all_spots.append(spot)
        self.last_refresh_ts = time.monotonic()
        self._apply_filter()

        # "Ti sta chiamando": avviso immediato, distinto dall'alert normale
        if getattr(spot, "calling_me", False):
            self._notified_ids.add(spot.id)  # evita il doppio avviso da _check_alerts
            self._notify_calling(spot)

    def _on_wsjtx_status(self, info):
        self.wsjtx_last_status = info
        dial = info.get("dial_hz")
        parts = [f"WSJT-X in ascolto su UDP :{self.port_spin.value()}"]
        if dial:
            parts.append(f"dial {dial / 1000:.1f} kHz")
        if info.get("de_call"):
            parts.append(f"DE {info['de_call']}")
        if info.get("de_grid"):
            parts.append(f"griglia {info['de_grid']}")
        parts.append(f"{info.get('decodes', 0)} decodifiche")
        parts.append(f"{info.get('datagrams', 0)} datagrammi")
        if self.wsjtx_listener and self.wsjtx_listener.relay_targets:
            parts.append(f"{self.wsjtx_listener.forwarded_count} inoltrati → "
                         + ", ".join(f"{h}:{p}" for h, p in self.wsjtx_listener.relay_targets))
        self.source_status_label.setText(" — ".join(parts))

    def _prune_spots(self):
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.SPOT_TTL_SECONDS)
        kept = [s for s in self.all_spots if s.timestamp >= cutoff]
        if len(kept) > self.MAX_SPOTS_IN_MEMORY:
            kept.sort(key=lambda s: s.timestamp, reverse=True)
            kept = kept[: self.MAX_SPOTS_IN_MEMORY]
        self.all_spots = kept

    def refresh(self):
        # In modalità WSJT-X/PSKR la rete cluster non viene interrogata (41).
        if self.data_source == "wsjtx":
            self._prune_spots()
            self._apply_filter()
            return
        if self.data_source == "pskr":
            self._on_pskr_timer()
            return
        selected_bands = self._get_selected_bands()
        extra = {}
        
        if len(selected_bands) == 0:
            self.all_spots = []
            self._apply_filter()
            return
        elif len(selected_bands) == 1:
            extra["band"] = selected_bands[0]
            limit = 300
        else:
            limit = 500
            
        self.provider.extra_params = extra
        
        try:
            new_spots = self.provider.fetch_spots(limit=limit)
            self._hide_error()
        except Exception as e:
            logging.error(f"Errore fetch spot: {e}")
            self._show_error("Errore di rete: impossibile aggiornare gli spot. Riprovo tra 60 secondi.")
            return

        by_id = {s.id: s for s in self.all_spots}
        for s in new_spots: by_id[s.id] = s
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.SPOT_TTL_SECONDS)
        kept = [s for s in by_id.values() if s.timestamp >= cutoff]
        if len(kept) > self.MAX_SPOTS_IN_MEMORY:
            kept.sort(key=lambda s: s.timestamp, reverse=True)
            kept = kept[:self.MAX_SPOTS_IN_MEMORY]
        self.all_spots = kept
        self.last_refresh_ts = time.monotonic()
        self._apply_filter()

    def _apply_filter(self):
        filtered = self._current_filtered_view()
        filtered = sorted(filtered, key=lambda s: s.timestamp, reverse=True)
        alert_entries = self._get_alert_entries()
        self.spot_list.set_alerts(alert_entries)
        self.map.update_spots(filtered)
        self.spot_list.set_spots(filtered)
        self._update_heat(filtered)
        self._update_status()

    def _current_filtered_view(self):
        filtered = self.all_spots
        selected_bands = self._get_selected_bands()
        
        if len(selected_bands) < len(BANDS):
            filtered = [s for s in filtered if s.band in selected_bands]
            
        if self.current_mode: 
            filtered = [s for s in filtered if s.mode_category == self.current_mode]
        if self.current_continent: 
            filtered = [s for s in filtered if s.spotter_continent == self.current_continent]
        
        if self.new_spots_cb.isChecked():
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.age_slider.value())
            filtered = [s for s in filtered if s.timestamp >= cutoff]

        return filtered

    def _update_status(self):
        filtered = self._current_filtered_view()
        with_coords = sum(1 for s in filtered if s.has_coords)
        
        selected_bands = self._get_selected_bands()
        if len(selected_bands) == len(BANDS):
            band_str = "tutte le bande"
        elif len(selected_bands) == 0:
            band_str = "nessuna banda"
        else:
            band_str = ", ".join(selected_bands)

        parts = [band_str]
        if self.current_mode: parts.append(self.current_mode)
        if self.current_continent: parts.append(f"spotter {self.current_continent}")
        if self.new_spots_cb.isChecked(): parts.append(f"solo nuovi ({self.age_slider.value()}m)")
        label = " / ".join(parts)
        
        age = f"{int(time.monotonic() - self.last_refresh_ts)}s fa" if self.last_refresh_ts else "—"
        self.statusBar().showMessage(
            f"{len(filtered)} spot ({with_coords} sulla mappa) — {label} — aggiornato {age}"
        )
        # Orologio UTC (0): sempre visibile nella barra di stato
        self.status_utc.setText(f"{datetime.now(timezone.utc):%H:%M} UTC")

def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    if "--smoke-test" in sys.argv:
        # Test automatico del pacchetto (usato da check.sh e da GitHub Actions):
        # costruisce la finestra e chiude dopo qualche secondo senza UI.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
        os.environ.setdefault(
            "QTWEBENGINE_CHROMIUM_FLAGS",
            "--disable-gpu --no-sandbox --in-process-gpu")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setOrganizationName("DXClusterMap")
    app.setApplicationName("DXClusterMap")
    app.setQuitOnLastWindowClosed(False)

    win = MainWindow()
    win.show()

    if "--smoke-test" in sys.argv:
        def _smoke_ok():
            print("SMOKE OK", flush=True)
            app.quit()
        QTimer.singleShot(8000, _smoke_ok)
        sys.exit(app.exec())

    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
