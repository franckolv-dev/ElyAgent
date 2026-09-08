#!/usr/bin/env bash
# La voix d'Ely, sur la machine — voir README.md.
set -euo pipefail
cd "$(dirname "$0")"

# torchcodec cherche les bibliothèques FFmpeg de Homebrew ici.
export DYLD_FALLBACK_LIBRARY_PATH="${DYLD_FALLBACK_LIBRARY_PATH:-/opt/homebrew/lib}"
# Le modèle XTTS-v2 est sous Coqui Public Model License (non commerciale) :
# lancer ce service vaut acceptation.
export COQUI_TOS_AGREED=1
export XTTS_PORT="${XTTS_PORT:-8020}"
export XTTS_DEVICE="${XTTS_DEVICE:-mps}"

if [ ! -x .venv/bin/python ]; then
  echo "Pas de .venv : voir README.md (uv venv --python 3.11 .venv && uv pip install -e '.[modele]')" >&2
  exit 1
fi
exec .venv/bin/python serveur.py
