# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_slm_warmup_never_blocks_boot.py
# @brief      Un modèle optionnel injoignable ne doit pas coûter le service.
# @license    Elastic License 2.0
# =============================================================================
"""L'incident du 08/08/2026 — Ely ne démarre plus.

Franck pose ``SLM_ENABLED=true`` dans son `.env`. Au redémarrage :

    ✗ Container physicalagent-master-backend-1  Error dependency backend
      failed to start                                              82.1s
    dependency failed to start: container ... is unhealthy

Or les logs disent « Application startup complete ». Ely démarrait — Docker
avait juste cessé d'attendre. Le healthcheck du compose abandonne à
``start_period 15s + 3 × interval 30s``, et le warm-up du SLM, **attendu dans
le lifespan**, brûlait 62 s de backoff (2+4+8+16+32) sur cinq tentatives qui
ne pouvaient pas aboutir.

⚠️ **Pourquoi elles ne pouvaient pas aboutir** — le défaut le plus sournois
des trois. L'ancien code interrogeait ``{ollama_base_url}/api/generate`` avec
``settings.slm_model``, alors que ``get_slm()`` rend
``get_llm_for_tier(ComplexityTier.SIMPLE)`` : le tier A configuré par
l'utilisateur, LM Studio chez Franck. Le warm-up pingait un serveur Ollama
inexistant pour un modèle qui n'était pas le bon. C'est le même défaut que
#327 corrigeait sur l'étiquette et la fenêtre de contexte — l'identité du SLM
lue dans des réglages périmés — et ce fichier en était le troisième site.

Run with:  cd backend && python -m pytest tests/test_slm_warmup_never_blocks_boot.py -v
"""
from __future__ import annotations

import asyncio
import inspect

import pytest


@pytest.mark.asyncio
async def test_warmup_returns_immediately_even_when_the_model_hangs(monkeypatch):
    """LE pin de l'incident : le boot ne doit rien attendre.

    Le double simule un serveur local injoignable qui pend. Avant, cet appel
    retenait le lifespan ; le healthcheck expirait, et le conteneur passait
    pour mort alors que l'application allait bien.
    """
    from app.services import slm_warmup

    lance: list[str] = []
    monkeypatch.setattr(
        "app.services.background_tasks.spawn",
        lambda coro, label=None: (lance.append(label or ""), coro.close()),
    )

    await asyncio.wait_for(slm_warmup.warmup_slm(), timeout=1.0)
    assert lance, "la chauffe doit partir en tâche de fond, pas être attendue"


def test_warmup_delegates_instead_of_looping_in_place():
    """Garde structurel. ⚠️ Ce pin visait d'abord `await warmup_slm()` dans
    `main.py` — c'était une erreur : la fonction est `async` et rend la main
    aussitôt, l'`await` y est correct. Ce qui compte est qu'elle DÉLÈGUE au
    lieu de boucler sur place. C'est la forme qu'avait le défaut.
    """
    import inspect

    from app.services import slm_warmup

    src = inspect.getsource(slm_warmup.warmup_slm)
    assert "spawn(" in src, "la chauffe doit partir en tâche de fond"
    assert "for " not in src and "sleep" not in src, (
        "la boucle de tentatives ne doit pas vivre dans la fonction appelée "
        "par le lifespan"
    )


def test_the_backoff_cannot_exceed_the_healthcheck_window():
    """Le budget de la chauffe doit rester loin sous la patience de Docker.

    ``start_period 15s + 3 × 30s`` = 105 s côté compose ; l'ancien backoff en
    consommait 62 à lui seul. Ce pin échoue si quelqu'un « améliore » la
    robustesse en rallongeant les pauses — l'intention exacte qui a produit
    le défaut.
    """
    from app.services import slm_warmup

    total = sum(slm_warmup._PAUSES) + slm_warmup._TENTATIVES * slm_warmup._TIMEOUT_APPEL
    assert sum(slm_warmup._PAUSES) <= 15, (
        f"pauses = {slm_warmup._PAUSES} : un serveur LOCAL muet au bout de "
        f"quelques secondes ne répondra pas davantage à la 62ᵉ"
    )
    assert total <= 105, f"budget total {total}s — au-delà de la patience du compose"


@pytest.mark.asyncio
async def test_a_remote_provider_is_not_warmed_up(monkeypatch):
    """Chauffer un modèle facturé coûterait un appel par démarrage pour rien :
    un fournisseur distant n'a aucun modèle à charger en RAM."""
    from app.services import slm_warmup

    appels: list[str] = []

    class _LLM:
        async def ainvoke(self, *_a, **_k):
            appels.append("boum")

    monkeypatch.setattr("app.config.get_settings", lambda: type(
        "S", (), {"slm_enabled": True, "slm_model": "x"})())
    monkeypatch.setattr("app.services.llm_provider.get_slm", lambda: _LLM())
    monkeypatch.setattr(
        "app.services.llm_provider.describe_llm", lambda llm: ("openai", "gpt-5.6"),
    )
    # Rien de déclaré : on retombe sur la déduction, qui est le sujet ici.
    monkeypatch.setattr(slm_warmup, "_provider_declare", lambda: "")

    await slm_warmup._warmup()
    assert appels == [], "un fournisseur distant ne doit pas être chauffé"


