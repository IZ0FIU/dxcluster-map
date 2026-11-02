import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QIcon, QPalette, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QSplitter, QStatusBar, QSystemTrayIcon, QVBoxLayout, 
    QWidget, QStackedWidget, QPushButton, QFormLayout, QToolButton, QWidgetAction
)

from geo import maidenhead_to_latlon, haversine_km, initial_bearing
from map_view import MapView
from models import BANDS
from providers.spothole import SpotholeProvider
from solar_provider import SolarProvider
from solar_dashboard import SolarDashboard
from satellite_provider import SatelliteProvider, SatelliteTLE
from spot_list import SpotList

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
        self.setWindowTitle("DX Cluster Map")
        self.resize(1400, 850)

        # --- Stato ---
        self.provider = SpotholeProvider()
        self.solar_provider = SolarProvider()
        self.sat_provider = SatelliteProvider()
        self.all_spots = []
        self.current_mode = None
        self.current_continent = None
        self.last_refresh_ts = None
        self._notified_ids = set()
        self.current_spot_detail = None
        self.distance_unit = "km"
        
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

        # --- Creazione delle due "Pagine" della Sidebar ---
        self.sidebar_stack = QStackedWidget()
        
        self.page_list = self._build_list_page()
        self.sidebar_stack.addWidget(self.page_list)
        
        self.page_detail = self._build_detail_page()
        self.sidebar_stack.addWidget(self.page_detail)

        # --- Layout principale ---
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.error_banner)
        
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.map)
        self.splitter.addWidget(self.sidebar_stack)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([1000, 400])
        main_layout.addWidget(self.splitter, 1)
        
        self.setCentralWidget(main_widget)
        self.setStatusBar(QStatusBar())

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
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)

        self.solar_dashboard = SolarDashboard()
        layout.addWidget(self.solar_dashboard)
        
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #ccc;")
        layout.addWidget(line)

        # Filtro Bande
        band_row = QHBoxLayout()
        band_row.addWidget(QLabel("Bande:"))
        self.band_btn = QToolButton()
        self.band_btn.setText("Tutte")
        self.band_btn.setPopupMode(QToolButton.InstantPopup)
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
        band_row.addWidget(self.band_btn, 1)
        layout.addLayout(band_row)

        # Menu Satelliti (inizialmente vuoto, si popola dopo il fetch)
        sat_row = QHBoxLayout()
        sat_row.addWidget(QLabel("Satelliti:"))
        self.sat_btn = QToolButton()
        self.sat_btn.setText("Nessuno")
        self.sat_btn.setPopupMode(QToolButton.InstantPopup)
        self.sat_menu = QMenu(self.sat_btn)
        self.sat_btn.setMenu(self.sat_menu)
        sat_row.addWidget(self.sat_btn, 1)
        layout.addLayout(sat_row)

        # Filtro Modo
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Modo:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Tutti", userData=None)
        self.mode_combo.addItem("CW", userData="CW")
        self.mode_combo.addItem("Fonia", userData="PHONE")
        self.mode_combo.addItem("Digitale", userData="DIGITAL")
        mode_row.addWidget(self.mode_combo, 1)
        layout.addLayout(mode_row)

        # Filtro Continente
        cont_row = QHBoxLayout()
        cont_row.addWidget(QLabel("Spotter:"))
        self.cont_combo = QComboBox()
        for label, code in CONTINENTS:
            self.cont_combo.addItem(label, userData=code)
        cont_row.addWidget(self.cont_combo, 1)
        layout.addLayout(cont_row)

        # Locator e Unità di misura
        loc_row = QHBoxLayout()
        loc_row.addWidget(QLabel("Locator:"))
        self.locator_edit = QLineEdit()
        self.locator_edit.setPlaceholderText("es. JN45")
        self.locator_edit.setMaxLength(6)
        loc_row.addWidget(self.locator_edit, 2)
        
        self.unit_combo = QComboBox()
        self.unit_combo.addItem("km", userData="km")
        self.unit_combo.addItem("miglia", userData="mi")
        loc_row.addWidget(self.unit_combo, 1)
        
        layout.addLayout(loc_row)
        layout.addWidget(self.locator_status_label)

        # Alert
        alert_row = QHBoxLayout()
        alert_row.addWidget(QLabel("Alert:"))
        self.alert_edit = QLineEdit()
        self.alert_edit.setPlaceholderText("Nominativi separati da virgola")
        alert_row.addWidget(self.alert_edit, 1)
        layout.addLayout(alert_row)

        # Opzioni
        options_row = QHBoxLayout()
        self.grayline_cb = QCheckBox("Grayline")
        self.grayline_cb.setChecked(True)
        options_row.addWidget(self.grayline_cb)
        self.theme_cb = QCheckBox("Tema Scuro")
        options_row.addWidget(self.theme_cb)
        self.new_spots_cb = QCheckBox("Solo nuovi (5m)")
        options_row.addWidget(self.new_spots_cb)
        layout.addLayout(options_row)

        self.spot_list = SpotList()
        layout.addWidget(self.spot_list, 1)
        return page

    def _build_detail_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)

        self.btn_back = QPushButton("← Torna alla lista")
        self.btn_back.setFont(QFont("", -1, QFont.Bold))
        self.btn_back.clicked.connect(self._back_to_list)
        layout.addWidget(self.btn_back)

        layout.addSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        
        self.lbl_dx_call = QLabel("—")
        font = QFont()
        font.setPointSize(18)
        font.setBold(True)
        self.lbl_dx_call.setFont(font)
        form.addRow("Stazione DX:", self.lbl_dx_call)

        self.lbl_country = QLabel("—")
        form.addRow("Nazione:", self.lbl_country)

        self.lbl_freq = QLabel("—")
        form.addRow("Frequenza:", self.lbl_freq)

        self.lbl_mode = QLabel("—")
        form.addRow("Modo:", self.lbl_mode)

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
        self.btn_qrz.setStyleSheet("padding: 8px; background-color: #007bff; color: white; border-radius: 4px;")
        self.btn_qrz.clicked.connect(self._open_qrz)
        layout.addWidget(self.btn_qrz)

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
        
        # Aggiungi azioni rapide
        action_all = self.sat_menu.addAction("Seleziona tutti")
        action_all.triggered.connect(self._select_all_sats)
        action_none = self.sat_menu.addAction("Deseleziona tutti")
        action_none.triggered.connect(self._select_no_sats)
        self.sat_menu.addSeparator()

        widget_cb = QWidget()
        layout_cb = QVBoxLayout(widget_cb)
        layout_cb.setContentsMargins(5, 5, 5, 5)
        layout_cb.setSpacing(2)

        for tle in tles:
            cb = QCheckBox(tle.name)
            cb.setChecked(tle.name in saved_sats)
            cb.stateChanged.connect(self._on_sat_selection_changed)
            layout_cb.addWidget(cb)
            self.sat_checkboxes[tle.name] = cb

        widget_action = QWidgetAction(self.sat_menu)
        widget_action.setDefaultWidget(widget_cb)
        self.sat_menu.addAction(widget_action)
        
        self._on_sat_selection_changed()

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
            
        QSettings().setValue("filters/satellites", list(selected))
        self.map.update_satellites(self.all_tles, self.selected_sats)

    def _update_satellites(self):
        tles = self.sat_provider.fetch_tles()
        if tles:
            self.all_tles = tles
            if not self.sat_checkboxes:
                self._populate_sat_menu(tles)
            else:
                self.map.update_satellites(self.all_tles, self.selected_sats)

    # ---------- Logica Master-Detail ----------
    def _show_spot_details(self, spot):
        self.current_spot_detail = spot
        self.lbl_dx_call.setText(spot.dx_call)
        self.lbl_country.setText(spot.country or "Sconosciuta")
        self.lbl_freq.setText(f"{spot.freq_khz:.1f} kHz ({spot.band})")
        self.lbl_mode.setText(spot.mode)
        self.lbl_spotter.setText(spot.spotter)
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

        self.lbl_comment.setText(spot.comment or "Nessun commento")
        self.sidebar_stack.setCurrentIndex(1)

    def _back_to_list(self):
        self.sidebar_stack.setCurrentIndex(0)

    def _open_qrz(self):
        if self.current_spot_detail:
            url = f"https://www.qrz.com/db/{self.current_spot_detail.dx_call}"
            QDesktopServices.openUrl(QUrl(url))

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
            
        saved_theme = settings.value("ui/dark_theme", False, type=bool)
        self.theme_cb.setChecked(saved_theme)
        self._apply_theme(saved_theme)

        saved_new_spots = settings.value("filters/new_spots", False, type=bool)
        self.new_spots_cb.setChecked(saved_new_spots)
        
        saved_unit = settings.value("ui/distance_unit", "km", type=str)
        idx = self.unit_combo.findData(saved_unit)
        if idx >= 0: self.unit_combo.setCurrentIndex(idx)
        self.distance_unit = saved_unit
        self.map.set_distance_unit(self.distance_unit)

    def _connect_signals(self):
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.cont_combo.currentIndexChanged.connect(self._on_continent_changed)
        self.locator_edit.editingFinished.connect(self._on_locator_changed)
        self.alert_edit.editingFinished.connect(self._on_alerts_changed)
        self.grayline_cb.toggled.connect(self.map.toggle_grayline)
        self.theme_cb.toggled.connect(self._on_theme_toggled)
        self.new_spots_cb.toggled.connect(self._on_new_spots_toggled)
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        self.spot_list.spot_selected.connect(self._on_spot_selected)

    # ---------- Eventi ----------
    def _update_solar(self):
        data = self.solar_provider.fetch()
        self.solar_dashboard.update_data(
            data.sfi, data.a_index, data.k_index, 
            data.band_conditions, data.geomag_field, data.signal_noise
        )

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
        else:
            app.setPalette(app.style().standardPalette())
        if hasattr(self, 'map'):
            self.map.set_theme(is_dark)

    def showEvent(self, event):
        super().showEvent(event)
        if self.windowHandle():
            self.windowHandle().screenChanged.connect(self._on_screen_changed)
        if self.screen():
            self.screen().geometryChanged.connect(self._update_layout_orientation)
            QTimer.singleShot(100, self._update_layout_orientation)

    def _on_screen_changed(self, screen):
        self._update_layout_orientation()
        try:
            self.screen().geometryChanged.disconnect(self._update_layout_orientation)
        except (TypeError, RuntimeError): pass
        self.screen().geometryChanged.connect(self._update_layout_orientation)

    def _update_layout_orientation(self):
        screen = self.screen()
        if not screen: return
        geo = screen.geometry()
        is_portrait = geo.height() > geo.width()
        target_orientation = Qt.Vertical if is_portrait else Qt.Horizontal
        if self.splitter.orientation() != target_orientation:
            self.splitter.setOrientation(target_orientation)
            if target_orientation == Qt.Horizontal:
                self.splitter.setSizes([1000, 400])
            else:
                self.splitter.setSizes([600, 400])

    def _on_map_loaded(self, ok):
        if not ok: return
        self.map.toggle_grayline(self.grayline_cb.isChecked())
        self.map.set_user_location(self.user_lat, self.user_lng)
        self.map.set_theme(self.theme_cb.isChecked())
        self.map.set_distance_unit(self.distance_unit)
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

    def _on_spot_selected(self, spot):
        self.map.focus_on(spot.id)
        self._show_spot_details(spot)

    # ---------- Dati e Alert ----------
    def _get_alert_calls(self) -> set:
        raw = self.alert_edit.text()
        if not raw.strip(): return set()
        return set(c.strip().upper() for c in raw.split(",") if c.strip())

    def _check_alerts(self):
        alert_calls = self._get_alert_calls()
        if not alert_calls: return
        new_alerts = []
        for s in self.all_spots:
            if s.dx_call.upper() in alert_calls and s.id not in self._notified_ids:
                new_alerts.append(s)
                self._notified_ids.add(s.id)
        if new_alerts:
            first = new_alerts[0]
            msg = f"{first.dx_call} su {first.freq_khz:.1f} kHz ({first.band}, {first.mode})"
            if len(new_alerts) > 1: msg += f" e altri {len(new_alerts)-1} spot"
            self.tray_icon.showMessage("🚨 DX Alert!", msg, QSystemTrayIcon.MessageIcon.Information, 5000)
            QApplication.beep()

    def refresh(self):
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
        alert_calls = self._get_alert_calls()
        self.spot_list.set_alerts(alert_calls)
        self.map.update_spots(filtered)
        self.spot_list.set_spots(filtered)
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
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
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
        if self.new_spots_cb.isChecked(): parts.append("solo nuovi (5m)")
        label = " / ".join(parts)
        
        age = f"{int(time.monotonic() - self.last_refresh_ts)}s fa" if self.last_refresh_ts else "—"
        self.statusBar().showMessage(
            f"{len(filtered)} spot ({with_coords} sulla mappa) — {label} — aggiornato {age}"
        )

def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setOrganizationName("DXClusterMap")
    app.setApplicationName("DXClusterMap")
    app.setQuitOnLastWindowClosed(False)
    
    win = MainWindow()
    win.show()

    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
