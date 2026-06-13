# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_openai_codex_auth.py
# @brief      Provider openai-codex (abonnement ChatGPT) — import des tokens
#             du CLI officiel, refresh auto + rotation, httpx.Auth par
#             requête, classification fallback, builder LLM.
# @license    Elastic License 2.0
# =============================================================================
"""Pins provider openai-codex.

Run with:  cd backend && python -m pytest tests/test_openai_codex_auth.py -v
"""
from __future__ import annotations

import json
import time

import httpx
import pytest

from app.services import openai_codex_auth as codex
from app.services.openai_codex_auth import (
    CODEX_BASE_URL,
    CODEX_CLIENT_ID,
    CODEX_TOKEN_URL,
    CodexAuthError,
    CodexBearerAuth,
    _parse_auth_json,
    codex_status,
    disconnect_codex,
    get_codex_access_token,
    import_codex_tokens,
)

# Format exact écrit par `codex login` (CLI officiel) dans ~/.codex/auth.json.
_CLI_AUTH_JSON = json.dumps({
    "OPENAI_API_KEY": None,
    "tokens": {
        "id_token": "eyJhbGciOi...",
        "access_token": "at-from-cli",
        "refresh_token": "rt-1",
        "account_id": "acc-123",
    },
    "last_refresh": "2026-06-12T08:00:00Z",
})


# ── Fixtures ──────────────────────────────────────────────────────────────────


class _FakeStore:
    """system_config en mémoire — enregistre aussi le flag is_secret."""

    def __init__(self):
        self.data: dict[str, str] = {}
        self.secret_keys: set[str] = set()


@pytest.fixture
def store(monkeypatch) -> _FakeStore:
    fake = _FakeStore()

    async def fake_get(key: str, fallback: str = "") -> str:
        return fake.data.get(key, fallback)

    async def fake_set(key: str, value: str, *, is_secret: bool = False,
                       description: str = "") -> None:
        fake.data[key] = value
        if is_secret:
            fake.secret_keys.add(key)

    async def fake_delete(key: str) -> None:
        fake.data.pop(key, None)

    import app.services.system_config as sc
    monkeypatch.setattr(sc, "get_config", fake_get)
    monkeypatch.setattr(sc, "set_config", fake_set)
    monkeypatch.setattr(sc, "delete_config", fake_delete)
    return fake


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    codex._reset_cache_for_tests()
    monkeypatch.setattr(codex, "_transport_for_tests", None)
    yield
    codex._reset_cache_for_tests()


class _FakeTokenEndpoint:
    """auth.openai.com/oauth/token mocké — enregistre les bodies reçus."""

    def __init__(self, *, status: int = 200, rotate: bool = True,
                 expires_in: int | None = 3600, with_access: bool = True):
        self.status = status
        self.rotate = rotate
        self.expires_in = expires_in
        self.with_access = with_access
        self.bodies: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CODEX_TOKEN_URL
        self.bodies.append(json.loads(request.content))
        if self.status != 200:
            return httpx.Response(self.status, text="invalid_grant")
        payload: dict = {}
        if self.with_access:
            payload["access_token"] = f"at-new-{len(self.bodies)}"
        if self.expires_in is not None:
            payload["expires_in"] = self.expires_in
        if self.rotate:
            payload["refresh_token"] = f"rt-{len(self.bodies) + 1}"
        return httpx.Response(200, json=payload)

    def install(self, monkeypatch) -> None:
        monkeypatch.setattr(codex, "_transport_for_tests",
                            httpx.MockTransport(self.handler))


# ── Parsing de l'auth.json ────────────────────────────────────────────────────


class TestParseAuthJson:
    def test_cli_format_with_tokens_key(self):
        state = _parse_auth_json(_CLI_AUTH_JSON)
        assert state["access_token"] == "at-from-cli"
        assert state["refresh_token"] == "rt-1"
        assert state["account_id"] == "acc-123"
        # Pas d'expiry exploitable dans l'auth.json → refresh forcé au 1er usage
        assert state["expires_at"] == 0.0

    def test_flat_dict_accepted(self):
        state = _parse_auth_json({"access_token": "at", "refresh_token": "rt"})
        assert state["refresh_token"] == "rt"
        assert state["account_id"] == ""

    def test_missing_refresh_token_raises_actionable_error(self):
        with pytest.raises(CodexAuthError) as err:
            _parse_auth_json({"access_token": "at-only"})
        assert "codex login" in str(err.value)

    def test_garbage_string_raises_value_error(self):
        with pytest.raises(ValueError):
            _parse_auth_json("pas du json {{{")

    def test_terminal_wrapped_paste_is_repaired(self):
        # Cas réel (12 juin) : copie depuis nano/terminal → le repli visuel
        # des lignes longues injecte des \n au milieu des tokens JWT.
        wrapped = "\n".join(_CLI_AUTH_JSON[i:i + 60]
                            for i in range(0, len(_CLI_AUTH_JSON), 60))
        state = _parse_auth_json(wrapped)
        assert state["access_token"] == "at-from-cli"
        assert state["refresh_token"] == "rt-1"


# ── Import + validation par refresh immédiat ──────────────────────────────────


