"""Previsione passaggi satelliti (AOS/LOS) e angoli di puntamento.

Usa SGP4 (pacchetto ``sgp4``) per propagare i TLE e calcolare, per una
posizione di osservatore, azimuth/elevazione e i passaggi sopra l'orizzonte.
Nessuna dipendenza da numpy: basta il wheel di sgp4.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sgp4.api import Satrec, jday

from satellite_provider import SatelliteTLE

# WGS84
_A = 6378.137          # semiasse maggiore (km)
_F = 1.0 / 298.257223563
_E2 = _F * (2.0 - _F)
_DEG = math.pi / 180.0
_TWO_PI = 2.0 * math.pi


@dataclass
class SatellitePass:
    """Un passaggio del satellite sopra l'orizzonte dell'osservatore."""

    satellite: str
    aos: datetime                 # acquisizione (elevazione = soglia)
    los: datetime                 # perdita del segnale
    max_time: datetime            # istante di massima elevazione
    max_elevation: float          # gradi
    aos_azimuth: float            # gradi da nord
    los_azimuth: float
    max_azimuth: float
    in_progress: bool = False     # già iniziato al momento del calcolo

    @property
    def duration(self) -> float:
        return (self.los - self.aos).total_seconds()

    @property
    def duration_min(self) -> float:
        return self.duration / 60.0


def _jd(dt: datetime) -> Tuple[float, float]:
    """Data/ora UTC -> (jd, frazione) per sgp4."""
    dt = dt.astimezone(timezone.utc)
    return jday(dt.year, dt.month, dt.day, dt.hour, dt.minute,
                dt.second + dt.microsecond / 1e6)


def _gmst(jd: float, fr: float) -> float:
    """Tempo siderale medio di Greenwich (radianti), formula IAU-82."""
    tut1 = ((jd - 2451545.0) + fr) / 36525.0
    temp = (-6.2e-6 * tut1 ** 3 + 0.093104 * tut1 ** 2
            + (876600.0 * 3600.0 + 8640184.812866) * tut1 + 67310.54841)
    return (temp * _DEG / 240.0) % _TWO_PI


def _observer_ecef(lat: float, lon: float, height_km: float = 0.0):
    phi = lat * _DEG
    lam = lon * _DEG
    sin_phi, cos_phi = math.sin(phi), math.cos(phi)
    n = _A / math.sqrt(1.0 - _E2 * sin_phi * sin_phi)
    x = (n + height_km) * cos_phi * math.cos(lam)
    y = (n + height_km) * cos_phi * math.sin(lam)
    z = (n * (1.0 - _E2) + height_km) * sin_phi
    return x, y, z


class _Propagator:
    """Wrappra un TLE e calcola posizione/angoli per un osservatore."""

    def __init__(self, tle: SatelliteTLE, lat: float, lon: float,
                 height_km: float = 0.0):
        self.tle = tle
        self.sat = Satrec.twoline2rv(tle.line1, tle.line2)
        self.lat = lat
        self.lon = lon
        self.obs = _observer_ecef(lat, lon, height_km)
        self.sin_lat = math.sin(lat * _DEG)
        self.cos_lat = math.cos(lat * _DEG)
        self.sin_lon = math.sin(lon * _DEG)
        self.cos_lon = math.cos(lon * _DEG)

    def look(self, when: datetime) -> Optional[Tuple[float, float, float]]:
        """Ritorna (azimuth, elevazione, distanza_km) o None se il TLE fallisce."""
        jd, fr = _jd(when)
        err, pos, _vel = self.sat.sgp4(jd, fr)
        if err != 0 or pos is None:
            return None
        g = _gmst(jd, fr)
        cos_g, sin_g = math.cos(g), math.sin(g)
        # TEME -> ECEF (rotazione attorno all'asse z)
        x = cos_g * pos[0] + sin_g * pos[1]
        y = -sin_g * pos[0] + cos_g * pos[1]
        z = pos[2]
        dx = x - self.obs[0]
        dy = y - self.obs[1]
        dz = z - self.obs[2]
        # ECEF -> topocentrico ENU
        east = -self.sin_lon * dx + self.cos_lon * dy
        north = (-self.sin_lat * self.cos_lon * dx
                 - self.sin_lat * self.sin_lon * dy
                 + self.cos_lat * dz)
        up = (self.cos_lat * self.cos_lon * dx
              + self.cos_lat * self.sin_lon * dy
              + self.sin_lat * dz)
        rng = math.sqrt(east * east + north * north + up * up)
        if rng <= 0:
            return None
        el = math.degrees(math.asin(max(-1.0, min(1.0, up / rng))))
        az = math.degrees(math.atan2(east, north)) % 360.0
        return az, el, rng

    def elevation(self, when: datetime) -> float:
        hit = self.look(when)
        return hit[1] if hit else -90.0

    def azimuth(self, when: datetime) -> float:
        hit = self.look(when)
        return hit[0] if hit else 0.0


def _refine_crossing(prop: _Propagator, t0: datetime, t1: datetime,
                     threshold: float) -> datetime:
    """Bisezione sull'istante in cui l'elevazione attraversa ``threshold``."""
    f0 = prop.elevation(t0) - threshold
    lo, hi = t0, t1
    for _ in range(24):
        mid = lo + (hi - lo) / 2
        fm = prop.elevation(mid) - threshold
        if (fm >= 0) == (f0 >= 0):
            lo, f0 = mid, fm
        else:
            hi = mid
    return lo + (hi - lo) / 2


def _find_max(prop: _Propagator, start: datetime, end: datetime,
              step_s: float = 5.0) -> Tuple[datetime, float, float]:
    """Massima elevazione in [start, end] con campionamento fine."""
    best_t, best_el, best_az = start, -90.0, 0.0
    t = start
    while t <= end:
        hit = prop.look(t)
        if hit and hit[1] > best_el:
            best_az, best_el = hit[0], hit[1]
            best_t = t
        t += timedelta(seconds=step_s)
    hit = prop.look(end)
    if hit and hit[1] > best_el:
        best_az, best_el = hit[0], hit[1]
        best_t = end
    return best_t, best_el, best_az


def find_passes(tle: SatelliteTLE, lat: float, lon: float,
                start: Optional[datetime] = None, hours: float = 24.0,
                min_elevation: float = 5.0, step_s: float = 30.0,
                max_passes: int = 40) -> List[SatellitePass]:
    """Calcola i passaggi di ``tle`` sopra ``min_elevation`` nelle prossime ore.

    Il primo elemento può essere un passaggio già in corso (``in_progress``).
    """
    start = (start or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        prop = _Propagator(tle, lat, lon)
    except (ValueError, TypeError):
        return []

    passes: List[SatellitePass] = []
    end = start + timedelta(hours=hours)

    # Se il satellite è già sopra la soglia, risali all'AOS (max 20 minuti).
    first_el = prop.elevation(start)
    in_progress = first_el >= min_elevation
    if in_progress:
        aos = None
        t_prev = start
        for i in range(1, 41):  # 40 * 30 s = 20 min
            t = start - timedelta(seconds=step_s * i)
            if prop.elevation(t) < min_elevation:
                aos = _refine_crossing(prop, t, t_prev, min_elevation)
                break
            t_prev = t
        if aos is None:
            aos = start

    prev_t = start
    prev_el = first_el
    current_aos = start if in_progress else None
    t = start + timedelta(seconds=step_s)

    while t <= end and len(passes) < max_passes:
        el = prop.elevation(t)
        if current_aos is None:
            if prev_el < min_elevation <= el:
                current_aos = _refine_crossing(prop, prev_t, t, min_elevation)
        else:
            if el < min_elevation:
                los = _refine_crossing(prop, prev_t, t, min_elevation)
                mt, max_el, max_az = _find_max(prop, current_aos, los)
                passes.append(SatellitePass(
                    satellite=tle.name,
                    aos=current_aos,
                    los=los,
                    max_time=mt,
                    max_elevation=max_el,
                    aos_azimuth=prop.azimuth(current_aos),
                    los_azimuth=prop.azimuth(los),
                    max_azimuth=max_az,
                    in_progress=in_progress and not passes,
                ))
                in_progress = False
                current_aos = None
        prev_t, prev_el = t, el
        t += timedelta(seconds=step_s)

    # Passaggio ancora in corso alla fine della finestra: chiudilo a ``end``.
    if current_aos is not None and len(passes) < max_passes:
        mt, max_el, max_az = _find_max(prop, current_aos, end)
        passes.append(SatellitePass(
            satellite=tle.name,
            aos=current_aos,
            los=end,
            max_time=mt,
            max_elevation=max_el,
            aos_azimuth=prop.azimuth(current_aos),
            los_azimuth=prop.azimuth(end),
            max_azimuth=max_az,
            in_progress=in_progress,
        ))
    return passes


def next_pass(tle: SatelliteTLE, lat: float, lon: float,
              min_elevation: float = 5.0) -> Optional[SatellitePass]:
    """Il prossimo passaggio (o quello in corso), entro 48 ore."""
    passes = find_passes(tle, lat, lon, hours=48.0,
                         min_elevation=min_elevation, max_passes=1)
    return passes[0] if passes else None


def polar_path(tle: SatelliteTLE, lat: float, lon: float,
               aos: datetime, los: datetime,
               margin_s: float = 90.0, step_s: float = 15.0
               ) -> List[Tuple[float, float]]:
    """Punti (azimuth, elevazione) del passaggio per il polar plot.

    Include un margine prima dell'AOS e dopo il LOS per mostrare la salita e
    la discesa; i punti sotto -3° vengono scartati (fuori dal grafico).
    """
    try:
        prop = _Propagator(tle, lat, lon)
    except (ValueError, TypeError):
        return []
    t = aos - timedelta(seconds=margin_s)
    stop = los + timedelta(seconds=margin_s)
    pts: List[Tuple[float, float]] = []
    while t <= stop:
        hit = prop.look(t)
        if hit and hit[1] >= -3.0:
            pts.append((hit[0], hit[1]))
        t += timedelta(seconds=step_s)
    return pts


def current_look(tle: SatelliteTLE, lat: float, lon: float,
                 when: Optional[datetime] = None
                 ) -> Optional[Tuple[float, float, float]]:
    """(azimuth, elevazione, distanza) del satellite in questo istante."""
    try:
        prop = _Propagator(tle, lat, lon)
    except (ValueError, TypeError):
        return None
    return prop.look(when or datetime.now(timezone.utc))
