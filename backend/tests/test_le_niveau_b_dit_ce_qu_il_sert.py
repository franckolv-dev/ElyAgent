# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_le_niveau_b_dit_ce_qu_il_sert.py
# @brief      La description d'un niveau de routage nomme ses appelants RÉELS.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""16/09/2026 — Franck configure un modèle local sur le niveau B et pose des
questions pour le voir répondre. Il ne répond jamais : depuis le 27/07,
`classify_complexity` ne rend que IMAGE ou COMPLEX, et le niveau A prend ce
qui passe sous le seuil SLM. Le niveau B n'est plus jamais choisi par le chat.

Mais la page Routage disait encore « la majorité des échanges, score de
complexité 30-70 ». Une description qui promet un routage mort fait
configurer une chaîne pour rien.

Le niveau B n'est pas mort pour autant : l'exécuteur de missions YAML et la
critique de mission (réglée sur « B ») le demandent explicitement. Le
diagnostiqueur, troisième appelant à l'origine, a été retiré le 19/09/2026. C'est du travail de fond, et c'est ce que la description doit
dire. Ce pin relie le texte aux appelants : si un appelant bouge, le texte
devra bouger avec.
"""
from __future__ import annotations

import pathlib

import pytest

_APP = pathlib.Path(__file__).parent.parent / "app"

_DEMANDES = [
    "bonjour",
    "quelle météo à Poitiers ?",
    "envoie un mail à Paul pour décaler la réunion",
    "refactor cette fonction python",
    "traduis ce document en gardant exactement la mise en page",
    "résume-moi les 3 derniers mails de Marie",
]


@pytest.mark.parametrize("demande", _DEMANDES)
def test_le_chat_ne_choisit_jamais_le_niveau_b(demande):
    from app.agent.nodes import tier_du_tour
    from app.services.llm_provider import ComplexityTier, classify_complexity

    assert classify_complexity(demande) is not ComplexityTier.MEDIUM
    assert tier_du_tour("", demande) is not ComplexityTier.MEDIUM
    # Même une épingle « medium » n'est pas honorée : seules complex et mission le sont.
    assert tier_du_tour("medium", demande) is not ComplexityTier.MEDIUM


def _meta():
    from app.routers.settings_llm import TIER_META

    return {m["id"]: m for m in TIER_META}


def test_le_niveau_b_se_presente_comme_du_travail_de_fond():
    b = _meta()["medium"]
    assert "fond" in b["label"].lower()
    desc = b["description"].lower()
    assert "travail de fond" in desc
    for appelant in ("missions yaml", "critique"):
        assert appelant in desc, f"l'appelant « {appelant} » n'est pas nommé"
    assert "jamais" in desc and "chat" in desc, "doit dire que le chat ne l'appelle pas"
    assert "diagnosti" not in desc, "le diagnostiqueur est retiré depuis le 19/09/2026"
    assert "majorité des échanges" not in desc
    assert "score" not in desc


def test_les_appelants_nommes_demandent_vraiment_le_niveau_b():
    """Le texte cite deux appelants ; chacun doit demander MEDIUM dans son code."""
    for chemin in (
        "services/mission_spec_runtime.py",
        "services/learning/mission_critic.py",
    ):
        src = (_APP / chemin).read_text()
        assert "ComplexityTier.MEDIUM" in src, f"{chemin} ne demande plus le niveau B"


def test_aucun_niveau_ne_promet_un_score_de_complexite():
    """Le score 0-100 n'existe plus que pour le seuil SLM du niveau A."""
    for tid in ("simple", "medium", "complex"):
        assert "score de complexité" not in _meta()[tid]["description"].lower(), tid


def test_le_niveau_c_se_presente_comme_le_niveau_du_chat():
    desc = _meta()["complex"]["description"].lower()
    assert "chat" in desc
    assert "27/07" in desc or "seuil" in desc
