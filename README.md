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
- **Passaggi satelliti** (`F10`): previsione AOS/LOS, elevazione massima,
  azimut e **polar plot** del passaggio in corso o successivo (SGP4)
- **Worked-before da log ADIF**: legge `wsjtx_log.adi`, marca **B4** gli spot
  già a log e segnala **NUOVO** (nuova entità DXCC) e **BANDA** (nuova banda);
  ricarica automatica quando WSJT-X aggiorna il log
- **Avvisi sonori e vocali**: suoni distinti per alert, nuovo DXCC e
  "ti sta chiamando" (decodifiche WSJT-X col proprio nominativo), con sintesi
  vocale e notifica di sistema
- **Filtri**: bande, modo, continente dello spotter, età degli spot, alert
- **Mappa**: grayline, heatmap, legenda bande, distanza/bearing dal proprio locator
- **Interfaccia**: tema scuro/chiaro, dock spostabili, orologio UTC

## Sviluppo

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

### Sviluppo e release

Flusso di lavoro: **modifica → test → conferma → pubblicazione**.

```bash
./check.sh              # compila tutto + smoke test della UI (da fare sempre)
git add -A && git commit -m "descrizione modifica"
```

Solo dopo aver verificato che tutto funziona, si pubblica una release:

```bash
./release.sh 2.1.0      # controlla il repo, esegue i test, aggiorna version.py,
                        # commit + tag v2.1.0, push e segue la build GitHub Actions
```

GitHub Actions compila automaticamente l'exe Windows e l'archivio Linux
e crea la Release con i file allegati.

Le modifiche al codice possono essere pushate su `main` anche senza release
(non generano build): la build parte **solo** quando si pusha un tag `v*`.

## Licenza

Uso personale/radioamatoriale. Contatta IZ0FIU per altri usi.
