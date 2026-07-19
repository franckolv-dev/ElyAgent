# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_ntfy_headers.py
# @brief      ascii_header — en-têtes ntfy sûrs (bug live 19/07 : le premier
#             push « candidate à valider » tué par un tiret cadratin).
# @license    Elastic License 2.0
# =============================================================================
"""httpx encode les en-têtes HTTP en ASCII : tout caractère typographique
français (« — », guillemets, accents) tuait le push silencieusement. Le push
« question » de mission_spec_runtime n'était JAMAIS parti depuis sa création.

Run with:  cd backend && python -m pytest tests/test_ntfy_headers.py -v
"""
from __future__ import annotations

from pathlib import Path

from app.services.ntfy_headers import ascii_header

_REPO = Path(__file__).resolve().parents[1]


def test_typographic_punctuation_transliterated():
    out = ascii_header("Ely — outil candidat : « levenshtein »")
    assert "—" not in out and "«" not in out and "»" not in out
    assert "levenshtein" in out and "Ely - outil candidat" in out
    out2 = ascii_header("Mission « Veille IA — test mandat »")
    assert out2.encode("ascii", "strict")  # encodable, ne lève pas
    assert "Veille IA - test mandat" in out2


def test_accents_fold_to_base_letters():
    assert ascii_header("créée à côté") == "creee a cote"


def test_result_is_pure_printable_ascii():
    out = ascii_header("émoji 🚀 — tabs\tet\r\nnewlines…")
    assert out == out.encode("ascii", "strict").decode()  # ne lève pas
    assert "\r" not in out and "\n" not in out


def test_plain_ascii_untouched():
    assert ascii_header("Mission completed : Daily") == "Mission completed : Daily"


def test_all_ntfy_sites_use_ascii_header():
    for rel_path in (
        "app/services/learning/candidate_notify.py",
        "app/services/mission_heartbeat.py",
        "app/services/mission_spec_runtime.py",
    ):
        src = (_REPO / rel_path).read_text(encoding="utf-8")
        assert "ascii_header" in src, (
            f"{rel_path} envoie un Title ntfy — il doit passer par "
            "ascii_header (un caractère non-ASCII tue le push en silence)."
        )
