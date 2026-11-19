from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem

from models import spot_matches_alert

COLUMNS = ["Ora", "DX", "Banda", "Freq", "Modo", "Spotter", "Commento"]

class SpotList(QTableWidget):
    spot_selected = Signal(object)

    def __init__(self):
        super().__init__(0, len(COLUMNS))
        self.setHorizontalHeaderLabels(COLUMNS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(False)

        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        self.setColumnWidth(0, 60)
        self.setColumnWidth(1, 90)
        self.setColumnWidth(2, 60)
        self.setColumnWidth(3, 80)
        self.setColumnWidth(4, 60)
        self.setColumnWidth(5, 80)

        self._spots = []
        self._alert_entries = []
        self.cellClicked.connect(self._on_cell_clicked)

    def set_alerts(self, entries):
        """Imposta le voci di alert (prefissi, '@banda') per l'evidenziazione (20)."""
        self._alert_entries = list(entries)

    def set_spots(self, spots):
        self._spots = spots
        self.setRowCount(0)
        self.setRowCount(len(spots))

        alert_bg = QColor(255, 176, 46, 46)  # ambra trasparente (tema scuro)

        dx_font = QFont("Monospace")
        dx_font.setBold(True)

        for row, s in enumerate(spots):
            ora = s.timestamp.strftime("%H:%M") if s.timestamp else "—"
            freq = f"{s.freq_khz:.1f}"
            comment = (s.comment or "")[:120]
            if not s.has_coords:
                comment = "⚠ nessuna posizione — " + comment

            is_alert = spot_matches_alert(s, self._alert_entries)
            dx_text = f"⭐ {s.dx_call}" if is_alert else s.dx_call

            values = [ora, dx_text, s.band, freq, s.mode, s.spotter, comment]

            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 1:
                    item.setForeground(QColor("#ffb02e"))
                    item.setFont(dx_font)
                if col == 2:
                    item.setForeground(QColor(s.color))
                    f = QFont()
                    f.setBold(True)
                    item.setFont(f)
                    item.setText("● " + s.band)
                if not s.has_coords:
                    item.setForeground(QColor("#999"))

                if is_alert:
                    item.setBackground(alert_bg)
                    f = QFont()
                    f.setBold(True)
                    item.setFont(f)

                self.setItem(row, col, item)

            # Paese dello spotter come tooltip (21)
            sc = getattr(s, "spotter_country", None)
            if sc:
                flag = getattr(s, "spotter_flag", None) or ""
                tip = f"{s.spotter} — {sc}".strip()
                if flag:
                    tip = f"{flag} {tip}"
                self.item(row, 5).setToolTip(tip)

    def _on_cell_clicked(self, row, _col):
        if 0 <= row < len(self._spots):
            self.spot_selected.emit(self._spots[row])
