# Contribuire e sviluppare

Guida per eseguire DX Cluster Map dal sorgente e pubblicare una nuova versione.

## Ambiente di sviluppo

Serve **Python 3.10 o superiore**. Le dipendenze sono in `requirements.txt`.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

## Test prima di ogni commit

```bash
./check.sh
```

Compila tutti i moduli Python e lancia uno smoke test dell'interfaccia in
modalità offscreen. Va eseguito sempre prima di committare.

## Flusso di lavoro

**modifica → test → conferma → pubblicazione**

```bash
./check.sh                              # test (sempre)
git add -A && git commit -m "descrizione modifica"
```

Le modifiche al codice possono essere pushate su `main` anche senza release:
la build parte **solo** quando si pusha un tag `v*`.

## Pubblicare una release

```bash
./release.sh 2.1.0
```

Lo script:

1. verifica che l'albero sia pulito e allineato a `origin/main`
2. esegue `./check.sh`
3. aggiorna `version.py` (unica fonte del numero di versione), fa il commit e
   crea il tag `v2.1.0`
4. esegue il push di `main` e del tag
5. segue la build GitHub Actions fino alla Release

Il workflow `release.yml` compila e verifica il pacchetto Windows con
PyInstaller (smoke test automatico), crea l'installer con Inno Setup
(compressione LZMA2) e l'archivio sorgenti Linux, poi pubblica la Release con
i file allegati:

- `DXClusterMap-vX.Y.Z-windows-setup.exe` — installer per-utente
- `DXClusterMap-vX.Y.Z-windows-x64.zip` — versione portable
- `DXClusterMap-vX.Y.Z-linux.tar.gz` — sorgenti

Con **Actions → Release → Run workflow** (`workflow_dispatch`) si può provare
una build completa senza creare la Release; gli artefatti sono scaricabili
dalla pagina del run, ma solo da utenti GitHub autenticati.

### Note

- `version.py` è l'unica fonte del numero di versione: il workflow verifica
  che il tag corrisponda e la build fallisce in caso di discrepanza.
- L'installer è definito in `installer/dxcluster_map.iss` e usa
  `installer/dxcluster_map.ico` come icona.
- L'eseguibile non è firmato: SmartScreen può quindi chiedere conferma al
  primo avvio.
- Non inviare query duplicate: tieni **una sola istanza** dell'app attiva
  (due istanze = doppie richieste a PSK Reporter e doppio listener UDP).
