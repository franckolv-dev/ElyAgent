# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/openai_codex_auth.py
# @brief      Provider openai-codex — tokens d'abonnement ChatGPT (OAuth),
#             importés depuis le CLI Codex officiel puis auto-rafraîchis.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.0.0
# @link       https://github.com/franckolv-dev/ElyAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Accès GPT-5.x via l'ABONNEMENT ChatGPT (forfait) au lieu de l'API au token.

Motivation (Franck, 12 juin) : une journée de prospection ≈ 7 $ d'API
DeepSeek — l'abonnement ChatGPT (20 €/mois) est amorti en < 4 jours lourds,
pour un modèle supérieur. Design d'usage : **GPT-5.5 primaire du tier C,
DeepSeek pro en fallback de chaîne** (le quota fair-use qui sature ne casse
jamais une mission — `codex_rate_limited`/429 sont classifiés recoverable).

Architecture « oauth_external » (le choix Hermes, audité dans
NousResearch/hermes-agent) : on n'implémente PAS le flow d'autorisation —
l'admin se connecte UNE fois avec le CLI Codex officiel (`codex login`,
qui écrit `~/.codex/auth.json`), colle ce fichier dans Settings, et Ely
prend le relais : stockage CHIFFRÉ (system_config, B-11) et
rafraîchissement automatique via le token endpoint public (le refresh
token tourne à chaque refresh — on persiste la rotation).

Constantes publiques (mêmes valeurs que le CLI officiel et Hermes) :
client_id ``app_EMoamEEZ73f0CkXaXp7hrann``, token endpoint
``auth.openai.com/oauth/token``, backend ``chatgpt.com/backend-api/codex``
(format **Responses API** — le provider construit ChatOpenAI avec
``use_responses_api=True``).

L'injection du Bearer se fait par un ``httpx.Auth`` (token frais par
REQUÊTE, pas par construction du client) — les ChatOpenAI restent
cachables par tier sans jamais servir un token périmé.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Optional

import httpx

logger = logging.getLogger(__name__)

# Constantes publiques du programme Codex (identiques CLI officiel / Hermes).
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
# Refresh 120 s avant expiry (même skew qu'Hermes) ; durée par défaut si le
# token endpoint n'annonce pas expires_in.
_REFRESH_SKEW_S = 120
_DEFAULT_TTL_S = 3600

_CONFIG_KEY = "openai_codex_auth"

# Cache process : {access_token, refresh_token, account_id, expires_at}
_cache: dict[str, Any] | None = None
_refresh_lock = asyncio.Lock()

# Transport injectable pour les tests (httpx.MockTransport) — None en prod.
_transport_for_tests: Optional[httpx.AsyncBaseTransport] = None


class CodexAuthError(RuntimeError):
    """Erreur d'auth Codex avec message exploitable par l'admin."""


# ─────────────────────────────────────────────────────────────────────────
# Import / persistance
# ─────────────────────────────────────────────────────────────────────────


def _parse_auth_json(raw: str | dict) -> dict[str, Any]:
    """Accepte le ``~/.codex/auth.json`` du CLI officiel (clé ``tokens``)
    ou un dict plat {access_token, refresh_token[, account_id]}."""
    data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else data
    access = (tokens.get("access_token") or "").strip()
    refresh = (tokens.get("refresh_token") or "").strip()
    if not refresh:
        raise CodexAuthError(
            "auth.json invalide : refresh_token absent. Lance `codex login` "
            "avec le CLI officiel puis colle le contenu de ~/.codex/auth.json."
        )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "account_id": (tokens.get("account_id") or "").strip(),
        # L'auth.json du CLI ne porte pas d'expiry exploitable : on force un
        # refresh au premier usage (et à l'import, comme validation).
        "expires_at": 0.0,
    }


async def _persist(state: dict[str, Any]) -> None:
    from app.services.system_config import set_config
    await set_config(
        _CONFIG_KEY,
        json.dumps(state, ensure_ascii=False),
        is_secret=True,
        description="Tokens OAuth abonnement ChatGPT (provider openai-codex)",
    )


