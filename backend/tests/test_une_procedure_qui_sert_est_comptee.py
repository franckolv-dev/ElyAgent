# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_procedure_qui_sert_est_comptee.py
# @brief      La voie DOCUMENT : un playbook complet, proposé, et compté.
# @license    Elastic License 2.0
# =============================================================================
"""La compétence est un DOCUMENT — et on sait s'il sert.

Le constat, mesuré le 02/09/2026
--------------------------------
    98 compétences apprises   dont 43 périmées, 13 archivées, 3 graduées
    49 correctifs proposés    dont 28 appliqués
    0 exécution d'outil en bac à sable

La boucle produit, et presque rien n'est consommé. Deux trous précis derrière
ce chiffre, et ce fichier les épingle tous les deux.

Trou 1 — le document ne portait pas ce qu'on lui demande
--------------------------------------------------------
``skill_from_success`` réclamait trois rubriques : quand l'appliquer, la
procédure, comment vérifier. Manquaient les DEUX qui font la différence entre
une procédure et un pense-bête :

  - **quand NE PAS l'employer** — un anti-déclencheur noyé dans la prose de
    « quand l'appliquer » ne se relit pas et ne se contrôle pas ;
  - **les pièges rencontrés** — c'est précisément ce que le tour vient
    d'apprendre, et ça n'était demandé nulle part.

Le contrôle de forme AVERTIT, il ne jette pas : l'appel de modèle est déjà payé
quand on le lit, et c'est l'humain qui valide — on lui dit ce qui manque, dans
la raison qu'il a sous les yeux.

Trou 2 — le compteur d'usage ne pouvait plus bouger
----------------------------------------------------
``use_count`` n'est incrémenté que par ``skill_view`` (**0 appel depuis
toujours**, cf. ``active_skills``), par ``find_tool``, et par l'invocation
d'un ``python_tool``. Or depuis le 28/07 le chemin NOMINAL d'un playbook est
l'injection directe de sa procédure dans le prompt. Une procédure chargée à
chaque conversation affichait donc ``use_count = 0``, ce qui la faisait passer
``active -> stale -> archived`` par le curateur.

⚠️ Compter l'INJECTION aurait été pire que le mal. Et compter TOUTE procédure
qui cite un outil appelé ne valait pas mieux : trois procédures livrées citant
la recherche web voyaient leur compteur monter pour UN appel de recherche. On
compte donc au plus UNE procédure par tour — la plus proche de ce qui s'est
passé — et RIEN en cas d'égalité.

⚠️ Et on lit le bloc RÉELLEMENT injecté (le snapshot figé de la conversation),
on ne rejoue pas la sélection : cette sélection est triée par le compteur
lui-même, et la rejouer bouclait — une procédure sous la coupe n'était jamais
livrée, donc jamais comptée, donc jamais remontée.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillSource,
    SkillStatus,
)


# ─────────────────────────────────────────────────────────────────────────
# Ce que le document doit porter
# ─────────────────────────────────────────────────────────────────────────


_COMPLET = """---
name: pdf-vers-docx-garder-marges
description: Conserver la géométrie de page lors d'une conversion PDF vers Word.
---

## Quand l'appliquer
Une conversion PDF -> DOCX où l'utilisateur exige la mise en page.

## Ne pas appliquer quand
Le PDF est un scan sans couche texte : passer par l'OCR d'abord.

## Procédure
1. Appeler `pdf_to_docx` avec `keep_geometry=True`.

## Pièges
Sans `keep_geometry`, l'outil rend un document propre mais aux marges fausses,
et il ne le signale pas.

