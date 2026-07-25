# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_background_llm_no_think.py
# @brief      Robustesse des appels LLM de tâche de fond : content en blocs,
#             bloc <think>, isolation du stream.
# @license    Elastic License 2.0
# =============================================================================
"""Pins de l'appel LLM de tâche de fond.

Ces chemins tournent hors du regard de l'utilisateur : quand ils échouent,
ils échouent en silence. Trois garanties, qu'aucun n'avait toutes.

**1. Un `content` en LISTE de blocs ne fait plus planter le parse.** Le tier
codex renvoie ``content`` en blocs ; les chemins de fond faisaient
``raw.strip()`` dessus → ``AttributeError``, avalé par le ``try/except``
best-effort. L'immunisation ``content_to_text`` existe pour les missions et
les canaux (#205) — **elle manquait ici**. Vérifié : l'ancien chemin lève
bien `'list' object has no attribute 'strip'`.

**2. Un bloc `<think>` ne casse plus `json.loads`.**

**3. L'isolation du stream est uniforme** — la génération de titre, qui
tourne PENDANT un tour de chat actif, ne l'avait pas.

⚠️ **Ce lot n'est PAS une optimisation de tokens, contrairement à ce que
j'avais d'abord conclu.** ``usage_logs`` montrait 2 101 tokens de sortie par
extraction contre 151 pour un modèle sans raisonnement — mais ce chiffre
agrégeait toute l'histoire et était dominé par l'essai d'`ornith-1.0-9b`
(16-17/07), abandonné depuis. **Sur les 7 derniers jours, l'extraction tourne
à 102 tokens de sortie : elle est déjà sobre.**

Et ``/no_think`` **n'a aucun effet sur Qwen 3.5** — ``llm_provider.py`` le
documente, et une mesure au chrono l'a confirmé (7,5 s contre 8,9 s :
indiscernable). Le raisonnement est coupé au niveau du fournisseur par
``enable_thinking=False``. La directive est conservée parce qu'elle reste
correcte pour Qwen 3 et inerte ailleurs.

Run with:  cd backend && python -m pytest tests/test_background_llm_no_think.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest


class _FakeLocalQwen:
    """Imite un ChatOpenAI pointé sur LM Studio (détecté comme local)."""

    def __init__(self, reply: str = '{"facts": []}') -> None:
        self.__class__.__name__ = "ChatOpenAI"
        self.model_name = "qwen/qwen3.5-9b"
        self.openai_api_base = "http://host.docker.internal:1234/v1"
        self.received: list = []
        self.config = None
        self._reply = reply

    async def ainvoke(self, messages, config=None):
        self.received = messages
        self.config = config
        return type("R", (), {"content": self._reply})()


class _FakeCloud:
    def __init__(self) -> None:
        self.__class__.__name__ = "ChatAnthropic"
        self.model_name = "claude-opus-5"
        self.received: list = []

    async def ainvoke(self, messages, config=None):
        self.received = messages
        return type("R", (), {"content": '{"facts": []}'})()


# --------------------------------------------------------- le contrat

@pytest.mark.asyncio
async def test_a_local_qwen_receives_the_no_think_directive():
    """Correct pour Qwen 3 (inerte sur 3.5, où le fournisseur s'en charge)."""
    from app.services.background_llm import ainvoke_background

    llm = _FakeLocalQwen()
    await ainvoke_background(llm, [{"role": "user", "content": "extrais les faits"}])

    sent = llm.received[-1]["content"]
    assert "/no_think" in sent


@pytest.mark.asyncio
async def test_a_cloud_model_is_left_untouched():
    """`/no_think` est une directive Qwen : l'envoyer à Claude ou GPT
    polluerait le prompt sans rien désactiver."""
    from app.services.background_llm import ainvoke_background

    llm = _FakeCloud()
    await ainvoke_background(llm, [{"role": "user", "content": "extrais les faits"}])

    assert "/no_think" not in llm.received[-1]["content"]


@pytest.mark.asyncio
async def test_the_call_is_isolated_from_the_active_stream():
    """Sans `callbacks: []`, les tokens de la tâche de fond fuient dans le
    stream d'un autre tour (bug vécu le 19/07, cf. spawn detach_context)."""
    from app.services.background_llm import ainvoke_background

    llm = _FakeLocalQwen()
    await ainvoke_background(llm, [{"role": "user", "content": "x"}])

    assert llm.config == {"callbacks": []}


@pytest.mark.asyncio
async def test_a_think_block_never_reaches_the_json_parser():
    """Filet de sécurité : si un modèle raisonne quand même en clair, le bloc
    doit disparaître avant le parse — sinon `json.loads` échoue et
    l'extraction ne produit rien, en silence."""
    from app.services.background_llm import ainvoke_background

    llm = _FakeLocalQwen(reply='<think>hmm voyons voir…</think>{"facts": [{"fact": "a"}]}')
    content = await ainvoke_background(llm, [{"role": "user", "content": "x"}])

    assert "<think>" not in content
    assert content.strip().startswith("{")


@pytest.mark.asyncio
async def test_reasoning_can_be_requested_explicitly():
    """Toutes les tâches de fond ne se valent pas : un juge (mission_critic,
    diagnostician) peut légitimement vouloir raisonner. L'appelant décide."""
    from app.services.background_llm import ainvoke_background

    llm = _FakeLocalQwen()
    await ainvoke_background(llm, [{"role": "user", "content": "juge ceci"}], reasoning=True)

    assert "/no_think" not in llm.received[-1]["content"]


@pytest.mark.asyncio
async def test_an_llm_failure_is_not_swallowed_by_the_helper():
    """Le helper ne doit pas masquer une panne : les appelants ont déjà leur
    propre `try/except` best-effort, et un échec avalé deux fois devient
    invisible."""
    from app.services.background_llm import ainvoke_background

    class _Boom:
        __name__ = "ChatOpenAI"

        async def ainvoke(self, messages, config=None):
            raise RuntimeError("modèle indisponible")

    with pytest.raises(RuntimeError):
        await ainvoke_background(_Boom(), [{"role": "user", "content": "x"}])


# ------------------------------------- les chemins qui doivent l'utiliser

@pytest.mark.parametrize("path,skill", [
    ("app/services/memory_service.py", "memory_extraction + conversation_summary"),
    ("app/services/memory/maintenance_rapid.py", "memory_consolidation"),
])
def test_the_costly_background_paths_use_the_helper(path, skill):
    """Ces chemins parsent du JSON issu du modèle : ce sont exactement ceux
    qu'un `content` en blocs ou un `<think>` casserait en silence."""
    src = Path(path).read_text(encoding="utf-8")

    assert "ainvoke_background" in src, (
        f"{skill} appelle encore le LLM sans garde-fou"
    )


def test_the_extraction_no_longer_calls_the_llm_directly():
    """Pin de non-retour : un futur refactor ne doit pas remettre un
    `llm.ainvoke` nu, qui reperdrait les trois garde-fous."""
    src = Path("app/services/memory_service.py").read_text(encoding="utf-8")

    assert "llm.ainvoke(" not in src, (
        "appel LLM nu réintroduit — les garde-fous sautent sur ce chemin"
    )


@pytest.mark.asyncio
async def test_a_list_block_content_no_longer_crashes_the_caller():
    """LE test du lot. Le tier codex renvoie `content` en LISTE de blocs ;
    l'ancien chemin faisait `raw.strip()` dessus et levait
    `'list' object has no attribute 'strip'`, avalé en silence. Basculer le
    tier MAINTENANCE sur un modèle codex aurait cassé l'extraction de faits
    à chaque appel, sans trace exploitable."""
    from app.services.background_llm import ainvoke_background

    class _BlocksLLM:
        __name__ = "ChatOpenAI"

        async def ainvoke(self, messages, config=None):
            return type("R", (), {
                "content": [{"type": "text", "text": '{"facts": [{"fact": "a"}]}'}]
            })()

    content = await ainvoke_background(_BlocksLLM(), [{"role": "user", "content": "x"}])

    import json
    assert json.loads(content)["facts"][0]["fact"] == "a"