async def _load() -> dict[str, Any] | None:
    from app.services.system_config import get_config
    raw = await get_config(_CONFIG_KEY, "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning("openai_codex_auth: stored state unreadable — reconnect needed")
        return None


async def import_codex_tokens(raw: str | dict) -> dict[str, Any]:
    """Importe les tokens du CLI officiel, valide par un refresh immédiat
    (échec = feedback à l'import, pas au premier appel LLM), persiste
    chiffré. Retourne le statut."""
    global _cache
    state = _parse_auth_json(raw)
    _cache = state
    # Validation par usage réel : le refresh prouve que le refresh_token
    # est vivant ET nous donne un access token frais + sa durée de vie.
    await _refresh(force=True)
    return await codex_status()


async def disconnect_codex() -> None:
    global _cache
    _cache = None
    from app.services.system_config import delete_config
    await delete_config(_CONFIG_KEY)
    logger.info("openai_codex_auth: disconnected (tokens deleted)")


async def codex_status() -> dict[str, Any]:
    state = _cache or await _load()
    if not state or not state.get("refresh_token"):
        return {"connected": False}
    return {
        "connected": True,
        "account_id": state.get("account_id") or None,
        "expires_at": state.get("expires_at") or None,
        "expires_in_s": max(0, int((state.get("expires_at") or 0) - time.time())) or None,
    }


# ─────────────────────────────────────────────────────────────────────────
# Token frais
# ─────────────────────────────────────────────────────────────────────────


async def _refresh(*, force: bool = False) -> dict[str, Any]:
    """Rafraîchit l'access token si périmé (skew 120 s). Thread-safe via
    lock asyncio ; persiste la ROTATION du refresh token (l'ancien meurt)."""
    global _cache
    async with _refresh_lock:
        state = _cache or await _load()
        if not state or not state.get("refresh_token"):
            raise CodexAuthError(
                "Abonnement ChatGPT non connecté — Settings → Admin → "
                "OpenAI Codex (coller ~/.codex/auth.json après `codex login`)."
            )
        if not force and state.get("expires_at", 0) - time.time() > _REFRESH_SKEW_S:
            _cache = state
            return state

        async with httpx.AsyncClient(timeout=30.0, transport=_transport_for_tests) as client:
            resp = await client.post(
                CODEX_TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "client_id": CODEX_CLIENT_ID,
                    "refresh_token": state["refresh_token"],
                },
            )
        if resp.status_code != 200:
            raise CodexAuthError(
                f"Refresh du token Codex refusé ({resp.status_code}) : "
                f"{resp.text[:200]} — reconnecte-toi via `codex login` + import."
            )
        payload = resp.json()
        state = {
            "access_token": payload.get("access_token") or "",
            # rotation : le nouveau refresh remplace l'ancien ; à défaut on
            # garde l'actuel (certains IdP ne tournent pas à chaque fois)
            "refresh_token": payload.get("refresh_token") or state["refresh_token"],
            "account_id": payload.get("account_id") or state.get("account_id", ""),
            "expires_at": time.time() + float(payload.get("expires_in") or _DEFAULT_TTL_S),
        }
        if not state["access_token"]:
            raise CodexAuthError("Réponse du token endpoint sans access_token.")
        _cache = state
        await _persist(state)
        logger.info(
            "openai_codex_auth: token rafraîchi (expire dans %ds)",
            int(state["expires_at"] - time.time()),
        )
        return state


async def get_codex_access_token() -> str:
    """Access token garanti frais (refresh auto sous le skew)."""
    state = await _refresh(force=False)
    return state["access_token"]


# ─────────────────────────────────────────────────────────────────────────
# Injection par requête (httpx.Auth) — les clients LLM restent cachables
# ─────────────────────────────────────────────────────────────────────────


class CodexBearerAuth(httpx.Auth):
    """Injecte un Bearer FRAIS par requête + l'en-tête de compte ChatGPT.

    Voie async uniquement : tout le chemin agent passe par ``ainvoke``.
    La voie sync sert le token du cache process si présent (best-effort)
    — un appel sync à froid lèvera une erreur claire plutôt qu'un 401 muet.
    """

    requires_request_body = False

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        token = await get_codex_access_token()
        request.headers["Authorization"] = f"Bearer {token}"
        account_id = (_cache or {}).get("account_id") or ""
        if account_id:
            request.headers["chatgpt-account-id"] = account_id
        yield request

    def sync_auth_flow(self, request: httpx.Request):
        state = _cache
        if not state or not state.get("access_token"):
            raise CodexAuthError(
                "Token Codex indisponible sur le chemin synchrone — utiliser "
                "ainvoke (chemin agent standard) ou réchauffer via un appel async."
            )
        request.headers["Authorization"] = f"Bearer {state['access_token']}"
        if state.get("account_id"):
            request.headers["chatgpt-account-id"] = state["account_id"]
        yield request


def _reset_cache_for_tests() -> None:
    global _cache
    _cache = None