## Terminé quand
Le calibrage rapporté par l'outil est à 0 caractère perdu.
"""


def test_la_demande_de_redaction_reclame_les_cinq_rubriques():
    """Les cinq choses que le produit promet, nommées dans la consigne."""
    from app.services.learning.skill_from_success import build_success_skill_prompt

    prompt = build_success_skill_prompt([
        HumanMessage(content="convertis ce pdf en docx en gardant les marges"),
        HumanMessage(content="[Vérification — …]\n- les marges sautent"),
        AIMessage(content="Voilà, marges conservées."),
    ])
    for rubrique in (
        "Quand l'appliquer",
        "Ne pas appliquer quand",
        "Procédure",
        "Pièges",
        "Terminé quand",
    ):
        assert rubrique in prompt, f"la consigne ne réclame pas « {rubrique} »"


def test_un_document_complet_ne_manque_de_rien():
    from app.services.learning.skill_from_success import missing_playbook_sections

    assert missing_playbook_sections(_COMPLET) == []


def test_un_document_sans_anti_declencheur_est_signale():
    """Une procédure qui ne dit pas quand s'abstenir se déclenche partout."""
    from app.services.learning.skill_from_success import missing_playbook_sections

    ampute = _COMPLET.replace("## Ne pas appliquer quand", "## Remarque")
    assert "Ne pas appliquer quand" in missing_playbook_sections(ampute)


def test_un_document_sans_pieges_est_signale():
    """Le piège EST la leçon du tour : sans lui, on a écrit « fais le travail »."""
    from app.services.learning.skill_from_success import missing_playbook_sections

    ampute = _COMPLET.replace("## Pièges", "## Divers")
    assert "Pièges" in missing_playbook_sections(ampute)


def test_un_document_sans_critere_de_fin_est_signale():
    from app.services.learning.skill_from_success import missing_playbook_sections

    ampute = _COMPLET.replace("## Terminé quand", "## Fin")
    assert "Terminé quand" in missing_playbook_sections(ampute)


def test_les_accents_et_la_casse_ne_recalent_pas_un_document_valide():
    """Un modèle qui écrit « ## PROCEDURE » a quand même écrit la rubrique."""
    from app.services.learning.skill_from_success import missing_playbook_sections

    variante = (
        _COMPLET.replace("## Procédure", "### PROCEDURE")
        .replace("## Pièges", "## PIEGES rencontrés")
        .replace("## Terminé quand", "## Termine quand")
    )
    assert missing_playbook_sections(variante) == []


def test_les_titres_reellement_lus_sont_restituables():
    """Dire « il manque Pièges » sans montrer ce qu'on a lu ne permet pas de
    distinguer une dérive de formulation d'un document amputé."""
    from app.services.learning.skill_from_success import playbook_section_titles

    titres = playbook_section_titles(_COMPLET.replace("## Pièges", "## Écueils"))
    assert "Écueils" in titres
    assert "Pièges" not in titres


# ─────────────────────────────────────────────────────────────────────────
# La proposition — jamais active d'office
# ─────────────────────────────────────────────────────────────────────────


def _tour_difficile() -> list:
    return [
        HumanMessage(content="convertis ce pdf en docx en gardant les marges"),
        AIMessage(content="", tool_calls=[{"name": "pdf_to_docx", "args": {}, "id": "1"}]),
        ToolMessage(content="Document créé, marges non conservées", tool_call_id="1"),
        AIMessage(content="Voilà."),
        HumanMessage(content="[Vérification — …]\n- les marges ne sont pas conservées"),
        AIMessage(
            content="",
            tool_calls=[{"name": "pdf_to_docx", "args": {"keep_geometry": True}, "id": "2"}],
        ),
        ToolMessage(content="Document créé, marges conservées", tool_call_id="2"),
        AIMessage(content="Voilà, marges conservées."),
    ]


@pytest.fixture
def modele(monkeypatch):
    def _install(reponse: str):
        from app.services.learning import skill_from_success as sfs

        monkeypatch.setattr(
            "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
        )

        async def _faux(*_a, **_k):
            return AIMessage(content=reponse)

        monkeypatch.setattr(sfs, "ainvoke_with_deadline", _faux)

    return _install


@pytest.mark.asyncio
async def test_une_tache_difficile_reussie_propose_un_document(modele):
    from app.services.learning.skill_from_success import draft_skill_from_success

    modele(_COMPLET)
    skill = await draft_skill_from_success("user-doc", _tour_difficile())

    assert skill is not None
    assert skill.content_format == SkillContentFormat.MARKDOWN_PLAYBOOK, (
        "la voie document produit du Markdown, jamais du code"
    )
    assert "Pièges" in skill.content


