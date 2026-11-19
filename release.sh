#!/usr/bin/env bash
# Pubblica una nuova release: ./release.sh 2.1.0
# 1) verifica che l'albero sia pulito e allineato a origin
# 2) esegue i test (check.sh)
# 3) aggiorna version.py, commit, tag, push
# 4) segue la build GitHub Actions fino alla Release
set -eo pipefail

cd "$(dirname "$(readlink -f "$0")")"

NEW="${1:-}"
if [ -z "$NEW" ]; then
    echo "Uso: ./release.sh <versione>   es. ./release.sh 2.1.0"
    exit 1
fi
if ! [[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERRORE: versione non valida '$NEW' (formato: X.Y.Z)"
    exit 1
fi

echo "→ Controllo stato del repository…"
if [ -n "$(git status --porcelain)" ]; then
    echo "ERRORE: ci sono modifiche non committate. Fai prima il commit."
    git status --short
    exit 1
fi
git fetch origin --quiet
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
    echo "ERRORE: il locale non è allineato a origin/main (pull/push prima)."
    exit 1
fi
echo "   OK"

echo "→ Eseguo i test…"
./check.sh

echo "→ Aggiorno version.py a $NEW…"
python3 - "$NEW" <<'EOF'
import re, sys
new = sys.argv[1]
p = "version.py"
src = open(p, encoding="utf-8").read()
src = re.sub(r'__version__ = "[^"]*"', f'__version__ = "{new}"', src)
open(p, "w", encoding="utf-8").write(src)
EOF

git commit -q -am "Release $NEW" || { echo "ERRORE: commit fallito"; exit 1; }
git tag -a "v$NEW" -m "DX Cluster Map v$NEW"
git push origin main
git push origin "v$NEW"

echo "→ Attendo la build GitHub Actions…"
sleep 5
RUN_ID=$(gh run list --workflow=release.yml --limit=1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status

echo
echo "✓ Release v$NEW pubblicata:"
gh release view "v$NEW" --json url --jq '.url'
