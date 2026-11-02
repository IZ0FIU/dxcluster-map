import urllib.request
import logging
from dataclasses import dataclass
from typing import List

log = logging.getLogger(__name__)

@dataclass
class SatelliteTLE:
    name: str
    line1: str
    line2: str

class SatelliteProvider:
    URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=tle"

    def fetch_tles(self) -> List[SatelliteTLE]:
        try:
            with urllib.request.urlopen(self.URL, timeout=15) as response:
                data = response.read().decode('utf-8')
            
            lines = [line.strip() for line in data.splitlines() if line.strip()]
            tles = []
            for i in range(0, len(lines), 3):
                if i + 2 < len(lines):
                    tles.append(SatelliteTLE(name=lines[i], line1=lines[i+1], line2=lines[i+2]))
            log.info(f"Scaricati {len(tles)} TLE satelliti.")
            return tles
        except Exception as e:
            log.error(f"Errore fetch TLE: {e}")
            return []
