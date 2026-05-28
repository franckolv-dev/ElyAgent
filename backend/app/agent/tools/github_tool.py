# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/github_tool.py
# @brief      GitHub tools — repo stats, traffic (clones + visitors),
#             notifications. Read-only, all backed by the GitHub REST API v3.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""GitHub tools — read-only repo stats, traffic, notifications.

Authentication
--------------
Uses a Personal Access Token (PAT) loaded from settings.github_token
(env var GITHUB_TOKEN). Required scopes :

  - ``public_repo`` (or ``repo`` for private repos) — for repo stats
  - Push access on the target repo — for traffic endpoints (clones,
    visitors). GitHub gates these to repo admins/maintainers.
  - ``notifications`` — for the notifications endpoint

If no token is configured, the tools return a clear setup message
instead of crashing.

Default repo
------------
If the user omits owner/repo, we fall back to ``settings.github_default_repo``
(format: ``owner/repo``). This makes « combien de clones aujourd'hui ? »
work without arguments for the project owner's own repo.

Created 2026-05-17 to unblock Franck's screencast scenario step 13-14
(« vérifie les clones du repo + crée un XLSX quotidien »). Listed as a
backlog item before, now in. Not HITL-gated — read-only.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from langchain_core.tools import tool

from app.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_HEADERS_BASE = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "ELY-Agent/1.1",
}


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _resolve_repo(owner: str, repo: str) -> tuple[str, str] | None:
    """Return (owner, repo) from explicit args or the default in settings.

    Returns None if neither source is available.
    """
    if owner and repo:
        return owner.strip(), repo.strip()
    default = (get_settings().github_default_repo or "").strip()
    if "/" in default:
        o, r = default.split("/", 1)
        if o and r:
            return o.strip(), r.strip()
    return None


def _auth_headers() -> dict[str, str] | None:
    """Return GitHub headers with bearer token, or None if no token.

    Caller is responsible for returning a setup message in that case.
    """
    token = get_settings().github_token
    if not token:
        return None
    return {**_HEADERS_BASE, "Authorization": f"Bearer {token}"}


def _setup_hint() -> str:
    return (
        "GitHub non configuré : ajoute `GITHUB_TOKEN=<ton_PAT>` dans le `.env` "
        "du backend (token créable sur https://github.com/settings/tokens — "
        "scope `public_repo` + `notifications` suffisent pour la plupart des "
        "demandes ; pour les stats de trafic, le token doit appartenir à un "
        "admin du repo). Optionnellement : `GITHUB_DEFAULT_REPO=owner/repo` "
        "pour éviter de redonner le nom à chaque appel."
    )


async def _gh_get(path: str, params: dict | None = None) -> tuple[int, Any]:
    """GET a GitHub API path, return (status, json_or_text)."""
    headers = _auth_headers()
    if headers is None:
        return 401, _setup_hint()
    url = f"{_API_BASE}{path}"
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.get(url, headers=headers, params=params or {})
        except httpx.HTTPError as exc:
            logger.warning("GitHub API call failed (%s): %s", path, exc)
            return 0, f"Erreur réseau GitHub : {exc}"
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, resp.text


def _fmt_int(n: int | None) -> str:
    """Pretty 1234 → 1 234 (French-style thousands)."""
    if n is None:
        return "?"
    return f"{n:,}".replace(",", " ")


# ──────────────────────────────────────────────────────────────────────
# Tool 1 — Repo stats (stars / forks / issues / watchers)
# ──────────────────────────────────────────────────────────────────────


