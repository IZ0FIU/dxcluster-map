import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional, Dict, List

import requests

log = logging.getLogger(__name__)


@dataclass
class SolarData:
    sfi: Optional[int] = None
    a_index: Optional[int] = None
    k_index: Optional[int] = None
    updated: str = ""
    band_conditions: Optional[Dict[str, str]] = None
    vhf_conditions: Optional[Dict[str, str]] = None
    forecast: Optional[List[Dict[str, str]]] = None
    geomag_field: Optional[str] = None
    signal_noise: Optional[str] = None


class SolarProvider:
    URL = "https://www.hamqsl.com/solarxml.php"
    TIMEOUT = 10
    RETRIES = 3
    USER_AGENT = "DXClusterMap/1.0 (+ham radio spot viewer)"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.USER_AGENT

    def _get(self) -> bytes:
        last_exc = None
        for attempt in range(self.RETRIES):
            try:
                resp = self.session.get(self.URL, timeout=self.TIMEOUT)
                resp.raise_for_status()
                return resp.content
            except requests.RequestException as e:
                last_exc = e
                if attempt < self.RETRIES - 1:
                    wait = 2 ** attempt
                    log.warning("Solar: retry %d/%d fra %ds: %s", attempt + 1, self.RETRIES, wait, e)
                    time.sleep(wait)
        raise last_exc

    def fetch(self) -> SolarData:
        try:
            xml_data = self._get()
            root = ET.fromstring(xml_data)
            solardata = root.find('solardata')
            if solardata is None:
                return SolarData()

            def get_int(tag):
                el = solardata.find(tag)
                return int(el.text) if el is not None and el.text else None

            # Condizioni bande HF
            band_conditions = {}
            calc_cond = solardata.find('calculatedconditions')
            if calc_cond is not None:
                for band in calc_cond.findall('band'):
                    name = band.get('name', '')
                    time = band.get('time', '')
                    cond = band.text
                    if name and time and cond:
                        band_conditions[f"{name} {time.title()}"] = cond

            # Condizioni VHF (stile widget HamQSL solar101vhf)
            vhf_conditions = {}
            calc_vhf = solardata.find('calculatedvhfconditions')
            if calc_vhf is not None:
                for ph in calc_vhf.findall('phenomenon'):
                    name = ph.get('name', '')
                    loc = ph.get('location', '')
                    cond = ph.text
                    if name and cond:
                        vhf_conditions[f"{name} ({loc})"] = cond

            geomag = solardata.findtext('geomagfield', default='')
            signal_noise = solardata.findtext('signalnoise', default='')

            return SolarData(
                sfi=get_int('solarflux'),
                a_index=get_int('aindex'),
                k_index=get_int('kindex'),
                updated=solardata.findtext('updated', default=''),
                band_conditions=band_conditions,
                vhf_conditions=vhf_conditions,
                geomag_field=geomag,
                signal_noise=signal_noise
            )
        except (requests.RequestException, ET.ParseError) as e:
            log.error("Errore fetch dati solari: %s", e)
            return SolarData()
