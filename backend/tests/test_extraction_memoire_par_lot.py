# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_extraction_memoire_par_lot.py
# @brief      L'extraction de faits coûtait un appel de modèle par TOUR.
#             Elle en coûte désormais un par utilisateur et par JOUR.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Le travail de fond pesait quatre fois la demande de l'utilisateur.

Mesure de production, 30 jours glissants (02/09/2026)
----------------------------------------------------

    extraction mémoire ....... 336 appels de modèle
    consolidation ............  45 appels
    demandes web réelles ..... 208

Pour 42 454 lignes de ``user_memory_logs`` et 573 lignes de profil, dont
seule une poignée de clés atteint réellement un prompt. Le premier poste
était l'extraction : ``maybe_spawn_fact_extraction`` partait à la fin de
CHAQUE tour et lançait un appel de modèle sur une conversation qui n'avait
bougé que d'un échange depuis le tour précédent.

Le correctif
------------
La fin d'un tour ne déclenche plus rien. Une passe quotidienne (02:45, juste
avant la consolidation de 03:00) relit ce qui est nouveau depuis la dernière
extraction et n'émet **qu'un seul appel par utilisateur**.

La borne « depuis quand » n'a demandé aucune table ni colonne nouvelle :
c'est l'horodatage ``observed_at`` le plus récent des ``UserMemoryLog`` de
l'utilisateur, comparé à ``Message.created_at``. Seul ``extract_and_store_
facts`` écrit dans cette table, donc la borne ne peut pas être avancée par
un autre chemin.

Coût pour un utilisateur qui fait 20 tours dans une journée :
20 appels avant, 1 après.

Run with:  cd backend && python -m pytest tests/test_extraction_memoire_par_lot.py -v
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage

from app.models.conversation import Conversation, Message
from app.models.user import User
from app.models.user_memory import UserMemoryLog, UserProfile


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


@pytest.fixture(autouse=True)
def _pas_d_extraction_par_tour(monkeypatch):
    """Éteint ``MEMORY_EXTRACTION_PER_TURN`` hérité de l'environnement.

    Symétrique de la fixture du fichier voisin
    (``test_memory_extraction_once_per_turn.py``), qui l'allume parce que
    c'est SON sujet. Ici c'est l'inverse : ce fichier décrit le
    fonctionnement PAR DÉFAUT, sans le drapeau.

    ⚠️ Mesuré le 02/09/2026 : sans cette fixture, avec le drapeau posé dans
    l'environnement — exactement ce que docker-compose pousse depuis le
    ``.env`` — le fichier ne devenait pas rouge, il PENDAIT (toujours vivant
    à quatre minutes) : les extractions par tour partaient pour de vrai en
    tâche de fond. Le test qui a besoin du drapeau le pose lui-même, dans son
    corps — donc après cette fixture.
    """
    monkeypatch.delenv("MEMORY_EXTRACTION_PER_TURN", raising=False)


class _Modele:
    """Le modèle de fond, remplacé : on compte les appels et on lit le prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.reponses: list[str] = []

    def __len__(self) -> int:
        return len(self.prompts)

    def __getitem__(self, i: int) -> str:
        return self.prompts[i]

    def __eq__(self, other) -> bool:
        return self.prompts == other


@pytest.fixture
def appels(monkeypatch) -> _Modele:
    """Intercepte les appels de modèle des corvées de fond.

    On remplace le point d'entrée partagé (``ainvoke_background_with_usage``)
    plutôt que le service : ce qu'on veut compter, ce sont les appels au
    modèle, quel que soit le chemin qui y mène.
    """
    modele = _Modele()

    async def _fake(_llm, messages, **_kw):
        modele.prompts.append(messages[0]["content"])
        if modele.reponses:
            return modele.reponses.pop(0), None
        return json.dumps({"facts": [
            {"fact": "L'utilisateur travaille sur un projet nommé Ely", "type": "context"},
        ]}), None

    monkeypatch.setattr(
        "app.services.background_llm.ainvoke_background_with_usage", _fake
    )
    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
    )
    return modele


async def _drain() -> None:
    """Laisse les tâches de fond déjà planifiées s'exécuter."""
    for _ in range(5):
        await asyncio.sleep(0)


def _naive_utc(delta_minutes: int = 0) -> datetime:
    """Les colonnes ``DateTime`` de ce dépôt sont naïves (UTC implicite)."""
    return (
        datetime.now(timezone.utc) + timedelta(minutes=delta_minutes)
    ).replace(tzinfo=None)


