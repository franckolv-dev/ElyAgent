# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/licence_service.py
# @brief      Licence service — Elastic License v2 (no tiers, no activation)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#             https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Licence service — Elastic License v2.

Pre-2026-05-28 this module implemented a tiered licensing system
(free / pro / business / enterprise) with activation, max-user
enforcement, click-wrap consent, and a paid licence-key column. The
22 May 2026 pivot dropped all that in favour of a single Elastic
License v2 that covers any personal use AND any internal business use,
with no activation flow and no user cap.

The ``Licence`` SQLAlchemy table is kept (see ``models/licence.py``) so
existing installations don't blow up at boot — its only remaining role
is forensic / audit. Production code no longer reads or writes it.

Public API (kept for backwards compatibility — every caller still works,
they just get a permissive "always allowed" response now)
-----------------------------------------------------------------------
* ``check_user_creation_allowed(db)``  always returns ``(True, None)``.
  Kept because ``routers/auth.py`` calls it before each user creation;
  removing the call would create needless churn.
* ``get_licence_status(db)``  returns a fixed dict describing the
  Elastic License v2 — consumed by ``GET /api/licence/status``.
* ``get_active_licence(db)``  kept as a no-op alias that returns None;
  some legacy tests reference it.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Stable identifier used by the status endpoint + the frontend panel.
LICENSE_ID = "elastic-license-v2"
LICENSE_URL = "https://www.elastic.co/licensing/elastic-license"
LICENSE_SUMMARY_URL = "https://agent-ely.fr/pricing.html"


# ── Public API ───────────────────────────────────────────────────────────────


async def check_user_creation_allowed(
    db: AsyncSession,
) -> tuple[bool, Optional[str]]:
    """Always allows user creation under Elastic License v2.

    Returns ``(True, None)`` unconditionally — the licence has no
    max-user cap. Kept as a function (instead of inlined ``True``) so
    ``routers/auth.py`` keeps its existing call site and we have a
    single place to add a guard if a future need arises (e.g. a
    self-imposed installation cap).
    """
    return True, None


async def get_active_licence(db: AsyncSession):
    """Legacy no-op: returns ``None``. Kept so old tests + scripts that
    still import this symbol don't break."""
    return None


async def get_licence_status(db: AsyncSession) -> dict:
    """Return a fixed licence-info payload for ``GET /api/licence/status``.

    Shape consumed by the frontend panel (see
    ``LicenceSection.tsx``). Includes plain-English summary fields so
    the panel can render without round-tripping translations.
    """
    return {
        "license": LICENSE_ID,
        "name": "Elastic License v2",
        "url": LICENSE_URL,
        "summary_url": LICENSE_SUMMARY_URL,
        "free_for": [
            "personal use (unlimited)",
            "internal business use (any organisation size)",
            "modification and redistribution (keeping notices)",
        ],
        "forbidden": [
            "resell as hosted SaaS or managed service to third parties",
            "remove or obscure copyright / licence notices",
        ],
    }
