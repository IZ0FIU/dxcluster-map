import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QSplitter, QStatusBar, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from geo import maidenhead_to_latlon
from map_view import MapView
from models import BANDS
from providers.spothole import SpotholeProvider
from spot_list import SpotList

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

CONTINENTS = [
    ("Tutti", None),
    ("Europa", "EU"),
    ("Nord America", "NA"),
    ("Sud America", "SA"),
    ("Asia", "AS"),
    ("Africa", "AF"),
    ("Oceania", "OC"),
    ("Antartide", "AN"),
]


class MainWindow(QMainWindow):
    REFRESH_MS = 60_000
    ALERT_CHECK_MS = 10_000
    SPOT_TTL_SECONDS = 30 * 60
    MAX_SPOTS_IN_MEMORY = 1000

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DX Cluster Map")
        self.resize(1400, 850)

        # --- Stato ---
        self.provider = SpotholeProvider()
        self.all_spots = []
        self.current_band = None
        self.current_mode = None
        self.current_continent = None
        self.last_refresh_ts = None
        self._notified_ids = set()

        # Stato locator
        self.user_lat = None
        self.user_lng = None
        self._last_applied_locator = ""
        self.locator_status_label = QLabel("")
        self.locator_status_label.setStyleSheet("color: #888; font-size: 11px;")

        # --- Tray Icon e Menu ---
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

        # --- Sidebar ---
        sidebar = QWidget()
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(6, 6, 6, 6)

        # Combo banda
        band_row = QHBoxLayout()
        band_row.addWidget(QLabel("Banda:"))
        self.band_combo = QComboBox()
        self.band_combo.addItem("Tutte", userData=None)
        for name, _low, _high in BANDS:
            self.band_combo.addItem(name, userData=name)
        band_row.addWidget(self.band_combo, 1)
        side_layout.addLayout(band_row)

        # Combo modo
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Modo:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Tutti", userData=None)
        self.mode_combo.addItem("CW", userData="CW")
        self.mode_combo.addItem("Fonia", userData="PHONE")
        self.mode_combo.addItem("Digitale", userData="DIGITAL")
        mode_row.addWidget(self.mode_combo, 1)
        side_layout.addLayout(mode_row)

        # Combo continente
        cont_row = QHBoxLayout()
        cont_row.addWidget(QLabel("Spotter:"))
        self.cont_combo = QComboBox()
        for label, code in CONTINENTS:
            self.cont_combo.addItem(label, userData=code)
        cont_row.addWidget(self.cont_combo, 1)
        side_layout.addLayout(cont_row)

        # Locator
        loc_row = QHBoxLayout()
        loc_row.addWidget(QLabel("Il mio locator:"))
        self.locator_edit = QLineEdit()
        self.locator_edit.setPlaceholderText("es. JN45")
        self.locator_edit.setMaxLength(6)
        loc_row.addWidget(self.locator_edit, 1)
        side_layout.addLayout(loc_row)
        side_layout.addWidget(self.locator_status_label)

        # Alert (Watchlist)
        alert_row = QHBoxLayout()
        alert_row.addWidget(QLabel("Alert:"))
        self.alert_edit = QLineEdit()
        self.alert_edit.setPlaceholderText("Nominativi separati da virgola (es. IK2XYZ, W1AW)")
        alert_row.addWidget(self.alert_edit, 1)
        side_layout.addLayout(alert_row)

        # Toggle Grayline
        self.grayline_cb = QCheckBox("Mostra Grayline (giorno/notte)")
        self.grayline_cb.setChecked(True)
        side_layout.addWidget(self.grayline_cb)

        # Lista spot
        self.spot_list = SpotList()
        side_layout.addWidget(self.spot_list, 1)

        # --- Ripristino impostazioni ---
        settings = QSettings()
        
        saved_band = settings.value("filters/band", "", type=str)
        if saved_band:
            idx = self.band_combo.findData(saved_band)
            if idx >= 0: self.band_combo.setCurrentIndex(idx)
            self.current_band = saved_band
            
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
            except ValueError: 
                pass
        
        saved_alerts = settings.value("alerts/list", "", type=str)
        if saved_alerts:
            self.alert_edit.setText(saved_alerts)

        # --- Connessioni ---
        self.band_combo.currentIndexChanged.connect(self._on_band_changed)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.cont_combo.currentIndexChanged.connect(self._on_continent_changed)
        self.locator_edit.editingFinished.connect(self._on_locator_changed)
        self.alert_edit.editingFinished.connect(self._on_alerts_changed)
        self.grayline_cb.toggled.connect(self.map.toggle_grayline)
        
        self.spot_list.spot_selected.connect(self._on_spot_selected)

        # --- Layout principale (Splitter) ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.map)
        self.splitter.addWidget(sidebar)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([1000, 400])
        self.setCentralWidget(self.splitter)

        self.setStatusBar(QStatusBar())

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

        self.map.loadFinished.connect(self._on_map_loaded)

    # ---------- Gestione Orientamento Monitor ----------
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

    # ---------- Eventi ----------
    def _on_map_loaded(self, ok):
        if not ok: return
        self.map.toggle_grayline(self.grayline_cb.isChecked())
        self.map.set_user_location(self.user_lat, self.user_lng)
        self.refresh()

    def _on_band_changed(self, _index):
        self.current_band = self.band_combo.currentData()
        QSettings().setValue("filters/band", self.current_band or "")
        self._apply_filter()
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
        extra = {}
        if self.current_band: extra["band"] = self.current_band
        self.provider.extra_params = extra
        new_spots = self.provider.fetch_spots(limit=300)

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
        if self.current_band: filtered = [s for s in filtered if s.band == self.current_band]
        if self.current_mode: filtered = [s for s in filtered if s.mode_category == self.current_mode]
        if self.current_continent: filtered = [s for s in filtered if s.spotter_continent == self.current_continent]
        return filtered

    def _update_status(self):
        filtered = self._current_filtered_view()
        with_coords = sum(1 for s in filtered if s.has_coords)
        
        parts = [self.current_band or "tutte le bande"]
        if self.current_mode: parts.append(self.current_mode)
        if self.current_continent: parts.append(f"spotter {self.current_continent}")
        label = " / ".join(parts)
        
        age = f"{int(time.monotonic() - self.last_refresh_ts)}s fa" if self.last_refresh_ts else "—"
        self.statusBar().showMessage(
            f"{len(filtered)} spot ({with_coords} sulla mappa) — {label} — aggiornato {age}"
        )


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
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
