# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_engaging_tools_are_guarded.py
# @brief      Aucun acte engageant ne s'exécute sans que Franck l'ait voulu —
#             et ce qui en est dispensé l'est explicitement, avec sa raison.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Lot 3 du plan de marche — fermer le trou que le lot 1 a rendu visible.

⚠️ Ce que le lot 1 avait mal mesuré, et qu'il faut corriger ici
----------------------------------------------------------------
#296 annonçait « 26 actes engageants sans autorisation, dont ``ssh_execute`` et
``gmail_empty_trash`` ». **C'était faux.** ``ALREADY_GUARDED`` avait été bâti
sur ``hitl_descriptions.py`` (6 outils) alors que la garde réelle vit dans
``hitl_preferences.LOCKED_HITL_TOOLS`` ∪ ``security_filter.ALWAYS_CRITICAL_TOOLS``
— **38 outils**. ``ssh_execute``, ``gmail_empty_trash``,
``contacts_delete``, ``drive_share_file`` et les sept ``*_raw_api_call`` étaient
déjà protégés.

Et l'inventaire était incomplet : 154 outils recensés pour **208** réels — les
55 de ``skills/builtin`` (``desktop_*``, ``os_*``, ``browser_*``, ``trainer_*``,
``mcp_*``) n'avaient jamais été vus.

Une table de sécurité bâtie sur la mauvaise source est pire qu'une absence de
table : elle rassure. D'où le premier pin de ce fichier, qui interdit à
``ALREADY_GUARDED`` de diverger de la garde réelle.

Ce que ce lot ajoute
---------------------
Sur le périmètre complet, 18 actes engageants n'étaient soumis à rien. Huit
passent sous autorisation ; dix en sont **explicitement dispensés**, chacun
avec sa raison écrite — décisions de Franck du 28/07/2026 :

    « Je ne veux pas avoir à confirmer pour l'ouverture d'un onglet Chrome ou
      pour déclencher une tâche que j'ai créée et encore moins pour m'envoyer
      un message via Telegram. »

Pourquoi une dispense, et pas un reclassement
-----------------------------------------------
``telegram_send_message`` **est** engageant : il envoie un message. Le
reclasser en ECRITURE ferait mentir la table sur sa nature pour obtenir un
effet de politique. On sépare donc **ce que l'outil est** (la table) de **ce
qui exige un accord** (la dispense, motivée). La nature reste vraie, l'arbitrage
reste traçable.

⚠️ Une dispense ne peut jamais s'appliquer à un outil déjà gardé — sans quoi ce
mécanisme deviendrait une porte pour déprotéger, exactement ce que le lot 1
interdisait à la table.

Run with:  cd backend && python -m pytest tests/test_engaging_tools_are_guarded.py -v
"""
from __future__ import annotations

import pytest


def _real_guard() -> set[str]:
    """La garde RÉELLE, lue à ses deux sources."""
    from app.services.hitl_preferences import LOCKED_HITL_TOOLS
    from app.services.security_filter import ALWAYS_CRITICAL_TOOLS

    return set(LOCKED_HITL_TOOLS) | set(ALWAYS_CRITICAL_TOOLS)


# ─────────────────────────────────────────────────────────────────────
# La correction du lot 1 : lire la BONNE source
# ─────────────────────────────────────────────────────────────────────


def test_already_guarded_matches_the_real_guard():
    """LE pin qui aurait évité l'erreur de #296.

    ``ALREADY_GUARDED`` y était une liste écrite à la main depuis la mauvaise
    source. Elle a fait annoncer 26 trous là où il y en avait 9, et surtout elle
    aurait pu faire croire protégé ce qui ne l'était pas. Elle doit désormais
    DÉRIVER de la garde réelle, jamais la paraphraser.
    """
    from app.agent.tool_nature import ALREADY_GUARDED

    assert set(ALREADY_GUARDED) == _real_guard()


def test_tools_declared_outside_agent_tools_are_classified():
    """L'inventaire du lot 1 ne regardait que ``app/agent/tools``. Les 55 outils
    de ``skills/builtin`` — dont ceux qui pilotent le clavier et la souris —
    n'étaient donc ni classés ni comptés."""
    from app.agent.tool_nature import TOOL_NATURE

    for name in ("os_click", "desktop_delete_file", "browser_fill",
                 "trainer_start", "mcp_connect"):
        assert name in TOOL_NATURE, f"{name} absent de la table"


