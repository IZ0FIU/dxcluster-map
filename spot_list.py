from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem

from adif_log import NEW_BAND, NEW_CALL, NEW_COUNTRY, WORKED
from models import spot_matches_alert

COLUMNS = ["Ora", "DX", "Log", "Banda", "Freq", "Modo", "Spotter", "Commento"]

# Etichette e colori della colonna "Log" (worked-before)
LOG_STYLE = {
    NEW_COUNTRY: ("NUOVO", QColor("#ffb02e")),
    NEW_BAND: ("BANDA", QColor("#5fd38d")),
    NEW_CALL: ("", QColor("#6aa9ff")),
    WORKED: ("B4", QColor("#777a82")),
}
LOG_TIP = {
    NEW_COUNTRY: "Nuova entità DXCC: non risulta mai lavorata",
    NEW_BAND: "Entità già lavorata, ma non su questa banda",
    NEW_CALL: "Nominativo mai lavorato (entità e banda già a log)",
    WORKED: "Già a log su questa banda (B4)",
}


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
        self.setColumnWidth(1, 100)
        self.setColumnWidth(2, 64)
        self.setColumnWidth(3, 60)
        self.setColumnWidth(4, 80)
        self.setColumnWidth(5, 60)
        self.setColumnWidth(6, 80)

        self._spots = []
        self._alert_entries = []
        self._adif = None
        self.cellClicked.connect(self._on_cell_clicked)

    def set_alerts(self, entries):
        """Imposta le voci di alert (prefissi, '@banda') per l'evidenziazione (20)."""
        self._alert_entries = list(entries)

    def set_adif_log(self, adif):
        """Imposta il log ADIF per le verifiche worked-before."""
        self._adif = adif

    def set_spots(self, spots):
        self._spots = spots
        self.setRowCount(0)
        self.setRowCount(len(spots))

        alert_bg = QColor(255, 176, 46, 46)  # ambra trasparente (tema scuro)
        dim = QColor("#777a82")

        dx_font = QFont("Monospace")
        dx_font.setBold(True)

        for row, s in enumerate(spots):
            ora = s.timestamp.strftime("%H:%M") if s.timestamp else "—"
            freq = f"{s.freq_khz:.1f}"
            comment = (s.comment or "")[:120]
            if not s.has_coords:
                comment = "⚠ nessuna posizione — " + comment

            is_alert = spot_matches_alert(s, self._alert_entries)
            is_calling = bool(getattr(s, "calling_me", False))
            prefix = "📞 " if is_calling else ("⭐ " if is_alert else "")
            dx_text = prefix + s.dx_call

            log_status = None
            if self._adif is not None:
                log_status = self._adif.status_for(
                    s.dx_call, s.band, getattr(s, "country", None))
            log_label, log_color = LOG_STYLE.get(log_status, ("", None))

            values = [ora, dx_text, log_label, s.band, freq, s.mode,
                      s.spotter, comment]

            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 1:
                    item.setForeground(QColor("#ffb02e"))
                    item.setFont(dx_font)
                if col == 2:
                    if log_color:
                        item.setForeground(log_color)
                        f = QFont()
                        f.setBold(True)
                        item.setFont(f)
                    tip = LOG_TIP.get(log_status)
                    if tip:
                        item.setToolTip(tip)
                if col == 3:
                    item.setForeground(QColor(s.color))
                    f = QFont()
                    f.setBold(True)
                    item.setFont(f)
                    item.setText("● " + s.band)
                if not s.has_coords:
                    item.setForeground(dim)

                if is_alert or is_calling:
                    item.setBackground(alert_bg)
                    f = QFont()
                    f.setBold(True)
                    item.setFont(f)
                elif log_status == WORKED:
                    # B4: riga attenuata, ma la banda resta riconoscibile
                    if col != 3:
                        item.setForeground(dim)

                self.setItem(row, col, item)

            # Paese dello spotter come tooltip (21)
            sc = getattr(s, "spotter_country", None)
            if sc:
                flag = getattr(s, "spotter_flag", None) or ""
                tip = f"{s.spotter} — {sc}".strip()
                if flag:
                    tip = f"{flag} {tip}"
                self.item(row, 6).setToolTip(tip)

    def _on_cell_clicked(self, row, _col):
        if 0 <= row < len(self._spots):
            self.spot_selected.emit(self._spots[row])
