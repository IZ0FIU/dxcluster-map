#!/usr/bin/env bash
set -eo pipefail  # rimosso -u per evitare problemi con activate

cd "$(dirname "$(readlink -f "$0")")"

VENV=".venv"
REQ="requirements.txt"
STAMP="$VENV/.deps-installed"

export QT_LOGGING_RULES="${QT_LOGGING_RULES:-qt.qpa.wayland.textinput=false}"

# 1) Crea il venv se manca
if [ ! -d "$VENV" ]; then
    echo "→ Creo il virtualenv in $VENV ..."
    python3 -m venv "$VENV" || { echo "ERRORE: impossibile creare il venv"; exit 1; }
fi

# 2) Installa le dipendenze se requirements.txt è cambiato
if [ ! -f "$STAMP" ] || [ "$REQ" -nt "$STAMP" ]; then
    echo "→ Installo/aggiorno le dipendenze ..."
    "$VENV/bin/python" -m pip install --upgrade pip || { echo "ERRORE pip upgrade"; exit 1; }
    "$VENV/bin/python" -m pip install -r "$REQ" || { echo "ERRORE pip install"; exit 1; }
    touch "$STAMP"
fi

# 3) Lancia l'app usando esplicitamente il Python del venv
exec "$VENV/bin/python" main.py "$@"
