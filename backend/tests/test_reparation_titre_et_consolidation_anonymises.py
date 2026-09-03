# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_reparation_titre_et_consolidation_anonymises.py
# @brief      Les deux derniers chemins qui envoyaient du texte en clair à un
#             modèle passent par le masque de la conversation.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Réparation post-audit (03/09/2026).

L'audit du 02/09 (§9) nommait deux chemins qui envoient encore le texte brut
d'une conversation à un modèle : le titre automatique et la consolidation de
fin de conversation. Tous deux tournent sur le tier MAINTENANCE — local par
défaut, mais c'est une configuration d'administrateur, pas une garantie. La
page de transparence les nomme depuis ``b3cbe4d`` ; ce lot les ferme.

Le masque est celui de la conversation (``conversation_filters.get_filter``),
pour que les jetons ``[EMAIL_n]`` désignent les mêmes personnes que dans le
tour, et que la sortie se démasque avec le même dictionnaire.
"""
from __future__ import annotations

import re
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.conversation import Conversation, Message

_EMAIL = "paul.durand@example.org"
_JETON = re.compile(r"\[EMAIL_\d+\]")


@pytest_asyncio.fixture
async def _conv():
    await init_db()
    from app.models.user import User
    uid = "t_" + uuid.uuid4().hex[:8]
    cid = uuid.uuid4().hex
    async with async_session() as db:
        db.add(User(id=uid, username=uid, email=f"{uid}@t.local", hashed_password="x"))
        await db.commit()
    async with async_session() as db:
        db.add(Conversation(id=cid, user_id=uid, title="ecris a paul"))
        await db.flush()
        db.add(Message(conversation_id=cid, role="user",
                       content=f"Écris à {_EMAIL} pour le devis"))
        db.add(Message(conversation_id=cid, role="assistant",
                       content=f"Mail envoyé à {_EMAIL}."))
        await db.commit()
    yield uid, cid
    async with async_session() as db:
        await db.execute(delete(Message).where(Message.conversation_id == cid))
        await db.execute(delete(Conversation).where(Conversation.id == cid))
        await db.commit()


# ── Le titre ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_titre_est_genere_sur_un_prompt_masque_puis_demasque(_conv, monkeypatch):
    uid, cid = _conv
    recus: list[str] = []

    async def _faux_fond(llm, messages, **kw):
        prompt = messages[0].content
        recus.append(prompt)
        jeton = _JETON.search(prompt)
        assert jeton, "le prompt du titre doit porter un jeton, pas l'adresse"
        return f"Devis pour {jeton.group(0)}"

    import app.services.background_llm as fond
    import app.services.llm_provider as llm_mod
    monkeypatch.setattr(fond, "ainvoke_background", _faux_fond)
    monkeypatch.setattr(llm_mod, "get_llm_for_tier", lambda tier: object())

    from app.routers.chat import _maybe_generate_title
    await _maybe_generate_title(
        cid, uid, f"Écris à {_EMAIL} pour le devis", f"Mail envoyé à {_EMAIL}.",
    )

    assert len(recus) == 1
    assert _EMAIL not in recus[0]
    async with async_session() as db:
        titre = (await db.execute(
            select(Conversation.title).where(Conversation.id == cid)
        )).scalar_one()
    assert titre == f"Devis pour {_EMAIL}"


# ── La consolidation de fin de conversation ──────────────────────────────────

@pytest.mark.asyncio
async def test_la_consolidation_extrait_sur_un_texte_masque_et_demasque_les_faits(monkeypatch):
    recus: list[str] = []

    async def _faux_fond(llm, messages, **kw):
        prompt = messages[0]["content"]
        recus.append(prompt)
        jeton = _JETON.search(prompt)
        assert jeton, "la consolidation doit recevoir un jeton, pas l'adresse"
        return (
            '{"facts": [{"type": "fact", "key": "contact_devis", '
            f'"value": "{jeton.group(0)}", "confidence": 0.9}}]}}',
            SimpleNamespace(usage_metadata={}),
        )

    import app.services.background_llm as fond
    import app.services.llm_provider as llm_mod
    monkeypatch.setattr(fond, "ainvoke_background_with_usage", _faux_fond)
    monkeypatch.setattr(llm_mod, "get_llm_for_tier", lambda tier: object())

    from app.services.memory.maintenance_rapid import MaintenanceAgentRapid
    agent = MaintenanceAgentRapid()
    faits = await agent._extract_facts(
        f"user: Écris à {_EMAIL} pour le devis\nassistant: fait.",
        "user-consolidation", "conv-consolidation-" + uuid.uuid4().hex[:6],
    )

    assert len(recus) == 1
    assert _EMAIL not in recus[0]
    assert faits and faits[0]["value"] == _EMAIL


# ── Le résumé de fin de conversation (3 prompts, 30 messages) ───────────────

class _FauxMemoire:
    def __init__(self) -> None:
        self.contenus: list[str] = []
        self.preferences: list[str] = []

    async def store_memory(self, content, user_id, conversation_id=None, **kw):
        self.contenus.append(content)

    async def store_preference(self, preference, user_id, **kw):
        self.preferences.append(preference)


@pytest.mark.asyncio
async def test_le_resume_de_fin_de_conversation_masque_le_transcript_et_demasque_les_sorties(
    _conv, monkeypatch,
):
    uid, cid = _conv
    async with async_session() as db:
        db.add(Message(conversation_id=cid, role="user", content="et son numéro ?"))
        db.add(Message(conversation_id=cid, role="assistant",
                       content=f"C'est {_EMAIL}, je l'ai noté."))
        await db.commit()

    recus: list[str] = []

    async def _faux_fond(llm, messages, **kw):
        prompt = messages[0]["content"]
        recus.append(prompt)
        jeton = _JETON.search(prompt)
        assert jeton, "chaque prompt du résumé doit porter un jeton, pas l'adresse"
        j = jeton.group(0)
        if prompt.startswith("Résume"):
            texte = f"L'utilisateur écrit à {j} pour ses devis."
        elif prompt.startswith("À partir de cette conversation, extrais"):
            texte = f'["L\'utilisateur travaille avec {j} sur un devis"]'
        else:
            texte = '["L\'utilisateur préfère des réponses courtes et directes"]'
        return texte, SimpleNamespace(content=texte, usage_metadata={})

    memoire = _FauxMemoire()
    import app.routers.chat as chat_mod
    import app.services.background_llm as fond
    import app.services.llm_provider as llm_mod
    monkeypatch.setattr(fond, "ainvoke_background_with_usage", _faux_fond)
    monkeypatch.setattr(llm_mod, "get_llm_for_tier", lambda tier: object())
    monkeypatch.setattr(chat_mod, "get_memory_manager", lambda: memoire)

    await chat_mod._summarize_conversation(cid, uid)

    assert len(recus) == 3
    assert all(_EMAIL not in p for p in recus)
    assert memoire.contenus == [
        f"L'utilisateur écrit à {_EMAIL} pour ses devis.",
        f"L'utilisateur travaille avec {_EMAIL} sur un devis",
    ]
    assert memoire.preferences == ["L'utilisateur préfère des réponses courtes et directes"]
