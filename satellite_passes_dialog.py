"""Dialogo passaggi satelliti con tabella AOS/LOS e polar plot.

Mostra i prossimi passaggi dei satelliti selezionati per la posizione
dell'operatore, con una vista polare azimuth/elevazione del passaggio scelto.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from satellite_passes import (
    SatellitePass, current_look, find_passes, polar_path,
)

ACCENT = QColor("#ffb02e")
CYAN = QColor("#4fc3f7")
DIM = QColor("#8d9099")
GREEN = QColor("#5fd38d")


def _fmt_dt(dt: datetime) -> str:
    return dt.astimezone().strftime("%d/%m %H:%M:%S")


def _fmt_countdown(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 0:
        return "passato"
    if seconds < 60:
        return f"tra {seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"tra {minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"tra {hours}h {minutes:02d}m"


class PolarPlot(QWidget):
    """Grafico polare: nord in alto, cerchi a 30/60/90° di elevazione."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self._name = ""
        self._points: List[Tuple[float, float]] = []
        self._current: Optional[Tuple[float, float, float]] = None
        self._aos: Optional[Tuple[float, float]] = None
        self._los: Optional[Tuple[float, float]] = None
        self._max: Optional[Tuple[float, float]] = None
        self._aos_time: Optional[datetime] = None
        self._los_time: Optional[datetime] = None
        self._max_el = 0.0

    def set_pass(self, name: str, points, current=None, aos=None, los=None,
                 max_point=None, aos_time=None, los_time=None, max_el=0.0):
        self._name = name or ""
        self._points = list(points or [])
        self._current = current
        self._aos = aos
        self._los = los
        self._max = max_point
        self._aos_time = aos_time
        self._los_time = los_time
        self._max_el = max_el
        self.update()

    def _map(self, az: float, el: float, cx: float, cy: float, radius: float):
        el = max(-2.0, min(90.0, el))
        r = (90.0 - el) / 90.0 * radius
        a = math.radians(az)
        return QPointF(cx + r * math.sin(a), cy - r * math.cos(a))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#1e1f24"))

        w, h = self.width(), self.height()
        margin = 30
        cx, cy = w / 2.0, h / 2.0 + 8
        radius = max(40.0, min(w, h) / 2.0 - margin)

        # sfondo del cerchio
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#232529"))
        p.drawEllipse(QPointF(cx, cy), radius, radius)

        # cerchi di elevazione
        p.setBrush(Qt.NoBrush)
        for el, label in ((0, "0°"), (30, "30°"), (60, "60°"), (90, "90°")):
            r = (90.0 - el) / 90.0 * radius
            pen = QPen(QColor("#3a3c42"), 1)
            if el == 0:
                pen.setColor(QColor("#55575f"))
            p.setPen(pen)
            p.drawEllipse(QPointF(cx, cy), r, r)
            if el in (30, 60):
                p.setPen(QPen(DIM, 1))
                p.setFont(QFont("Sans", 7))
                p.drawText(QPointF(cx + 3, cy - r + 9), label)

        # raggi e punti cardinali
        p.setPen(QPen(QColor("#34363c"), 1))
        for az in range(0, 360, 30):
            a = math.radians(az)
            x = cx + radius * math.sin(a)
            y = cy - radius * math.cos(a)
            p.drawLine(QPointF(cx, cy), QPointF(x, y))
        p.setFont(QFont("Sans", 9, QFont.Bold))
        for az, label in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            a = math.radians(az)
            x = cx + (radius + 15) * math.sin(a)
            y = cy - (radius + 15) * math.cos(a)
            p.setPen(QPen(ACCENT if az == 0 else DIM))
            p.drawText(QPointF(x - 4, y + 4), label)

        # traiettoria del passaggio
        if len(self._points) >= 2:
            poly = QPolygonF([self._map(az, el, cx, cy, radius)
                              for az, el in self._points])
            p.setPen(QPen(ACCENT, 2.2))
            p.drawPolyline(poly)
            # punti di inizio/fine
            for pt, color in ((self._aos, GREEN), (self._los, QColor("#ff6b6b"))):
                if pt:
                    q = self._map(pt[0], pt[1], cx, cy, radius)
                    p.setPen(Qt.NoPen)
                    p.setBrush(color)
                    p.drawEllipse(q, 4, 4)
            if self._max:
                q = self._map(self._max[0], self._max[1], cx, cy, radius)
                p.setPen(QPen(QColor("#111"), 1))
                p.setBrush(ACCENT)
                p.drawEllipse(q, 5, 5)
                p.setPen(ACCENT)
                p.setFont(QFont("Sans", 8, QFont.Bold))
                p.drawText(QPointF(q.x() + 8, q.y() - 5),
                           f"{self._max_el:.0f}°")

        # posizione attuale (solo se sopra l'orizzonte: sotto è fuori dal plot)
        if self._current:
            az, el, _rng = self._current
            if el >= 0:
                q = self._map(az, el, cx, cy, radius)
                p.setPen(QPen(QColor("#111"), 1))
                p.setBrush(CYAN)
                p.drawEllipse(q, 5, 5)
                p.setPen(CYAN)
                p.setFont(QFont("Sans", 8, QFont.Bold))
                p.drawText(QPointF(q.x() + 7, q.y() + 12), "ora")
            else:
                p.setPen(CYAN)
                p.setFont(QFont("Sans", 8))
                p.drawText(QRectF(8, h - 18, w - 16, 14), Qt.AlignLeft,
                           f"sotto l'orizzonte (elevazione {el:.0f}°)")

        # titolo
        p.setPen(QColor("#e8e8ea"))
        p.setFont(QFont("Sans", 10, QFont.Bold))
        title = self._name or "Nessun satellite selezionato"
        p.drawText(QRectF(8, 4, w - 16, 18), Qt.AlignLeft, title)
        if self._aos_time and self._los_time:
            p.setPen(DIM)
            p.setFont(QFont("Sans", 8))
            p.drawText(QRectF(8, 20, w - 16, 16), Qt.AlignLeft,
                       f"{self._aos_time:%H:%M:%S} → "
                       f"{self._los_time:%H:%M:%S} UTC  max {self._max_el:.0f}°")

        if not self._points:
            p.setPen(DIM)
            p.setFont(QFont("Sans", 9))
            p.drawText(QRectF(0, cy - 10, w, 20), Qt.AlignCenter,
                       "Nessun passaggio da mostrare")


