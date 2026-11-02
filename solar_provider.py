import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional, Dict, List

@dataclass
class SolarData:
    sfi: Optional[int] = None
    a_index: Optional[int] = None
    k_index: Optional[int] = None
    updated: str = ""
    band_conditions: Optional[Dict[str, str]] = None
    forecast: Optional[List[Dict[str, str]]] = None  # Lista di dict per i 3 giorni
    geomag_field: Optional[str] = None
    signal_noise: Optional[str] = None

class SolarProvider:
    URL = "https://www.hamqsl.com/solarxml.php"

    def fetch(self) -> SolarData:
        try:
            with urllib.request.urlopen(self.URL, timeout=10) as response:
                xml_data = response.read()
            root = ET.fromstring(xml_data)
            solardata = root.find('solardata')
            if solardata is None:
                return SolarData()
            
            def get_int(tag):
                el = solardata.find(tag)
                return int(el.text) if el is not None and el.text else None

            # Condizioni bande
            band_conditions = {}
            calc_cond = solardata.find('calculatedconditions')
            if calc_cond is not None:
                for band in calc_cond.findall('band'):
                    name = band.get('name', '')
                    time = band.get('time', '')
                    cond = band.text
                    if name and time and cond:
                        band_conditions[f"{name} {time}"] = cond

            # Previsioni 3 giorni
            forecast = []
            calc_forecast = solardata.find('calculatedconditions')
            # Nota: HamQSL a volte usa tag diversi per le previsioni, proviamo a cercare 'forecast'
            # In alternativa, usiamo i dati grezzi se presenti
            # Per semplicità, se non ci sono, restituiamo None
            # (Implementazione semplificata basata sulla struttura tipica)
            # In realtà HamQSL fornisce solo le condizioni correnti, non previsioni a 3 giorni nell'XML base.
            # Quindi lasciamo stare le previsioni per non complicare troppo.

            geomag = solardata.findtext('geomagfield', default='')
            signal_noise = solardata.findtext('signalnoise', default='')

            return SolarData(
                sfi=get_int('solarflux'),
                a_index=get_int('aindex'),
                k_index=get_int('kindex'),
                updated=solardata.findtext('updated', default=''),
                band_conditions=band_conditions,
                geomag_field=geomag,
                signal_noise=signal_noise
            )
        except Exception as e:
            print(f"Errore fetch dati solari: {e}")
            return SolarData()
