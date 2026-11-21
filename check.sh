#!/usr/bin/env bash
# Verifica che l'app sia pronta per il commit: compilazione + smoke test
# headless (crea la finestra, controlla dock/menubar/filtri, chiude).
set -eo pipefail

cd "$(dirname "$(readlink -f "$0")")"

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

echo "→ 1/2 Compilazione di tutti i moduli Python…"
"$PY" -m py_compile *.py providers/*.py
echo "   OK"

echo "→ 2/2 Smoke test interfaccia (offscreen)…"
QT_QPA_PLATFORM=offscreen "$PY" - <<'EOF'
import sys
sys.path.insert(0, ".")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication
QCoreApplication.setOrganizationName("DXClusterMap")
QCoreApplication.setApplicationName("DXClusterMap")
app = QApplication(sys.argv)

import main
from version import __version__

w = main.MainWindow()
w.show()

# Controlli essenziali: se qualcuno rompe la UI, qui si vede subito
assert w.dock_spot is not None, "dock Spot mancante"
assert w.dock_detail is not None, "dock Dettaglio mancante"
assert w.menuBar().actions(), "menubar vuota"
assert w.source_combo.count() >= 3, "sorgenti mancanti"
assert w.band_checkboxes, "menu bande vuoto"
assert w.spot_list is not None, "lista spot mancante"
assert w.map is not None, "mappa mancante"
assert w.locator_edit is not None, "dialogo impostazioni mancante"
assert w.adif is not None, "log ADIF mancante"
assert w.adif_path_edit is not None, "campo ADIF mancante"
assert w.sound_cb is not None and w.voice_cb is not None, "opzioni audio mancanti"

# Parser ADIF e worked-before (file temporaneo)
import os, tempfile
from adif_log import AdifLog, NEW_BAND, NEW_COUNTRY, WORKED
fd, adi = tempfile.mkstemp(suffix=".adi")
os.close(fd)
with open(adi, "wb") as fh:
    fh.write(b"<ADIF_VER:5>3.1.4<EOH>\n"
             b"<CALL:6>IK1XYZ<BAND:3>20m<MODE:3>FT8<COUNTRY:5>Italy<EOR>\n"
             b"<CALL:5>W1ABC<BAND:3>40m<MODE:3>FT8<EOR>\n")
log = AdifLog()
assert log.load(adi), "ADIF non caricato"
assert log.status_for("IK1XYZ", "20m") == WORKED, "worked-before errato"
assert log.status_for("IK1XYZ", "15m") == NEW_BAND, "nuova banda errata"
assert log.status_for("JA1ABC", "20m") == NEW_COUNTRY, "nuovo DXCC errato"
os.unlink(adi)

# Riconoscimento "ti sta chiamando" nelle decodifiche WSJT-X
from wsjtx_listener import WSJTXListener
call, _grid, mine = WSJTXListener._extract_call_and_grid("W1ABC IZ0FIU -10", "IZ0FIU")
assert call == "W1ABC" and mine, "chiamata a noi non riconosciuta"
call, _grid, mine = WSJTXListener._extract_call_and_grid("CQ IK1XYZ JN45", "IZ0FIU")
assert call == "IK1XYZ" and not mine, "CQ scambiato per chiamata"

# Dialogo passaggi satelliti (con posizione di prova)
w.user_lat, w.user_lng = 41.9, 12.5
w._open_passes_dialog()
assert w.passes_dialog is not None and w.passes_dialog.table is not None, "dialogo passaggi mancante"
w.passes_dialog.close()

# Il menu satelliti si popola con i TLE in cache (se presente)
from satellite_provider import SatelliteProvider
tles = SatelliteProvider()._parse(
    open(SatelliteProvider.CACHE_FILE, encoding="utf-8").read()
) if __import__("os").path.exists(SatelliteProvider.CACHE_FILE) else []
if tles:
    w._populate_sat_menu(tles)
    assert w.sat_checkboxes, "menu satelliti non popolato"
    assert w.selected_sats, "nessun satellite selezionato di default"
    print(f"   satelliti: {len(w.sat_checkboxes)} in elenco, selezionati {len(w.selected_sats)}")

print(f"   versione {__version__} — interfaccia OK")
EOF

echo
echo "✓ Tutti i controlli superati: puoi committare."