class TestImport:
    @pytest.mark.asyncio
    async def test_import_validates_by_refresh_and_persists_encrypted(
            self, store, monkeypatch):
        endpoint = _FakeTokenEndpoint()
        endpoint.install(monkeypatch)

        result = await import_codex_tokens(_CLI_AUTH_JSON)

        assert result["connected"] is True
        assert result["account_id"] == "acc-123"
        # Le refresh de validation a bien envoyé le grant attendu
        assert endpoint.bodies == [{
            "grant_type": "refresh_token",
            "client_id": CODEX_CLIENT_ID,
            "refresh_token": "rt-1",
        }]
        # Persistance chiffrée (is_secret) avec ROTATION du refresh token
        assert codex._CONFIG_KEY in store.secret_keys
        persisted = json.loads(store.data[codex._CONFIG_KEY])
        assert persisted["access_token"] == "at-new-1"
        assert persisted["refresh_token"] == "rt-2"

    @pytest.mark.asyncio
    async def test_import_with_dead_refresh_token_fails_at_import(
            self, store, monkeypatch):
        endpoint = _FakeTokenEndpoint(status=401)
        endpoint.install(monkeypatch)

        with pytest.raises(CodexAuthError) as err:
            await import_codex_tokens(_CLI_AUTH_JSON)
        # Feedback à l'IMPORT (pas au premier appel LLM), rien de persisté
        assert "401" in str(err.value)
        assert codex._CONFIG_KEY not in store.data


# ── Refresh : skew, rotation, erreurs ─────────────────────────────────────────


class TestRefresh:
    def _seed(self, store: _FakeStore, *, expires_in_s: float) -> None:
        store.data[codex._CONFIG_KEY] = json.dumps({
            "access_token": "at-stored",
            "refresh_token": "rt-1",
            "account_id": "acc-123",
            "expires_at": time.time() + expires_in_s,
        })

    @pytest.mark.asyncio
    async def test_fresh_token_served_without_http_call(self, store, monkeypatch):
        self._seed(store, expires_in_s=3600)
        endpoint = _FakeTokenEndpoint()
        endpoint.install(monkeypatch)

        token = await get_codex_access_token()

        assert token == "at-stored"
        assert endpoint.bodies == []  # aucun appel réseau

    @pytest.mark.asyncio
    async def test_token_under_skew_is_refreshed(self, store, monkeypatch):
        # 60 s restantes < skew 120 s → refresh proactif
        self._seed(store, expires_in_s=60)
        endpoint = _FakeTokenEndpoint()
        endpoint.install(monkeypatch)

        token = await get_codex_access_token()

        assert token == "at-new-1"
        assert len(endpoint.bodies) == 1

    @pytest.mark.asyncio
    async def test_no_rotation_keeps_current_refresh_token(self, store, monkeypatch):
        # Certains refresh ne tournent pas le refresh_token → on garde l'actuel
        self._seed(store, expires_in_s=0)
        endpoint = _FakeTokenEndpoint(rotate=False)
        endpoint.install(monkeypatch)

        await get_codex_access_token()

        persisted = json.loads(store.data[codex._CONFIG_KEY])
        assert persisted["refresh_token"] == "rt-1"

    @pytest.mark.asyncio
    async def test_refresh_http_error_raises_actionable_error(self, store, monkeypatch):
        self._seed(store, expires_in_s=0)
        endpoint = _FakeTokenEndpoint(status=400)
        endpoint.install(monkeypatch)

        with pytest.raises(CodexAuthError) as err:
            await get_codex_access_token()
        assert "400" in str(err.value) and "codex login" in str(err.value)

    @pytest.mark.asyncio
    async def test_response_without_access_token_raises(self, store, monkeypatch):
        self._seed(store, expires_in_s=0)
        endpoint = _FakeTokenEndpoint(with_access=False)
        endpoint.install(monkeypatch)

        with pytest.raises(CodexAuthError):
            await get_codex_access_token()

    @pytest.mark.asyncio
    async def test_not_connected_raises_actionable_error(self, store):
        with pytest.raises(CodexAuthError) as err:
            await get_codex_access_token()
        assert "non connecté" in str(err.value)


# ── Statut / déconnexion ──────────────────────────────────────────────────────


class TestStatusDisconnect:
    @pytest.mark.asyncio
    async def test_status_not_connected(self, store):
        assert await codex_status() == {"connected": False}

    @pytest.mark.asyncio
    async def test_disconnect_deletes_tokens(self, store, monkeypatch):
        endpoint = _FakeTokenEndpoint()
        endpoint.install(monkeypatch)
        await import_codex_tokens(_CLI_AUTH_JSON)
        assert (await codex_status())["connected"] is True

        await disconnect_codex()

        assert codex._CONFIG_KEY not in store.data
        assert await codex_status() == {"connected": False}


# ── CodexBearerAuth : Bearer frais PAR REQUÊTE ────────────────────────────────


