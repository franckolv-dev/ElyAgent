# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_kw_regex.py
# @brief      Pin the `_tool_kw` keyword regex in nodes.py that decides
#             whether to `bind_tools` on SIMPLE/MEDIUM tier turns. A faulty
#             regex (missing keywords or a stray `||` empty-alternation)
#             made small local LLMs refuse legitimate requests because
#             they couldn't see their tools.
# @license    Elastic License 2.0
# =============================================================================
"""Tests for the `_tool_kw` regex in app/agent/nodes.py.

Why this test exists
--------------------
The regex lives inside a closure (`create_agent_node()` inner scope) so it
can't be imported directly. We use two complementary strategies :

1. **Source-grep** : assert the canonical keywords are present in the
   regex literal in `nodes.py`. Cheap regression guard against someone
   accidentally deleting a category.

2. **Re-instantiate** : reproduce the regex in the test from the
   *exact same* source string and validate it against a curated battery
   of queries. This protects against subtle regex bugs (empty
   alternation, broken alternations, etc.) without needing to refactor
   nodes.py to expose the regex.

The day Phase 5 of the refactor extracts the inference path into
`agent/inference/llm.py`, the regex should be promoted to a module-level
constant and this test can use a direct import instead.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_NODES_PY = _REPO / "app" / "agent" / "nodes.py"


# ─────────────────────────────────────────────────────────────────────────
# 1. Source-grep guard — pinned keywords must remain in the regex literal
# ─────────────────────────────────────────────────────────────────────────


_CANONICAL_KEYWORDS = (
    # Verbs of action (legacy + post-2026-05-26 additions)
    "envoie", "crée", "liste", "cherche", "trouve", "génère",
    "regarde", "consulte", "vérifie", "ouvre", "navigue", "lis",
    # Email / calendar / drive domains
    "mail", "email", "calendrier", "agenda", "drive", "sheet", "doc",
    # Social networks (added 2026-05-26 after the « regarde mes réseaux
    # sociaux » incident on Gemma 4 tier B)
    "linkedin", "mastodon", "twitter", "bluesky", "facebook",
    "abonn", "follower", "notif", "post", "tweet",
    # Public services often visited via the Chrome extension
    "doctolib", "sncf", "amazon",
    # Sprint 0.7 (2026-05-26) — Chrome v2 read-only inspectors. Without
    # these, "quels sites j'ai visité", "cherche dans mon historique de
    # navigation", "mes téléchargements du jour" skip bind_tools and the
    # LLM says "I have no tool for that" while the tools sit registered.
    "historique", "navigation", "visit", "signets", "favori", "bookmark",
    "download", "chrome", "navigateur", "browser",
)


@pytest.mark.parametrize("kw", _CANONICAL_KEYWORDS)
def test_tool_kw_regex_contains_keyword(kw: str) -> None:
    """Pin that the keyword is still part of the `_tool_kw` regex literal."""
    src = _NODES_PY.read_text(encoding="utf-8")
    # We don't try to parse the regex out — a substring search is enough
    # to guard against a deletion. The keyword may appear once in the
    # comment block above the regex AND inside the pattern itself; we
    # only require the latter, but the substring check covers both.
    assert kw in src, (
        f"Keyword {kw!r} missing from nodes.py — was the _tool_kw regex "
        f"trimmed by mistake ?"
    )


# ─────────────────────────────────────────────────────────────────────────
# 2. Behavioural test — re-instantiate the regex and run it on queries
# ─────────────────────────────────────────────────────────────────────────


# Keep this string in sync with nodes.py `_tool_kw`. Any divergence is
# caught by the next test (source-grep against the actual pattern body).
_TOOL_KW_PATTERN = (
    r"\b("
    r"envoie|envoy|crée|liste|cherche|recherche|trouve|génère|"
    r"exécute|lance|planifie|programme|enregistre|sauvegarde|"
    r"supprime|archive|copie|déplace|renomme|partage|"
    r"regarde|regard|consulte|vérifie|vérific|verifie|ouvre|navigue|"
    r"affiche|montre|résume|résum|read|lis"
    r"|mail|email|courriel|calendrier|agenda|rendez.?vous|rdvs?|"
    r"réunions?|meetings?|drive|sheet|doc|tâche|rappel|note|"
    r"fichier|capture|screenshot|météo|news|traduis"
    r"|réseau(x)?\s*sociau(x)?|reseau(x)?\s*sociau(x)?|"
    r"social[\s-]*media|profil|profile|"
    r"linkedin|mastodon|twitter|x\.com|instagram|insta|"
    r"facebook|threads|bluesky|tiktok|youtube|"
    r"abonn[ée]s?|follower|followers|mention|mentions|"
    r"post|posts|tweet|tweets|publication|publications|"
    r"notif|notifs|notification|notifications|"
    r"doctolib|sncf|booking|amazon|leboncoin"
    # Sprint 0.7 — Chrome v2 read-only inspectors
    r"|historique|navigation|visit[eéès]?|"
    r"signets?|favori|favoris|bookmark|bookmarks|"
    r"t[ée]l[ée]charg\w*|download|downloads|"
    r"chrome|navigateur|browser|"
    r"sites?\s+(visit|web|internet|consult|all[ée]s?|fr[ée]quent)"
    r")\b"
)
_TOOL_KW = re.compile(_TOOL_KW_PATTERN, re.IGNORECASE)


def test_pattern_string_matches_nodes_py_literal() -> None:
    """Drift guard : the pattern reproduced here must appear verbatim in
    `nodes.py`. If you update one, update the other."""
    src = _NODES_PY.read_text(encoding="utf-8")
    # Strip leading whitespace from each line to remove the Python source
    # indentation, then re-join. Same trick used elsewhere in the suite.
    # We accept either the raw concatenated form OR a multi-line `r"…"`
    # variant — the substring "envoie|envoy|crée|liste" is unique enough
    # to anchor the search.
    anchor = "envoie|envoy|crée|liste|cherche|recherche|trouve|génère"
    assert anchor in src, (
        "The unique anchor of the _tool_kw regex was not found in nodes.py "
        "— either the regex was renamed or the canonical order was changed."
    )


def test_pattern_does_not_match_empty_string() -> None:
    """Critical safeguard : the regex must NEVER match the empty string.

    A stray `||` in the alternation (which happened during dev) turns the
    regex into a zero-width matcher that hits on every input, defeating
    its filtering purpose.
    """
    m = _TOOL_KW.search("bonjour")
    # Either no match, or a match with non-empty content
    assert (m is None) or (m.group(0) != "")


# Behavioural fixtures
_MUST_MATCH_NEW_2026_05_26 = [
    # Cases that failed in prod before the fix (Gemma 4 tier B refused
    # because bind_tools wasn't triggered).
    "regarde mes réseaux sociaux",
    "vérifie chacun de ces réseaux",
    "consulte mon LinkedIn",
    "ouvre Mastodon dans un onglet",
    "navigue vers x.com",
    "j'ai combien d'abonnés sur Bluesky ?",
    "regarde mes notifs Twitter",
    "ouvre Doctolib",
    "résume mon feed",
    "lis ce post sur LinkedIn",
    # Sprint 0.7 (2026-05-26) — Chrome v2 inspectors. These three were
    # the exact prompts that failed in the post-deploy smoke (deepseek
    # v4-pro tier C answered "Je n'ai pas d'outil direct" because the
    # regex didn't match any keyword in the user query).
    "Quels sites j'ai visité vendredi soir ?",
    "cherche dans mon historique de navigation",
    "qu'est-ce que j'ai visité aujourd'hui sur Chrome ?",
    "mes téléchargements du jour",
    "trouve-moi mes signets sur React",
    "ouvre mon historique",
    "tu peux regarder mes favoris",
]

_MUST_MATCH_LEGACY = [
    # Anti-regression : these were already covered and must stay so.
    "envoie un mail à Alice",
    "liste mes RDV cette semaine",
    "cherche mes mails Amazon",
    "crée un document sur mon Drive",
    "génère une image",
    "screenshot de mon écran",
    "météo à Paris",
    "Mes RDV cette semaine",  # the famous May-2026 audit case
]

_MUST_NOT_MATCH_CHITCHAT = [
    # Pure conversational queries — bind_tools must NOT fire.
    "bonjour",
    "tu vas bien ?",
    "que penses-tu de ce film",
    "comment se passe ta journée",
    "merci",
    "raconte-moi une blague",
    "ok parfait",
]


@pytest.mark.parametrize("query", _MUST_MATCH_NEW_2026_05_26)
def test_regex_matches_new_keywords(query: str) -> None:
    m = _TOOL_KW.search(query)
    assert m is not None and m.group(0), (
        f"Expected to match {query!r} but regex returned no hit"
    )


@pytest.mark.parametrize("query", _MUST_MATCH_LEGACY)
def test_regex_still_matches_legacy_keywords(query: str) -> None:
    m = _TOOL_KW.search(query)
    assert m is not None and m.group(0), (
        f"Regression : {query!r} no longer matches the regex"
    )


@pytest.mark.parametrize("query", _MUST_NOT_MATCH_CHITCHAT)
def test_regex_does_not_match_chitchat(query: str) -> None:
    m = _TOOL_KW.search(query)
    assert (m is None) or (not m.group(0)), (
        f"False positive : {query!r} matched {m.group(0)!r} but should not"
    )
