#!/usr/bin/env bash
# Avvio dx-cluster-map: prepara il venv se necessario e lancia l'app.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

VENV=".venv"
REQ="requirements.txt"
STAMP="$VENV/.deps-installed"

# Silenzia i warning Wayland di Qt (innocui ma rumorosi)
export QT_LOGGING_RULES="${QT_LOGGING_RULES:-qt.qpa.wayland.textinput=false}"

# 1) Crea il venv se manca
if [ ! -d "$VENV" ]; then
    echo "→ Creo il virtualenv in $VENV ..."
    python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

# 2) Installa le dipendenze se requirements.txt è cambiato (o se non è mai stato fatto)
if [ ! -f "$STAMP" ] || [ "$REQ" -nt "$STAMP" ]; then
    echo "→ Installo/aggiorno le dipendenze ..."
    pip install --upgrade pip >/dev/null
    pip install -r "$REQ"
    touch "$STAMP"
fi

# 3) Lancia l'app (passa eventuali argomenti extra)
exec python main.py "$@"
