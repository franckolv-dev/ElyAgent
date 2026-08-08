# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_config_reality_check.py
# @brief      Confronter la configuration DÉCLARÉE aux valeurs RÉELLEMENT
#             présentes — la classe de défaut qui a coûté le plus cher.
# @license    Elastic License 2.0
# =============================================================================
"""Pins du contrôle de réalité de la configuration.

**Pourquoi ce lot existe.** Le 26/07/2026, ``get_context_window()`` renvoyait
**8 192 tokens pour absolument tous les modèles** : la table ne connaissait
que ``gemma4:26b``, ``gpt-4o`` et ``claude-sonnet-4-6``, dont Ely ne fait
tourner aucun. Elle tronquait donc son contexte à 8 K en permanence, jetant
jusqu'à 95 % de ce qu'elle avait le droit de garder — sans une erreur, sans un
test rouge, pendant des mois.

**La signature de la classe.** Une correspondance qui (a) reçoit une clé
produite ailleurs dans le système, (b) possède un repli pour les clés
inconnues, et (c) dont le repli est *plausible* plutôt que manifestement
cassé. Personne ne vérifie jamais que les clés RÉELLES tombent dans la table
plutôt que dans le repli.

**Trois occurrences déjà constatées**, toutes de la même famille :

- la fenêtre de contexte — 0/8 modèles connus (corrigé #263) ;
- la table de tarification — 5/8 modèles connus, le coût affiché est donc
  faux pour les autres ;
- ``web_search_news`` et ``news_get_headlines`` bindés dans le profil sans
  exister au catalogue aurait produit le même silence (#257).

**Ce que ce lot ajoute, et ce qu'il ne remplace pas.** Un banc d'essai n'aurait
trouvé aucun des trois : il aurait dit « c'est lent », jamais « la table
renvoie 8 192 ». Ce contrôle-ci ne mesure pas la performance ; il vérifie que
ce que le système *croit* correspond à ce qui *existe*. Les deux sont
complémentaires — mais celui-ci vient d'abord, sinon le banc grave la panne
dans sa référence.

Run with:  cd backend && python -m pytest tests/test_config_reality_check.py -v
"""
from __future__ import annotations

import pytest


# ------------------------------------------------ la forme du diagnostic

@pytest.mark.asyncio
async def test_a_clean_configuration_reports_nothing():
    """Le contrôle doit rester silencieux quand tout résout — sinon il devient
    un décor qu'on cesse de lire, exactement comme l'avertissement
    « Unknown model » que personne n'a jamais vu passer."""
    from app.services.config_reality import check_config_reality

    # On isole la dimension testée : `bound_tools=[]` écarte le profil réel,
    # `resolved_models={}` écarte la sonde du résolveur ajoutée par le lot B
    # (elle a son propre fichier de tests). Un contrôle qui mêle ses sources
    # rend ses échecs illisibles.
    # `deepseek-v4-pro` est connu des tables de fenêtre et de tarif, mais son
    # plafond de SORTIE ne peut venir que de l'instance (lot E) : on le
    # déclare, sinon le contrôle le signale à juste titre.
    from app.services.context_manager import set_instance_overrides

    set_instance_overrides(outputs={"deepseek-v4-pro": 8_192})
    try:
        findings = await check_config_reality(
            models=["deepseek-v4-pro"], bound_tools=[], resolved_models={},
        )
    finally:
        set_instance_overrides()

    assert findings == [], f"faux positifs : {findings}"


@pytest.mark.asyncio
async def test_a_model_without_a_context_window_is_reported():
    """LE test du lot : c'est très exactement le défaut du 26/07."""
    from app.services.config_reality import check_config_reality

    findings = await check_config_reality(models=["un-modele-tout-neuf-jamais-declare"])

    kinds = {f.kind for f in findings}
    assert "model_window" in kinds, (
        "un modèle inconnu de la table des fenêtres passe encore inaperçu — "
        "il sera tronqué à 8 192 tokens sans que personne ne le sache"
    )


@pytest.mark.asyncio
async def test_a_model_without_a_price_is_reported():
    """Constaté le 26/07 : gpt-5.6-terra et les deux modèles locaux `qwen/`
    n'ont aucun tarif. Le coût affiché à l'utilisateur est donc faux."""
    from app.services.config_reality import check_config_reality

    findings = await check_config_reality(models=["un-modele-tout-neuf-jamais-declare"])

    assert "model_pricing" in {f.kind for f in findings}


