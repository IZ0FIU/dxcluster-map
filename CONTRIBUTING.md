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

Il workflow `release.yml` compila l'exe Windows con PyInstaller, crea
l'archivio sorgenti Linux e pubblica la Release con i file allegati
(`DXClusterMap-vX.Y.Z-windows-x64.zip` e `DXClusterMap-vX.Y.Z-linux.tar.gz`).

### Note

- `version.py` è l'unica fonte del numero di versione: il workflow verifica
  che il tag corrisponda e la build fallisce in caso di discrepanza.
- Non inviare query duplicate: tieni **una sola istanza** dell'app attiva
  (due istanze = doppie richieste a PSK Reporter e doppio listener UDP).
