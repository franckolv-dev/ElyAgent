# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_mission_ne_se_bloque_pas_sur_son_routage.py
# @brief      Ce qu'un profil EXCLUT, rien ne le rebranche — pas même l'union
#             des outils nommés dans le prompt ; et une procédure apprise ne
#             peut pas conditionner le travail à un auto-diagnostic.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Mission « Prospection Market-Comm » (64e6f1a1), 04/09/2026, 19h07-19h31 :
200 itérations, 5 000 000 de tokens — le budget maximum — et RIEN d'écrit.
Ni Google Sheet, ni historique. Les trois sociétés et leurs contacts étaient
trouvés dès le milieu du passage ; le modèle a refusé de les écrire.

Sa raison, dans son propre bilan : ``BLOQUE_CONFIG_TIER``. Sur 200 actions,
34 ``system_get_logs`` et 11 ``system_check_llm_providers``.

Deux défauts, indépendants, qui se sont additionnés.

1. **Le profil `mission` excluait ces outils depuis #378** — et l'union des
   « outils nommés dans le prompt » (le filet des tâches automatisées, qui
   lit la consigne, carnet compris) les rebranchait à chaque tour :
   ``[automated_task] +2 named tool(s) bound: ['system_check_llm_providers',
   'system_get_logs']``. Un carnet qui cite un outil le fait revenir : la
   boucle d'auto-diagnostic de #378 rouvrait par la porte de service.
   👉 Ce qu'un profil EXCLUT n'est pas « ce qui n'a pas été demandé », c'est
   une INTERDICTION. Aucun filet ne la lève.

2. **Sept procédures apprises « valider-tier-avant-mutations »**, écrites par
   Ely elle-même entre le 09/08 et le 31/08, actives, injectées dans chaque
   prompt. Leur étape 5 : « si une métadonnée reste absente […] n'appeler
   AUCUN outil Gmail, GoogleDrive ou GoogleSheets ». Leur étape 4 reconnaît
   qu'aucun outil ne permet d'obtenir cette métadonnée. Une condition
   inatteignable posée en préalable de tout travail : le blocage est écrit
   dans la procédure.
   👉 Une procédure apprise ne conditionne pas le travail à un
   auto-diagnostic. Une mission ne s'ausculte pas (#378) — elle ne peut pas
   davantage l'apprendre.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

_DIAGNOSTIC = ("system_get_logs", "system_check_llm_providers", "system_get_health")


# ── 1. Ce qu'un profil exclut, rien ne le rebranche ──────────────────────────

def test_le_profil_mission_declare_ses_exclusions():
    from app.agent.toolset_profiles import outils_exclus_du_profil

    exclus = outils_exclus_du_profil("mission")

    assert set(_DIAGNOSTIC) <= exclus
    assert outils_exclus_du_profil("default") == frozenset(), (
        "au chat, « montre-moi les journaux » reste une demande légitime"
    )


def _outil(nom: str):
    return StructuredTool.from_function(
        func=lambda x="": "ok", name=nom, description=f"Outil de test {nom}.",
    )


_BUT = (
    "Relis le carnet : au passage précédent, system_get_logs et "
    "system_check_llm_providers ont été appelés. Note trois imprimeries avec "
    "sheets_ajoute_une_ligne."
)


class _ModeleQuiNoteSesOutils:
    def __init__(self):
        self.liaisons: list[set[str]] = []

    def bind_tools(self, tools, **_kw):
        self.liaisons.append({getattr(t, "name", "?") for t in tools})
        return self

    def with_config(self, *_a, **_kw):
        return self

    async def ainvoke(self, messages, config=None, **_kw):
        return AIMessage(content="Rien a faire.")


@pytest_asyncio.fixture
async def mission(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.database import async_session, init_db
    from app.models.user import User
    from app.services import mission_service
    from tests._user_cleanup import purge_user

    await init_db()
    uid = f"test_rout_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal=_BUT, budget_iterations=30,
    )
    await mission_service.start_mission(m.id)
    yield uid, m.id
    await purge_user(uid)