class TestBearerAuth:
    @pytest.mark.asyncio
    async def test_async_flow_injects_fresh_bearer_and_account_header(
            self, store, monkeypatch):
        endpoint = _FakeTokenEndpoint()
        endpoint.install(monkeypatch)
        await import_codex_tokens(_CLI_AUTH_JSON)

        auth = CodexBearerAuth()
        request = httpx.Request("POST", f"{CODEX_BASE_URL}/responses")
        flow = auth.async_auth_flow(request)
        sent = await flow.__anext__()

        assert sent.headers["Authorization"] == "Bearer at-new-1"
        assert sent.headers["chatgpt-account-id"] == "acc-123"

    def test_sync_flow_cold_raises_clear_error(self):
        auth = CodexBearerAuth()
        request = httpx.Request("POST", f"{CODEX_BASE_URL}/responses")
        with pytest.raises(CodexAuthError):
            next(auth.sync_auth_flow(request))


# ── Fallback : le quota Codex est RECOVERABLE (chaîne tier C) ─────────────────


class TestFallbackClassification:
    def test_codex_rate_limited_classified_rate_limit(self):
        # Pin : "rate_limit" de _REASON_KEYWORDS matche "codex_rate_limited"
        # par sous-chaîne — si la table change, ce test casse et le quota
        # Codex ne déclencherait plus la chaîne de fallback du tier.
        from app.services.fallback_manager import FailoverReason, classify_exception
        exc = Exception("codex_rate_limited: usage limit reached, retry later")
        assert classify_exception(exc) == FailoverReason.RATE_LIMIT

    def test_http_429_classified_rate_limit(self):
        from app.services.fallback_manager import FailoverReason, classify_exception
        exc = Exception("Error code: 429 - too many requests")
        assert classify_exception(exc) == FailoverReason.RATE_LIMIT

    def test_codex_not_connected_classified_auth(self):
        # Tier routé sur openai_codex SANS connexion : CodexAuthError doit
        # déclencher la bascule de chaîne (AUTH), pas tuer le tour.
        from app.services.fallback_manager import FailoverReason, classify_exception
        exc = CodexAuthError(
            "Abonnement ChatGPT non connecté — Settings → Admin → "
            "OpenAI Codex (coller ~/.codex/auth.json après `codex login`)."
        )
        assert classify_exception(exc) == FailoverReason.AUTH

    def test_codex_keyword_does_not_shadow_rate_limit(self):
        # Le mot-clé "codex" (AUTH) est APRÈS les mots-clés rate-limit :
        # codex_rate_limited doit RESTER RATE_LIMIT.
        from app.services.fallback_manager import FailoverReason, classify_exception
        exc = Exception("codex_rate_limited: usage limit reached")
        assert classify_exception(exc) == FailoverReason.RATE_LIMIT


# ── Builder LLM ───────────────────────────────────────────────────────────────


class TestProviderBuilder:
    def test_make_llm_builds_responses_api_client_on_codex_backend(self):
        from langchain_openai import ChatOpenAI

        from app.services.llm_provider import (
            _make_llm_for_instance,
            register_instance_cache,
            unregister_instance_cache,
        )
        register_instance_cache("codex-test-inst", "openai_codex", "gpt-5.5", None)
        try:
            llm = _make_llm_for_instance("codex-test-inst")
            assert isinstance(llm, ChatOpenAI)
            assert llm.model_name == "gpt-5.5"
            assert llm.use_responses_api is True
            assert str(llm.openai_api_base) == CODEX_BASE_URL
            # Contraintes du backend codex (spike live 12 juin) — chacune de
            # ces valeurs est OBLIGATOIRE, le backend renvoie 400 sinon :
            assert llm.streaming is True            # "Stream must be set to true"
            assert llm.store is False               # "Store must be set to false"
            assert llm.max_tokens is None           # "Unsupported parameter: max_output_tokens"
            assert llm.model_kwargs.get("instructions")  # "Instructions are required"
            # Épure le content des blocs reasoning (TTS/sanitizer)
            assert llm.output_version == "v0"
            # L'Authorization réelle vient de CodexBearerAuth (par requête),
            # pas du placeholder api_key.
            assert isinstance(llm.http_async_client._auth, CodexBearerAuth)
            assert isinstance(llm.http_client._auth, CodexBearerAuth)
        finally:
            unregister_instance_cache("codex-test-inst")

    def test_legacy_provider_path_builds_codex_too(self):
        # Bug 12 juin : l'entrée legacy « openai_codex » du dropdown Routage
        # passait par _make_llm_for_provider qui ne la connaissait pas →
        # build None → skip silencieux vers le fallback du tier (DeepSeek).
        # Le chemin legacy doit construire le même client que les instances.
        from langchain_openai import ChatOpenAI

        from app.config import get_settings
        from app.services.llm_provider import _make_llm_for_provider

        llm = _make_llm_for_provider("openai_codex", get_settings())
        assert isinstance(llm, ChatOpenAI)
        assert llm.model_name == "gpt-5.5"  # défaut du provider (sans instance)
        assert str(llm.openai_api_base) == CODEX_BASE_URL
        assert llm.streaming is True
        assert llm.store is False
        assert llm.max_tokens is None
        assert llm.model_kwargs.get("instructions")
        assert isinstance(llm.http_async_client._auth, CodexBearerAuth)
