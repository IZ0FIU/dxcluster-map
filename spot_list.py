from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem


COLUMNS = ["Ora", "DX", "Banda", "Freq", "Modo", "Spotter", "Commento"]


class SpotList(QTableWidget):
#    spot_selected = Signal(str)  # emette lo spot.id
    spot_selected = Signal(object)  # emette l'oggetto Spot

    def __init__(self):
        self._spots = []
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
        self.setColumnWidth(0, 60)   # Ora
        self.setColumnWidth(1, 90)   # DX
        self.setColumnWidth(2, 60)   # Banda
        self.setColumnWidth(3, 80)   # Freq
        self.setColumnWidth(4, 60)   # Modo
        self.setColumnWidth(5, 80)   # Spotter

        self._id_by_row = {}
        self.cellClicked.connect(self._on_cell_clicked)

    def set_spots(self, spots):
        self._spots = spots
        self.setRowCount(0)
        self.setRowCount(0)
        self._id_by_row.clear()
        self.setRowCount(len(spots))

        for row, s in enumerate(spots):
            self._id_by_row[row] = s.id

            ora = s.timestamp.strftime("%H:%M") if s.timestamp else "—"
            freq = f"{s.freq_khz:.1f}"
            comment = s.comment or ""
            if not s.has_coords:
                comment = "⚠ nessuna posizione — " + comment

            values = [ora, s.dx_call, s.band, freq, s.mode, s.spotter, comment]

            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 2:  # colonna banda: pallino colorato
                    item.setForeground(QColor(s.color))
                    f = QFont()
                    f.setBold(True)
                    item.setFont(f)
                    item.setText("● " + s.band)
                if not s.has_coords:
                    item.setForeground(QColor("#999"))
                self.setItem(row, col, item)

    def _on_cell_clicked(self, row, _col):
        if 0 <= row < len(self._spots):
            self.spot_selected.emit(self._spots[row])
