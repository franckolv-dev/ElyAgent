# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_le_prompt_systeme_ne_part_pas_en_clair.py
# @brief      Ce qui part vers un modele NON LOCAL est anonymise, quelle que
#             soit la voie du prompt systeme (complete ou compacte).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""La frontiere d'envoi du prompt systeme (02/09/2026).

LE CONSTAT
----------
Le correctif de souverainete du 02/09 ne fermait que la voie COMPLETE : la
mission pose d'avance un instantane memoire deja anonymise, et `agent_node`
le lit au cache au lieu de le reconstruire.

La voie COMPACTE ne passait par aucun filtre. Pire, son aiguillage se decidait
sur le MAUVAIS modele : `is_local_openai_llm(get_llm())` regarde le LLM PAR
DEFAUT, alors que l'inference passe par `get_llm_for_tier(COMPLEX)`. Chez
Franck, le defaut est une tete LOCALE (LM Studio) et le tier COMPLEX est
CLOUD : la voie compacte etait donc choisie, et elle reconstruisait profil /
souvenirs / contraintes EN CLAIR avant de les envoyer chez zhipu.

CE QUE CES TESTS EPINGLENT
--------------------------
- la voie est choisie sur le modele REELLEMENT retenu, pas sur le defaut ;
- le prompt systeme envoye a un modele NON LOCAL est anonymise, sur les deux
  voies, et sur le chat ordinaire autant que sur les missions ;
- un modele LOCAL garde le clair : rien ne quitte la machine, l'anonymisation
  n'y couterait que de la qualite ;
- les placeholders sont ceux du filtre de la mission, pas d'un second vault
  qui les rendrait irresolubles a la sortie.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage

_BUT = "Prepare le dossier de prospection et note l'avancement."
_EMAIL = "jean.dupont@exemple.fr"
_TEL = "06 12 34 56 78"


# ── Les doubles ──────────────────────────────────────────────────────────────


def _texte_des_messages(messages) -> str:
    morceaux = []
    for m in messages or ():
        c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        morceaux.append(c if isinstance(c, str) else str(c))
    return "\n".join(morceaux)


class _ModeleCloud:
    """Le modele du tier COMPLEX : cloud, et il garde ce qu'on lui envoie."""

    model_name = "glm-4.6"

    def __init__(self, tours=None):
        self._tours = list(tours or [])
        self.prompts: list[str] = []

    def bind_tools(self, tools, **_kw):
        return self

    def with_config(self, *_a, **_kw):
        return self

    async def ainvoke(self, messages, config=None, **_kw):
        self.prompts.append(_texte_des_messages(messages))
        if "Tu vérifies qu'un travail répond à la demande" in self.prompts[-1]:
            return AIMessage(content="CONFORME")
        if self._tours:
            return self._tours.pop(0)
        return AIMessage(content="Rien a faire de plus.")


class ChatOpenAI(_ModeleCloud):  # noqa: N801 — le detecteur lit le NOM DE CLASSE
    """Le meme modele, mais servi par la machine (LM Studio).

    `is_local_openai_llm` exige trois choses, et le double les porte toutes :
    le nom de classe `ChatOpenAI`, un `base_url` local, et un nom de modele
    sans marqueur cloud (« google/ » en est un — d'ou `gemma-3-27b-it` nu)."""

    model_name = "gemma-3-27b-it"
    openai_api_base = "http://localhost:1234/v1"


def _branche(monkeypatch, modele_du_tier):
    """Le decor : c'est le modele du TIER qui decide, et lui seul.

    ⚠️ 02/09/2026 — ce helper posait aussi `nodes.get_llm`. C'etait le decor
    d'AVANT le correctif : l'aiguillage se decidait alors sur le LLM par
    defaut. Depuis qu'il se decide sur le modele reellement retenu, ce
    monkeypatch ne mordait plus sur rien — un decor inerte qui laissait croire
    que le test couvrait la configuration « defaut local + tier cloud ». Le
    symbole `get_llm` n'est meme plus importe par `nodes`.
    """
    import app.services.llm_provider as lp

    monkeypatch.setattr(lp, "get_llm_for_tier", lambda *a, **k: modele_du_tier)
    monkeypatch.setattr(lp, "get_fallback_llms", lambda *a, **k: [], raising=False)