@pytest.mark.asyncio
async def test_le_document_propose_n_est_pas_actif_tant_qu_il_n_est_pas_valide(modele):
    """Le contrat du produit : l'humain tranche ce qui relève du jugement."""
    from app.services.learning.skill_from_success import draft_skill_from_success

    modele(_COMPLET)
    skill = await draft_skill_from_success("user-doc", _tour_difficile())
    assert skill.status == SkillStatus.CANDIDATE
    assert skill.status != SkillStatus.ACTIVE


@pytest.mark.asyncio
async def test_un_document_ampute_est_propose_mais_dit_ce_qui_manque(modele):
    """L'appel a DÉJÀ été payé quand on lit le document.

    Le refuser sur un titre mal formulé brûlait un appel par tour sans jamais
    produire de candidat, et aucune surface ne le montrait. La porte qui compte
    est ailleurs : le document sort en CANDIDATE, un humain le lit — on lui dit
    donc ce qui manque là où il décide.
    """
    from app.services.learning.skill_from_success import draft_skill_from_success

    modele(_COMPLET.replace("## Pièges", "## Divers"))
    skill = await draft_skill_from_success("user-doc", _tour_difficile())

    assert skill is not None, "un appel payé ne doit pas disparaître en silence"
    assert skill.status == SkillStatus.CANDIDATE
    assert "Pièges" in (skill.rationale or ""), (
        "la raison doit nommer la rubrique manquante"
    )
    assert "Divers" in (skill.rationale or ""), (
        "et les titres réellement écrits, sinon on ne sait pas si c'est une "
        "dérive de formulation ou un document amputé"
    )


# ─────────────────────────────────────────────────────────────────────────
# Le compteur — il bouge sur la procédure la plus PROCHE du tour
# ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def utilisateur():
    await init_db()
    from app.models.user import User

    async with async_session() as db:
        for uid, nom in (("pu1", "playbook_usage_1"), ("pu2", "playbook_usage_2")):
            existe = (await db.execute(
                select(User).where(User.id == uid)
            )).scalar_one_or_none()
            if existe is None:
                db.add(User(
                    id=uid,
                    username=nom,
                    email=f"{uid}@test.local",
                    hashed_password="x",
                ))
        await db.commit()
        await db.execute(
            delete(LearnedSkill).where(LearnedSkill.user_id.in_(["pu1", "pu2"]))
        )
        await db.commit()
    yield "pu1"


async def _poser(
    user_id: str,
    nom: str,
    corps: str,
    *,
    status: str = SkillStatus.ACTIVE,
    content_format: str = SkillContentFormat.MARKDOWN_PLAYBOOK,
    cree_le: datetime | None = None,
    promu_le: datetime | None = None,
) -> str:
    async with async_session() as db:
        s = LearnedSkill(
            user_id=user_id,
            name=nom,
            description="procédure de test",
            content=corps,
            frontmatter_json="{}",
            status=status,
            source=SkillSource.AUTO_GENERATED,
            content_format=content_format,
            iteration_count=1,
            from_failure_case_ids="[]",
            use_count=0,
            promoted_at=promu_le,
        )
        if cree_le is not None:
            s.created_at = cree_le
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def _bloc_du_prompt(user_id: str) -> str:
    """Le bloc tel que le prompt l'écrit — même sélection, même formateur.

    C'est le chemin exact de ``memory_snapshot`` : ce que le modèle a eu sous
    les yeux, et donc la seule preuve dont dispose le compteur.
    """
    from app.services.learning.active_skills import (
        format_active_skills_block,
        get_active_skills_for_user,
    )

    return format_active_skills_block(await get_active_skills_for_user(user_id))


async def _compteur(skill_id: str) -> tuple[int, object]:
    async with async_session() as db:
        row = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        return int(row.use_count or 0), row.last_used_at


@pytest.mark.asyncio
async def test_le_compteur_bouge_quand_la_procedure_sert(utilisateur):
    from app.services.learning.playbook_usage import record_playbooks_served

    sid = await _poser(
        utilisateur, "marges", "## Procédure\n1. Appeler `pdf_to_docx`.",
    )
    servis = await record_playbooks_served(
        utilisateur, ["pdf_to_docx"], await _bloc_du_prompt(utilisateur),
    )

    assert servis == [sid]
    compte, vu_le = await _compteur(sid)
    assert compte == 1
    assert vu_le is not None


