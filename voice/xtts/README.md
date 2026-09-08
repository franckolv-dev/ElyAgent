# La voix d'Ely, sur la machine

Service local de synthèse vocale : XTTS-v2 et une voix clonée, sur le Mac,
appelé par le backend d'Ely. Le texte lu et la voix ne quittent pas la
machine. Sans lui, Ely parle par edge-tts (voix Microsoft, cloud).

## Ce qu'il faut savoir

- Le modèle XTTS-v2 est publié par Coqui sous la **Coqui Public Model
  License**, non commerciale. Il n'est pas dans ce dépôt : il se télécharge
  au premier lancement (1,8 Go), et le lancement vaut acceptation
  (`COQUI_TOS_AGREED=1`).
- Une voix clonée demande **l'accord de la personne**. Les enregistrements
  vont dans `voices/<nom>/`, dossier ignoré par git : ils restent ici.
- Mesuré sur un Mac Studio M1 Max (MPS), empreinte pré-calculée : 1,3 à
  2,5 s de calcul par phrase pour 3 à 5 s d'audio. Plus vite que le temps
  réel, phrase par phrase — le client d'Ely découpe et demande chaque phrase.

## Installation (macOS Apple Silicon)

```bash
cd voice/xtts
brew install ffmpeg                     # torchcodec lit l'audio par FFmpeg
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e ".[modele]"
```

Quatre pièges rencontrés le 08/09/2026, déjà réglés par `pyproject.toml`
et `run.sh` : torch et torchaudio s'installent à part de `coqui-tts` ;
`transformers` doit rester en 4.55 à 4.x (la 5 casse XTTS) ; torch ≥ 2.9
exige l'extra `codec` ; torchcodec ne trouve les bibliothèques FFmpeg de
Homebrew que si `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` est posé.

## Une voix

10 à 30 secondes de parole propre, une pièce calme, un vrai micro à quinze
centimètres, voix posée. Convertir et normaliser :

```bash
mkdir -p voices/gert
ffmpeg -i enregistrement.aifc -ac 1 -ar 24000 \
  -af "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.3,areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.3,areverse,volume=+0dB" \
  voices/gert/ref.wav
```

Si la prise est basse (pic sous −12 dB dans `ffmpeg -af volumedetect`),
remonter avec `volume=15dB,alimiter=limit=0.95`. Plusieurs `.wav` dans le
même dossier sont pris ensemble.

## Lancer

```bash
./run.sh                 # port 8020, MPS, voix par défaut = la première
```

Variables : `XTTS_PORT` (8020), `XTTS_DEVICE` (`mps`, ou `cpu`),
`XTTS_VOICES_DIR`, `XTTS_DEFAULT_VOICE`, `XTTS_HOST` (127.0.0.1 : le
conteneur y accède par `host.docker.internal`).

Au démarrage du Mac : copier `fr.agent-ely.xtts.plist` dans
`~/Library/LaunchAgents/` en remplaçant `__REPO__` par le chemin du dépôt,
puis `launchctl load ~/Library/LaunchAgents/fr.agent-ely.xtts.plist`.
Journal dans `voice/xtts/xtts.log`.

## Côté Ely

Dans le `.env` à la racine :

```
TTS_PROVIDER=xtts
XTTS_URL=http://host.docker.internal:8020
XTTS_VOICE=gert
```

puis `docker compose up -d`. Si le service ne répond pas, Ely retombe sur
edge-tts et l'écrit dans son journal. `GET /tts/status` dit le fournisseur
en vigueur et les voix que le service connaît.

## Contrat

```
GET  /health   → {ok, device, voices, default_voice, model_loaded}
GET  /voices   → {voices, default_voice}
POST /speak    {"text": "…", "voice": "gert", "language": "fr"} → audio/wav 24 kHz
```

## Tests

```bash
uv run --extra dev pytest -q      # sans le modèle : un double le remplace
```