# ── Le decor ─────────────────────────────────────────────────────────────────


async def _semer_le_profil(uid: str) -> None:
    """Deux faits du NOYAU du profil : ils sont toujours injectes."""
    from app.database import async_session
    from app.models.user_memory import UserProfile

    async with async_session() as db:
        db.add(UserProfile(user_id=uid, key="primary_email", value=_EMAIL,
                           confidence=1.0, source_count=9))
        db.add(UserProfile(user_id=uid, key="strict_rules",
                           value=f"Toujours me joindre au {_TEL}.",
                           confidence=1.0, source_count=9))
        await db.commit()


@pytest_asyncio.fixture
async def mission_avec_pii(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.database import async_session, init_db
    from app.models.user import User
    from app.services import mission_service
    from tests._user_cleanup import purge_user

    await init_db()
    uid = f"test_fuite_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    await _semer_le_profil(uid)
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal=_BUT, budget_iterations=30,
    )
    await mission_service.start_mission(m.id)
    yield uid, m.id
    await purge_user(uid)


@pytest_asyncio.fixture
async def utilisateur_avec_pii():
    from app.database import async_session, init_db
    from app.models.user import User
    from tests._user_cleanup import purge_user

    await init_db()
    uid = f"test_chat_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    await _semer_le_profil(uid)
    yield uid
    await purge_user(uid)


# ── Le prompt du profil arrive-t-il seulement jusqu'au modele ? ──────────────


@pytest.mark.asyncio
async def test_le_profil_atteint_bien_le_modele_quand_il_est_local(
    utilisateur_avec_pii, monkeypatch,
):
    """Garde-fou du banc : sans ce test, un prompt vide ferait passer les
    autres pour de bonnes raisons. Une tete LOCALE recoit le clair."""
    uid = utilisateur_avec_pii
    modele = ChatOpenAI([AIMessage(content="Bonjour.")])
    _branche(monkeypatch, modele)

    from app.agent.nodes import create_agent_node

    await create_agent_node()({
        "messages": [HumanMessage(content="Quelle est mon adresse ?")],
        "user_id": uid,
        "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
        "toolset_profile": "default",
        "iteration_count": 0,
    })

    vus = "\n".join(modele.prompts)
    assert _EMAIL in vus, (
        "le profil n'atteint pas le modele : le banc ne prouverait rien"
    )


# ── La voie compacte ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_la_voie_est_choisie_sur_le_modele_retenu_pas_sur_le_defaut(
    utilisateur_avec_pii, monkeypatch,
):
    """Defaut LOCAL + tier COMPLEX cloud : le prompt compact partait au cloud.

    Le prompt compact fait ~300 caracteres et ne porte AUCUNE des regles de
    conduite d'Ely. L'envoyer a un modele frontier, c'est le faire tourner
    sans son socle."""
    uid = utilisateur_avec_pii
    modele = _ModeleCloud([AIMessage(content="Bonjour.")])
    _branche(monkeypatch, modele)

    from app.agent.nodes import create_agent_node

    await create_agent_node()({
        "messages": [HumanMessage(content="Bonjour, comment vas-tu ?")],
        "user_id": uid,
        "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
        "toolset_profile": "default",
        "iteration_count": 0,
    })

    from app.agent.prompts import _SYSTEM_PROMPT_BASE

    repere = _SYSTEM_PROMPT_BASE.strip().splitlines()[0].strip()
    assert repere and repere in "\n".join(modele.prompts), (
        "le modele cloud a recu le prompt COMPACT : l'aiguillage s'est fait "
        "sur le LLM par defaut, pas sur celui qui repond"
    )


