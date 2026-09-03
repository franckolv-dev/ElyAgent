# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_nature.py
# @brief      Chaque outil sait ce qu'il est : mécanique, arbitre, ou engageant.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Lot 1 du plan de marche du 28/07/2026 — la donnée de référence.

La contradiction que Franck a relevée, et sa résolution
--------------------------------------------------------
    « Je te dis qu'Ely ne doit rien faire mais je t'ai demandé qu'elle nettoie
      mes mails et ajoute des rendez-vous. Je te dis un truc et son contraire. »

Elle se dissout : **un LLM ne peut pas agir sur le monde**, il n'émet que du
texte. Toute action est donc TOUJOURS exécutée par Ely — contrainte physique,
pas choix d'architecture. Ce qui était reproché le 27/07 n'était pas qu'Ely
agisse, c'est qu'elle **arbitre à la place de l'utilisateur** avec des seuils
codés d'avance.

D'où deux axes INDÉPENDANTS, et non trois catégories exclusives — c'est ce que
la classification a montré : ``gmail_send_email`` est à la fois engageant (il
part chez un tiers) et arbitre (le corps du message se rédige) :

- **l'EFFET** : ``LECTURE`` (ne modifie rien) · ``ECRITURE`` (réversible et
  privé) · ``ENGAGEANT`` (irréversible, visible par des tiers, ou coûte) ;
- **l'ARBITRAGE** : l'outil doit-il trancher des choix de forme sur lesquels
  deux personnes compétentes pourraient différer ?

Ce que ce lot livre, et ce qu'il ne livre PAS
----------------------------------------------
Il livre la table et la rend **observable**. Il ne change **aucun**
comportement : étendre l'autorisation aux 26 actes engageants nus est le lot 3,
et ça se décide en voyant la liste, pas en la subissant.

⚠️ Ici on échoue **FERMÉ**, contrairement à la boucle de conformité
--------------------------------------------------------------------
Pour la conformité, un doute laisse passer : une vérification cassée ne doit
pas retenir la réponse. Pour l'autorisation c'est l'inverse — un outil qu'on ne
sait pas classer est traité comme engageant. Un faux positif coûte une question
à l'utilisateur ; un faux négatif envoie un message ou supprime des données
sans qu'il l'ait voulu.

Run with:  cd backend && python -m pytest tests/test_tool_nature.py -v
"""
from __future__ import annotations

import ast
import pathlib

import pytest


def _declared_tools() -> set[str]:
    """Les outils réellement déclarés dans le code, lus à la source.

    On relit l'AST plutôt qu'on importe : un import tirerait tout le graphe de
    dépendances des outils (Google, navigateur, MCP) pour une question qui ne
    porte que sur des noms.

    ⚠️ Corrigé au lot 3 : ce scan ne regardait que ``app/agent/tools``, et
    ratait donc les **55 outils de ``skills/builtin``** — dont ceux qui pilotent
    le clavier, la souris et le système de fichiers. 154 recensés pour 208
    réels. Un pin de couverture qui ne couvre pas tout est un faux témoin.
    """
    root = pathlib.Path(__file__).parent.parent / "app"
    found: set[str] = set()
    for f in root.rglob("*.py"):
        try:
            tree = ast.parse(f.read_text())
        except Exception:  # noqa: BLE001 — un fichier illisible n'est pas un outil
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(getattr(d, "id", getattr(d, "attr", None)) == "tool"
                   for d in node.decorator_list):
                found.add(node.name)
    return found


# ─────────────────────────────────────────────────────────────────────
# La table couvre le code, et le code ne dérive pas de la table
# ─────────────────────────────────────────────────────────────────────


def test_every_declared_tool_is_classified():
    """Un outil non classé est une frontière qu'on n'a pas tranchée. Ce pin est
    ce qui force à classer un NOUVEL outil au lieu de le laisser filer."""
    from app.agent.tool_nature import TOOL_NATURE

    manquants = _declared_tools() - set(TOOL_NATURE)
    assert not manquants, f"outils déclarés mais non classés : {sorted(manquants)}"


def test_the_table_does_not_invent_tools():
    """Un nom qui n'existe plus dans le code laisse croire à une protection qui
    ne s'applique à rien."""
    from app.agent.tool_nature import TOOL_NATURE

    fantomes = set(TOOL_NATURE) - _declared_tools()
    assert not fantomes, f"classés mais absents du code : {sorted(fantomes)}"


def test_every_entry_declares_a_known_effect():
    from app.agent.tool_nature import EFFECTS, TOOL_NATURE

    mauvais = {n: v.effect for n, v in TOOL_NATURE.items() if v.effect not in EFFECTS}
    assert not mauvais, f"effets hors contrat : {mauvais}"


# ─────────────────────────────────────────────────────────────────────
# L'invariant : ne JAMAIS retirer une protection existante
# ─────────────────────────────────────────────────────────────────────


