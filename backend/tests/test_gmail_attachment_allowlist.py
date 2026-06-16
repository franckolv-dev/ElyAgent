# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_gmail_attachment_allowlist.py
# @brief      gmail_send_with_local_attachment : liste blanche des dossiers
#             sources, incluant /tmp/ely-screenshots (browser_tab_screenshot).
# =============================================================================
"""La garde de sécurité de gmail_send_with_local_attachment doit accepter les
captures de l'extension Chrome (browser_tab_screenshot → /tmp/ely-screenshots)
et toujours refuser les chemins hors liste blanche (/etc/passwd…).
"""
from __future__ import annotations

import os

import pytest

from app.agent.tools.gmail_tool import (
    _ALLOWED_ATTACHMENT_DIRS,
    gmail_send_with_local_attachment,
)

# La whitelist compare des chemins littéraux /tmp/... après os.path.realpath.
# Sous Linux (conteneur prod + CI), /tmp n'est pas un lien → la comparaison
# tient. Sous macOS, /tmp → /private/tmp, donc on saute les assertions qui
# dépendent de cette résolution (la whitelist ne vise QUE le conteneur).
_TMP_IS_REAL = os.path.realpath("/tmp") == "/tmp"


def test_screenshots_dir_is_allowlisted():
    assert "/tmp/ely-screenshots" in _ALLOWED_ATTACHMENT_DIRS
    # rétrocompat : l'ancien dossier reste autorisé
    assert "/tmp/ely-attachments" in _ALLOWED_ATTACHMENT_DIRS


@pytest.mark.asyncio
async def test_outside_path_refused():
    out = await gmail_send_with_local_attachment.ainvoke(
        {"to": "a@b.c", "subject": "s", "body": "b", "local_path": "/etc/passwd"}
    )
    assert "refusé" in out.lower()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _TMP_IS_REAL,
    reason="/tmp symlinké (macOS) — whitelist littérale /tmp valable seulement dans le conteneur Linux",
)
async def test_screenshots_path_passes_whitelist():
    out = await gmail_send_with_local_attachment.ainvoke(
        {
            "to": "a@b.c",
            "subject": "s",
            "body": "b",
            "local_path": "/tmp/ely-screenshots/tab-x-00000000.png",
        }
    )
    # Passe la whitelist → échoue plus loin sur 'introuvable', PAS sur 'refusé'.
    assert "refusé" not in out.lower()
    assert "introuvable" in out.lower()