async def _user(nb_conversations: int = 0, messages_par_conv: int = 0,
                contenu: str = "je bosse sur Ely") -> str:
    from app.database import async_session
    async with async_session() as db:
        u = User(
            id=str(uuid.uuid4()), username=f"u_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
        )
        db.add(u)
        await db.flush()
        for c in range(nb_conversations):
            conv = Conversation(id=str(uuid.uuid4()), user_id=u.id, title=f"conv {c}")
            db.add(conv)
            await db.flush()
            for m in range(messages_par_conv):
                db.add(Message(
                    id=str(uuid.uuid4()),
                    conversation_id=conv.id,
                    role="user" if m % 2 == 0 else "assistant",
                    content=f"(conv {c}, message {m}) {contenu}",
                    created_at=_naive_utc(-60 + c * 10 + m),
                ))
        await db.commit()
        return u.id


async def _deux_fils_entrelaces() -> str:
    """Deux conversations menées EN PARALLÈLE : leurs messages alternent.

    C'est le cas réel que le tri par date seule mélange — A, B, A, B, … —
    et que le lot doit regrouper avant de le donner au modèle.
    """
    from app.database import async_session
    async with async_session() as db:
        u = User(
            id=str(uuid.uuid4()), username=f"u_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
        )
        db.add(u)
        await db.flush()
        fils = []
        for tag in ("fil-A", "fil-B"):
            conv = Conversation(id=str(uuid.uuid4()), user_id=u.id, title=tag)
            db.add(conv)
            await db.flush()
            fils.append((tag, conv.id))
        for tour in range(3):
            for decalage, (tag, conv_id) in enumerate(fils):
                db.add(Message(
                    id=str(uuid.uuid4()), conversation_id=conv_id, role="user",
                    content=f"{tag}: tour {tour}",
                    created_at=_naive_utc(-60 + tour * 2 + decalage),
                ))
        await db.commit()
        return u.id


async def _logs(user_id: str) -> list[UserMemoryLog]:
    from sqlalchemy import select
    from app.database import async_session
    async with async_session() as db:
        rows = await db.execute(
            select(UserMemoryLog).where(UserMemoryLog.user_id == user_id)
        )
        return list(rows.scalars().all())


# ─────────────────────────────────────────────────────────────────────────
# La fin d'un tour ne coûte plus rien
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_la_fin_d_un_tour_ne_declenche_aucun_appel_de_modele(appels):
    """LE test du lot. Le tour se termine normalement (réponse sans
    ``tool_calls``) : avant, c'était exactement le moment où partait un appel
    d'extraction."""
    from app.services.memory_service import maybe_spawn_fact_extraction

    lance = maybe_spawn_fact_extraction(
        "user-1",
        [HumanMessage(content="je bosse sur Ely")],
        AIMessage(content="Noté."),
    )
    await _drain()

    assert lance is False
    assert appels == [], "un tour de chat paie encore un appel de modèle"


@pytest.mark.asyncio
async def test_vingt_tours_ne_coutent_toujours_rien(appels):
    """La journée type mesurée en production : 20 tours, 20 appels avant."""
    from app.services.memory_service import maybe_spawn_fact_extraction

    for _ in range(20):
        maybe_spawn_fact_extraction(
            "user-1", [HumanMessage(content="?")], AIMessage(content="ok")
        )
    await _drain()

    assert appels == []


@pytest.mark.asyncio
async def test_le_drapeau_de_sortie_retablit_l_extraction_par_tour(appels, monkeypatch):
    """Porte de sortie documentée : ``MEMORY_EXTRACTION_PER_TURN=true``
    rétablit le comportement historique, au cas où la passe quotidienne
    manquerait quelque chose en production."""
    from app.services.memory_service import maybe_spawn_fact_extraction

    monkeypatch.setenv("MEMORY_EXTRACTION_PER_TURN", "true")

    lance = maybe_spawn_fact_extraction(
        "user-1", [HumanMessage(content="je bosse sur Ely")], AIMessage(content="Noté.")
    )
    await _drain()

    assert lance is True
    assert len(appels) == 1


# ─────────────────────────────────────────────────────────────────────────
# La passe quotidienne
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_la_passe_quotidienne_extrait_les_faits_des_messages_nouveaux(appels):
    from app.services.memory_service import extract_new_facts_for_user

    uid = await _user(nb_conversations=1, messages_par_conv=4)

    n = await extract_new_facts_for_user(uid)

    assert len(appels) == 1
    assert n == 1
    faits = await _logs(uid)
    assert [f.fact for f in faits] == [
        "L'utilisateur travaille sur un projet nommé Ely"
    ]


@pytest.mark.asyncio
async def test_plusieurs_conversations_tiennent_dans_un_seul_appel(appels):
    """Trois conversations dans la journée : un seul appel, qui les voit
    toutes. C'est ce regroupement qui divise la facture."""
    from app.services.memory_service import extract_new_facts_for_user

    uid = await _user(nb_conversations=3, messages_par_conv=4)

    await extract_new_facts_for_user(uid)

    assert len(appels) == 1, f"{len(appels)} appels pour une journée"
    prompt = appels[0]
    for c in range(3):
        assert f"conv {c}" in prompt, f"la conversation {c} n'a pas été lue"