@pytest.mark.asyncio
async def test_un_outil_nomme_dans_la_consigne_ne_leve_pas_l_exclusion(
    mission, monkeypatch,
):
    """LE défaut du 04/09 : la consigne cite `system_get_logs` (le carnet le
    fait à chaque passage), l'union le rebranchait, la mission s'auscultait."""
    uid, mid = mission
    import app.agent.missions.nodes as mn
    import app.services.llm_provider as lp
    from app.agent.missions import outillage
    from app.skills import get_skill_registry
    from app.skills.base import Skill

    registre = get_skill_registry()
    registre.register_or_replace(Skill(
        name="_bench_routage", display_name="R", description="R", icon="R",
        tools=[_outil("sheets_ajoute_une_ligne"), *(_outil(n) for n in _DIAGNOSTIC)],
    ))

    async def _selecteur(goal, tools, *, include_core=True):
        return [t for t in tools if t.name == "sheets_ajoute_une_ligne"]

    monkeypatch.setattr(outillage, "select_tools", _selecteur)

    async def _dispatch(nom, args, _cid, _uid, **_kw):
        return "ok", True

    modele = _ModeleQuiNoteSesOutils()
    monkeypatch.setattr(lp, "get_llm_for_tier", lambda *a, **k: modele)
    monkeypatch.setattr(lp, "get_fallback_llms", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(lp, "get_llm", lambda *a, **k: modele, raising=False)
    monkeypatch.setattr(mn, "dispatch_tool", _dispatch)
    from app.agent.missions.chat_loop import run_mission_chat_passage

    try:
        await run_mission_chat_passage(mid, uid, _BUT)
    finally:
        registre.unregister("_bench_routage")

    lies = modele.liaisons[0]
    assert not (lies & set(_DIAGNOSTIC)), lies & set(_DIAGNOSTIC)
    assert "sheets_ajoute_une_ligne" in lies, (
        "l'union doit continuer à rattraper les outils MÉTIER nommés"
    )


# ── 2. Une procédure apprise ne bloque pas le travail sur un diagnostic ──────

# Le texte réel de `valider-tier-avant-appels-metier` (27/08), abrégé.
_PROCEDURE_QUI_BLOQUE = """\
---
name: valider-tier-avant-appels-metier
description: Contrôler le routage avant tout appel métier.
---

## Quand l'appliquer
Avant tout appel Gmail, GoogleDrive ou GoogleSheets lorsque l'exécution
exige un contrôle CONFIG_TIER.

## Ne pas appliquer quand
Les métadonnées actives ne sont pas obligatoires.

## Procédure
1. Appeler `system_check_llm_providers`, puis `system_get_health` et
   `system_get_logs`, avant tout outil métier.
2. Exiger cinq métadonnées actives : provider, modèle, tier, fallback, erreur.
3. Si aucun outil enregistré ne permet de forcer ces tentatives, considérer
   ce contrôle comme hors de portée.
4. Si une métadonnée reste absente, n'appeler AUCUN outil Gmail, GoogleDrive
   ou GoogleSheets.

## Pièges
Le fallback silencieux.

## Terminé quand
Le statut `BLOQUE_CONFIG_TIER` est produit ou le contrôle réussit.
"""

_PROCEDURE_SAINE = """\
---
name: prospection-calameo-sans-doublons
description: Prospecter des catalogues Calaméo sans reprendre l'historique.
---

## Quand l'appliquer
Quand une mission demande des sociétés publiant sur Calaméo.

## Ne pas appliquer quand
L'historique n'est pas accessible.

## Procédure
1. Lire `historique_Prospection_Print.md` avec `drive_read_file`.
2. Chercher les catalogues avec `web_search`, exclure les sociétés déjà vues.
3. Écrire les contacts avec `sheets_append_rows`, puis relire la feuille.

## Pièges
Une requête LinkedIn trop longue ne rend rien : simplifier avant de renoncer.

## Terminé quand
La feuille contient trois sociétés absentes de l'historique.
"""


def test_une_procedure_qui_exige_un_diagnostic_est_reconnue():
    from app.services.learning.skill_from_success import exige_un_auto_diagnostic

    assert exige_un_auto_diagnostic(_PROCEDURE_QUI_BLOQUE) is True
    assert exige_un_auto_diagnostic(_PROCEDURE_SAINE) is False
    assert exige_un_auto_diagnostic("") is False


def test_le_verrou_compte_meme_sous_sa_forme_polie():
    """`fiabiliser-prospection-catalogues-linkedin`, écrit par la mission
    elle-même le 04/09 à 19h12 : pas de « n'appelle aucun outil », mais un
    « ne pas appliquer si le routage n'est pas certifiable » — et l'étape 1
    qui appelle les sondes. Le cul-de-sac est le même."""
    from app.services.learning.skill_from_success import exige_un_auto_diagnostic

    texte = (
        "## Ne pas appliquer quand\nLe routage primaire exigé n'est pas "
        "certifiable.\n\n## Procédure\n1. Appeler `system_check_llm_providers`, "
        "puis `system_get_logs` pour `fallback` et `tier`.\n"
    )
    assert exige_un_auto_diagnostic(texte) is True


def test_une_procedure_qui_cite_un_outil_de_diagnostic_sans_bloquer_passe():
    """On refuse le VERROU, pas le mot. « J'ai lu les journaux pour
    comprendre » reste une procédure de chat légitime."""
    from app.services.learning.skill_from_success import exige_un_auto_diagnostic

    texte = (
        "## Procédure\n1. Quand l'utilisateur demande pourquoi une tâche a "
        "échoué, appeler `system_get_logs` et lui rendre les lignes utiles.\n"
    )
    assert exige_un_auto_diagnostic(texte) is False


def _tour_reussi() -> list:
    return [
        HumanMessage(content="Trouve trois sociétés et note-les."),
        AIMessage(content="", tool_calls=[
            {"name": "web_search", "args": {"q": "calaméo"}, "id": "1"},
        ]),
        ToolMessage(content="trois sociétés trouvées", tool_call_id="1"),
        AIMessage(content="Voilà, trois sociétés notées."),
    ]


@pytest.fixture
def modele(monkeypatch):
    def _install(reponse: str):
        from app.services.learning import skill_from_success as sfs

        monkeypatch.setattr(
            "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object(),
        )

        async def _faux(*_a, **_k):
            return AIMessage(content=reponse)

        monkeypatch.setattr(sfs, "ainvoke_with_deadline", _faux)

    return _install


@pytest.mark.asyncio
async def test_une_procedure_qui_bloque_le_travail_n_entre_pas_au_catalogue(modele):
    from app.services.learning.skill_from_success import draft_skill_from_success

    modele(_PROCEDURE_QUI_BLOQUE)

    assert await draft_skill_from_success("user-routage", _tour_reussi()) is None


@pytest.mark.asyncio
async def test_une_procedure_de_travail_est_toujours_proposee(modele):
    from app.services.learning.skill_from_success import draft_skill_from_success

    modele(_PROCEDURE_SAINE)
    skill = await draft_skill_from_success("user-routage", _tour_reussi())

    assert skill is not None
    assert skill.name == "prospection-calameo-sans-doublons"
