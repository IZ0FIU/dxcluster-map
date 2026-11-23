import logging
import re
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)

from solar_provider import SolarProvider

log = logging.getLogger(__name__)


class _FetchDone(QObject):
    """Ponte thread→GUI: il fetch avviene in background, l'aggiornamento no."""
    done = Signal(object)


class SolarDashboard(QWidget):
    """Pannello compatto con i principali indici di propagazione.

    I dati arrivano dal feed XML di HamQSL (N0NBH), lo stesso del widget
    solar101vhf, ma qui vengono mostrati come valori testuali: niente
    immagine, quindi il pannello si adatta da solo alla larghezza del dock.
    """

    SITE_URL = "https://www.hamqsl.com/solar.html"

    # (etichetta, campo di SolarData) — i valori principali
    METRICS = (
        ("SFI", "sfi"),
        ("A", "a_index"),
        ("K", "k_index"),
        ("SSN", "sunspots"),
    )

    def __init__(self):
        super().__init__()
        self._provider = SolarProvider()
        self._bridge = _FetchDone()
        self._bridge.done.connect(self._apply_data)
        self._busy = False
        self._last = None
        self._value_labels = {}

        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Indici di propagazione N0NBH — hamqsl.com "
                        "(clicca per aprire il sito)")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 4)
        outer.setSpacing(1)

        # Intestazione: titolo + ora dell'ultimo aggiornamento
        head = QHBoxLayout()
        head.setContentsMargins(2, 0, 2, 0)
        title = QLabel("Propagazione")
        title.setStyleSheet("color: #8d9099; font-size: 10px; font-weight: bold;")
        self.updated_label = QLabel("")
        self.updated_label.setStyleSheet("color: #8d9099; font-size: 10px;")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.updated_label)
        outer.addLayout(head)

        # Indici principali, in colonne che si allargano con il dock
        grid = QGridLayout()
        grid.setContentsMargins(0, 1, 0, 1)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(0)
        for col, (key, attr) in enumerate(self.METRICS):
            key_label = QLabel(key)
            key_label.setAlignment(Qt.AlignCenter)
            key_label.setStyleSheet("color: #8d9099; font-size: 10px;")
            value_label = QLabel("–")
            value_label.setAlignment(Qt.AlignCenter)
            value_label.setStyleSheet("font-size: 16px; font-weight: bold;")
            grid.addWidget(key_label, 0, col)
            grid.addWidget(value_label, 1, col)
            grid.setColumnStretch(col, 1)
            self._value_labels[attr] = value_label
        outer.addLayout(grid)

        # Riga secondaria: raggi X, vento solare, campo geomagnetico
        self.detail_label = QLabel("In attesa dei dati…")
        self.detail_label.setStyleSheet("color: #8d9099; font-size: 10px;")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setWordWrap(True)
        outer.addWidget(self.detail_label)

    # ---------- Aggiornamento dati ----------
    def refresh(self):
        """Avvia il download in background (una richiesta alla volta)."""
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._fetch, name="solar-fetch",
                         daemon=True).start()

    def _fetch(self):
        try:
            data = self._provider.fetch()
        except Exception:
            log.exception("Errore imprevisto nei dati solari")
            data = None
        self._bridge.done.emit(data)

    def _apply_data(self, data):
        self._busy = False
        if data is None or not data.ok:
            if self._last is None:
                self.detail_label.setText("Dati di propagazione non disponibili")
            return
        self._last = data
        for attr, label in self._value_labels.items():
            value = getattr(data, attr, None)
            label.setText("–" if value is None else str(value))
        self.updated_label.setText(_format_updated(data.updated))
        parts = []
        if data.xray:
            parts.append(f"Raggi X {data.xray}")
        if data.solarwind:
            parts.append(f"Vento {data.solarwind} km/s")
        if data.geomag_field:
            parts.append(f"Geo {data.geomag_field}")
        self.detail_label.setText("  ·  ".join(parts))

    # ---------- Interazione ----------
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            QDesktopServices.openUrl(QUrl(self.SITE_URL))
        super().mouseReleaseEvent(event)


def _format_updated(raw: str) -> str:
    """' 22 Nov 2026 2103 GMT' -> 'agg. 21:03 UTC' (indipendente dalla lingua)."""
    raw = (raw or "").strip()
    match = re.search(r"\b(\d{2})(\d{2})\s+GMT\b", raw)
    if match:
        return f"agg. {match.group(1)}:{match.group(2)} UTC"
    return raw
