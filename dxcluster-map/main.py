import logging
import sys
import time
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QSplitter, QStatusBar, QVBoxLayout, QWidget,
)

from geo import maidenhead_to_latlon, haversine_km, initial_bearing
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
    SPOT_TTL_SECONDS = 30 * 60
    MAX_SPOTS_IN_MEMORY = 1000

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DX Cluster Map")
        self.resize(1400, 850)

        self.provider = SpotholeProvider()
        self.all_spots = []
        self.current_band = None
        self.current_mode = None
        self.current_continent = None
        self.last_refresh_ts = None

        # Stato locator utente (creato PRIMA di ogni possibile uso)
        self.user_lat = None
        self.user_lng = None
        self.distance_label = QLabel("")
        self.distance_label.setWordWrap(True)

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

        # Combo continente spotter
        cont_row = QHBoxLayout()
        cont_row.addWidget(QLabel("Spotter:"))
        self.cont_combo = QComboBox()
        for label, code in CONTINENTS:
            self.cont_combo.addItem(label, userData=code)
        cont_row.addWidget(self.cont_combo, 1)
        side_layout.addLayout(cont_row)

        # Riga locator
        loc_row = QHBoxLayout()
        loc_row.addWidget(QLabel("Il mio locator:"))
        self.locator_edit = QLineEdit()
        self.locator_edit.setPlaceholderText("es. JN45")
        self.locator_edit.setMaxLength(6)
        loc_row.addWidget(self.locator_edit, 1)
        side_layout.addLayout(loc_row)

        side_layout.addWidget(self.distance_label)

        # Lista spot
        self.spot_list = SpotList()
        side_layout.addWidget(self.spot_list, 1)

        # --- Ripristino impostazioni salvate ---
        settings = QSettings()

        saved_band = settings.value("filters/band", "", type=str)
        if saved_band:
            idx = self.band_combo.findData(saved_band)
            if idx >= 0:
                self.band_combo.setCurrentIndex(idx)
                self.current_band = saved_band

        saved_mode = settings.value("filters/mode", "", type=str)
        if saved_mode:
            idx = self.mode_combo.findData(saved_mode)
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
                self.current_mode = saved_mode

        saved_continent = settings.value("filters/continent", "", type=str)
        if saved_continent:
            idx = self.cont_combo.findData(saved_continent)
            if idx >= 0:
                self.cont_combo.setCurrentIndex(idx)
                self.current_continent = saved_continent

        saved_locator = settings.value("user/locator", "", type=str)
        if saved_locator:
            self.locator_edit.setText(saved_locator)
            try:
                self.user_lat, self.user_lng = maidenhead_to_latlon(saved_locator)
                self.distance_label.setText(f"Locator impostato: {saved_locator.upper()}")
            except ValueError:
                self.user_lat = self.user_lng = None

        # Connessione segnali (dopo il ripristino, per evitare refresh prematuri)
        self.band_combo.currentIndexChanged.connect(self._on_band_changed)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.cont_combo.currentIndexChanged.connect(self._on_continent_changed)
        self.locator_edit.editingFinished.connect(self._on_locator_changed)
        self.spot_list.spot_selected.connect(self._on_spot_selected)

        # --- Splitter ---
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.map)
        splitter.addWidget(sidebar)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1000, 400])
        self.setCentralWidget(splitter)

        self.setStatusBar(QStatusBar())

        # Timer fetch
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.REFRESH_MS)

        # Timer 1 Hz per la status bar
        self.second_timer = QTimer(self)
        self.second_timer.timeout.connect(self._update_status)
        self.second_timer.start(1000)

        self.map.loadFinished.connect(lambda ok: ok and self.refresh())

    # ---------- eventi ----------

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
        settings = QSettings()

        if not text:
            self.user_lat = self.user_lng = None
            self.distance_label.setText("")
            settings.remove("user/locator")
            return

        try:
            self.user_lat, self.user_lng = maidenhead_to_latlon(text)
            self.distance_label.setText(f"Locator impostato: {text}")
            settings.setValue("user/locator", text)
        except ValueError as e:
            self.user_lat = self.user_lng = None
            self.distance_label.setText(f"⚠ {e}")
            settings.remove("user/locator")

    def _on_spot_selected(self, spot):
        # Fallback locator (se scritto e non ancora confermato)
        if self.user_lat is None:
            text = self.locator_edit.text().strip().upper()
            if text:
                try:
                    self.user_lat, self.user_lng = maidenhead_to_latlon(text)
                    self._last_applied_locator = text
                    self.locator_status_label.setText(f"Locator: {text}")
                except ValueError:
                    pass

        distance_html = None
        if self.user_lat is not None and spot.has_coords:
            dist = haversine_km(self.user_lat, self.user_lng, spot.lat, spot.lng)
            az = initial_bearing(self.user_lat, self.user_lng, spot.lat, spot.lng)
            distance_html = f"{dist:.0f} km — az {az:.0f}°"
            self.distance_label.setText(
                f"<b>{spot.dx_call}</b> — {dist:.0f} km — azimuth {az:.0f}°"
            )
        else:
            self.distance_label.setText("")

        # Sposta la mappa e mostra la distanza nel popup
        self.map.focus_on(spot.id, distance_html)

    # ---------- dati ----------

    def refresh(self):
        extra = {}
        if self.current_band:
            extra["band"] = self.current_band
        self.provider.extra_params = extra
        new_spots = self.provider.fetch_spots(limit=300)

        # Merge per id (niente duplicati)
        by_id = {s.id: s for s in self.all_spots}
        for s in new_spots:
            by_id[s.id] = s

        # Scadenza TTL
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.SPOT_TTL_SECONDS)
        kept = [s for s in by_id.values() if s.timestamp >= cutoff]

        # Tetto massimo
        if len(kept) > self.MAX_SPOTS_IN_MEMORY:
            kept.sort(key=lambda s: s.timestamp, reverse=True)
            kept = kept[:self.MAX_SPOTS_IN_MEMORY]

        self.all_spots = kept
        self.last_refresh_ts = time.monotonic()
        self._apply_filter()

    def _apply_filter(self):
        filtered = self._current_filtered_view()
        filtered = sorted(filtered, key=lambda s: s.timestamp, reverse=True)

        self.map.update_spots(filtered)
        self.spot_list.set_spots(filtered)
        self._update_status()

    def _current_filtered_view(self):
        filtered = self.all_spots
        if self.current_band:
            filtered = [s for s in filtered if s.band == self.current_band]
        if self.current_mode:
            filtered = [s for s in filtered if s.mode_category == self.current_mode]
        if self.current_continent:
            filtered = [s for s in filtered if s.spotter_continent == self.current_continent]
        return filtered

    def _update_status(self):
        filtered = self._current_filtered_view()
        with_coords = sum(1 for s in filtered if s.has_coords)

        parts = [self.current_band or "tutte le bande"]
        if self.current_mode:
            parts.append(self.current_mode)
        if self.current_continent:
            parts.append(f"spotter {self.current_continent}")
        label = " / ".join(parts)

        if self.last_refresh_ts is None:
            age = "—"
        else:
            secs = int(time.monotonic() - self.last_refresh_ts)
            age = f"{secs}s fa"

        self.statusBar().showMessage(
            f"{len(filtered)} spot ({with_coords} sulla mappa) — "
            f"{label} — aggiornato {age}"
        )


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("DXClusterMap")
    app.setApplicationName("DXClusterMap")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
