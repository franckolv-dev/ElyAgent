# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_erreur_serveur_openai_est_passagere.py
# @brief      Une erreur serveur du fournisseur (openai.APIError sans code,
#             connexion, délai) se reporte et se replie ; elle ne tue ni le
#             tour ni la mission.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Mission « Nettoyage mails » (ff48cbc2), 04/09/2026 à 06:12, 70 actions :

    passage coupé par APIError: An error occurred while processing your
    request. You can retry your request … request ID 383af7be-…
    Mission ff48cbc2: tick crashed → failed

Le carnet avait bien noté « Passage 2 — INTERROMPU », mais la mission est
passée en `failed` : ni le classifieur de repli ni la détection de panne
passagère du battement ne reconnaissaient ``openai.APIError`` — l'erreur
générique du SDK, sans code HTTP dans son message, que le serveur renvoie
pour une panne de son côté. Les deux lisaient des MOTS (« 429 », « 503 »,
« timeout »), et ce message n'en contient aucun.

La règle : une exception du SDK OpenAI est passagère sauf si c'est une
erreur de REQUÊTE (400, 401, 403, 404, 422) — celles-là ne se résolvent pas
en attendant.
"""
from __future__ import annotations

import httpx
import openai
import pytest

_REQ = httpx.Request("POST", "https://api.openai.com/v1/responses")
_MESSAGE = (
    "An error occurred while processing your request. You can retry your "
    "request, or contact us through our help center at help.openai.com if the "
    "error persists. Please include the request ID 383af7be in your message."
)


def _statut(cls, code: int):
    return cls("erreur", response=httpx.Response(code, request=_REQ), body=None)


# ── Le battement des missions reporte au lieu de tuer ────────────────────────

@pytest.mark.parametrize("exc", [
    openai.APIError(_MESSAGE, _REQ, body=None),
    openai.APIConnectionError(request=_REQ),
    openai.APITimeoutError(request=_REQ),
    _statut(openai.InternalServerError, 500),
    _statut(openai.RateLimitError, 429),
    RuntimeError(f"wrapped: {_MESSAGE}"),
])
def test_une_erreur_serveur_du_fournisseur_est_passagere(exc):
    from app.services.mission_heartbeat import _est_passagere

    assert _est_passagere(exc) is True


@pytest.mark.parametrize("exc", [
    _statut(openai.BadRequestError, 400),
    _statut(openai.AuthenticationError, 401),
    _statut(openai.PermissionDeniedError, 403),
    _statut(openai.NotFoundError, 404),
    _statut(openai.UnprocessableEntityError, 422),
    KeyError("foo"),
    AttributeError("'NoneType' object has no attribute 'x'"),
])
def test_une_erreur_de_requete_ou_un_bug_ne_l_est_pas(exc):
    from app.services.mission_heartbeat import _est_passagere

    assert _est_passagere(exc) is False


# ── Le repli du tour bascule au lieu de laisser remonter ─────────────────────

def test_le_classifieur_reconnait_l_erreur_serveur_generique():
    from app.services.fallback_manager import FailoverReason, classify_exception

    assert classify_exception(openai.APIError(_MESSAGE, _REQ, body=None)) is FailoverReason.UNAVAILABLE
    assert classify_exception(openai.APIConnectionError(request=_REQ)) is FailoverReason.UNAVAILABLE
    assert classify_exception(openai.APITimeoutError(request=_REQ)) is FailoverReason.TIMEOUT
    assert classify_exception(_statut(openai.InternalServerError, 500)) is FailoverReason.UNAVAILABLE


def test_le_classifieur_garde_les_erreurs_de_requete_et_les_bugs():
    from app.services.fallback_manager import FailoverReason, classify_exception

    assert classify_exception(_statut(openai.BadRequestError, 400)) is FailoverReason.BAD_REQUEST
    assert classify_exception(_statut(openai.AuthenticationError, 401)) is FailoverReason.AUTH
    assert classify_exception(KeyError("foo")) is None
