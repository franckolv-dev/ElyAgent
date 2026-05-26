# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_chrome_privacy_filter.py
# @brief      Pin the V2.0 hardcoded blacklist used by the Chrome v2
#             history/bookmarks/downloads tools. A regression here
#             leaks the user's bank, doctor, or porn history into the
#             cloud LLM prompt — the very risk the filter exists to
#             prevent.
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Tests for `app.services.chrome_privacy_filter`.

We pin three categories explicitly:
  - Banking (BNP / Boursorama / PayPal / Chase / ".bank/" generic)
  - Health (Doctolib / Ameli / Maiia)
  - Adult (PornHub / OnlyFans)
  - Sensitive gov (Impôts / CAF / Pôle Emploi)

We also pin a *non*-blacklist of harmless hosts the agent must still
see — false positives here break the product silently.
"""
from __future__ import annotations

import pytest

from app.services.chrome_privacy_filter import (
    is_blacklisted_url,
    filter_rows,
)


# ─────────────────────────────────────────────────────────────────────
# Must block — the whole point of the filter
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    # Banking
    "https://clients.boursorama.com/connexion",
    "https://mabanque.bnpparibas/connexion",
    "https://www.creditmutuel.fr/cmne/fr/banque/",
    "https://www.creditagricole.fr/particulier/operations.html",
    "https://particuliers.societegenerale.fr/",
    "https://www.labanquepostale.fr/index.html",
    "https://www.lcl.fr/",
    "https://www.hsbc.fr/",
    "https://www.paypal.com/myaccount/transfer/homepage",
    "https://dashboard.stripe.com/payments",
    "https://app.revolut.com/home",
    "https://wise.com/account/",
    "https://www.chase.com/",
    "https://my.foo.bank/dashboard",
    # Health
    "https://www.doctolib.fr/dermatologue/paris/dr-foo",
    "https://www.ameli.fr/assure/",
    "https://www.maiia.com/medecin/dr-foo",
    "https://www.qare.fr/teleconsultation/",
    # Adult
    "https://www.pornhub.com/",
    "https://xvideos.com/anything",
    "https://onlyfans.com/foo",
    "https://chaturbate.com/",
    # Sensitive gov
    "https://www.impots.gouv.fr/portail/",
    "https://www.caf.fr/allocataires",
    "https://www.pole-emploi.fr/accueil/",
    "https://www.francetravail.fr/candidat/",
])
def test_blacklisted_urls(url: str) -> None:
    assert is_blacklisted_url(url) is True, (
        f"URL {url} should be blacklisted — leaking it to the LLM is a "
        "privacy incident, not a feature"
    )


# ─────────────────────────────────────────────────────────────────────
# Must NOT block — false positives break the product
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "https://github.com/anthropics/claude-code",
    "https://news.ycombinator.com/",
    "https://www.lemonde.fr/",
    "https://stackoverflow.com/questions/123",
    "https://www.amazon.fr/dp/B08N5WRWNW",
    # Looks bank-ish but isn't (e.g. "banker" subreddit, "bank-of-bytes" repo)
    "https://www.reddit.com/r/banking/",
    "https://github.com/foo/bank-of-bytes",
    # Domains containing "doc" but unrelated to health
    "https://docs.python.org/3/library/",
    "https://docker.com/",
    # Sensitive-looking words inside a path on a harmless host
    "https://en.wikipedia.org/wiki/Pornography",  # path is sensitive, host isn't
    "https://en.wikipedia.org/wiki/Banking",
    # Empty / None / garbage
])
def test_non_blacklisted_urls(url: str) -> None:
    assert is_blacklisted_url(url) is False, (
        f"URL {url} should pass — the filter is now too greedy and is "
        "hiding harmless content from the user's own agent"
    )


@pytest.mark.parametrize("bad", [None, "", "not-a-url", "javascript:alert(1)"])
def test_defensive_inputs(bad) -> None:
    """Empty / None / unparseable URLs return False (safe-ish default)."""
    assert is_blacklisted_url(bad) is False


# ─────────────────────────────────────────────────────────────────────
# filter_rows — the high-level API the tools call
# ─────────────────────────────────────────────────────────────────────


def test_filter_rows_drops_only_blacklisted() -> None:
    rows = [
        {"url": "https://github.com/", "title": "GitHub"},
        {"url": "https://www.boursorama.com/", "title": "Bourso"},  # drop
        {"url": "https://news.ycombinator.com/", "title": "HN"},
        {"url": "https://doctolib.fr/", "title": "Doctolib"},  # drop
        {"url": "https://www.lemonde.fr/", "title": "Le Monde"},
    ]
    out = filter_rows(rows)
    urls = [r["url"] for r in out]
    assert "https://github.com/" in urls
    assert "https://news.ycombinator.com/" in urls
    assert "https://www.lemonde.fr/" in urls
    assert all("boursorama" not in u for u in urls)
    assert all("doctolib" not in u for u in urls)


def test_filter_rows_keeps_rows_without_url() -> None:
    """Folder bookmarks have no URL — they must pass through, not crash."""
    rows = [
        {"id": "1", "title": "Bookmarks bar", "url": None},
        {"id": "2", "title": "GitHub", "url": "https://github.com/"},
    ]
    out = filter_rows(rows)
    assert len(out) == 2  # both kept


def test_filter_rows_custom_url_key() -> None:
    """Caller can point the filter at a different key (e.g. `final_url`)."""
    rows = [
        {"final_url": "https://github.com/"},
        {"final_url": "https://www.paypal.com/"},
    ]
    out = filter_rows(rows, url_key="final_url")
    assert len(out) == 1
    assert "github" in out[0]["final_url"]