@pytest.mark.asyncio
async def test_a_finding_says_what_it_costs_not_just_what_is_missing():
    """Un diagnostic qui liste des noms sans dire la conséquence se lit comme
    du bruit. Chaque constat doit porter son enjeu."""
    from app.services.config_reality import check_config_reality

    findings = await check_config_reality(models=["un-modele-tout-neuf"])

    for f in findings:
        assert f.subject
        assert len(f.detail) > 30, f"constat sans conséquence énoncée : {f}"


# --------------------------------------- les outils bindés existent-ils ?

@pytest.mark.asyncio
async def test_a_bound_tool_that_does_not_exist_is_reported():
    """La leçon de #257 : un nom bindé au profil mais absent du catalogue ne
    lève rien — l'agent ne voit simplement jamais l'outil, et affirme en toute
    honnêteté qu'il ne l'a pas."""
    from app.services.config_reality import check_config_reality

    findings = await check_config_reality(
        models=[], bound_tools=["outil_qui_nexiste_pas"],
    )

    assert "bound_tool_missing" in {f.kind for f in findings}


# Trouvés par ce contrôle DÈS SON PREMIER PASSAGE, et confirmés en
# production (le profil déclare 86 noms, 82 existent). Ils sont écrits dans le
# code mais jamais enregistrés : `browser_extension_skill` déclare 12 outils et
# oublie les trois recherches, `gmail_empty_trash` n'apparaît pas dans
# `gmail_skill`. Les inscrire ici plutôt que d'exiger zéro fantôme rend le
# constat visible sans bloquer, ET fait échouer la CI si un CINQUIÈME apparaît.
# Vidé le 26/07 : les trois recherches Chrome ont été enregistrées et
# `gmail_empty_trash` retiré du profil (il supprime définitivement). Le
# maintenir vide fait échouer la CI au PREMIER nouveau fantôme.
_KNOWN_GHOST_TOOLS: set[str] = set()


@pytest.mark.asyncio
async def test_no_new_ghost_tool_appears_in_the_profile():
    """Contrôle sur les VRAIES données. Les quatre fantômes connus sont
    tolérés — leur sort est un arbitrage (enregistrer, ou retirer du profil ;
    `gmail_empty_trash` supprime définitivement, ce n'est pas anodin). Tout
    NOUVEAU fantôme, lui, est une régression."""
    from app.agent.toolset_profiles import _DEFAULT_TOOLS
    from app.services.config_reality import check_config_reality

    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    catalog = {t.name for t in get_skill_registry().all_tools}

    # `orchestrate` s'enregistre par AUTO-DÉCOUVERTE. Isolée, celle-ci
    # fonctionne (6 outils trouvés) et la production le confirme ; mais en
    # suite complète, l'ordre des tests l'empêche parfois d'aboutir. Sans ce
    # garde-fou, le contrôle signalerait un fantôme qui n'en est pas un —
    # exactement le genre de faux positif qui fait cesser de lire un rapport.
    if "orchestrate" not in catalog:
        pytest.skip("auto-découverte incomplète dans ce contexte de test")

    findings = await check_config_reality(
        models=[], bound_tools=sorted(_DEFAULT_TOOLS),
    )

    ghosts = {f.subject for f in findings if f.kind == "bound_tool_missing"}
    new = ghosts - _KNOWN_GHOST_TOOLS
    assert not new, f"nouveaux noms bindés qui n'existent pas : {sorted(new)}"


# ------------------------------------------------ le contrôle ne casse rien

@pytest.mark.asyncio
async def test_the_check_never_raises():
    """C'est un instrument de diagnostic : il ne doit jamais empêcher Ely de
    démarrer, quelle que soit la forme de ce qu'il inspecte."""
    from app.services.config_reality import check_config_reality

    for models in (None, [], ["x"], [""]):
        out = await check_config_reality(models=models, bound_tools=None)
        assert isinstance(out, list)


@pytest.mark.asyncio
async def test_it_reads_the_real_instances_when_asked():
    """Sans argument, il inspecte ce qui est RÉELLEMENT configuré en base —
    c'est là que se produit la dérive : Franck ajoute une instance depuis
    l'interface, aucune table statique ne le sait."""
    from app.services.config_reality import check_config_reality

    out = await check_config_reality()

    assert isinstance(out, list)


def test_the_startup_runs_the_check():
    """Un contrôle qu'on doit penser à lancer ne sert à rien : celui-ci part
    au démarrage et journalise ce qui est tombé dans un repli."""
    from pathlib import Path

    src = Path("app/main.py").read_text(encoding="utf-8")

    assert "log_config_reality" in src


