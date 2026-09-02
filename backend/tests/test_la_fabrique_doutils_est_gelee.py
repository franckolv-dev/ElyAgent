# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_la_fabrique_doutils_est_gelee.py
# @brief      Point 11 de l'audit — la compétence est un DOCUMENT, plus du code.
# @license    Elastic License 2.0
# =============================================================================
"""Geler la fabrique d'outils, sans rendre l'apprentissage muet (02/09/2026).

LA MESURE, cinq mois de production
-----------------------------------
    98 compétences apprises — dont 43 PÉRIMÉES, 13 archivées, 3 graduées
    49 correctifs proposés  — 28 appliqués, TOUS sur des prompts planifiés
     0 exécution d'outil en bac à sable, jamais
     1 retour utilisateur sur 1 637 conversations

La voie « outil » ne produit rien qui serve. La voie « document » (une
procédure Markdown validée par l'humain) devient le SEUL produit de
l'apprentissage.

⚠️ CE QUE FAISAIT LE DRAPEAU AVANT CE LOT
-------------------------------------------
``auto_tool_generation_enabled`` ne gelait pas la fabrique : il éteignait
l'apprentissage TOUT ENTIER. Deux endroits, l'un après l'autre :

  ``find_tool_skill._record_gap_and_trigger``  ne lançait même pas la
      rédaction quand le drapeau était à False — le manque était consigné
      puis plus personne ne s'en occupait ;
  ``auto_tool_generation.maybe_generate_for_gap``  sortait par ``return
      None`` en première ligne, avant l'aiguillage.

Éteindre le drapeau, c'était donc perdre AUSSI les procédures. Le geler
proprement veut dire : la fabrique se tait, la rédaction continue.

⚠️ CE QUI NE DOIT PAS CASSER
------------------------------
Geler la FABRIQUE n'est pas désactiver ses PRODUITS. Les outils Python déjà
promus et actifs restent chargés et appelables — c'est le dernier test de ce
fichier, et c'est la garde qui autorise le gel.

Run with:  cd backend && python -m pytest tests/test_la_fabrique_doutils_est_gelee.py -v
"""
from __future__ import annotations

import textwrap
import uuid

import pytest
import pytest_asyncio

from app.services.learning import auto_tool_generation as atg
from tests._user_cleanup import purge_user


@pytest.fixture(autouse=True)
def _tentatives_vierges():
    atg.reset_attempts()
    yield
    atg.reset_attempts()


def _fabrique(monkeypatch, *, ouverte: bool):
    """Ouvre ou gèle la fabrique d'outils.

    ``get_settings`` est ``lru_cache``é : on patche l'INSTANCE partagée, un
    attribut de classe serait masqué par le champ pydantic de l'instance.
    """
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "auto_tool_generation_enabled", ouverte)


class _Espion:
    def __init__(self, resultat=None):
        self.appels: list = []
        self._resultat = resultat

    async def __call__(self, *args, **kwargs):
        self.appels.append((args, kwargs))
        return self._resultat


@pytest.fixture
def _pas_doutil_existant(monkeypatch):
    """Le pré-check anti-doublon ne trouve rien — on juge le gel, pas lui."""
    monkeypatch.setattr(
        "app.skills.builtin.find_tool_skill.capability_has_existing_tool",
        _Espion(None),
    )


# ─────────────────────────────────────────────────────────────────────
# 1 — Fabrique gelée : une capacité manquante devient une PROCÉDURE
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_une_capacite_manquante_produit_une_procedure_et_pas_du_code(
    monkeypatch, _pas_doutil_existant,
):
    """LE test du lot. Drapeau OFF : on rédige, on ne fabrique pas."""
    _fabrique(monkeypatch, ouverte=False)
    fabriquer = _Espion({"status": "created", "tool_name": "sms_send"})
    rediger = _Espion({"status": "drafted", "skill_name": "envoyer-un-sms"})
    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_and_persist_tool", fabriquer)
    monkeypatch.setattr(
        "app.services.learning.skill_creator.draft_playbook_for_gap", rediger)

    sortie = await atg.maybe_generate_for_gap(1, "envoyer un SMS", "u1")

    assert fabriquer.appels == [], "un candidat de code a été fabriqué malgré le gel"
    assert len(rediger.appels) == 1, "aucune procédure écrite — la boucle est muette"
    assert sortie and sortie["status"] == "drafted", (
        "la boucle rend None : l'appelant ne sait pas qu'une procédure est partie"
    )


