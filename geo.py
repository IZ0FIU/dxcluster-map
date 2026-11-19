import math
from datetime import date, datetime, timedelta, timezone


def maidenhead_to_latlon(locator: str) -> tuple[float, float]:
    """Converte un locator Maidenhead (4 o 6 caratteri) nel centro del quadrato.
    Restituisce (lat, lon) in gradi decimali."""
    loc = locator.strip().upper()
    if len(loc) not in (4, 6):
        raise ValueError("Locator non valido: usa 4 o 6 caratteri (es. JN45 o JN45AA)")

    lon = (ord(loc[0]) - ord('A')) * 20.0 - 180.0
    lat = (ord(loc[1]) - ord('A')) * 10.0 - 90.0
    lon += int(loc[2]) * 2.0
    lat += int(loc[3]) * 1.0

    if len(loc) == 4:
        # centro del quadrato da 2° x 1°
        return lat + 0.5, lon + 1.0

    # subsquare (5' x 2.5')
    lon += (ord(loc[4]) - ord('A')) * (2.0 / 24.0)
    lat += (ord(loc[5]) - ord('A')) * (1.0 / 24.0)
    # centro del subsquare
    return lat + (1.0 / 24.0) / 2.0, lon + (2.0 / 24.0) / 2.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in km tra due punti sulla sfera (formula di Haversine)."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Azimuth iniziale (gradi da nord) per andare da (lat1, lon1) a (lat2, lon2)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def maidenhead_square_center(lat: float, lng: float) -> tuple[float, float]:
    """Centro del quadrato Maidenhead da 4 caratteri contenente (lat, lng).
    Usato per l'heatmap (26) e in generale per aggregare spot per griglia."""
    lng = ((lng + 180.0) % 360.0) - 180.0  # normalizza in [-180, 180)
    field_lng = math.floor((lng + 180.0) / 20.0)          # 0..17
    field_lat = math.floor((lat + 90.0) / 10.0)           # 0..17
    square_lng = math.floor((lng - (field_lng * 20.0 - 180.0)) / 2.0)   # 0..9
    square_lat = math.floor((lat - (field_lat * 10.0 - 90.0)) / 1.0)    # 0..9
    lng0 = field_lng * 20.0 - 180.0 + square_lng * 2.0
    lat0 = field_lat * 10.0 - 90.0 + square_lat * 1.0
    return lat0 + 0.5, lng0 + 1.0


def _acos_deg(cos_v: float) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_v))))


def sunrise_sunset(lat: float, lng: float, day: date | None = None) -> tuple[datetime | None, datetime | None]:
    """Alba e tramonto (UTC) per (lat, lng) nella data indicata.
    Restituisce (None, None) nelle zone polari (sole sempre su o sempre giù)."""
    if day is None:
        day = datetime.now(timezone.utc).date()

    n = day.timetuple().tm_yday
    lng_hour = lng / 15.0

    def compute(t: float, is_rise: bool) -> datetime | None:
        m = (0.9856 * t) - 3.289
        l = (m + 1.916 * math.sin(math.radians(m)) + 0.020 * math.sin(math.radians(2 * m)) + 282.634) % 360
        ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l)))) % 360
        l_quadrant = math.floor(l / 90) * 90
        ra_quadrant = math.floor(ra / 90) * 90
        ra = (ra + (l_quadrant - ra_quadrant)) / 15
        sin_dec = 0.39782 * math.sin(math.radians(l))
        cos_dec = math.cos(math.asin(sin_dec))
        zenith = 90.833
        cos_h = ((math.cos(math.radians(zenith)) - (sin_dec * math.sin(math.radians(lat)))) /
                 (cos_dec * math.cos(math.radians(lat))))
        if cos_h > 1:   # il sole non sorge mai
            return None
        if cos_h < -1:  # il sole non tramonta mai
            return None
        h = (360 - _acos_deg(cos_h)) / 15 if is_rise else _acos_deg(cos_h) / 15
        t_local = h + ra - (0.06571 * t) - 6.622
        ut = (t_local - lng_hour) % 24
        base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        return base + timedelta(hours=ut)

    t_rise = n + ((6 - lng_hour) / 24)
    t_set = n + ((18 - lng_hour) / 24)
    return compute(t_rise, True), compute(t_set, False)