def test_no_tool_protected_today_loses_its_protection():
    """LE pin de sécurité du lot.

    La classification a placé ``gmail_trash_*`` en ECRITURE — raisonnement
    défendable, la corbeille Gmail est réversible. Mais ces trois outils sont
    sous autorisation AUJOURD'HUI. Suivre la table aveuglément retirerait une
    protection que Franck a demandée : une table de données ne doit jamais
    pouvoir déprotéger quoi que ce soit.
    """
    from app.agent.tool_nature import ALREADY_GUARDED, requires_approval

    perdus = [n for n in ALREADY_GUARDED if not requires_approval(n)]
    assert not perdus, f"protection perdue pour : {perdus}"


def test_an_unknown_tool_is_treated_as_engaging():
    """Échouer FERMÉ. Un faux positif coûte une question ; un faux négatif
    envoie un message ou supprime des données sans que l'utilisateur l'ait
    voulu. L'asymétrie est trop forte pour laisser passer le doute."""
    from app.agent.tool_nature import requires_approval

    assert requires_approval("outil_qui_nexiste_pas_encore") is True


def test_a_reading_tool_never_requires_approval():
    """Le pendant du pin précédent : demander l'autorisation de LIRE rendrait
    l'agent inutilisable, et apprendrait à l'utilisateur à valider sans lire."""
    from app.agent.tool_nature import requires_approval

    assert requires_approval("pdf_read") is False


# ─────────────────────────────────────────────────────────────────────
# Ce que la table sert à voir
# ─────────────────────────────────────────────────────────────────────


def test_there_is_no_unguarded_engaging_tool_left():
    """⚠️ Ce pin disait l'inverse au lot 1, sur une mesure FAUSSE.

    #296 affirmait « 26 actes engageants sans autorisation, dont
    ``ssh_execute`` et ``gmail_empty_trash`` ». Ces deux-là étaient déjà
    protégés : ``ALREADY_GUARDED`` avait été bâti sur ``hitl_descriptions.py``
    (6 outils) au lieu de la garde réelle (38). Le vrai trou était de 9 sur le
    périmètre connu, 18 sur le périmètre complet.

    Depuis le lot 3, il est fermé : tout acte engageant est soit sous
    autorisation, soit explicitement dispensé avec sa raison. Cette liste doit
    donc rester VIDE — et ce pin est ce qui le garantit dans la durée.
    """
    from app.agent.tool_nature import unguarded_engaging_tools

    assert unguarded_engaging_tools() == []


def test_tools_that_arbitrate_without_a_way_to_be_instructed_are_reported():
    """Le défaut exact de ``pdf_to_docx(source, output_name)`` avant #294 :
    l'outil tranchait la structure, et la demande de l'utilisateur n'avait aucun
    chemin pour l'atteindre. Mesuré : seulement 3 outils dans ce cas — le trou
    était isolé, pas systémique."""
    from app.agent.tool_nature import mute_arbitrating_tools

    muets = mute_arbitrating_tools()
    assert isinstance(muets, list)
    # pdf_to_docx a été débouché en #294 : il ne doit plus figurer ici.
    assert "pdf_to_docx" not in muets


def test_the_classification_is_readable_per_tool():
    from app.agent.tool_nature import arbitrates, effect_of

    assert effect_of("gmail_send_email") == "ENGAGEANT"
    assert effect_of("pdf_read") == "LECTURE"
    assert arbitrates("pdf_to_docx") is True


# ─────────────────────────────────────────────────────────────────────
# Le consommateur — sans lui, la table est une donnée morte
# ─────────────────────────────────────────────────────────────────────


def test_the_startup_check_stays_silent_now_that_the_hole_is_closed():
    """Une table que personne ne lit ne vaut rien — c'est le défaut relevé par
    l'audit du 25/07 (42 playbooks pour 1 usage). Le contrôle de réalité, qui
    tourne déjà au démarrage, en est le lecteur.

    Depuis le lot 3 il n'a plus rien à dire, et c'est le résultat recherché : un
    contrôle qui crie en permanence finit par ne plus être lu du tout."""
    from app.services.config_reality import check_unguarded_engaging_tools

    assert check_unguarded_engaging_tools() == []


def test_a_finding_would_state_its_consequence_not_just_the_name():
    """Leçon de #265 : « un constat qui énonce sa conséquence se remarque, un
    nom seul se noie ». L'avertissement « Unknown model » n'a jamais été lu.

    Le trou étant fermé, on vérifie la FORME du constat sur un outil simulé —
    sinon ce pin disparaîtrait avec le dernier trou, et la prochaine régression
    reviendrait avec un message illisible."""
    from app.services.config_reality import check_unguarded_engaging_tools

    findings = check_unguarded_engaging_tools(unguarded=["outil_engageant_fictif"])
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "unguarded_engaging_tool"
    assert len(f.detail) > 30
    assert f.subject not in f.detail, "le détail répète le nom au lieu d'expliquer"


def test_an_already_guarded_tool_is_not_reported_as_a_hole():
    from app.services.config_reality import check_unguarded_engaging_tools

    sujets = {f.subject for f in check_unguarded_engaging_tools()}
    assert "gmail_send_email" not in sujets