@pytest.mark.asyncio
async def test_la_fabrique_gelee_ne_paie_pas_le_juge(monkeypatch, _pas_doutil_existant):
    """Demander « outil ou compétence ? » quand aucun outil ne peut sortir est
    un appel de modèle payé pour rien : la réponse ne change plus rien."""
    _fabrique(monkeypatch, ouverte=False)
    juge = _Espion(True)
    monkeypatch.setattr("app.services.learning.tool_or_skill.needs_a_tool", juge)
    monkeypatch.setattr(
        "app.services.learning.skill_creator.draft_playbook_for_gap",
        _Espion({"status": "drafted"}))

    await atg.maybe_generate_for_gap(2, "envoyer un SMS", "u1")

    assert juge.appels == [], "le juge est encore interrogé alors qu'il n'arbitre plus rien"


@pytest.mark.asyncio
async def test_fabrique_ouverte_laccord_du_juge_fabrique_toujours(
    monkeypatch, _pas_doutil_existant,
):
    """Le gel est un RÉGLAGE, pas une suppression : rouvert, le chemin outil
    refonctionne à l'identique (le code de la fabrique reste dormant, pas mort)."""
    _fabrique(monkeypatch, ouverte=True)
    monkeypatch.setattr(
        "app.services.learning.tool_or_skill.needs_a_tool", _Espion(True))
    fabriquer = _Espion({"status": "created", "tool_name": "sms_send"})
    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_and_persist_tool", fabriquer)
    monkeypatch.setattr(
        "app.services.learning.candidate_notify.notify_candidate", _Espion(None))

    await atg.maybe_generate_for_gap(3, "envoyer un SMS", "u1")

    assert len(fabriquer.appels) == 1


# ─────────────────────────────────────────────────────────────────────
# 2 — Le déclencheur ne se tait plus quand la fabrique est gelée
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_un_manque_lance_la_redaction_meme_fabrique_gelee(monkeypatch):
    """⚠️ Le second endroit où le drapeau éteignait tout.

    ``_record_gap_and_trigger`` ne lançait la tâche de fond QUE si le drapeau
    était ouvert. Gelé, le manque était consigné et abandonné : la voie
    document n'était jamais empruntée, faute de départ.
    """
    from app.skills.builtin import find_tool_skill as fts

    _fabrique(monkeypatch, ouverte=False)
    monkeypatch.setattr(
        "app.services.learning.failure_capture.record_tool_absent", _Espion(51))

    lances: list[str] = []

    def _spawn(coro, *, label="", **kwargs):
        lances.append(label)
        coro.close()  # rien ne tourne dans un test : on ne laisse pas de coroutine en l'air

    monkeypatch.setattr("app.services.background_tasks.spawn", _spawn)

    message = await fts._record_gap_and_trigger("envoyer un SMS")

    assert lances == ["auto-tool-generation"], (
        "aucune rédaction lancée : le manque est consigné puis oublié"
    )
    assert "procédure" in message, (
        "le message ne dit pas ce qui démarre — le modèle attend un outil qui "
        "ne viendra pas"
    )


@pytest.mark.asyncio
async def test_fabrique_gelee_le_message_ne_promet_plus_un_outil(monkeypatch):
    """Promettre « un outil candidat » quand la fabrique est gelée ferait
    attendre au modèle une capacité appelable qui n'arrivera jamais."""
    from app.skills.builtin import find_tool_skill as fts

    _fabrique(monkeypatch, ouverte=False)
    monkeypatch.setattr(
        "app.services.learning.failure_capture.record_tool_absent", _Espion(52))
    monkeypatch.setattr(
        "app.services.background_tasks.spawn",
        lambda coro, **kw: coro.close())

    message = await fts._record_gap_and_trigger("envoyer un SMS")

    assert "outil candidat" not in message, (
        "la fabrique est gelée et le message annonce encore un outil candidat"
    )
    assert "outil peut y être généré" not in message, (
        "le repli annonce une génération d'outil que le gel interdit"
    )


# ─────────────────────────────────────────────────────────────────────
# 3 — Geler la fabrique n'éteint pas ses PRODUITS
# ─────────────────────────────────────────────────────────────────────


_OUTIL_PROMU = textwrap.dedent(
    '''
    from langchain_core.tools import tool


    @tool
    def doubler(x: int) -> int:
        """Doubler l'entier x."""
        return x * 2
    '''
).strip()


@pytest_asyncio.fixture
async def _utilisateur():
    from app.database import async_session, init_db
    from app.models.user import User

    await init_db()
    uid = f"gel-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"gel_{uid}", email=f"{uid}@t.local",
                    hashed_password="x"))
        await db.commit()
    yield uid
    from app.services.learning import learned_tools_runtime as rt

    rt.invalidate(uid)
    await purge_user(uid)


