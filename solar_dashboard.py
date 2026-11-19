import logging

import requests
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

log = logging.getLogger(__name__)


class _ClickableLabel(QLabel):
    """QLabel cliccabile: apre il link di HamQSL nel browser di sistema."""
    def __init__(self, dashboard):
        super().__init__()
        self._dashboard = dashboard

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            QDesktopServices.openUrl(QUrl("https://www.hamqsl.com/solar.html"))
        super().mouseReleaseEvent(event)


class SolarDashboard(QWidget):
    """Pannello dati solari: widget ufficiale HamQSL (solar101vhf),
    identico a quello pubblicato su hamqsl.com, cliccabile per aprirne il sito."""

    IMAGE_URL = "https://www.hamqsl.com/solar101vhfpic.php"
    TIMEOUT = 15

    def __init__(self):
        super().__init__()
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(2)

        self.image_label = _ClickableLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setToolTip("Dati solari di N0NBH — hamqsl.com (clicca per aprire il sito)")
        main_layout.addWidget(self.image_label)

        self.error_label = QLabel("Dati solari non disponibili")
        self.error_label.setStyleSheet("font-size: 11px; color: #888;")
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.hide()
        main_layout.addWidget(self.error_label)

        self.session = requests.Session()
        self.session.headers["User-Agent"] = "DXClusterMap/1.0 (+ham radio spot viewer)"

    def refresh(self):
        """Scarica (e ricarica) il widget HamQSL ufficiale."""
        try:
            resp = self.session.get(self.IMAGE_URL, timeout=self.TIMEOUT)
            resp.raise_for_status()
            pixmap = QPixmap()
            if not pixmap.loadFromData(resp.content):
                raise ValueError("formato immagine non riconosciuto")
            self.error_label.hide()
            self.image_label.show()
            # L'immagine nativa è 460x148: la scaliamo alla larghezza disponibile
            width = max(self.width(), 240)
            if 0 < width <= 460:
                pixmap = pixmap.scaledToWidth(width, Qt.SmoothTransformation)
            self.image_label.setPixmap(pixmap)
        except (requests.RequestException, ValueError) as e:
            log.error("Errore fetch widget solare HamQSL: %s", e)
            if self.image_label.pixmap() is None:
                self.image_label.hide()
                self.error_label.show()