# ─────────────────────────────────────────────────────────────────────
# Le trou est fermé
# ─────────────────────────────────────────────────────────────────────


def test_no_engaging_tool_is_left_unguarded_without_a_reason():
    """L'invariant du lot. Tout acte engageant est soit sous autorisation, soit
    dispensé AVEC une raison écrite — jamais oublié en silence."""
    from app.agent.tool_nature import APPROVAL_WAIVED, TOOL_NATURE

    engageants = {n for n, v in TOOL_NATURE.items() if v.effect == "ENGAGEANT"}
    orphelins = engageants - _real_guard() - set(APPROVAL_WAIVED)
    assert not orphelins, f"actes engageants ni gardés ni dispensés : {sorted(orphelins)}"


@pytest.mark.parametrize("tool", [
    "gmail_send_with_local_attachment",   # envoie un mail — les autres gmail_send_* étaient gardés
    "calendar_create_meet_event",         # crée un Meet, donc envoie des invitations à des tiers
    "sheets_delete_rows",
    "sheets_batch_update",
    "notes_delete",
    "scheduler_delete_task",
    "trainer_start",                      # « ELY prend le contrôle de l'écran »
    "mcp_connect",                        # connexion autonome à un serveur distant
])
def test_these_now_require_approval(tool):
    from app.agent.tool_nature import requires_approval

    assert requires_approval(tool) is True, f"{tool} s'exécute encore sans accord"


# ─────────────────────────────────────────────────────────────────────
# Les dispenses — décisions de Franck, écrites
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tool", [
    "browser_tab_click", "browser_click", "browser_fill",
    "scheduler_run_task", "telegram_send_message",
    "trainer_click", "trainer_type", "trainer_hotkey", "trainer_move",
    "mcp_call_tool",
])
def test_these_stay_free_of_confirmation(tool):
    """« Je ne veux pas avoir à confirmer pour l'ouverture d'un onglet Chrome ou
    pour déclencher une tâche que j'ai créée et encore moins pour m'envoyer un
    message via Telegram. » — Franck, 28/07/2026."""
    from app.agent.tool_nature import requires_approval

    assert requires_approval(tool) is False, f"{tool} interrompt l'utilisateur pour rien"


def test_every_waiver_states_its_reason():
    """Une dispense sans motif est un trou qu'on a oublié de refermer. Dans six
    mois, seule la raison écrite permettra de savoir si elle tient encore."""
    from app.agent.tool_nature import APPROVAL_WAIVED

    for tool, raison in APPROVAL_WAIVED.items():
        assert len(raison) > 25, f"{tool} : dispense sans motif ({raison!r})"


def test_a_waiver_can_never_unprotect_a_guarded_tool():
    """Le garde-fou du mécanisme lui-même. Sans ce pin, une dispense deviendrait
    une porte pour retirer une protection — exactement ce que le lot 1
    interdisait à la table de faire."""
    from app.agent.tool_nature import APPROVAL_WAIVED, requires_approval

    conflits = set(APPROVAL_WAIVED) & _real_guard()
    assert not conflits, f"dispense sur un outil gardé : {sorted(conflits)}"
    for tool in _real_guard():
        assert requires_approval(tool) is True


def test_a_waived_tool_is_still_honestly_classified():
    """La dispense est une décision de POLITIQUE, pas une correction de nature.
    ``telegram_send_message`` envoie bien un message : la table doit continuer à
    le dire, sinon on perd l'information au lieu de l'arbitrer."""
    from app.agent.tool_nature import effect_of

    assert effect_of("telegram_send_message") == "ENGAGEANT"
    assert effect_of("browser_click") == "ENGAGEANT"
