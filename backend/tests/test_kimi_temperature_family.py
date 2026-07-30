# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_kimi_temperature_family.py
# @brief      Le garde-fou « temperature=1 » doit reconnaître la FAMILLE Kimi,
#             pas une liste de versions qui périme à chaque sortie.
# @license    Elastic License 2.0
# =============================================================================
"""Pins du garde-fou de température des modèles de raisonnement Moonshot.

**Le défaut.** Les Kimi K-série sont des modèles de raisonnement : l'API rend
un 400 « invalid temperature: only 1 is allowed for this model » dès qu'on
envoie autre chose que 1. Le code le savait et forçait la valeur — mais en
testant des sous-chaînes :

    if "k2" in model or "k1.5" in model or "thinking" in model:

``kimi-k3`` ne contient aucune des trois. Il recevait donc la température 0.1
du tier COMPLEX, se faisait rejeter, et la chaîne basculait sur le modèle
suivant.

**Ce que ça coûtait.** Franck avait mis `kimi-k3` en TÊTE du tier `complex` le
28/07, délibérément : modèle plus puissant, crédits API à consommer, et tier B
et C ne devaient plus partager le même modèle. Résultat mesuré le 30/07 :
`kimi-k3` n'avait **jamais servi** depuis le 6 mai, `provider_switches`
enregistrait 17 bascules `bad_request` en trois jours, et chaque tour de chat
téléversait les 13 707 tokens de catalogue vers Moonshot **pour rien** avant de
recommencer ailleurs. La configuration disait une chose, la production en
faisait une autre — la classe de défaut « repli silencieux ».

**Pourquoi une famille et pas `+ "k3"`.** Ajouter la version du jour rejouerait
la même partie à K4. Toute la série K de Moonshot est en raisonnement : on
reconnaît donc ``kimi-k<chiffre>``.

⚠️ Si Moonshot sort un jour un Kimi **non** raisonnant, c'est ici qu'il faudra
revenir — d'où le test qui documente la règle plutôt qu'une liste.

Run with:  cd backend && python -m pytest tests/test_kimi_temperature_family.py -v
"""
from __future__ import annotations

import pytest


def _built_temperature(model: str) -> float:
    """Construit le client Moonshot et rend la température réellement posée."""
    from app.services.llm_provider import _make_moonshot

    llm = _make_moonshot(model, api_key="test-key-not-used", temperature=0.1)
    return float(getattr(llm, "temperature", -1))


@pytest.mark.parametrize("model", [
    "kimi-k1.5",
    "kimi-k2",
    "kimi-k2.6",
    "kimi-k3",          # ← le cas qui échouait en production
    "kimi-k4",          # ← et celui qui échouerait à la prochaine sortie
    "moonshot-v1-kimi-k3-preview",
    "KIMI-K3",          # la casse ne doit pas décider
])
def test_reasoning_kimi_gets_temperature_one(model: str) -> None:
    """Toute la série K reçoit 1 — sinon l'API rend un 400 et la chaîne bascule."""
    assert _built_temperature(model) == 1.0, (
        f"{model} part avec une température refusée par Moonshot : le tour sera "
        f"rejeté en bad_request et basculera sur le modèle suivant, en silence"
    )


def test_a_thinking_model_still_gets_temperature_one() -> None:
    """Le motif « thinking » d'origine reste couvert."""
    assert _built_temperature("moonshot-thinking-preview") == 1.0


def test_a_non_reasoning_model_keeps_the_tier_temperature() -> None:
    """On ne force pas tout le monde : le réglage du tier doit survivre.

    Sans ce pin, « forcer 1 partout » passerait les autres tests tout en
    supprimant le contrôle de variance que le tier COMPLEX cherche justement à
    obtenir pour le choix d'outil.
    """
    assert _built_temperature("moonshot-v1-8k") == pytest.approx(0.1)
