from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Bande HF (in kHz) — estendi pure con VHF/UHF se ti serve
BANDS = [
    ("160m", 1800, 2000), ("80m", 3500, 4000), ("60m", 5330, 5406),
    ("40m", 7000, 7300), ("30m", 10100, 10150), ("20m", 14000, 14350),
    ("17m", 18068, 18168), ("15m", 21000, 21450), ("12m", 24890, 24990),
    ("10m", 28000, 29700), ("6m", 50000, 54000),
]

# Colore marker per banda (usato dalla mappa)
BAND_COLORS = {
    "160m": "#8b0000", "80m": "#b22222", "60m": "#ff4500",
    "40m": "#ff8c00", "30m": "#ffd700", "20m": "#32cd32",
    "17m": "#00ced1", "15m": "#1e90ff", "12m": "#9370db",
    "10m": "#ff69b4", "6m": "#ff1493", "?": "#888888",
}

# Categorizzazione dei modi
CW_MODES = {"CW"}
PHONE_MODES = {"SSB", "USB", "LSB", "AM", "FM", "NFM", "WFM", "PHONE", "VOICE"}
DIGITAL_MODES = {
    "FT8", "FT4", "FT2", "JT65", "JT9", "JS8", "RTTY", "PSK", "PSK31", "PSK63",
    "PSK125", "OLIVIA", "MFSK", "DOMINO", "HELL", "SSTV", "DIGITAL", "DATA",
    "DIGI", "DMR", "D-STAR", "DSTAR", "C4FM", "M17", "DV", "PKT", "PACKET",
}


def mode_category(mode: str) -> str:
    """Ritorna 'CW', 'PHONE', 'DIGITAL' o '?'."""
    if not mode:
        return "?"
    m = mode.upper().strip()
    if m in CW_MODES:
        return "CW"
    if m in PHONE_MODES:
        return "PHONE"
    if m in DIGITAL_MODES:
        return "DIGITAL"
    # fallback euristico per modi non elencati
    if m.startswith(("SSB", "USB", "LSB", "FM", "AM")):
        return "PHONE"
    if any(k in m for k in ("FT", "PSK", "RTTY", "JT", "MFSK", "OLIVIA", "JS8", "DIGI", "DATA")):
        return "DIGITAL"
    return "?"
def band_from_freq(freq_khz: Optional[float]) -> str:
    if not freq_khz:
        return "?"
    for name, low, high in BANDS:
        if low <= freq_khz <= high:
            return name
    return "?"


@dataclass
class Spot:
    spotter: str
    dx_call: str
    freq_khz: float
    mode: str
    comment: str
    timestamp: datetime
    lat: Optional[float] = None
    lng: Optional[float] = None
    dxcc: Optional[str] = None
    source: str = ""
    spotter_continent: Optional[str] = None   # de_continent (chi pubblica)
    dx_continent: Optional[str] = None        # dx_continent (stazione DX)
    country: Optional[str] = None  # Nome della nazione (DXCC)
    # Paese dello spotter (21)
    spotter_country: Optional[str] = None
    spotter_flag: Optional[str] = None
    # True se la decodifica WSJT-X è indirizzata al nostro nominativo
    calling_me: bool = False

    @property
    def id(self) -> str:
        ts = self.timestamp.isoformat() if self.timestamp else ""
        return f"{self.dx_call}@{self.freq_khz}@{ts}"

    @property
    def band(self) -> str:
        return band_from_freq(self.freq_khz)

    @property
    def color(self) -> str:
        return BAND_COLORS.get(self.band, BAND_COLORS["?"])

    @property
    def mode_category(self) -> str:
        return mode_category(self.mode)
    
    @property
    def has_coords(self) -> bool:
        return self.lat is not None and self.lng is not None

    @property
    def has_continent(self) -> bool:
        return self.spotter_continent is not None


# ---------- Alert estesi (20) ----------
def parse_alert_entries(text: str) -> list:
    """Parsing degli alert: voci separate da virgola.
    Formati ammessi:
      - 'IK1XYZ'          nominativo esatto
      - 'IK1*' o 'IK1'    prefisso (tutte le stazioni che iniziano con IK1)
      - 'IK1@20m'         con filtro banda opzionale
    Ritorna una lista di tuple (base, band) con base in maiuscolo, senza '*'.
    """
    entries = []
    for raw in (text or "").split(","):
        item = raw.strip().upper()
        if not item:
            continue
        band = None
        if "@" in item:
            item, _, band = item.partition("@")
            band = band.strip() or None
        item = item.replace("*", "").strip()
        if item:
            entries.append((item, band))
    return entries


def spot_matches_alert(spot, entries) -> bool:
    """True se lo spot corrisponde a una delle voci di alert (20)."""
    call = (spot.dx_call or "").upper()
    band = spot.band
    for base, alert_band in entries:
        if alert_band and (band or "").lower() != alert_band.lower():
            continue
        if call.startswith(base):
            return True
    return False