@pytest.mark.asyncio
async def test_une_seconde_passe_ne_re_extrait_rien(appels):
    """Deux passes de suite. La seconde ne trouve rien de nouveau : la borne
    est l'horodatage du dernier fait extrait."""
    from app.services.memory_service import extract_new_facts_for_user

    uid = await _user(nb_conversations=2, messages_par_conv=4)

    await extract_new_facts_for_user(uid)
    assert len(appels) == 1

    n = await extract_new_facts_for_user(uid)

    assert n == 0
    assert len(appels) == 1, "la seconde passe a repayé un appel de modèle"


@pytest.mark.asyncio
async def test_seuls_les_messages_posterieurs_a_la_derniere_extraction_sont_relus(appels):
    """Une conversation reprend après la passe : seul le nouvel échange doit
    entrer dans le lot suivant."""
    from app.database import async_session
    from app.services.memory_service import extract_new_facts_for_user

    uid = await _user(nb_conversations=1, messages_par_conv=2)
    await extract_new_facts_for_user(uid)

    from sqlalchemy import select
    async with async_session() as db:
        conv_id = (await db.execute(
            select(Conversation.id).where(Conversation.user_id == uid)
        )).scalar_one()
        db.add(Message(
            id=str(uuid.uuid4()), conversation_id=conv_id, role="user",
            content="j'habite a Nantes", created_at=_naive_utc(+5),
        ))
        await db.commit()

    await extract_new_facts_for_user(uid)

    assert len(appels) == 2
    assert "Nantes" in appels[1]
    assert "message 0" not in appels[1], "le lot relit du déjà-extrait"


@pytest.mark.asyncio
async def test_un_utilisateur_sans_message_nouveau_ne_coute_aucun_appel(appels):
    from app.services.memory_service import extract_new_facts_for_user

    uid = await _user()  # inscrit, jamais parlé

    assert await extract_new_facts_for_user(uid) == 0
    assert appels == []


@pytest.mark.asyncio
async def test_le_lot_reste_borne_pour_un_utilisateur_bavard(appels):
    """Un utilisateur qui a beaucoup parlé ne doit pas produire un prompt
    géant : mêmes bornes que le chemin par tour (les N derniers messages,
    tronqués), seul N change parce que la fenêtre est une journée."""
    from app.services.memory_service import (
        _DAILY_EXTRACTION_MESSAGE_WINDOW,
        _EXTRACTION_CHAR_CAP,
        extract_new_facts_for_user,
    )

    uid = await _user(nb_conversations=1, messages_par_conv=200, contenu="x" * 3000)

    await extract_new_facts_for_user(uid)

    prompt = appels[0]
    lignes = [
        ligne for ligne in prompt.splitlines()
        if ligne.startswith(("Utilisateur:", "Assistante:"))
    ]
    assert len(lignes) <= _DAILY_EXTRACTION_MESSAGE_WINDOW
    assert max(len(ligne) for ligne in lignes) <= _EXTRACTION_CHAR_CAP + 20
    assert "message 199" in prompt, "le lot doit garder les messages les plus RÉCENTS"


@pytest.mark.asyncio
async def test_la_passe_tous_utilisateurs_traite_celui_qui_a_parle(appels):
    """Le point d'entrée du cron. Sentinelle propre à cet utilisateur : la
    base de test peut contenir d'autres comptes."""
    from app.services.memory_service import extract_facts_for_all_users

    await _user(nb_conversations=1, messages_par_conv=2, contenu="sentinelle-cron-42")

    await extract_facts_for_all_users()

    vus = [p for p in appels.prompts if "sentinelle-cron-42" in p]
    assert len(vus) == 1


# ─────────────────────────────────────────────────────────────────────────
# La PII ne part pas en clair
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_le_prompt_d_extraction_ne_contient_aucune_pii_en_clair(appels):
    """La table ``messages`` stocke les valeurs RÉELLES (``chat.py`` persiste
    ``user_content``, pas ``clean_content``). Le lot les relit : sans filtre,
    l'adresse et le numéro partaient tels quels vers le modèle de fond, qui
    peut être un modèle cloud."""
    from app.services.memory_service import extract_new_facts_for_user

    uid = await _user(
        nb_conversations=1, messages_par_conv=2,
        contenu="ecris a paul.durand@exemple.fr ou appelle le 06 12 34 56 78",
    )

    await extract_new_facts_for_user(uid)

    prompt = appels[0]
    assert "paul.durand@exemple.fr" not in prompt, "l'adresse part en clair"
    assert "06 12 34 56 78" not in prompt, "le numero part en clair"
    assert "[EMAIL_" in prompt and "[PHONE_" in prompt, "rien n'a ete masque"


