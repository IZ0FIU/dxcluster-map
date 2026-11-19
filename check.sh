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
