"""Lettura del log ADIF di WSJT-X e stato "già lavorato" (worked-before).

Il file tipico è ``wsjtx_log.adi``. Il parser è volutamente minimale: legge i
tag ADIF ``<NOME:LUNGHEZZA[:TIPO]>valore`` e tiene solo i campi utili
(nominativo, banda, modo, paese/DXCC). Serve per evidenziare nella lista gli
spot già a log e segnalare i nuovi DXCC o le nuove bande.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, Set, Tuple

from dxcc_table import lookup_dxcc

# I tag ADIF possono contenere lettere, cifre, underscore, punti e trattini
# (es. APP_WSJT-X_RigControl). La lunghezza è in BYTE, non in caratteri.
_TAG_RE = re.compile(rb"<([A-Za-z0-9_.\-]+)(?::(\d+)(?::[A-Za-z])?)?>")

# Suffissi che non identificano una stazione diversa
_PORTABLE = {"P", "M", "MM", "AM", "QRP", "A", "R", "T", "QRP"}

# Stati possibili per uno spot
NEW_COUNTRY = "new_country"   # entità DXCC mai lavorata
NEW_BAND = "new_band"         # entità lavorata, ma non su questa banda
NEW_CALL = "new_call"         # nominativo mai lavorato (entità/banda già a log)
WORKED = "worked"             # già a log su questa banda


def normalize_call(call: str) -> str:
    """Nominativo "base": toglie suffissi portatili e prefissi di paese.

    Esempi: ``IK1XYZ/P`` -> ``IK1XYZ``; ``3A/IK1XYZ`` -> ``IK1XYZ``.
    """
    call = (call or "").strip().upper()
    if not call:
        return ""
    parts = [p for p in call.split("/") if p]
    if len(parts) <= 1:
        return call
    # scarta i suffissi portatili (P, M, MM, ...)
    meaningful = [p for p in parts if p not in _PORTABLE]
    if not meaningful:
        return parts[0]
    # tra i restanti scegli la parte più "nominativo": almeno una cifra e
    # almeno due lettere; a parità, la più lunga.
    def score(p: str) -> Tuple[int, int]:
        has_digit = any(c.isdigit() for c in p)
        has_alpha = sum(c.isalpha() for c in p) >= 2
        return (1 if (has_digit and has_alpha) else 0, len(p))
    return max(meaningful, key=score)


def _norm_country(name: str) -> str:
    # Normalizza nome e abbreviazioni più comuni tra i log ADIF/WSJT-X e la
    # tabella DXCC interna (es. "Fed. Rep. of Germany" ↔ "Germany").
    key = " ".join((name or "").strip().lower().replace("&", "and").split())
    key = key.replace(".", "")
    return _COUNTRY_ALIASES.get(key, key)


# Alias delle entità DXCC: stesso paese scritto in modi diversi.
# Non unire entità distinte (Inghilterra, Scozia, Galles e Irlanda del Nord
# restano separate, come nel DXCC).
_COUNTRY_ALIASES = {
    "fed rep of germany": "germany",
    "federal republic of germany": "germany",
    "frg": "germany",
    "deutschland": "germany",
    "united states of america": "united states",
    "usa": "united states",
    "us": "united states",
    "italian republic": "italy",
    "italia": "italy",
    "russian federation": "russia",
    "european russia": "russia",
    "asiatic russia": "russia",
    "republic of korea": "south korea",
    "korea republic of": "south korea",
    "korea, republic of": "south korea",
    "korea": "south korea",
    "democratic peoples republic of korea": "north korea",
    "peoples republic of china": "china",
    "prc": "china",
    "czechia": "czech republic",
    "slovak republic": "slovakia",
    "the netherlands": "netherlands",
    "holland": "netherlands",
    "kingdom of the netherlands": "netherlands",
    "french republic": "france",
    "kingdom of spain": "spain",
    "portuguese republic": "portugal",
    "swiss confederation": "switzerland",
    "republic of austria": "austria",
    "republic of poland": "poland",
    "hellenic republic": "greece",
    "republic of turkey": "turkey",
    "turkiye": "turkey",
    "türkiye": "turkey",
    "republic of finland": "finland",
    "kingdom of norway": "norway",
    "kingdom of sweden": "sweden",
    "kingdom of denmark": "denmark",
    "republic of ireland": "ireland",
    "united mexican states": "mexico",
    "argentine republic": "argentina",
    "federative republic of brazil": "brazil",
    "brasil": "brazil",
    "republic of india": "india",
    "republic of south africa": "south africa",
}


def _norm_band(band: str) -> str:
    return (band or "").strip().lower()


def country_for(call: str, country: Optional[str] = None) -> Optional[str]:
    """Nome paese normalizzato: usa il campo ADIF, altrimenti la tabella DXCC."""
    if country:
        return _norm_country(country)
    hit = lookup_dxcc(call)
    return _norm_country(hit[2]) if hit else None


def default_adif_path() -> str:
    """Percorso più probabile di ``wsjtx_log.adi`` su questa piattaforma."""
    candidates = []
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            candidates += [
                os.path.join(base, "WSJT-X", "wsjtx_log.adi"),
                os.path.join(base, "WSJT-X", "wsjtx_log.adi"),
            ]
    elif sys.platform == "darwin":
        candidates.append(os.path.join(home, "Library", "Application Support",
                                       "WSJT-X", "wsjtx_log.adi"))
    else:
        candidates += [
            os.path.join(home, ".local", "share", "WSJT-X", "wsjtx_log.adi"),
            os.path.join(home, ".config", "WSJT-X", "wsjtx_log.adi"),
        ]
    candidates += [
        os.path.join(home, "wsjtx_log.adi"),
        os.path.join(home, "Documents", "wsjtx_log.adi"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_adif(text: bytes):
    """Genera i record ADIF come dizionari {TAG: valore} (tag in maiuscolo)."""
    # Salta l'eventuale intestazione fino a <EOH>
    upper = text.upper()
    eoh = upper.find(b"<EOH>")
    pos = eoh + 5 if eoh >= 0 else 0
    record: Dict[str, str] = {}
    while pos < len(text):
        m = _TAG_RE.search(text, pos)
        if not m:
            break
        tag = m.group(1).decode("ascii", errors="ignore").upper()
        length = int(m.group(2)) if m.group(2) else None
        value_start = m.end()
        if tag == "EOR":
            if record:
                yield record
                record = {}
            pos = value_start
            continue
        if tag == "EOH":
            pos = value_start
            continue
        if length is None:
            # Tag senza lunghezza: valore vuoto, si prosegue.
            pos = value_start
            continue
        value_end = min(len(text), value_start + length)
        value = _decode(text[value_start:value_end]).strip()
        record[tag] = value
        pos = value_end
    if record:
        yield record


@dataclass
class AdifLog:
    """Indice del log ADIF per le verifiche worked-before."""

    path: str = ""
    total_qsos: int = 0
    loaded_at: Optional[datetime] = None
    mtime: Optional[float] = None
    error: str = ""
    worked_calls: Set[str] = field(default_factory=set)
    worked_band: Dict[str, Set[str]] = field(default_factory=dict)
    worked_countries: Set[str] = field(default_factory=set)
    worked_band_country: Dict[str, Set[str]] = field(default_factory=dict)
    countries: Set[str] = field(default_factory=set)

    @property
    def loaded(self) -> bool:
        return self.loaded_at is not None and not self.error

    def load(self, path: Optional[str] = None) -> bool:
        """(Ri)carica il log. Ritorna True se il file è stato letto."""
        if path is not None:
            self.path = path
        self.error = ""
        if not self.path:
            self._clear()
            self.error = "nessun file ADIF configurato"
            return False
        try:
            mtime = os.path.getmtime(self.path)
            with open(self.path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            self._clear()
            self.error = f"impossibile leggere {self.path}: {exc}"
            return False

        self._clear()
        self.mtime = mtime
        for rec in parse_adif(raw):
            call = normalize_call(rec.get("CALL", ""))
            if not call:
                continue
            band = _norm_band(rec.get("BAND", ""))
            country = country_for(call, rec.get("COUNTRY"))
            self.total_qsos += 1
            self.worked_calls.add(call)
            if band:
                self.worked_band.setdefault(band, set()).add(call)
            if country:
                self.countries.add(country)
                self.worked_countries.add(country)
                if band:
                    self.worked_band_country.setdefault(band, set()).add(country)
        self.loaded_at = datetime.now(timezone.utc)
        return True

    def _clear(self):
        self.total_qsos = 0
        self.loaded_at = None
        self.mtime = None
        self.worked_calls.clear()
        self.worked_band.clear()
        self.worked_countries.clear()
        self.worked_band_country.clear()
        self.countries.clear()

    def status_for(self, call: str, band: str,
                   country: Optional[str] = None) -> Optional[str]:
        """Stato worked-before di un nominativo su una banda.

        Ritorna ``None`` se il log non è caricato, altrimenti uno tra
        ``worked``, ``new_country``, ``new_band``, ``new_call``.
        """
        if not self.loaded:
            return None
        base = normalize_call(call)
        if not base:
            return None
        band = _norm_band(band)
        entity = country_for(base, country)
        if base in self.worked_band.get(band, set()):
            return WORKED
        if entity and entity not in self.worked_countries:
            return NEW_COUNTRY
        if entity and band and entity not in self.worked_band_country.get(band, set()):
            return NEW_BAND
        return NEW_CALL

    def summary(self) -> str:
        if not self.loaded:
            return self.error or "log ADIF non caricato"
        when = self.loaded_at.astimezone().strftime("%d/%m/%Y %H:%M") if self.loaded_at else "—"
        return (f"{self.total_qsos} QSO, {len(self.worked_countries)} entità DXCC, "
                f"{len(self.worked_calls)} nominativi (caricato {when})")
