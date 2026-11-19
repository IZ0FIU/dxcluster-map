# DX Cluster Map

Mappa interattiva degli spot radioamatoriali: Spothole, WSJT-X (UDP locale) e
PSK Reporter, con satelliti in tempo reale (TLE CelesTrak), grayline, heatmap,
alert per nominativo e ponte UDP verso altri programmi (es. WavelogGate).

![versione](https://img.shields.io/badge/versione-2.0.0-ffb02e)

## Download

Dalla pagina [Releases](https://github.com/IZ0FIU/dxcluster-map/releases):

| Piattaforma | File | Avvio |
|---|---|---|
| **Windows 10/11 (64 bit)** | `DXClusterMap-vX.Y.Z-windows-x64.zip` | scompatta e avvia `DXClusterMap.exe` |
| **Linux** | `DXClusterMap-vX.Y.Z-linux.tar.gz` | scompatta, `pip install -r requirements.txt`, poi `./run.sh` |

Su Windows non serve installare Python: l'eseguibile contiene tutto
(Python + Qt/PySide6).

## Funzioni principali

- **Sorgenti dati**: Spothole (cluster web), WSJT-X via UDP (porta 2237),
  PSK Reporter (polling ogni 10 minuti con backoff)
- **Ponte UDP**: inoltro byte-per-byte dei datagrammi WSJT-X ad altri
  programmi (es. WavelogGate) su una porta separata
- **Satelliti**: 96 satelliti radioamatoriali con posizione in tempo reale,
  etichetta e traiettoria orbitale (clic sul marker); cache TLE su disco 24 h
- **Filtri**: bande, modo, continente dello spotter, età degli spot, alert
- **Mappa**: grayline, heatmap, legenda bande, distanza/bearing dal proprio locator
- **Interfaccia**: tema scuro/chiaro, dock spostabili, orologio UTC

## Sviluppo

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

### Release

1. Aggiorna `version.py` (es. `2.1.0`)
2. Commit e tag:
   ```bash
   git commit -am "Release 2.1.0"
   git tag v2.1.0
   git push origin main --tags
   ```
3. GitHub Actions compila automaticamente l'exe Windows e l'archivio Linux
   e crea la Release con i file allegati.

## Licenza

Uso personale/radioamatoriale. Contatta IZ0FIU per altri usi.
