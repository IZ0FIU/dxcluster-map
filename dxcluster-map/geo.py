import math

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
