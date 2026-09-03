# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/ntfy_headers.py
# @brief      ascii_header() — en-têtes HTTP sûrs pour les push ntfy.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.0.0
# @link       https://github.com/franckolv-dev/ElyAgent
# =============================================================================
"""En-têtes HTTP ASCII-sûrs pour les push ntfy.

Bug réel (19/07/2026, attrapé en live) : httpx encode les en-têtes en ASCII —
un tiret cadratin « — » dans le Title tue le push (`'ascii' codec can't
encode character '\\u2014'`). Le push « candidate à valider » est mort en vol,
et celui de `mission_spec_runtime` (guillemets + tiret dans le titre) n'est
JAMAIS parti depuis sa création ; les push de missions échouent dès qu'un
titre contient un caractère non-ASCII.

``ascii_header`` : translittération légère (ponctuation typographique →
équivalents ASCII, accents → lettres de base via NFKD) puis suppression des
restes. Le CORPS du message reste en UTF-8 (envoyé en bytes) — seuls les
en-têtes ont cette contrainte.
"""
from __future__ import annotations

import unicodedata

_REPLACEMENTS = {
    "—": "-", "–": "-",
    "«": '"', "»": '"',
    "‘": "'", "’": "'",
    "“": '"', "”": '"',
    "…": "...",
    " ": " ",
}


def ascii_header(value: str) -> str:
    """Valeur d'en-tête HTTP sûre : ASCII imprimable, sans CR/LF."""
    out = value or ""
    for k, v in _REPLACEMENTS.items():
        out = out.replace(k, v)
    # é → e (+ diacritique combinant, supprimé par le filtre ASCII).
    out = unicodedata.normalize("NFKD", out)
    out = "".join(c for c in out if 32 <= ord(c) < 127)
    return out.strip()
