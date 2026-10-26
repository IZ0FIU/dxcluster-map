import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import requests

from models import Spot
from .base import SpotProvider

log = logging.getLogger(__name__)


class SpotholeProvider(SpotProvider):
    """
    Provider basato sull'API pubblica di Spothole.
    Doc: https://spothole.app/apidocs
    """

    BASE_URL = "https://spothole.app/api/v1"
    TIMEOUT = 15

    def __init__(self, endpoint: str = "/spots", extra_params: Optional[dict] = None):
        self.endpoint = endpoint
        self.extra_params = extra_params or {}

    def fetch_spots(self, limit: int = 200) -> List[Spot]:
        params = {"limit": limit, **self.extra_params}
        url = f"{self.BASE_URL}{self.endpoint}"
        try:
            resp = requests.get(url, params=params, timeout=self.TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as e:
            log.error("Errore fetch Spothole: %s", e)
            return []

        # Spothole può restituire {"spots": [...]} oppure direttamente una lista
        raw = payload.get("spots", payload) if isinstance(payload, dict) else payload
        spots = [self._to_spot(item) for item in raw]
        spots = [s for s in spots if s is not None]
        log.info("Ricevuti %d spot (di cui %d con coordinate)",
                 len(spots), sum(1 for s in spots if s.has_coords))
        return spots

    def _to_spot(self, item: dict) -> Optional[Spot]:
        try:
            freq_hz = item.get("freq") or item.get("frequency") or 0
            freq_khz = float(freq_hz) / 1000.0 if freq_hz > 100000 else float(freq_hz)

            lat, lng = self._extract_coords(item)

            ts = item.get("timestamp") or item.get("time")
            timestamp = self._parse_ts(ts)

            dxcc = item.get("dxcc") or item.get("dx_entity") or {}
            dxcc_name = dxcc.get("name") if isinstance(dxcc, dict) else None

            # Nominativo dello spotter: Spothole usa de_call
            spotter = (
                item.get("de_call")
                or item.get("de_call_sign")
                or item.get("spotter")
                or ""
            )
            # Nominativo DX
            dx_call = (
                item.get("dx_call")
                or item.get("dx_call_sign")
                or item.get("call")
                or ""
            )

            return Spot(
                spotter=str(spotter),
                dx_call=str(dx_call),
                freq_khz=freq_khz,
                mode=str(item.get("mode", "")),
                comment=str(item.get("comment", "")),
                timestamp=timestamp,
                lat=lat,
                lng=lng,
                dxcc=dxcc_name,
                source="spothole",
                spotter_continent=item.get("de_continent"),
                dx_continent=item.get("dx_continent"),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Spot scartato (%s): %s", e, item)
            return None





    @staticmethod
    def _extract_coords(item: dict) -> Tuple[Optional[float], Optional[float]]:
        # Spothole usa dx_latitude / dx_longitude per la stazione DX
        lat = item.get("dx_latitude")
        lng = item.get("dx_longitude")
        # Fallback: se mancano, prova de_latitude / de_longitude (spotter)
        if lat is None:
            lat = item.get("de_latitude")
            lng = item.get("de_longitude")
        # Fallback estremo per altri provider (non Spothole)
        if lat is None:
            lat = item.get("lat") or item.get("latitude")
            lng = item.get("lng") or item.get("lon") or item.get("longitude")
        try:
            if lat is not None and lng is not None:
                return float(lat), float(lng)
            return None, None
        except (TypeError, ValueError):
            return None, None

    @staticmethod
    def _parse_ts(value) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return datetime.now(timezone.utc)