@pytest.mark.asyncio
async def test_un_seul_appel_ne_credite_pas_les_trois_procedures_qui_le_citent(
    utilisateur,
):
    """LE défaut mesuré : la sélection est re-rankée sur la question, donc les
    procédures co-livrées sont précisément celles qui partagent leur outillage.
    Trois procédures citant la recherche web ne peuvent pas avoir toutes servi
    à un seul appel de recherche — et rien ne dit LAQUELLE a servi."""
    from app.services.learning.playbook_usage import record_playbooks_served

    ids = [
        await _poser(utilisateur, nom, f"## Procédure\n1. Appeler `web_search`.\n{nom}")
        for nom in ("veille", "prospection", "sourcing")
    ]
    servis = await record_playbooks_served(
        utilisateur, ["web_search"], await _bloc_du_prompt(utilisateur),
    )

    assert servis == []
    for sid in ids:
        assert (await _compteur(sid))[0] == 0


@pytest.mark.asyncio
async def test_la_procedure_la_plus_proche_du_tour_est_celle_qui_compte(utilisateur):
    """Deux procédures livrées, une seule explique le tour entier."""
    from app.services.learning.playbook_usage import record_playbooks_served

    proche = await _poser(
        utilisateur, "conversion-complete",
        "## Procédure\n1. `pdf_to_docx`\n2. `docx_repair`",
    )
    lointaine = await _poser(
        utilisateur, "conversion-simple", "## Procédure\n1. `pdf_to_docx`",
    )
    servis = await record_playbooks_served(
        utilisateur, ["pdf_to_docx", "docx_repair"],
        await _bloc_du_prompt(utilisateur),
    )

    assert servis == [proche]
    assert (await _compteur(lointaine))[0] == 0


@pytest.mark.asyncio
async def test_un_outil_nomme_pour_dire_de_s_en_abstenir_ne_compte_pas(utilisateur):
    """« Ne pas appliquer quand » est une contre-indication, pas un usage."""
    from app.services.learning.playbook_usage import record_playbooks_served

    sid = await _poser(
        utilisateur, "ocr-avant-tout",
        "## Quand l'appliquer\nUn PDF scanné.\n\n"
        "## Ne pas appliquer quand\nLe PDF a une couche texte : `pdf_to_docx` suffit.\n\n"
        "## Procédure\n1. Appeler `ocr_extract`.",
    )
    servis = await record_playbooks_served(
        utilisateur, ["pdf_to_docx"], await _bloc_du_prompt(utilisateur),
    )

    assert servis == []
    assert (await _compteur(sid))[0] == 0


@pytest.mark.asyncio
async def test_une_procedure_chargee_mais_jamais_suivie_reste_a_zero(utilisateur):
    """Livrer n'est pas consommer. Si le compteur montait à l'injection, les 20
    playbooks du prompt marqueraient +1 par conversation et le chiffre ne dirait
    plus rien."""
    from app.services.learning.playbook_usage import record_playbooks_served

    sid = await _poser(
        utilisateur, "boite-mail", "## Procédure\n1. Appeler `gmail_send`.",
    )
    bloc = await _bloc_du_prompt(utilisateur)
    assert await record_playbooks_served(utilisateur, ["pdf_to_docx"], bloc) == []
    assert (await _compteur(sid))[0] == 0


@pytest.mark.asyncio
async def test_un_tour_sans_outil_ne_compte_rien(utilisateur):
    from app.services.learning.playbook_usage import record_playbooks_served

    sid = await _poser(utilisateur, "rien", "## Procédure\n1. `pdf_to_docx`.")
    bloc = await _bloc_du_prompt(utilisateur)
    assert await record_playbooks_served(utilisateur, [], bloc) == []
    assert (await _compteur(sid))[0] == 0


@pytest.mark.asyncio
async def test_une_candidate_ne_compte_pas(utilisateur):
    """Elle n'est pas dans le prompt : elle n'a rien pu servir. Compter là
    ferait passer pour éprouvée une procédure que personne n'a validée."""
    from app.services.learning.playbook_usage import record_playbooks_served

    sid = await _poser(
        utilisateur, "candidate", "## Procédure\n1. `pdf_to_docx`.",
        status=SkillStatus.CANDIDATE,
    )
    bloc = await _bloc_du_prompt(utilisateur)
    assert await record_playbooks_served(utilisateur, ["pdf_to_docx"], bloc) == []
    assert (await _compteur(sid))[0] == 0


