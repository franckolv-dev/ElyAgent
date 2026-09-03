# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/chrome_privacy_filter.py
# @brief      Server-side domain blacklist applied to the rows returned by
#             the Chrome v2 read-only inspectors (history, bookmarks,
#             downloads). The user's browser may know that they bank with
#             BNP, take antidepressants from Doctolib, and unwind on
#             PornHub — none of that needs to be visible to the agent
#             prompt, the LLM provider, or anything downstream.
#
#             V2.0 ships a hardcoded list (sprint validation 2026-05-26
#             "no settings UI to slow ship"). V2.1 may move this into a
#             user-configurable table — the API of `filter_rows` is
#             designed to make that swap a one-line change.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Drop rows whose `url` matches a privacy-sensitive domain.

Design choices
--------------
- Substring match on the host, not the full URL. We want
  ``mail.google.com`` to be classified by ``google.com`` only if
  ``google.com`` is on the list — which it ISN'T. We DO want
  ``my.health.gouv.fr`` to be dropped by the marker ``health.``.
- Substring matchers are LOWERCASED — host names are case-insensitive
  and Chrome may return them in mixed case after IDNA / punycode.
- We never raise on bad input — a row with no ``url`` field, or a URL
  we can't parse, is kept as-is (the agent will see the title and the
  visit timestamp, which is rarely sensitive on its own).
- The match list is intentionally short. False positives here are
  more harmful than false negatives: if the agent can't see
  ``react-fr.org`` because ``fr.`` happens to look bank-ish, the
  product breaks for everyone.
"""
from __future__ import annotations

from typing import Iterable
from urllib.parse import urlparse


# Hardcoded V2.0 blacklist. Each entry is a lowercased substring tested
# against the URL's HOST (not the path). Be conservative — every entry
# silently hides data from the user's own agent.
#
# Buckets are documentation only; matching is flat.
_BLACKLIST: tuple[str, ...] = (
    # ── Banking ─────────────────────────────────────────────────────
    "paypal.",
    "stripe.com",
    "revolut.com",
    "wise.com",
    "n26.com",
    "boursorama.com",
    # BNP owns the `.bnpparibas` gTLD (e.g. `mabanque.bnpparibas`)
    # so we match the bare brand, no trailing dot needed.
    "bnpparibas",
    "creditmutuel.",
    "creditagricole.",
    "societegenerale.",
    "labanquepostale.",
    "caisse-epargne.",
    "lcl.",
    "hsbc.",
    "fortuneo.",
    "chase.com",
    "wellsfargo.com",
    "bankofamerica.",
    # Generic — matches *.bank/, *.banque/ TLDs and obvious markers
    ".bank/",
    ".banque/",
    # ── Health ──────────────────────────────────────────────────────
    "doctolib.",
    "ameli.fr",
    "mondossiermedical.",
    "mes.sante.gouv.fr",
    "maiia.com",
    "qare.fr",
    "livi.fr",
    "mypeakd.",  # peakday tracker
    "myhealth.",
    # ── Adult ───────────────────────────────────────────────────────
    "pornhub.",
    "xvideos.",
    "xhamster.",
    "redtube.",
    "youporn.",
    "onlyfans.",
    "chaturbate.",
    "stripchat.",
    # ── Gov / sensitive admin ───────────────────────────────────────
    "impots.gouv.fr",
    "caf.fr",
    "pole-emploi.fr",
    "francetravail.fr",
    "service-public.fr",
)


def is_blacklisted_url(url: str | None) -> bool:
    """Return True iff ``url`` matches any blacklist substring on the host.

    Empty / unparseable URLs return False (we don't have evidence they're
    sensitive, and the agent benefits from seeing them).
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except (ValueError, AttributeError):
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    # Generic ".bank/" / ".banque/" markers want to match the full URL,
    # not just the host, since they include a trailing slash.
    lowered = url.lower()
    for needle in _BLACKLIST:
        if needle.endswith("/"):
            if needle in lowered:
                return True
        elif needle in host:
            return True
    return False


def filter_rows(rows: Iterable[dict], *, url_key: str = "url") -> list[dict]:
    """Return rows whose ``url_key`` is NOT blacklisted.

    Rows without the key are kept (folder entries in bookmarks have no
    ``url`` — only their children do, and those are separate rows).
    """
    out: list[dict] = []
    for row in rows:
        url = row.get(url_key) if isinstance(row, dict) else None
        if url is None:
            out.append(row)
            continue
        if not is_blacklisted_url(url):
            out.append(row)
    return out
