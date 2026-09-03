# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_google_account_alias_never_falls_back.py
# @brief      Un alias de compte Google inconnu refuse l'appel ; il ne
#             retombe jamais sur le compte par défaut.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Le mauvais compte, en silence (audit du 02/09/2026).

`_inject_google_credentials` cherchait le compte lié à l'alias demandé
(« travail ») et, s'il était introuvable ou si la recherche levait, posait un
avertissement dans les logs et continuait avec les identifiants du compte par
défaut. « Envoie ce mail depuis mon compte travail » partait donc du compte
personnel, et rien ne le disait à l'utilisateur.

Un alias qui ne résout pas est un refus : l'outil n'est pas exécuté, et le
modèle reçoit un message qui nomme le compte demandé.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.database import init_db


@pytest_asyncio.fixture(autouse=True)
async def _db():
    await init_db()


class _Hitl:
    async def request_validation(self, description, user_id):
        return ("allow", None)


class _EspionGmail:
    name = "gmail_send_email"

    def __init__(self) -> None:
        self.appels: list[dict] = []

    async def ainvoke(self, args):
        self.appels.append(dict(args))
        return "Message envoyé"


def _ctx():
    from app.services.conversation_filters import get_filter
    from app.services.security_filter import SecurityFilter
    from app.services.tool_gateway import GatewayContext

    conv = f"conv-alias-{uuid.uuid4()}"
    return GatewayContext(
        user_id=f"u-alias-{uuid.uuid4().hex[:6]}", conversation_id=conv,
        pii_filter=get_filter(conv), criticality_filter=SecurityFilter(),
        hitl=_Hitl(), memory=None,
    )


def _texte(resultat) -> str:
    if isinstance(resultat, (list, tuple)):
        resultat = resultat[0] if resultat else ""
    return str(getattr(resultat, "content", resultat))


@pytest.mark.asyncio
async def test_un_alias_inconnu_refuse_l_appel_sans_executer_l_outil() -> None:
    from app.services.tool_gateway import execute_tool_call

    espion = _EspionGmail()
    resultat = await execute_tool_call(
        _ctx(),
        {"name": "gmail_send_email", "id": "g-alias",
         "args": {"account": "travail", "to": "paul@example.com",
                  "subject": "s", "body": "b"}},
        {"gmail_send_email": espion},
    )

    assert espion.appels == [], (
        "l'outil a été exécuté : avec les identifiants de quel compte ?"
    )
    texte = _texte(resultat).lower()
    assert "travail" in texte and "compte" in texte, texte