@pytest.mark.asyncio
async def test_un_outil_appris_n_est_pas_compte_par_ce_chemin(utilisateur):
    """``learned_tools_runtime`` bumpe déjà chaque invocation d'un python_tool.
    Le recompter ici doublerait la gate « invocations » de la graduation."""
    from app.services.learning.playbook_usage import record_playbooks_served

    sid = await _poser(
        utilisateur, "outil_appris", "def pdf_to_docx(): ...",
        content_format=SkillContentFormat.PYTHON_TOOL,
    )
    bloc = await _bloc_du_prompt(utilisateur)
    assert await record_playbooks_served(utilisateur, ["pdf_to_docx"], bloc) == []
    assert (await _compteur(sid))[0] == 0


@pytest.mark.asyncio
async def test_les_procedures_d_un_autre_utilisateur_ne_bougent_pas(utilisateur):
    from app.services.learning.playbook_usage import record_playbooks_served

    autre = await _poser("pu2", "chez-lui", "## Procédure\n1. `pdf_to_docx`.")
    await _poser(utilisateur, "chez-elle", "## Procédure\n1. `pdf_to_docx`.")
    # Le bloc de pu2, joué pour pu1 : même un nom de procédure connu ne doit
    # pas franchir la frontière des comptes.
    await record_playbooks_served(
        utilisateur, ["pdf_to_docx"], await _bloc_du_prompt("pu2"),
    )
    assert (await _compteur(autre))[0] == 0


@pytest.mark.asyncio
async def test_un_nom_d_outil_noye_dans_un_mot_plus_long_ne_compte_pas(utilisateur):
    """``web_search`` ne doit pas marquer un playbook qui ne parle que de
    ``web_search_deep`` — sinon toute la famille se compte l'une pour l'autre."""
    from app.services.learning.playbook_usage import record_playbooks_served

    sid = await _poser(
        utilisateur, "recherche", "## Procédure\n1. Appeler `web_search_deep`.",
    )
    bloc = await _bloc_du_prompt(utilisateur)
    assert await record_playbooks_served(utilisateur, ["web_search"], bloc) == []
    assert (await _compteur(sid))[0] == 0


@pytest.mark.asyncio
async def test_une_procedure_seulement_nommee_dans_le_prompt_ne_compte_pas(
    utilisateur,
):
    """Au-delà du budget de contenu, un playbook n'est plus que NOMMÉ.

    ``format_active_skills_block`` détaille les procédures jusqu'à
    ``PLAYBOOK_CONTENT_BUDGET_CHARS``, puis se contente de nommer les
    suivantes. Celles-là n'ont pas livré leur marche à suivre : le modèle
    n'a pas pu la suivre, et la compter reviendrait à compter un titre.
    """
    from app.services.learning.active_skills import PLAYBOOK_CONTENT_BUDGET_CHARS
    from app.services.learning.playbook_usage import record_playbooks_served

    # L'ordre de sélection est ``created_at desc`` à compteur égal : la plus
    # récente est détaillée la première et mange tout le budget.
    detaillee = await _poser(
        utilisateur, "detaillee",
        "## Procédure\n1. Appeler `pdf_to_docx`.\n"
        + "x" * PLAYBOOK_CONTENT_BUDGET_CHARS,
        cree_le=datetime(2026, 9, 2, 12, 0, 0),
    )
    nommee = await _poser(
        utilisateur, "nommee-seulement",
        "## Procédure\n1. Appeler `pdf_to_docx`.",
        cree_le=datetime(2026, 9, 1, 12, 0, 0),
    )

    servis = await record_playbooks_served(
        utilisateur, ["pdf_to_docx"], await _bloc_du_prompt(utilisateur),
    )
    assert servis == [detaillee]
    assert (await _compteur(nommee))[0] == 0