@tool
async def github_repo_stats(owner: str = "", repo: str = "") -> str:
    """Get current stats for a GitHub repository (stars, forks, issues, etc.).

    Read-only, no destructive action. Returns a concise summary string
    suitable for inclusion in an agent reply.

    Args:
        owner: GitHub owner/organization name (e.g. "franckolv-dev"). If
            empty, falls back to settings.github_default_repo.
        repo: Repository name (e.g. "ElyAgent"). If empty, falls back to
            settings.github_default_repo.

    Returns: a multi-line summary with stars, forks, open issues,
        watchers, language, default branch, last push date. Or a clear
        error message if the token is missing or the repo not found.
    """
    resolved = _resolve_repo(owner, repo)
    if not resolved:
        return (
            "Erreur : précise le repo sous la forme owner/repo, "
            "ou configure GITHUB_DEFAULT_REPO dans le `.env`."
        )
    owner, repo = resolved

    status, data = await _gh_get(f"/repos/{owner}/{repo}")
    if status == 401 or isinstance(data, str):
        return data if isinstance(data, str) else _setup_hint()
    if status == 404:
        return f"❌ Repo `{owner}/{repo}` introuvable (ou privé sans accès)."
    if status >= 400 or not isinstance(data, dict):
        return f"❌ Erreur GitHub {status} sur `{owner}/{repo}`."

    pushed = data.get("pushed_at", "?")
    try:
        pushed_dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
        pushed_fmt = pushed_dt.strftime("%d/%m/%Y %H:%M UTC")
    except Exception:
        pushed_fmt = pushed

    return (
        f"📊 `{owner}/{repo}`\n"
        f"⭐ Stars        : {_fmt_int(data.get('stargazers_count'))}\n"
        f"🍴 Forks        : {_fmt_int(data.get('forks_count'))}\n"
        f"👀 Watchers     : {_fmt_int(data.get('subscribers_count'))}\n"
        f"🐛 Open issues  : {_fmt_int(data.get('open_issues_count'))}\n"
        f"💻 Langage      : {data.get('language') or 'non détecté'}\n"
        f"🌿 Branche par défaut : {data.get('default_branch', '?')}\n"
        f"📅 Dernier push : {pushed_fmt}"
    )


# ──────────────────────────────────────────────────────────────────────
# Tool 2 — Traffic (clones + visitors, 14 jours glissants)
# ──────────────────────────────────────────────────────────────────────


@tool
async def github_traffic_stats(owner: str = "", repo: str = "") -> str:
    """Get the 14-day traffic stats for a GitHub repository.

    Returns total clones, unique cloners, total page views, unique
    visitors over the last 14 days (GitHub's window — non-configurable).
    Requires a token with push/admin access on the target repo (GitHub
    restricts traffic endpoints to repo maintainers).

    Useful for periodic monitoring (e.g. « tous les jours à 20h, log
    les clones dans un XLSX ») — the date returned is the most recent
    daily bucket so successive calls give the agent a per-day delta.

    Args:
        owner: GitHub owner. If empty, settings.github_default_repo.
        repo: Repository name. If empty, settings.github_default_repo.

    Returns: a multi-line summary. If the token lacks push access,
        returns 403 with a clear hint.
    """
    resolved = _resolve_repo(owner, repo)
    if not resolved:
        return (
            "Erreur : précise le repo sous la forme owner/repo, "
            "ou configure GITHUB_DEFAULT_REPO dans le `.env`."
        )
    owner, repo = resolved

    # Two independent endpoints — fetch both and aggregate.
    status_c, clones_data = await _gh_get(f"/repos/{owner}/{repo}/traffic/clones")
    if status_c == 401 or isinstance(clones_data, str):
        return clones_data if isinstance(clones_data, str) else _setup_hint()
    if status_c == 403:
        return (
            f"❌ Accès refusé sur les stats de trafic de `{owner}/{repo}` (HTTP 403). "
            "GitHub réserve ces données aux mainteneurs du repo — vérifie que "
            "ton token est issu d'un compte admin."
        )
    if status_c == 404:
        return f"❌ Repo `{owner}/{repo}` introuvable."
    if status_c >= 400 or not isinstance(clones_data, dict):
        return f"❌ Erreur GitHub {status_c} sur clones de `{owner}/{repo}`."

    status_v, views_data = await _gh_get(f"/repos/{owner}/{repo}/traffic/views")
    if status_v >= 400 or not isinstance(views_data, dict):
        # Clones succeeded but views failed — still useful, partial response.
        return (
            f"📈 `{owner}/{repo}` — trafic (14 jours)\n"
            f"📥 Clones       : {_fmt_int(clones_data.get('count'))} "
            f"({_fmt_int(clones_data.get('uniques'))} uniques)\n"
            f"⚠️ Vues : erreur HTTP {status_v} (clones OK, vues indisponibles)"
        )

    # Daily breakdown — most-recent day, useful for scheduled daily logging
    clones_today_n = clones_today_u = views_today_n = views_today_u = "—"
    today_str = ""
    daily_clones = clones_data.get("clones") or []
    daily_views = views_data.get("views") or []
    if daily_clones:
        last = daily_clones[-1]
        clones_today_n = _fmt_int(last.get("count"))
        clones_today_u = _fmt_int(last.get("uniques"))
        today_str = (last.get("timestamp") or "")[:10]
    if daily_views:
        lv = daily_views[-1]
        views_today_n = _fmt_int(lv.get("count"))
        views_today_u = _fmt_int(lv.get("uniques"))

    return (
        f"📈 `{owner}/{repo}` — trafic (14 jours glissants)\n"
        f"📥 Clones (total / uniques) : {_fmt_int(clones_data.get('count'))} / "
        f"{_fmt_int(clones_data.get('uniques'))}\n"
        f"👁️ Vues   (total / uniques) : {_fmt_int(views_data.get('count'))} / "
        f"{_fmt_int(views_data.get('uniques'))}\n"
        f"\n📅 Aujourd'hui ({today_str or 'dernier bucket'}) :\n"
        f"   📥 Clones : {clones_today_n} ({clones_today_u} uniques)\n"
        f"   👁️ Vues   : {views_today_n} ({views_today_u} uniques)"
    )