@pytest.mark.asyncio
async def test_un_outil_python_deja_promu_reste_appelable(_utilisateur, monkeypatch):
    """⚠️ LA GARDE QUI AUTORISE LE GEL.

    Trois outils ont été gradués en cinq mois ; ils tournent. Geler la
    FABRIQUE ne doit pas désactiver ses PRODUITS — sinon le lot casse ce qui
    sert au lieu de supprimer ce qui ne sert pas.
    """
    from app.database import async_session
    from app.models.learned_skill import (
        LearnedSkill,
        SkillContentFormat,
        SkillSource,
        SkillStatus,
    )
    from app.services.learning import learned_tools_runtime as rt

    _fabrique(monkeypatch, ouverte=False)          # fabrique GELÉE
    monkeypatch.setenv("LEARNED_PYTHON_TOOLS_ENABLED", "1")
    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_DISABLED", raising=False)

    async with async_session() as db:
        db.add(LearnedSkill(
            id=str(uuid.uuid4()), user_id=_utilisateur, name="doubler",
            description="x2", content=_OUTIL_PROMU,
            content_format=SkillContentFormat.PYTHON_TOOL,
            status=SkillStatus.ACTIVE, source=SkillSource.AUTO_GENERATED,
        ))
        await db.commit()

    outils = await rt.load_active_python_tools(_utilisateur, use_cache=False)

    assert [o.name for o in outils] == ["doubler"], (
        "un outil promu a disparu du binding parce que la fabrique est gelée"
    )
    assert outils[0].invoke({"x": 21}) == 42, "l'outil promu ne s'exécute plus"


# ─────────────────────────────────────────────────────────────────────
# 4 — La paire message/prompt (correctifs de relecture, 02/09/2026)
# ─────────────────────────────────────────────────────────────────────


def _consigne_systeme() -> str:
    """Ce que le prompt SERVI au modèle dit de `report_missing_capability`."""
    from app.agent.prompts import _SYSTEM_PROMPT_BASE

    lignes = [
        ligne for ligne in _SYSTEM_PROMPT_BASE.splitlines()
        if "report_missing_capability" in ligne
    ]
    assert lignes, "la consigne `report_missing_capability` a quitté le prompt système"
    return " ".join(lignes)


def _description_servie() -> str:
    """La docstring de l'outil est SERVIE au modèle comme sa description."""
    from app.skills.builtin.find_tool_skill import report_missing_capability

    return report_missing_capability.description


@pytest.mark.asyncio
async def test_le_prompt_ne_fait_pas_promettre_un_outil_que_loutil_ne_promet_pas(
    monkeypatch,
):
    """⚠️ LE DÉFAUT QUE LE LOT AVAIT LAISSÉ DERRIÈRE LUI.

    Corriger le message rendu par `find_tool` ne suffit pas : la consigne
    système ORDONNAIT au modèle de dire l'inverse (« un outil candidat est en
    cours de génération »). Fabrique gelée, l'utilisateur s'entendait donc
    toujours promettre une capacité appelable qui n'arrivera jamais — et
    aucun test du lot ne lisait le prompt.

    Les deux textes sont servis au modèle : ils doivent nommer la même issue.
    """
    from app.skills.builtin import find_tool_skill as fts

    _fabrique(monkeypatch, ouverte=False)
    monkeypatch.setattr(
        "app.services.learning.failure_capture.record_tool_absent", _Espion(53))
    monkeypatch.setattr(
        "app.services.background_tasks.spawn", lambda coro, **kw: coro.close())

    message = await fts._record_gap_and_trigger("envoyer un SMS", model_judged=True)

    assert "outil candidat" not in message, "garde du lot : le message a régressé"
    for texte, ou in ((_consigne_systeme(), "le prompt système"),
                      (_description_servie(), "la description de l'outil")):
        assert "un outil candidat est en cours de génération" not in texte, (
            f"{ou} fait annoncer un outil candidat que l'outil, lui, n'annonce "
            "pas — la fabrique est gelée"
        )
        assert "génération d'un outil candidat" not in texte, (
            f"{ou} nomme l'outil candidat comme issue UNIQUE de "
            "`report_missing_capability`"
        )


def test_la_consigne_systeme_nomme_la_redaction_et_sa_validation():
    """L'issue réelle : une RÉDACTION (procédure, ou outil si la fabrique est
    ouverte) soumise à validation humaine. Le prompt doit la nommer, sinon le
    modèle retombe sur « je ne peux pas » — le comportement que la consigne
    existe pour corriger."""
    consigne = _consigne_systeme()

    assert "procédure" in consigne, (
        "le prompt ne nomme pas la procédure : le modèle n'a plus que l'outil "
        "à annoncer, ou rien"
    )
    assert "validation" in consigne, (
        "le prompt ne dit pas que la rédaction passe par une validation humaine"
    )