@pytest.mark.asyncio
async def test_une_procedure_fraichement_promue_est_comptee_comme_les_autres(
    utilisateur,
):
    """Le prompt la marque « (nouveau) » — un ornement d'affichage ne doit pas
    la rendre invisible au compteur."""
    from app.services.learning.playbook_usage import record_playbooks_served

    sid = await _poser(
        utilisateur, "toute-neuve", "## Procédure\n1. Appeler `pdf_to_docx`.",
        promu_le=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    servis = await record_playbooks_served(
        utilisateur, ["pdf_to_docx"], await _bloc_du_prompt(utilisateur),
    )
    assert servis == [sid]


# ─────────────────────────────────────────────────────────────────────────
# La boucle cassée : on lit ce qui a été injecté, on ne le rejoue pas
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_une_procedure_absente_du_bloc_injecte_ne_compte_pas(utilisateur):
    """Le compteur ne reconstruit plus la sélection — et c'est le cœur du lot.

    Cette sélection est triée par ``use_count``, que ce compteur écrit : une
    procédure sous la coupe de budget n'était jamais livrée en entier, donc
    jamais comptée, donc jamais remontée. Le zéro avait l'air mérité ; il était
    fabriqué. Ici la procédure ``absente`` est ACTIVE et cite l'outil appelé —
    seule son absence du bloc réellement injecté la disqualifie.
    """
    from app.services.learning.active_skills import format_active_skills_block
    from app.services.learning.playbook_usage import record_playbooks_served

    absente = await _poser(
        utilisateur, "absente", "## Procédure\n1. Appeler `pdf_to_docx`.",
    )
    livree = await _poser(
        utilisateur, "livree", "## Procédure\n1. Appeler `pdf_to_docx`.",
    )
    async with async_session() as db:
        seule = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == livree)
        )).scalar_one()
        bloc = format_active_skills_block([seule])

    assert await record_playbooks_served(utilisateur, ["pdf_to_docx"], bloc) == [livree]
    assert (await _compteur(absente))[0] == 0


@pytest.mark.asyncio
async def test_sans_bloc_injecte_on_ne_compte_rien(utilisateur):
    """Pas de trace de ce que le modèle a eu sous les yeux = pas de preuve.

    On préfère un chiffre qui sous-compte à un chiffre reconstruit : c'est lui
    qui décide de ce que le curateur archive.
    """
    from app.services.learning.playbook_usage import record_playbooks_served

    sid = await _poser(utilisateur, "orpheline", "## Procédure\n1. `pdf_to_docx`.")
    assert await record_playbooks_served(utilisateur, ["pdf_to_docx"], "") == []
    assert (await _compteur(sid))[0] == 0


@pytest.mark.asyncio
async def test_le_comptage_ne_casse_jamais_le_tour(utilisateur, monkeypatch):
    """Un compteur est du confort : une panne DB ne remonte pas dans le tour.

    La procédure posée n'est pas décorative : sans elle il n'y aurait rien à
    compter, la fonction sortirait AVANT d'écrire, et le test passerait à vide
    sans jamais toucher la panne qu'il prétend éprouver.
    """
    from app.services.learning import playbook_usage

    await _poser(utilisateur, "a-compter", "## Procédure\n1. `pdf_to_docx`.")
    bloc = await _bloc_du_prompt(utilisateur)

    def _boum(*_a, **_k):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(playbook_usage, "async_session", _boum)
    assert await playbook_usage.record_playbooks_served(
        utilisateur, ["pdf_to_docx"], bloc,
    ) == []


# ─────────────────────────────────────────────────────────────────────────
# Le câblage : le comptage part APRÈS le tour, jamais dedans
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def snapshot_fige():
    """Pose (et retire) le snapshot mémoire figé d'une conversation."""
    from app.services import frozen_memory

    poses: list[str] = []

    def _poser_snapshot(conversation_id: str, texte: str) -> str:
        frozen_memory.preseed(conversation_id, texte)
        poses.append(conversation_id)
        return conversation_id

    yield _poser_snapshot
    for cid in poses:
        frozen_memory.discard(cid)


def test_le_comptage_est_programme_en_tache_de_fond(monkeypatch, snapshot_fige):
    """Leçon de #286 : ce qui n'appartient pas à la réponse ne tourne pas dans
    la boucle du tour."""
    from app.services.learning.active_skills import format_active_skills_block
    from app.services.learning.playbook_usage import schedule_playbook_usage

    class _Playbook:
        id = "s1"
        name = "marges"
        description = "garder les marges"
        content = "## Procédure\n1. `pdf_to_docx`"
        content_format = SkillContentFormat.MARKDOWN_PLAYBOOK
        promoted_at = None

    conv = snapshot_fige("conv-comptage", format_active_skills_block([_Playbook()]))

    planifie: dict = {}
    monkeypatch.setattr(
        "app.services.background_tasks.spawn",
        lambda coro, **kw: (coro.close(), planifie.update(kw))[0],
    )
    assert schedule_playbook_usage("user-doc", _tour_difficile(), conv) is True
    assert planifie.get("label") == "playbooks_servis"