# ──────────────────────────────────────────────────────────────────────
# Tool 3 — Notifications (read-only, no mark-as-read)
# ──────────────────────────────────────────────────────────────────────


@tool
async def github_notifications(unread_only: bool = True, limit: int = 10) -> str:
    """List the user's GitHub notifications.

    Read-only. Does NOT mark notifications as read (that would be a
    destructive UX change requiring HITL — a future tool can do that).

    Args:
        unread_only: If True (default), only return unread notifications.
            Set False to also see recent read ones.
        limit: Max number of notifications to return (default 10, max 50).

    Returns: a numbered list with reason, repo, subject title and URL.
        Or a clear setup message if the token lacks `notifications` scope.
    """
    limit = max(1, min(int(limit or 10), 50))
    params: dict = {"per_page": limit, "all": "false" if unread_only else "true"}
    status, data = await _gh_get("/notifications", params=params)
    if status == 401 or isinstance(data, str):
        return data if isinstance(data, str) else _setup_hint()
    if status == 403:
        return (
            "❌ Le token GitHub n'a pas le scope `notifications`. "
            "Regénère le PAT sur https://github.com/settings/tokens "
            "en cochant la case `notifications`."
        )
    if status >= 400 or not isinstance(data, list):
        return f"❌ Erreur GitHub {status} sur /notifications."

    if not data:
        return "✅ Aucune notification non lue." if unread_only else "Aucune notification récente."

    lines = [f"🔔 {len(data)} notification(s){' non lue(s)' if unread_only else ''} :"]
    for i, n in enumerate(data, 1):
        repo_full = (n.get("repository") or {}).get("full_name", "?")
        subject = n.get("subject") or {}
        title = subject.get("title", "(sans titre)")
        reason = n.get("reason", "?")
        # Subject URL is a GitHub API URL; convert to human URL if possible.
        api_url = subject.get("url") or ""
        web_url = ""
        if api_url and "/repos/" in api_url:
            # /repos/{owner}/{repo}/{kind}/{n} → https://github.com/{owner}/{repo}/{kind}/{n}
            human = api_url.split("api.github.com")[-1]
            human = human.replace("/repos/", "/")
            # pulls in API → pull in URL
            human = human.replace("/pulls/", "/pull/")
            web_url = f"https://github.com{human}"
        lines.append(
            f"{i}. [{reason}] {repo_full} — {title}"
            + (f"\n   → {web_url}" if web_url else "")
        )
    return "\n".join(lines)
