# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_whatsapp_runs_on_the_unified_runtime.py
# @brief      WhatsApp — le dernier canal de conversation resté hors du
#             runtime unique : ni profil d'outils, ni ligne d'usage.
# @license    MIT
# =============================================================================
"""Pins du tour WhatsApp (audit du 02/09/2026).

Ce que l'audit a trouvé, et que ces tests interdisent de refaire :

1. **Le profil d'outils manquait.** `process_whatsapp_message` invoquait le
   graphe avec `messages`, `user_id`, `conversation_id` et les creds Google,
   mais SANS `toolset_profile`. Telegram, Slack, Discord et la voix le
   passent tous depuis la vague 1 (`test_v1_surface_alignment.py`).
   Concrètement, sans ce champ : `routing.should_bind_tools` ne branchait les
   outils, hors tier COMPLEX, que si la demande contenait un mot-clé ; et
   `nodes.agent_node` refiltrait le catalogue par mots-clés à CHAQUE tour au
   lieu de le résoudre une fois pour la conversation, donc le modèle voyait
   un outillage différent d'une question à l'autre et le préfixe du prompt
   bougeait avec. Il n'y a en revanche plus de routeur à court-circuiter
   depuis le temps 2 (`test_the_supervisor_is_gone_since_temps_2`), et le
   bloc `<learned_skills>`, le vecteur d'état et les préférences viennent de
   `builders/memory_snapshot` à partir de l'utilisateur : ceux-là arrivaient
   déjà. `whatsapp_web.py` (pont neonize) délègue à la même fonction : il
   héritait du même trou.

2. **Aucune ligne d'usage.** Là où Telegram et Slack appellent
   `record_turn_usage` depuis la vague 2, WhatsApp n'écrivait rien : ses
   tours étaient invisibles au tableau de bord (coût, latence, architecture).

3. **Le drapeau de souveraineté n'était pas posé.** Le `ContextVar`
   `SOVEREIGNTY_STRICT`, que chat.py et telegram_bot.py positionnent depuis
   `User.sovereignty_strict`, restait à sa valeur par défaut : un
   utilisateur en souveraineté stricte partait quand même sur son
   fournisseur cloud habituel dès qu'il écrivait par WhatsApp.

Ces tests sont des tests de COMPORTEMENT (faux graphe qui capture l'état
reçu), pas des relectures de source : le dépôt en a déjà trop.

Run with:  cd backend && python -m pytest tests/test_whatsapp_runs_on_the_unified_runtime.py -v
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.models.user import User


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


@pytest.fixture(autouse=True)
def _restore_channel_state():
    """Les tables de liaison du canal sont des globales de module : on rend
    au module l'état qu'on lui a emprunté."""
    from app.channels import whatsapp

    linked = dict(whatsapp._linked_users)
    conversations = dict(whatsapp._conversations)
    yield
    whatsapp._linked_users.clear()
    whatsapp._linked_users.update(linked)
    whatsapp._conversations.clear()
    whatsapp._conversations.update(conversations)


class _CaptureGraph:
    """Faux graphe : capture l'état reçu et le contexte de souveraineté."""

    def __init__(self, reply: str = "C'est noté."):
        self._reply = reply
        self.seen: list[dict] = []
        self.sovereignty_seen: list[bool] = []

    async def ainvoke(self, state, config=None):
        from app.services.sovereignty import SOVEREIGNTY_STRICT

        self.seen.append(state)
        self.sovereignty_seen.append(SOVEREIGNTY_STRICT.get())
        return {"messages": [SimpleNamespace(content=self._reply, tool_calls=[])]}


async def _linked_user(*, sovereignty_strict: bool = False) -> tuple[str, str]:
    """Un utilisateur ELY dont le numéro WhatsApp est lié. Rend (user_id, numéro)."""
    from app.channels import whatsapp
    from app.database import async_session

    phone = f"3360{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        user = User(
            id=str(uuid.uuid4()), username=f"u_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
            whatsapp_phone=phone, sovereignty_strict=sovereignty_strict,
        )
        db.add(user)
        await db.commit()
        whatsapp._linked_users[phone] = user.id
        return user.id, phone


def _stub_the_turn(monkeypatch, graph) -> tuple[list[str], list[dict]]:
    """Neutralise tout ce qui sort du process (réseau WhatsApp, mémoire
    vectorielle, écriture d'usage). Rend (messages envoyés, appels d'usage)."""
    import app.agent.graph as graph_mod
    import app.channels.whatsapp as whatsapp_mod
    import app.services.memory_manager as memory_mod
    import app.services.usage_instrumentation as usage_mod

    sent: list[str] = []
    usages: list[dict] = []

    async def _fake_send(phone_number, text):
        sent.append(text)
        return True

    async def _fake_store(**_kw):
        return None

    async def _fake_usage(**kwargs):
        usages.append(kwargs)

    monkeypatch.setattr(graph_mod, "build_agent_graph", lambda: graph)
    monkeypatch.setattr(whatsapp_mod, "send_whatsapp_message", _fake_send)
    monkeypatch.setattr(
        memory_mod, "get_memory_manager",
        lambda: SimpleNamespace(store_interaction=_fake_store),
    )
    monkeypatch.setattr(usage_mod, "record_turn_usage", _fake_usage)
    return sent, usages