@pytest.mark.asyncio
async def test_a_local_provider_is_warmed_up_through_the_real_object(monkeypatch):
    """Et le local l'est — via l'objet LLM résolu, pas une URL reconstruite.

    L'ancien code appelait `{ollama_base_url}/api/generate` en dur : chez un
    utilisateur LM Studio, il ne pouvait rien chauffer du tout.
    """
    from app.services import slm_warmup

    appels: list[str] = []

    class _LLM:
        async def ainvoke(self, *_a, **_k):
            appels.append("chauffe")

    monkeypatch.setattr("app.config.get_settings", lambda: type(
        "S", (), {"slm_enabled": True, "slm_model": "x"})())
    monkeypatch.setattr("app.services.llm_provider.get_slm", lambda: _LLM())
    monkeypatch.setattr(
        "app.services.llm_provider.describe_llm",
        lambda llm: ("lm_studio", "nemotron-3-nano-4b"),
    )
    monkeypatch.setattr(slm_warmup, "_provider_declare", lambda: "")

    await slm_warmup._warmup()
    assert appels == ["chauffe"], "un modèle local doit être chargé en RAM"


def test_the_warmup_no_longer_hardcodes_the_ollama_endpoint():
    """Le troisième défaut, épinglé pour ne pas revenir.

    `get_slm()` rend le tier A résolu ; toute URL ou tout nom de modèle
    reconstruit à côté finira par diverger de lui, en silence.
    """
    from app.services import slm_warmup

    # Le CODE, pas la docstring : celle-ci cite l'ancien endpoint pour
    # raconter l'incident, et c'est précisément ce qu'on veut garder.
    src = inspect.getsource(slm_warmup._warmup)
    assert "ollama_base_url" not in src, (
        "l'endpoint ne doit plus être reconstruit : le tier A peut servir "
        "LM Studio, et l'appel partait alors vers un serveur inexistant"
    )
    assert "/api/generate" not in src
    assert "get_slm()" in src


@pytest.mark.asyncio
async def test_the_declared_provider_wins_over_the_guessed_one(monkeypatch):
    """Remarque de Franck (08/08) : « quand j'ajoute un modèle, je définis si
    c'est du Ollama ou du LM Studio — il faut utiliser cette info sinon
    pourquoi la définir ? »

    `describe_llm` DÉDUIT le fournisseur du `base_url`, faute de mieux : une
    même classe LangChain sert dix backends. Mais l'instance porte le choix
    EXPLICITE de l'utilisateur. Déduire ce qui est déclaré, c'est se donner
    une chance de tomber à côté sans aucune raison — et ici, se tromper
    signifie soit ne pas chauffer un local, soit payer un appel cloud à
    chaque démarrage.
    """
    from app.services import slm_warmup

    appels: list[str] = []

    class _LLM:
        async def ainvoke(self, *_a, **_k):
            appels.append("chauffe")

    monkeypatch.setattr("app.config.get_settings", lambda: type(
        "S", (), {"slm_enabled": True, "slm_model": "x"})())
    monkeypatch.setattr("app.services.llm_provider.get_slm", lambda: _LLM())
    # La déduction se trompe — un LM Studio derrière une classe ChatOpenAI se
    # lit volontiers « openai » quand le base_url n'est pas reconnu.
    monkeypatch.setattr(
        "app.services.llm_provider.describe_llm", lambda llm: ("openai", "nemotron"),
    )
    # …mais l'utilisateur a DÉCLARÉ lm_studio.
    monkeypatch.setattr(slm_warmup, "_provider_declare", lambda: "lm_studio")

    await slm_warmup._warmup()
    assert appels == ["chauffe"], (
        "le fournisseur déclaré doit primer : sinon un LM Studio mal deviné "
        "n'est jamais chauffé, et l'option de l'UI ne sert à rien"
    )


def test_the_declared_provider_is_read_from_the_instance_not_reinvented():
    """Il doit venir du cache d'instances — la source de ce que l'UI écrit."""
    import inspect

    from app.services import slm_warmup

    src = inspect.getsource(slm_warmup._provider_declare)
    assert "_instance_cache" in src and "get_tier_config" in src, (
        "le fournisseur déclaré se lit dans la configuration réelle du tier A"
    )