def test_sans_snapshot_de_la_conversation_rien_n_est_programme(monkeypatch):
    """Rien ne prouve ce qui a été injecté : on ne lance même pas le comptage,
    plutôt que de rejouer une sélection que ce compteur trie."""
    from app.services.learning.playbook_usage import schedule_playbook_usage

    appels = {"n": 0}
    monkeypatch.setattr(
        "app.services.background_tasks.spawn",
        lambda coro, **kw: (coro.close(), appels.update(n=appels["n"] + 1))[0],
    )
    assert schedule_playbook_usage(
        "user-doc", _tour_difficile(), "conversation-sans-snapshot",
    ) is False
    assert appels["n"] == 0


def test_un_tour_sans_aucun_outil_ne_programme_rien(monkeypatch):
    from app.services.learning.playbook_usage import schedule_playbook_usage

    appels = {"n": 0}
    monkeypatch.setattr(
        "app.services.background_tasks.spawn",
        lambda coro, **kw: (coro.close(), appels.update(n=appels["n"] + 1))[0],
    )
    assert schedule_playbook_usage(
        "user-doc", [AIMessage(content="bonjour")], "conv-1",
    ) is False
    assert appels["n"] == 0


@pytest.mark.asyncio
async def test_un_tour_arrete_sur_des_ecarts_ne_propose_aucun_document(monkeypatch):
    """Une tâche ÉCHOUÉE n'enseigne rien de fiable.

    On ignore ce qui aurait marché : écrire une procédure depuis un échec,
    c'est graver une supposition, et c'est ce qu'on retrouve derrière les 43
    compétences périmées. Ce test tient la porte fermée du côté du nœud, pas
    seulement du côté du prédicat.
    """
    from app.agent import conformity as conf

    propose = {"n": 0}
    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
    )

    async def _verdict(*_a, **_k):
        # La forme FRANÇAISE, espace comprise : c'est celle qui était
        # silencieusement classée conforme avant le 02/09.
        return AIMessage(content="ÉCARTS :\n- les marges ne sont pas conservées")

    monkeypatch.setattr(conf, "ainvoke_with_deadline", _verdict)
    monkeypatch.setattr(
        conf, "_maybe_learn_from_success",
        lambda *a, **k: propose.update(n=propose["n"] + 1) or True,
    )

    out = await conf.conformity_node({
        "messages": _tour_difficile(),
        "user_id": "user-doc",
        "conformity_retries": 0,
        "conformity_gap_count": 0,
    })
    assert out.get("messages"), "le tour aurait dû être relancé sur ses écarts"
    assert propose["n"] == 0


@pytest.mark.asyncio
async def test_un_tour_conforme_declenche_le_comptage_sur_sa_conversation(monkeypatch):
    """Sans ce câblage, la fonction existerait sans jamais tourner — le défaut
    exact que ce lot corrige. Et sans l'identifiant de conversation, le
    comptage n'aurait aucun bloc injecté à lire."""
    from app.agent import conformity as conf

    vu: dict = {}
    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
    )

    async def _verdict(*_a, **_k):
        return AIMessage(content="CONFORME")

    monkeypatch.setattr(conf, "ainvoke_with_deadline", _verdict)
    monkeypatch.setattr(conf, "_maybe_learn_from_success", lambda *a, **k: False)
    monkeypatch.setattr(
        "app.services.learning.playbook_usage.schedule_playbook_usage",
        lambda uid, msgs, conv: vu.update(uid=uid, conv=conv) or True,
    )

    await conf.conformity_node({
        "messages": _tour_difficile(),
        "user_id": "user-doc",
        "conversation_id": "conv-42",
        "conformity_retries": 0,
        "conformity_gap_count": 0,
    })
    assert vu == {"uid": "user-doc", "conv": "conv-42"}