# ── 1. Le profil d'outils ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_le_tour_whatsapp_porte_le_profil_d_outils(monkeypatch):
    from app.channels.whatsapp import process_whatsapp_message

    graph = _CaptureGraph()
    sent, _usages = _stub_the_turn(monkeypatch, graph)
    _user_id, phone = await _linked_user()

    await process_whatsapp_message(phone, "est-ce que j'ai des mails ?")

    assert graph.seen, f"le graphe n'a pas été invoqué (envoyé : {sent})"
    assert graph.seen[0].get("toolset_profile"), (
        "WhatsApp invoque le graphe sans toolset_profile : le canal reste "
        "privé de ses outils appris, de <learned_skills> et d'un catalogue stable"
    )


@pytest.mark.asyncio
async def test_le_profil_transmis_est_celui_persiste_sur_la_conversation(monkeypatch):
    """Le profil doit venir de la LIGNE de conversation, pas d'un littéral.

    Une conversation neuve ne discrimine rien : `auto_detect_profile` rend
    toujours le profil par défaut, qu'une constante en dur imiterait sans
    faute. On pose donc un profil NON par défaut avant le tour — seul un
    tour qui relit vraiment la conversation peut le restituer.
    """
    from app.agent.toolset_profiles import COMPACT_PROFILE, DEFAULT_PROFILE
    from app.channels import whatsapp
    from app.channels.whatsapp import process_whatsapp_message
    from app.database import async_session
    from app.models.conversation import Conversation

    assert COMPACT_PROFILE != DEFAULT_PROFILE, (
        "ce test n'épingle rien si le profil posé est celui que "
        "l'auto-détection rendrait de toute façon"
    )

    graph = _CaptureGraph()
    _sent, _usages = _stub_the_turn(monkeypatch, graph)
    user_id, phone = await _linked_user()

    async with async_session() as db:
        conv = Conversation(
            user_id=user_id,
            title="[WhatsApp] profil déjà choisi",
            toolset_profile=COMPACT_PROFILE,
        )
        db.add(conv)
        await db.commit()
        conversation_id = str(conv.id)
    whatsapp._conversations[phone] = conversation_id

    await process_whatsapp_message(phone, "classe mes photos de vacances")

    assert graph.seen, "le graphe n'a pas été invoqué"
    state = graph.seen[0]
    assert state["conversation_id"] == conversation_id
    assert state["toolset_profile"] == COMPACT_PROFILE, (
        f"le graphe reçoit {state['toolset_profile']!r} alors que la "
        f"conversation porte {COMPACT_PROFILE!r} : le canal passe une valeur "
        "en dur, et le catalogue d'outils cessera de suivre la conversation"
    )

    # Le tour ne doit pas non plus RÉÉCRIRE le profil au passage.
    async with async_session() as db:
        conversation = await db.get(Conversation, conversation_id)
    assert conversation.toolset_profile == COMPACT_PROFILE


# ── 2. La ligne d'usage ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_le_tour_whatsapp_arrive_au_tableau_de_bord(monkeypatch):
    from app.channels.whatsapp import process_whatsapp_message

    graph = _CaptureGraph()
    _sent, usages = _stub_the_turn(monkeypatch, graph)
    user_id, phone = await _linked_user()

    await process_whatsapp_message(phone, "bonjour")
    # L'enregistrement part en tâche de fond (best-effort) : on lui laisse
    # la main quelques tours de boucle.
    for _ in range(5):
        if usages:
            break
        await asyncio.sleep(0)

    assert usages, "aucune ligne d'usage : les tours WhatsApp restent invisibles"
    call = usages[0]
    assert call["channel"] == "whatsapp"
    assert call["user_id"] == user_id
    assert call["conversation_id"] == graph.seen[0]["conversation_id"]
    assert call["result"] is not None
    assert isinstance(call["started_at"], float)


@pytest.mark.asyncio
async def test_une_ecriture_d_usage_en_echec_ne_casse_pas_la_reponse(monkeypatch):
    """L'analytique ne doit jamais coûter une réponse déjà produite. Le faux
    échoue de façon SYNCHRONE (comme le ferait un import cassé) : c'est le cas
    qui remonterait jusqu'au `except` du canal et transformerait la réponse en
    « Désolé, une erreur s'est produite »."""
    import app.services.usage_instrumentation as usage_mod
    from app.channels.whatsapp import process_whatsapp_message

    graph = _CaptureGraph("Voilà.")
    sent, _usages = _stub_the_turn(monkeypatch, graph)
    _user_id, phone = await _linked_user()

    def _boom(**_kwargs):
        raise RuntimeError("tableau de bord indisponible")

    monkeypatch.setattr(usage_mod, "record_turn_usage", _boom)

    await process_whatsapp_message(phone, "merci")
    await asyncio.sleep(0)

    assert sent == ["Voilà."]


# ── 3. La souveraineté ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_le_drapeau_de_souverainete_est_pose_avant_l_invocation(monkeypatch):
    """Un utilisateur en souveraineté stricte doit l'être aussi par WhatsApp :
    le ContextVar est lu par la sélection de fournisseur pendant le tour."""
    from app.channels.whatsapp import process_whatsapp_message

    graph = _CaptureGraph()
    _sent, _usages = _stub_the_turn(monkeypatch, graph)
    _user_id, phone = await _linked_user(sovereignty_strict=True)

    await process_whatsapp_message(phone, "résume ma journée")

    assert graph.sovereignty_seen == [True], (
        "le tour WhatsApp part sans le drapeau de souveraineté : la demande "
        "repart vers le fournisseur cloud par défaut"
    )