@pytest.mark.asyncio
async def test_the_log_wrapper_counts_what_it_reports():
    """L'enveloppe de journalisation doit rendre le nombre de constats : c'est
    ce que le démarrage — et plus tard un écran d'administration — affiche."""
    from app.services.config_reality import log_config_reality

    count = await log_config_reality()

    assert isinstance(count, int) and count >= 0


# ─────────────────────────────────────────────────────────────────────
# Servir le rang 2 de sa propre chaîne — diagnostic du 05/08/2026
# ─────────────────────────────────────────────────────────────────────
#
# L'incident. Du 28/07 au 05/08, le tier `complex` a servi DeepSeek v4 Pro —
# son rang 2 — pendant neuf jours : 994 requêtes, 42 M tokens, ~14 $. Les
# ~42 500 tokens par requête disaient que ce modèle ne donnait pas un second
# avis, il FAISAIT le travail. Or `provider_switches` ne portait qu'UNE
# bascule sur `complex` pour toute la période.
#
# Parce que la cascade de CONSTRUCTION (`get_llm_for_tier`) ne passe pas par
# `fallback_manager` : quand le rang 1 ne peut pas être construit (clé absente,
# instance hors cache), il est écarté et le rang 2 sert — sans ligne, sans
# toast, sans rien.
#
# `_check_resolved_model` ne pouvait pas le voir : il vérifie que le modèle
# servi est CONNU des tables et DÉCLARÉ par une instance. Un rang 2 de la même
# chaîne satisfait les deux — il est parfaitement déclaré.


@pytest.mark.asyncio
async def test_a_tier_serving_its_own_rank_2_is_reported(monkeypatch):
    """C'est l'invariant « un repli doit se voir » sur le chemin le plus cher.

    Un repli qui se présente comme nominal fait conclure que la configuration
    est appliquée alors qu'elle est contournée — ici, pendant neuf jours et
    pour 14 $.
    """
    from app.services import config_reality

    async def _rangs_1():
        return {"complex": "gpt-5.6-sol"}

    monkeypatch.setattr(config_reality, "_primary_models", _rangs_1)

    findings = await config_reality.check_config_reality(
        models=["gpt-5.6-sol", "deepseek-v4-pro"], bound_tools=[],
        # Ce que le tier sert RÉELLEMENT : le rang 2.
        resolved_models={"complex": "deepseek-v4-pro"},
    )

    replis = [f for f in findings if f.kind == "tier_serves_fallback"]
    assert len(replis) == 1, (
        "un tier qui sert son rang 2 doit produire un constat — sans lui, "
        "aucune surface du système ne le dit"
    )
    detail = replis[0].detail
    assert "deepseek-v4-pro" in detail and "gpt-5.6-sol" in detail, (
        "le constat doit nommer les DEUX modèles : « le tier sert X alors que "
        "son rang 1 est Y ». Un seul des deux ne se diagnostique pas"
    )
    assert "invisible" in detail or "SANS enregistrer" in detail, (
        "le constat doit dire sa conséquence — c'est ce qui distingue une "
        "ligne qu'on lit d'un avertissement qu'on ignore (cf. log_config_reality)"
    )


@pytest.mark.asyncio
async def test_a_tier_serving_its_rank_1_reports_nothing(monkeypatch):
    """Le pendant obligatoire : un contrôle qui crie toujours ne se lit plus.

    Sans ce pin, remplacer la comparaison par `if resolved:` passerait le test
    ci-dessus et produirait un constat permanent sur chaque tier.
    """
    from app.services import config_reality

    async def _rangs_1():
        return {"complex": "gpt-5.6-sol"}

    monkeypatch.setattr(config_reality, "_primary_models", _rangs_1)

    findings = await config_reality.check_config_reality(
        models=["gpt-5.6-sol"], bound_tools=[],
        resolved_models={"complex": "gpt-5.6-sol"},
    )

    assert [f for f in findings if f.kind == "tier_serves_fallback"] == [], (
        "le rang 1 servi est le cas nominal : il ne doit rien signaler"
    )


@pytest.mark.asyncio
async def test_an_unknown_rank_1_does_not_invent_a_finding(monkeypatch):
    """Rang 1 illisible (cache vide, config absente) = « non vérifié », pas
    « repli détecté ». Accuser sans savoir ferait perdre au constat la
    confiance qui le rend utile."""
    from app.services import config_reality

    async def _rien():
        return {}

    monkeypatch.setattr(config_reality, "_primary_models", _rien)

    findings = await config_reality.check_config_reality(
        models=["deepseek-v4-pro"], bound_tools=[],
        resolved_models={"complex": "deepseek-v4-pro"},
    )

    assert [f for f in findings if f.kind == "tier_serves_fallback"] == []