class SatellitePassesDialog(QDialog):
    """Finestra non modale: tabella passaggi + polar plot."""

    REFRESH_MS = 30_000
    CACHE_SECONDS = 300

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main = main_window
        self.setWindowTitle("Passaggi satelliti — AOS/LOS e polar plot")
        self.resize(1120, 620)
        self._passes: List[SatellitePass] = []
        self._cache_key = None
        self._cache_time: Optional[datetime] = None
        self._truncated = False
        self._paths: Dict[Tuple[str, datetime], list] = {}

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Satelliti:"))
        self.scope_combo = QComboBox()
        self.scope_combo.setMinimumWidth(220)
        top.addWidget(self.scope_combo)

        top.addSpacing(10)
        top.addWidget(QLabel("Elevazione min:"))
        self.min_el_spin = QSpinBox()
        self.min_el_spin.setRange(0, 60)
        self.min_el_spin.setValue(5)
        self.min_el_spin.setSuffix("°")
        self.min_el_spin.setToolTip(
            "Soglia di elevazione per considerare un passaggio utile")
        top.addWidget(self.min_el_spin)

        top.addSpacing(10)
        top.addWidget(QLabel("Orizzonte:"))
        self.horizon_combo = QComboBox()
        for label, hours in (("6 ore", 6), ("12 ore", 12), ("24 ore", 24),
                             ("48 ore", 48)):
            self.horizon_combo.addItem(label, userData=hours)
        self.horizon_combo.setCurrentIndex(2)
        top.addWidget(self.horizon_combo)

        self.refresh_btn = QPushButton("Calcola")
        self.refresh_btn.clicked.connect(lambda: self.refresh(force=True))
        top.addWidget(self.refresh_btn)
        top.addStretch(1)
        layout.addLayout(top)

        body = QHBoxLayout()
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Satellite", "AOS (UTC)", "LOS (UTC)", "Durata", "Max el.",
             "Azimut AOS→LOS", "Stato"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        for col in range(6):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection)
        body.addWidget(self.table, 4)

        self.polar = PolarPlot()
        body.addWidget(self.polar, 2)
        layout.addLayout(body, 1)

        self.info = QLabel("")
        self.info.setStyleSheet("color: #9a9ca3; font-size: 11px;")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        self.timer = QTimer(self)
        self.timer.setInterval(self.REFRESH_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self.scope_combo.currentIndexChanged.connect(lambda _i: self.refresh(force=True))
        self.min_el_spin.valueChanged.connect(lambda _v: self.refresh(force=True))
        self.horizon_combo.currentIndexChanged.connect(lambda _i: self.refresh(force=True))

        self._rebuild_scope()
        self.refresh(force=True)

    # ---------- dati ----------
    def _selected_tles(self):
        tles = list(getattr(self.main, "all_tles", []) or [])
        selected = set(getattr(self.main, "selected_sats", set()) or set())
        if selected:
            tles = [t for t in tles if t.name in selected]
        return sorted(tles, key=lambda t: t.name.lower())

    def _rebuild_scope(self):
        current = self.scope_combo.currentData()
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()
        self.scope_combo.addItem("Tutti i satelliti selezionati", userData="__all__")
        for tle in self._selected_tles():
            self.scope_combo.addItem(tle.name, userData=tle.name)
        idx = self.scope_combo.findData(current)
        self.scope_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.scope_combo.blockSignals(False)

    def _scope_tles(self):
        tles = self._selected_tles()
        scope = self.scope_combo.currentData()
        if scope and scope != "__all__":
            tles = [t for t in tles if t.name == scope]
        # Non calcolare 96 satelliti in un colpo solo: la finestra diventerebbe
        # lenta. Il menu permette comunque di restringere la selezione.
        return tles[:16]

    def refresh(self, force: bool = False):
        lat, lng = self.main.user_lat, self.main.user_lng
        if lat is None or lng is None:
            self._passes = []
            self.table.setRowCount(0)
            self.info.setText(
                "⚠ Imposta il locator della tua stazione in Impostazioni → "
                "Locator per calcolare i passaggi.")
            self.polar.set_pass("", [])
            return

        tles = self._scope_tles()
        if not tles:
            self._passes = []
            self.table.setRowCount(0)
            self.info.setText(
                "Nessun satellite selezionato: scegli i satelliti dalla barra "
                "filtri o dal menu Satelliti.")
            self.polar.set_pass("", [])
            return

        min_el = float(self.min_el_spin.value())
        hours = float(self.horizon_combo.currentData() or 24)
        now = datetime.now(timezone.utc)
        key = (tuple(t.name for t in tles), min_el, hours, round(lat, 3), round(lng, 3))
        if (not force and self._cache_key == key and self._cache_time
                and (now - self._cache_time).total_seconds() < self.CACHE_SECONDS):
            self._update_countdowns()
            return

        self.info.setText("Calcolo dei passaggi…")
        self.info.repaint()
        passes: List[SatellitePass] = []
        for tle in tles:
            passes.extend(find_passes(tle, lat, lng, start=now, hours=hours,
                                      min_elevation=min_el))
        passes.sort(key=lambda p: p.aos)
        self._passes = passes
        self._truncated = len(self._selected_tles()) > len(tles)
        self._cache_key = key
        self._cache_time = now
        self._fill_table()
        self._update_countdowns()

    def _fill_table(self):
        self.table.setRowCount(len(self._passes))
        now = datetime.now(timezone.utc)
        for row, p in enumerate(self._passes):
            values = [
                p.satellite,
                p.aos.strftime("%d/%m %H:%M:%S"),
                p.los.strftime("%H:%M:%S"),
                f"{p.duration_min:.1f} min",
                f"{p.max_elevation:.0f}°",
                f"{p.aos_azimuth:.0f}° → {p.los_azimuth:.0f}°",
                self._status_text(p, now),
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setForeground(ACCENT)
                    f = QFont("Monospace")
                    f.setBold(True)
                    item.setFont(f)
                elif col == 4:
                    item.setForeground(GREEN if p.max_elevation >= 30 else DIM)
                elif col == 6:
                    if p.in_progress:
                        item.setForeground(GREEN)
                    elif p.aos < now:
                        item.setForeground(QColor("#666"))
                    else:
                        item.setForeground(CYAN)
                self.table.setItem(row, col, item)
        if self._passes:
            self.table.selectRow(0)

    @staticmethod
    def _status_text(p: SatellitePass, now: datetime) -> str:
        if p.in_progress:
            return "IN CORSO"
        if p.aos < now:
            return "passato"
        return _fmt_countdown((p.aos - now).total_seconds())

    def _update_countdowns(self):
        now = datetime.now(timezone.utc)
        for row, p in enumerate(self._passes):
            item = self.table.item(row, 6)
            if item:
                item.setText(self._status_text(p, now))
                item.setForeground(
                    GREEN if p.in_progress else
                    QColor("#666") if p.aos < now else CYAN)
        future = [p for p in self._passes if p.los >= now]
        if future:
            nxt = future[0]
            if nxt.in_progress:
                remaining = (nxt.los - now).total_seconds()
                self.info.setText(
                    f"🛰 {nxt.satellite} è in corso: max {nxt.max_elevation:.0f}° "
                    f"alle {nxt.max_time:%H:%M:%S} UTC, LOS tra "
                    f"{max(0, int(remaining // 60))}m {max(0, int(remaining % 60)):02d}s.")
            else:
                self.info.setText(
                    f"Prossimo passaggio: {nxt.satellite} {_fmt_countdown((nxt.aos - now).total_seconds())} "
                    f"({nxt.aos:%d/%m %H:%M:%S} UTC), max {nxt.max_elevation:.0f}° "
                    f"alle {nxt.max_time:%H:%M:%S} UTC, "
                    f"azimut {nxt.aos_azimuth:.0f}° → {nxt.los_azimuth:.0f}°.")
        elif self._passes:
            self.info.setText("Nessun passaggio nel periodo scelto: aumenta "
                              "l'orizzonte o abbassa l'elevazione minima.")
        else:
            self.info.setText("Nessun passaggio trovato.")
        if self._truncated:
            self.info.setText(
                self.info.text() + "  —  Calcolo limitato ai primi 16 satelliti "
                "selezionati: scegline uno dall'elenco per il dettaglio.")

    def _on_selection(self):
        row = self.table.currentRow()
        if not (0 <= row < len(self._passes)):
            return
        p = self._passes[row]
        tle = next((t for t in self.main.all_tles if t.name == p.satellite), None)
        if tle is None:
            return
        key = (p.satellite, p.aos)
        pts = self._paths.get(key)
        if pts is None:
            pts = polar_path(tle, self.main.user_lat, self.main.user_lng,
                             p.aos, p.los)
            self._paths[key] = pts
            if len(self._paths) > 80:
                self._paths.pop(next(iter(self._paths)))
        cur = current_look(tle, self.main.user_lat, self.main.user_lng)
        self.polar.set_pass(
            p.satellite, pts, current=cur,
            aos=(p.aos_azimuth, self.min_el_spin.value()),
            los=(p.los_azimuth, self.min_el_spin.value()),
            max_point=(p.max_azimuth, p.max_elevation),
            aos_time=p.aos, los_time=p.los, max_el=p.max_elevation)

    def _tick(self):
        if not self.isVisible():
            return
        self.refresh(force=False)
        # aggiorna il punto "ora" e il conto alla rovescia
        self._update_countdowns()
        self._on_selection()

    def showEvent(self, event):
        super().showEvent(event)
        self._rebuild_scope()
        self.refresh(force=True)