@pytest.mark.asyncio
async def test_le_drapeau_est_lu_avant_le_depart_de_la_redaction(monkeypatch):
    """⚠️ Le drapeau était lu APRÈS `spawn`, dans le même `try`.

    Une lecture de config qui lève faisait retomber le message sur « rien n'a
    pu être lancé » alors que la rédaction était DÉJÀ partie : Ely dirait à
    l'utilisateur que personne ne s'en occupe pendant qu'une procédure s'écrit.
    Probabilité minuscule, classe de défaut identique à celle du lot.
    """
    from app.skills.builtin import find_tool_skill as fts

    def _config_cassee():
        raise RuntimeError("settings illisibles")

    monkeypatch.setattr("app.config.get_settings", _config_cassee)
    monkeypatch.setattr(
        "app.services.learning.failure_capture.record_tool_absent", _Espion(54))

    lances: list[str] = []

    def _spawn(coro, *, label="", **kwargs):
        lances.append(label)
        coro.close()

    monkeypatch.setattr("app.services.background_tasks.spawn", _spawn)

    message = await fts._record_gap_and_trigger("envoyer un SMS")

    assert lances == ["auto-tool-generation"], (
        "le départ de la rédaction dépend d'une lecture de drapeau qui a levé"
    )
    # ⚠️ 02/09/2026 — l'assertion porte sur le message de REPLI, pas sur le
    # mot « rédaction ». Depuis que le chemin gelé cesse d'affirmer un départ
    # (la tâche de fond a deux sorties silencieuses légitimes : `deja_perimee`
    # et `candidate_en_attente`), le message gelé ne contient plus ce mot. Ce
    # que ce test retient reste vrai et reste le vrai invariant : quand la
    # rédaction EST partie, on ne sert pas la phrase qui dit que personne ne
    # s'en occupe.
    assert "attend une décision humaine" not in message, (
        "une rédaction est partie et le message sert le repli « rien ne s'est "
        "lancé » : Ely dit que personne ne s'en occupe pendant que ça s'écrit"
    )
    assert "validation humaine" in message, (
        "le message gelé doit dire où la capacité atterrit et qu'elle passe "
        "par une validation avant de servir"
    )
    assert "outil candidat" not in message, (
        "drapeau illisible : on ne promet pas un outil dont on ne sait pas si "
        "la fabrique peut le produire"
    )


@pytest.mark.asyncio
async def test_drapeau_illisible_la_redaction_promise_part_vraiment(
    monkeypatch, _pas_doutil_existant,
):
    """⚠️ LE MESSAGE PROMETTAIT UNE PROCÉDURE QUI NE PARTAIT PAS (02/09/2026).

    `_record_gap_and_trigger` lit le drapeau dans son propre `try` : illisible,
    il vaut « fabrique gelée » et le message annonce « une procédure est en
    cours de rédaction ». Mais `maybe_generate_for_gap` relisait le MÊME
    `get_settings`, tombait dans son `except` général et sortait par
    `return None` — après avoir brûlé le `case_id` dans `_attempted_cases`, ce
    qui interdit une seconde tentative dans le boot. Rien n'était écrit, et
    rien ne pouvait plus l'être.

    Le test du départ ne le voyait pas : il stube `spawn`, donc la rédaction
    ne tourne jamais. Un drapeau illisible vaut « gelée » des DEUX côtés.
    """
    def _config_cassee():
        raise RuntimeError("settings illisibles")

    monkeypatch.setattr("app.config.get_settings", _config_cassee)
    rediger = _Espion({"status": "drafted", "skill_name": "envoyer-un-sms"})
    monkeypatch.setattr(
        "app.services.learning.skill_creator.draft_playbook_for_gap", rediger)
    fabriquer = _Espion({"status": "created", "tool_name": "sms_send"})
    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_and_persist_tool", fabriquer)

    sortie = await atg.maybe_generate_for_gap(60, "envoyer un SMS", "u1")

    assert len(rediger.appels) == 1, (
        "le message a promis une procédure et rien n'est parti — le cas est "
        "en plus brûlé pour ce boot"
    )
    assert fabriquer.appels == [], (
        "drapeau illisible : on ne fabrique pas du code sans savoir si la "
        "fabrique est ouverte"
    )
    assert sortie and sortie["status"] == "drafted", sortie
