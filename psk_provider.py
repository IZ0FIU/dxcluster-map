"""Provider PSK Reporter (https://pskreporter.info).

Scarica le ricezioni caricate dal proprio WSJT-X ("Enable PSK Reporter spotting")
e le trasforma in Spot per la mappa: per ogni report di IZ0FIU (receiver) sappiamo
chi ha ricevuto (sender), con locator quando noto e altrimenti il centro DXCC.

Nota di utilizzo: l'API ufficiale non andrebbe interrogata più spesso di
una volta ogni 5 minuti.
"""
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import requests

from models import Spot
from dxcc_table import lookup_dxcc
from geo import maidenhead_to_latlon

log = logging.getLogger(__name__)


class PSKReporterProvider:
    URL = "https://retrieve.pskreporter.info/query"
    TIMEOUT = 30
    RETRIES = 2
    USER_AGENT = "DXClusterMap/1.0 (+ham radio spot viewer)"

    def __init__(self, receiver_callsign: str = ""):
        self.receiver_callsign = receiver_callsign.strip().upper()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.USER_AGENT

    def fetch(self, minutes: int = 30) -> Tuple[List[Spot], Optional[str]]:
        """Ritorna (spots, errore). errore è None se tutto ok."""
        if not self.receiver_callsign:
            return [], "nominativo ricevitore non impostato"
        params = {
            "receiverCallsign": self.receiver_callsign,
            "rronly": "1",        # solo i report di ricezione
            "noactive": "1",      # niente elenco receiver attivi
            "flowStartSeconds": f"-{minutes * 60}",
            "appcontact": "dxcluster-map@example.org",  # consigliato da PSKR
        }
        try:
            resp = self.session.get(self.URL, params=params, timeout=self.TIMEOUT)
            # 429/503: l'API limita le query per IP. NON ritentare subito,
            # il prossimo polling (5-10 min) sarà la our retry.
            if resp.status_code in (429, 503):
                return [], f"rate limit HTTP {resp.status_code} — riprovo al prossimo ciclo"
            resp.raise_for_status()
            return self._parse(resp.text), None
        except requests.RequestException as e:
            log.warning("PSKR: errore di rete: %s", e)
            return [], f"errore di rete: {e}"

    @staticmethod
    def _continent(lat: float, lng: float) -> Optional[str]:
        """Continente approssimato da coordinate (bastano box grezzi:
        serve solo per il filtro 'continente spotter')."""
        if lat < -60:
            return "AN"
        if lat < -30:  # Sud America / Oceania meridionale
            return "OC" if lng > 110 or lng < -140 else "SA"
        if lng < -30:  # emisfero ovest
            return "SA" if lat < 13 else "NA"
        if lng > 180 - 0:  # non capita: lng in [-180, 180]
            return "AS"
        if lng >= 110:
            return "OC" if lat < 25 else "AS"
        if lng >= 40:
            return "AS"
        if lat < 35:  # Africa sotto il Mediterraneo
            return "AF"
        return "EU"   # resto: Europa

    def _parse(self, text: str) -> List[Spot]:
        text = text.strip()
        # Il servizio può rispondere con un JSON di errore (rate limit, ecc.)
        if text.startswith("{"):
            try:
                import json
                msg = json.loads(text).get("message", "risposta inattesa")
                log.warning("PSKR: %s", msg)
                return []
            except ValueError:
                return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            log.error("PSKR: XML non valido: %s", e)
            return []

        spots: List[Spot] = []
        receiver_locator = None
        for rec in root.findall("receptionReport"):
            try:
                sender = rec.get("senderCallsign", "").upper()[:16]
                if not sender:
                    continue
                if receiver_locator is None:
                    receiver_locator = rec.get("receiverLocator")

                # Il "spotter" in PSKR è il receiver (cioè l'utente): il suo
                # continente serve al filtro "continente" della UI.
                recv_cont = None
                if receiver_locator:
                    try:
                        rlat, rlng = maidenhead_to_latlon(
                            receiver_locator.strip().upper()[:6])
                        recv_cont = self._continent(rlat, rlng)
                    except ValueError:
                        pass
                freq_hz = int(float(rec.get("frequency", "0") or 0))
                if freq_hz <= 0:
                    continue
                ts_raw = rec.get("flowStartSeconds")
                ts = (datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
                      if ts_raw else datetime.now(timezone.utc))
                mode = (rec.get("mode") or "FT8")[:16]
                snr = rec.get("sNR") or rec.get("snr")
                sender_locator = rec.get("senderLocator")

                lat = lng = None
                country = None
                if sender_locator:
                    loc = sender_locator.strip().upper()
                    if len(loc) >= 4:
                        loc = loc[:6]  # le griglie a 8 caratteri si troncano
                        try:
                            lat, lng = maidenhead_to_latlon(loc)
                        except ValueError:
                            lat = lng = None
                if lat is None:
                    hit = lookup_dxcc(sender)
                    if hit:
                        lat, lng, country = hit

                comment = "via PSK Reporter"
                if sender_locator:
                    comment += f" — locator {sender_locator}"
                if snr:
                    comment += f" — SNR {snr}"

                spots.append(Spot(
                    spotter="PSKR",
                    dx_call=sender,
                    freq_khz=freq_hz / 1000.0,
                    mode=mode,
                    comment=comment[:120],
                    timestamp=ts,
                    lat=lat,
                    lng=lng,
                    country=country,
                    source="pskr",
                    spotter_continent=recv_cont,
                ))
            except (ValueError, KeyError) as e:
                log.debug("Report PSKR scartato: %s (%s)", dict(rec.attrib), e)
        with_coords = sum(1 for s in spots if s.lat is not None and s.lng is not None)
        log.info("PSKR: %d ricezioni per %s negli ultimi %d minuti "
                 "(di cui %d con coordinate)", len(spots), self.receiver_callsign,
                 30, with_coords)
        return spots