@pytest.mark.asyncio
async def test_le_prompt_systeme_du_chat_est_anonymise_pour_un_modele_cloud(
    utilisateur_avec_pii, monkeypatch,
):
    """La regle de souverainete d'Ely : rien de nominatif ne part vers un
    modele CLOUD. Le prompt systeme est du texte comme un autre."""
    uid = utilisateur_avec_pii
    modele = _ModeleCloud([AIMessage(content="Bonjour.")])
    _branche(monkeypatch, modele)

    from app.agent.nodes import create_agent_node

    await create_agent_node()({
        "messages": [HumanMessage(content="Quelle est mon adresse ?")],
        "user_id": uid,
        "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
        "toolset_profile": "default",
        "iteration_count": 0,
    })

    vus = "\n".join(modele.prompts)
    assert _EMAIL not in vus, "l'adresse est partie en clair chez un fournisseur cloud"
    assert _TEL not in vus, "le telephone est parti en clair chez un fournisseur cloud"
    assert "[EMAIL_" in vus, "le fait doit rester la, sous placeholder"


@pytest.mark.asyncio
async def test_une_mission_sur_la_voie_compacte_ne_fuit_pas(
    mission_avec_pii, monkeypatch,
):
    """Le decor exact du defaut : le defaut est local, donc `_use_compact`
    valait True ; l'instantane pose d'avance etait ignore et les pieces
    etaient relues EN CLAIR par `refetch_compact_pieces`."""
    uid, mid = mission_avec_pii
    modele = _ModeleCloud([AIMessage(content="Dossier prepare.")])
    _branche(monkeypatch, modele)

    from app.agent.missions.chat_loop import run_mission_chat_passage

    await run_mission_chat_passage(mid, uid, _BUT)

    vus = "\n".join(modele.prompts)
    assert _EMAIL not in vus, (
        "la voie compacte a envoye le profil en clair au tier COMPLEX cloud"
    )
    assert _TEL not in vus


@pytest.mark.asyncio
async def test_les_placeholders_de_la_mission_sont_ceux_de_son_filtre(
    mission_avec_pii, monkeypatch,
):
    """Un second vault rendrait les placeholders irresolubles a la sortie —
    ou pire, les resoudrait vers la MAUVAISE valeur."""
    uid, mid = mission_avec_pii
    modele = _ModeleCloud([AIMessage(content="Dossier prepare.")])
    _branche(monkeypatch, modele)

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.agent.missions.pii import mission_filter

    await run_mission_chat_passage(mid, uid, _BUT)

    filtre = mission_filter(mid)
    vus = "\n".join(modele.prompts)
    import re

    poses = set(re.findall(r"\[(?:EMAIL|PHONE|CARD|IBAN|TOKEN)_\d+\]", vus))
    assert poses, "aucun placeholder pose : le prompt n'a pas ete filtre"
    inconnus = [p for p in poses if filtre.deanonymize(p) == p]
    assert not inconnus, (
        f"placeholders etrangers au filtre de la mission : {inconnus} — ils "
        "sortiront tels quels dans le resume livre a l'utilisateur"
    )


@pytest.mark.asyncio
async def test_un_modele_local_garde_le_clair(utilisateur_avec_pii, monkeypatch):
    """Anonymiser pour un modele qui tourne sur la machine ne protege rien et
    coute de la qualite : la frontiere est le RESEAU, pas le prompt."""
    uid = utilisateur_avec_pii
    modele = ChatOpenAI([AIMessage(content="Bonjour.")])
    _branche(monkeypatch, modele)

    from app.agent.nodes import create_agent_node

    await create_agent_node()({
        "messages": [HumanMessage(content="Quelle est mon adresse ?")],
        "user_id": uid,
        "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
        "toolset_profile": "default",
        "iteration_count": 0,
    })

    vus = "\n".join(modele.prompts)
    assert _EMAIL in vus, "un modele local ne doit pas payer le prix des placeholders"
    assert "[EMAIL_" not in vus
