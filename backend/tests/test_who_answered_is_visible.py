# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_who_answered_is_visible.py
# @brief      « Il n'y a que le local qui répond » — c'était faux, et l'écran
#             ne permettait pas de le savoir.
# @license    MIT
# =============================================================================
"""Deux tours d'enquête pour une conclusion fausse (24/08).

    Franck : « Depuis ce soir, j'ai l'impression que maintenant, il n'y a que
      le local qui répond. J'ai pourtant écrit des demandes assez longues et,
      dans la partie à droite, il y a toujours MODEL : gemma-4-E4B-it-MLX-8bit
      même s'il n'y a pas toujours le badge "Local" dans ses réponses. »

Le routage était JUSTE. Vérifié sur ses deux phrases exactes, avec son seuil
de 55 :

     95 caractères   score 55   → local     ← badge « local » présent
    276 caractères   score 80   → cloud     ← aucun badge

Et la réponse cloud remplissait trois formulaires d'inscription en
préremplissant son adresse mail. Un modèle de 4 milliards de paramètres ne
fait pas ça.

**C'est l'affichage qui n'a rien dit.** Trois défauts distincts, tous du même
genre : une information absente ou périmée, présentée comme si elle ne l'était
pas.

1. LE BADGE N'EXISTAIT QUE POUR LE LOCAL
-----------------------------------------
`local` s'affichait pour la voie SLM, **rien** pour le cloud — au motif qu'il
était « le défaut, l'attendu ». Donc « pas de badge » voulait dire « cloud »,
mais se lisait comme « pas d'information ». Un signal négatif qu'il faut savoir
interpréter n'est pas un signal.

2. LE PANNEAU AFFICHAIT LE TOUR PRÉCÉDENT PENDANT LE TOUR EN COURS
-------------------------------------------------------------------
`MODEL` et `LATENCY` décrivent UN TOUR. Pendant qu'un tour cloud de plusieurs
minutes travaillait, le panneau montrait encore « gemma / 25 325 ms » — les
chiffres du tour local d'avant, avec la même assurance. Il ne mentait pas : il
était en retard, et rien ne le disait.

3. UN TOUR SANS `model_used` GARDAIT L'ANCIENNE VALEUR
--------------------------------------------------------
`if (modelUsed) { setLastModel(modelUsed); }` — le garde sautait la mise à jour
au lieu d'effacer. Défaut latent, jamais observé chez Franck, mais de la même
famille : mieux vaut « — » qu'une valeur périmée.

⚠️ POURQUOI CES PINS SONT EN PYTHON SUR DU TSX. Même raison que
`test_theme_tokens.py` : la CI du dépôt fait tourner pytest et `tsc --noEmit`.
`tsc` vérifie les types, pas les décisions. Un contrôle textuel est grossier,
mais il rougit — et c'est tout ce qu'on lui demande.

Run with:  cd backend && python -m pytest tests/test_who_answered_is_visible.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"
_BULLE = _FRONT / "components" / "chat" / "MessageBubble.tsx"
_PANNEAU = _FRONT / "components" / "avatar" / "AvatarPanel.tsx"


@pytest.mark.parametrize("fichier", [_BULLE, _PANNEAU])
def test_the_files_are_still_there(fichier):
    """Un pin qui lit un fichier absent passerait en silence."""
    assert fichier.exists(), f"{fichier.name} a disparu"


# ─────────────────────────────────────────────────────────────────────
# 1 — Le badge nomme le modèle des DEUX côtés
# ─────────────────────────────────────────────────────────────────────

def test_a_cloud_reply_carries_a_badge_too():
    """LE pin de l'épisode.

    Le badge ne marquait que la voie locale. « Pas de badge » voulait dire
    « cloud » — un signal négatif, qu'on n'interprète pas quand on cherche
    autre chose.
    """
    src = _BULLE.read_text(encoding="utf-8")
    assert 'startsWith("llm:")' in src, "le cas cloud n'est plus distingué"
    # L'ancien code : `? null  // don't show badge for LLM`.
    assert "don't show badge for LLM" not in src, (
        "les réponses cloud n'affichent toujours aucun badge — l'utilisateur "
        "ne peut pas distinguer « le cloud a répondu » de « je n'ai pas "
        "l'information »"
    )


def test_the_cloud_badge_shows_the_model_not_the_provider():
    """`llm:openai-compat/gpt-5.6-sol+tools` → `gpt-5.6-sol`.

    Le fournisseur vit dans le panneau SESSION ; sur une bulle de message,
    c'est le MODÈLE qui renseigne — c'est lui qui explique la qualité de la
    réponse qu'on vient de lire.
    """
    src = _BULLE.read_text(encoding="utf-8")
    assert '.split("+")[0].split("/").pop()' in src, (
        "le badge cloud n'extrait pas le nom du modèle"
    )


def test_the_local_badge_keeps_its_name():
    """« local » est le mot que Franck lit depuis trois jours. Le renommer
    maintenant lui coûterait un repère pour un gain nul."""
    src = _BULLE.read_text(encoding="utf-8")
    assert '"local"' in src


# ─────────────────────────────────────────────────────────────────────
# 2 — Le panneau ne présente pas le tour d'avant comme le tour courant
# ─────────────────────────────────────────────────────────────────────

def test_the_panel_knows_a_turn_is_in_flight():
    """⚠️ `avatarState` ne pouvait PAS servir : la synthèse vocale le met aussi
    à « thinking » quand elle charge son audio. Il faut un état qui ne décrive
    que le tour."""
    src = _PANNEAU.read_text(encoding="utf-8")
    assert "const [enVol," in src, "aucun état ne suit le tour en cours"
    assert "setEnVol(true)" in src and "setEnVol(false)" in src


def test_the_in_flight_turn_blanks_the_per_turn_metrics():
    """`MODEL` et `LATENCY` décrivent UN TOUR. Les afficher pendant qu'un autre
    tourne, c'est présenter les chiffres du précédent comme les siens — ce qui
    a fait conclure à Franck que seul le local répondait."""
    src = _PANNEAU.read_text(encoding="utf-8")
    assert "enVol || !lastModel" in src, (
        "MODEL affiche encore le modèle du tour précédent pendant un tour"
    )
    assert "enVol || latencyMs === undefined" in src, (
        "LATENCY affiche encore la durée du tour précédent"
    )


def test_a_failed_turn_also_ends_the_wait():
    """Un tour qui échoue est un tour TERMINÉ. Sans ça, le panneau resterait
    en attente jusqu'au message suivant — donc muet sur le tour d'avant, ce
    qui est un autre genre de silence."""
    src = _PANNEAU.read_text(encoding="utf-8")
    bloc = src.split('wsMessage.type === "error"', 1)[1][:400]
    assert "setEnVol(false)" in bloc, (
        "une erreur laisse le panneau en attente indéfiniment"
    )


def test_the_cumulative_counter_is_not_blanked():
    """⚠️ TOKENS est CUMULÉ sur la session, pas par tour : il n'est jamais
    périmé, seulement pas encore à jour. Le masquer pendant un tour ferait
    clignoter le seul chiffre qui suit la dépense."""
    src = _PANNEAU.read_text(encoding="utf-8")
    bloc = src.split('<span className="k">TOKENS</span>', 1)[1][:300]
    assert "enVol" not in bloc, (
        "le total de tokens est masqué pendant un tour — or il est cumulé, "
        "donc toujours vrai"
    )


# ─────────────────────────────────────────────────────────────────────
# 3 — Le défaut latent : un tour sans modèle efface, il ne conserve pas
# ─────────────────────────────────────────────────────────────────────

def test_a_turn_without_a_model_clears_instead_of_keeping():
    """⚠️ Jamais observé chez Franck, et corrigé quand même.

    `if (modelUsed) { setLastModel(modelUsed); }` sautait la mise à jour : un
    tour terminé sans `model_used` laissait le panneau afficher le modèle du
    tour PRÉCÉDENT. Même famille que les deux défauts ci-dessus — un
    indicateur qui ment est pire qu'un indicateur vide.
    """
    src = _PANNEAU.read_text(encoding="utf-8")
    assert "setLastModel(modelUsed);" in src, "la mise à jour a disparu"
    assert "if (modelUsed) {\n        setNeuralScore" not in src, (
        "le garde conserve encore l'ancienne valeur quand le tour ne dit pas "
        "quel modèle l'a servi"
    )