@pytest.mark.asyncio
async def test_la_pii_d_un_message_assistant_est_masquee_aussi(appels):
    """Les messages assistant sont stockés DÉ-anonymisés (valeurs réelles,
    pour l'affichage) : c'est précisément pour ça que ``chat.py`` les
    ré-anonymise avant de les rendre au modèle. Le lot doit faire pareil."""
    from app.database import async_session
    from app.services.memory_service import extract_new_facts_for_user

    uid = await _user(nb_conversations=1, messages_par_conv=1)
    from sqlalchemy import select
    async with async_session() as db:
        conv_id = (await db.execute(
            select(Conversation.id).where(Conversation.user_id == uid)
        )).scalar_one()
        db.add(Message(
            id=str(uuid.uuid4()), conversation_id=conv_id, role="assistant",
            content="J'ai ecrit a claire.martin@exemple.fr.",
            created_at=_naive_utc(-1),
        ))
        await db.commit()

    await extract_new_facts_for_user(uid)

    assert "claire.martin@exemple.fr" not in appels[0]


@pytest.mark.asyncio
async def test_les_faits_stockes_restent_masques(appels):
    """On ne dé-anonymise PAS au retour : la consolidation de 03:00 renvoie
    le texte des faits au modèle sans aucun filtre, donc un fait remis en
    clair en base rouvrirait la fuite un cran plus loin."""
    from app.services.memory_service import extract_new_facts_for_user

    uid = await _user(
        nb_conversations=1, messages_par_conv=2,
        contenu="mon adresse est paul.durand@exemple.fr",
    )
    appels.reponses.append(json.dumps({"facts": [
        {"fact": "L'adresse de l'utilisateur est [EMAIL_0]", "type": "personal"},
    ]}))

    await extract_new_facts_for_user(uid)

    faits = [f.fact for f in await _logs(uid)]
    assert faits == ["L'adresse de l'utilisateur est [EMAIL_0]"]


# ─────────────────────────────────────────────────────────────────────────
# Les fils ne sont pas entrelacés
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deux_fils_paralleles_ne_sont_pas_entrelaces(appels):
    """Trié par date seule, un lot mélange ligne à ligne deux fils menés en
    parallèle : le modèle conflate alors des faits de sujets différents."""
    from app.services.memory_service import extract_new_facts_for_user

    uid = await _deux_fils_entrelaces()

    await extract_new_facts_for_user(uid)

    lignes = appels[0].splitlines()
    messages = [
        ligne for ligne in lignes
        if ligne.startswith(("Utilisateur:", "Assistante:"))
    ]
    tags = ["fil-A" if "fil-A" in ligne else "fil-B" for ligne in messages]
    blocs = [t for i, t in enumerate(tags) if i == 0 or tags[i - 1] != t]
    assert blocs == ["fil-A", "fil-B"], f"les fils ressortent entrelaces: {tags}"

    fin_a = max(i for i, ligne in enumerate(lignes) if "fil-A" in ligne)
    debut_b = min(i for i, ligne in enumerate(lignes) if "fil-B" in ligne)
    assert any(
        ligne.strip() and not ligne.startswith(("Utilisateur:", "Assistante:"))
        for ligne in lignes[fin_a + 1:debut_b]
    ), "rien ne signale au modele qu'il change de fil"


# ─────────────────────────────────────────────────────────────────────────
# La consolidation ne régresse pas : elle lit toujours UserMemoryLog
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_la_consolidation_fonctionne_sur_les_logs_produits_par_lot(appels):
    from sqlalchemy import select
    from app.database import async_session
    from app.services.memory_service import (
        consolidate_user_memory,
        extract_new_facts_for_user,
    )

    uid = await _user(nb_conversations=1, messages_par_conv=4)
    await extract_new_facts_for_user(uid)

    appels.reponses.append(json.dumps({"profile": [
        {"key": "main_project", "value": "Ely", "confidence": 0.9},
    ]}))
    traites = await consolidate_user_memory(uid)

    assert traites == 1
    async with async_session() as db:
        rows = list((await db.execute(
            select(UserProfile).where(UserProfile.user_id == uid)
        )).scalars().all())
        restants = list((await db.execute(
            select(UserMemoryLog)
            .where(UserMemoryLog.user_id == uid)
            .where(UserMemoryLog.is_consolidated == False)  # noqa: E712
        )).scalars().all())

    assert [(r.key, r.value) for r in rows] == [("main_project", "Ely")]
    assert restants == [], "les logs du lot n'ont pas été marqués consolidés"
