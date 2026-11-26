#!/usr/bin/env bash
# Costruisce un AppImage autonomo a partire dal bundle PyInstaller.
#
# Uso: ./packaging/build_appimage.sh [versione]
#
# Prerequisito: aver già compilato il bundle con
#   pyinstaller dxcluster_map.spec --noconfirm   (crea dist/DXClusterMap)
# appimagetool viene scaricato automaticamente se non è nel PATH.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")/.."

APPID="io.github.iz0fiu.DXClusterMap"
BUNDLE="dist/DXClusterMap"

VERSION="${1:-$(sed -n 's/^__version__ = "\(.*\)"/\1/p' version.py)}"
if [ -z "$VERSION" ]; then
    echo "ERRORE: versione non trovata in version.py"
    exit 1
fi
if [ ! -x "$BUNDLE/DXClusterMap" ]; then
    echo "ERRORE: manca $BUNDLE/DXClusterMap"
    echo "        compila prima con: pyinstaller dxcluster_map.spec --noconfirm"
    exit 1
fi

echo "→ Preparo l'AppDir ($APPID v$VERSION)…"
APPDIR="build/appimage/$APPID.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -a "$BUNDLE/." "$APPDIR/usr/bin/"

install -Dm644 "packaging/$APPID.desktop" "$APPDIR/$APPID.desktop"
install -Dm644 "packaging/$APPID.desktop" \
    "$APPDIR/usr/share/applications/$APPID.desktop"
install -Dm644 "packaging/$APPID.metainfo.xml" \
    "$APPDIR/usr/share/metainfo/$APPID.metainfo.xml"
install -Dm644 "packaging/icons/hicolor/256x256/apps/$APPID.png" \
    "$APPDIR/$APPID.png"
install -Dm644 "packaging/icons/hicolor/256x256/apps/$APPID.png" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps/$APPID.png"
install -Dm644 "packaging/icons/hicolor/512x512/apps/$APPID.png" \
    "$APPDIR/usr/share/icons/hicolor/512x512/apps/$APPID.png"
ln -sf "$APPID.png" "$APPDIR/.DirIcon"
# appimagetool cerca ancora il vecchio nome *.appdata.xml
ln -sf "$APPID.metainfo.xml" \
    "$APPDIR/usr/share/metainfo/$APPID.appdata.xml"
# L'AppImage deve essere leggibile da qualunque utente
chmod -R a+rX "$APPDIR"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export PATH="$HERE/usr/bin:$PATH"
exec "$HERE/usr/bin/DXClusterMap" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# appimagetool: usa quello nel PATH, altrimenti scaricalo una volta sola
TOOL="${APPIMAGETOOL:-}"
if [ -z "$TOOL" ]; then
    TOOL="build/appimage/appimagetool"
    if [ ! -x "$TOOL" ]; then
        echo "→ Scarico appimagetool…"
        mkdir -p "$(dirname "$TOOL")"
        curl -fsSL -o "$TOOL" \
            "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
        chmod +x "$TOOL"
    fi
fi

OUT="dist/DXClusterMap-v$VERSION-x86_64.AppImage"
rm -f "$OUT"
echo "→ Creo $OUT…"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 \
    "$TOOL" "$APPDIR" "$OUT"

echo "✓ AppImage pronta: $OUT ($(du -h "$OUT" | cut -f1))"
