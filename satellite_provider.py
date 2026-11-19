import logging
import os
import time
from dataclasses import dataclass
from typing import List

import requests

log = logging.getLogger(__name__)


@dataclass
class SatelliteTLE:
    name: str
    line1: str
    line2: str


class SatelliteProvider:
    URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=tle"
    TIMEOUT = 15
    RETRIES = 3
    USER_AGENT = "DXClusterMap/1.0 (+ham radio spot viewer)"
    # CelesTrak limita le query ripetute (403): non rifetchare più di una
    # volta al giorno e conserva una cache su disco come fallback offline.
    CACHE_MAX_AGE = 24 * 3600
    CACHE_FILE = os.path.expanduser("~/.cache/DXClusterMap/amateur_tle.txt")

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.USER_AGENT

    def _read_cache(self):
        try:
            age = time.time() - os.path.getmtime(self.CACHE_FILE)
            with open(self.CACHE_FILE, encoding="utf-8") as f:
                return f.read(), age
        except OSError:
            return None, None

    def _write_cache(self, text: str):
        try:
            os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            log.warning("TLE: cache non scrivibile: %s", e)

    def _get(self) -> str:
        last_exc = None
        for attempt in range(self.RETRIES):
            try:
                resp = self.session.get(self.URL, timeout=self.TIMEOUT)
                resp.raise_for_status()
                resp.encoding = "utf-8"
                return resp.text
            except requests.RequestException as e:
                last_exc = e
                if attempt < self.RETRIES - 1:
                    wait = 2 ** attempt
                    log.warning("TLE: retry %d/%d fra %ds: %s",
                                attempt + 1, self.RETRIES, wait, e)
                    time.sleep(wait)
        raise last_exc

    def fetch_tles(self) -> List[SatelliteTLE]:
        cached, age = self._read_cache()
        # Cache fresca (< 24 h): usa quella, niente richiesta di rete
        if cached is not None and age is not None and age < self.CACHE_MAX_AGE:
            tles = self._parse(cached)
            if tles:
                log.info("TLE: %d satelliti dalla cache (%.1f h fa).",
                         len(tles), age / 3600)
                return tles
        try:
            data = self._get()
            self._write_cache(data)
        except requests.RequestException as e:
            log.error("Errore fetch TLE: %s", e)
            if cached is not None:
                tles = self._parse(cached)
                if tles:
                    log.warning("TLE: uso la cache offline (%d satelliti, "
                                "%.1f giorni fa).", len(tles), age / 86400)
                    return tles
            return []

        tles = self._parse(data)
        log.info("Scaricati %d TLE satelliti.", len(tles))
        return tles

    @staticmethod
    def _parse(data: str) -> List[SatelliteTLE]:
        lines = [line.strip() for line in data.splitlines() if line.strip()]
        tles = []
        for i in range(0, len(lines), 3):
            if i + 2 < len(lines):
                tles.append(SatelliteTLE(
                    name=lines[i][:64],
                    line1=lines[i + 1],
                    line2=lines[i + 2],
                ))
        return tles
