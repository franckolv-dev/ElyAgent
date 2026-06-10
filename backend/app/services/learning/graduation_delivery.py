# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/graduation_delivery.py
# @brief      Sprint 4d (V4) J5 — livraison d'une graduation : branche +
#             commits + pull request via l'API GitHub, ou export local.
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
"""Livraison d'une graduation — design note Sprint 4d §4.3 (canal arbitré :
PR via API GitHub depuis le backend, 2026-06-10).

Le backend tourne en Docker SANS checkout git : la « PR ouverte par Ely »
passe par l'API REST GitHub (contents + pulls), authentifiée par un token
fine-grained stocké CHIFFRÉ dans system_config (clé
``github_graduation_token``, posée via l'admin ; jamais en env clair).
Périmètre minimal requis du token : Contents read/write + Pull requests
read/write sur le seul repo cible.

Fallback dégradé SANS token : export des fichiers dans
``GRADUATION_EXPORT_DIR`` (défaut /app/data/graduation_exports, persisté
par le volume) + instructions — la graduation reste possible à la main.

Après livraison : la row learned_skills reste ``active`` (le binding
dynamique continue de servir l'outil) ; c'est la garde de chargement (J4)
qui basculera en ``graduated`` quand la PR mergée + l'image rebuildée
feront apparaître le tool core homonyme. Aucun état intermédiaire à gérer.
La PR est tracée dans ``frontmatter_json.graduation``.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TOKEN_CONFIG_KEY = "github_graduation_token"
_API = "https://api.github.com"


def _repo() -> str:
    return os.environ.get("GRADUATION_GITHUB_REPO", "franckolv-dev/ElyAgent")


def _base_branch() -> str:
    return os.environ.get("GRADUATION_BASE_BRANCH", "main")


def _export_dir() -> str:
    return os.environ.get("GRADUATION_EXPORT_DIR", "/app/data/graduation_exports")


async def _token() -> str:
    """Token fine-grained depuis system_config (chiffré, B-11). Vide = pas
    de canal PR → fallback export."""
    try:
        from app.services.system_config import get_config
        return (await get_config(TOKEN_CONFIG_KEY, "")).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("graduation_delivery: token lookup failed: %s", exc)
        return ""


def _branch_name(tool_name: str, skill_id: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]", "-", tool_name.lower()).strip("-") or "tool"
    return f"graduate/{slug}-{skill_id[:8]}"


def _pr_body(manifest: dict[str, Any]) -> str:
    """Corps de PR = le manifest des preuves, lisible par un humain —
    c'est la pièce que Franck review avant merge."""
    gates_rows = "\n".join(
        f"| {'✅' if g['ok'] else '❌'} | `{g['key']}` | {g['value']} |"
        for g in manifest.get("gates", [])
    )
    stats = manifest.get("stats", {})
    return (
        f"## 🎓 Graduation : `{manifest['tool_name']}`\n\n"
        "Outil généré par Ely (auto-developing agent), **éprouvé à l'usage** "
        "et converti en code core par le pipeline de graduation (Sprint 4d V4). "
        "Le content livré est strictement la version qui a tourné — la "
        "provenance complète est dans l'en-tête du fichier.\n\n"
        f"- **Skill d'origine** : `{manifest['learned_skill_id']}` "
        f"(user `{manifest['origin_user']}…`, créé le {manifest.get('created_at', '?')})\n"
        f"- **Invocations** : {stats.get('invocations', '?')} — "
        f"erreurs récentes : {stats.get('errors_recent', '?')} — "
        f"refus HITL récents : {stats.get('refusals_recent', '?')} — "
        f"âge : {stats.get('age_days', '?')} j\n"
        f"- **Profil** : {manifest.get('tool_profile', 'pure')}\n\n"
        "### Gates au moment de la graduation\n\n"
        f"| | gate | valeur |\n|---|---|---|\n{gates_rows}\n\n"
        "Le test pytest livré dans cette PR exécute l'outil en CI avant "
        "tout merge. Après merge + rebuild, la garde de chargement bascule "
        "automatiquement la row d'origine en `graduated` (jamais deux "
        "outils homonymes bindés).\n\n"
        "🤖 PR ouverte par Ely — revue et merge humains requis.\n"
    )


# ─────────────────────────────────────────────────────────────────────────
# Canal GitHub
# ─────────────────────────────────────────────────────────────────────────


class GitHubDeliveryError(RuntimeError):
    """Échec de livraison côté API GitHub — message exploitable par l'admin."""


async def _deliver_via_github(
    *,
    token: str,
    manifest: dict[str, Any],
    files: list[dict[str, Any]],
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Branche + un commit par fichier (contents API) + pull request.

    ``transport`` est injectable pour les tests (httpx.MockTransport).
    Lève :class:`GitHubDeliveryError` avec le contexte exact en cas d'échec
    — jamais de PR à moitié silencieuse.
    """
    repo = _repo()
    base = _base_branch()
    branch = _branch_name(manifest["tool_name"], manifest["learned_skill_id"])
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(
        base_url=_API, headers=headers, timeout=30.0, transport=transport,
    ) as client:
        async def _call(method: str, url: str, *, ok: tuple[int, ...], **kw) -> httpx.Response:
            resp = await client.request(method, url, **kw)
            if resp.status_code not in ok:
                raise GitHubDeliveryError(
                    f"GitHub {method} {url} → {resp.status_code}: "
                    f"{resp.text[:300]}"
                )
            return resp

        # 1. sha de la base
        ref = await _call("GET", f"/repos/{repo}/git/ref/heads/{base}", ok=(200,))
        base_sha = ref.json()["object"]["sha"]

        # 2. branche de graduation (422 = existe déjà → on la réutilise :
        #    une re-livraison après échec partiel doit être possible)
        create_ref = await client.post(
            f"/repos/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        if create_ref.status_code not in (201, 422):
            raise GitHubDeliveryError(
                f"GitHub create branch → {create_ref.status_code}: "
                f"{create_ref.text[:300]}"
            )

        # 3. un commit par fichier (contents API — simple et idempotent)
        for f in files:
            path = f["path"]
            existing = await client.get(
                f"/repos/{repo}/contents/{path}", params={"ref": branch},
            )
            if existing.status_code == 200 and f.get("create_only"):
                continue  # __init__.py déjà présent : jamais écrasé
            payload: dict[str, Any] = {
                "message": f"feat(graduation): {manifest['tool_name']} — {os.path.basename(path)}",
                "content": base64.b64encode(f["content"].encode("utf-8")).decode("ascii"),
                "branch": branch,
            }
            if existing.status_code == 200:
                payload["sha"] = existing.json().get("sha")
            await _call("PUT", f"/repos/{repo}/contents/{path}", ok=(200, 201), json=payload)

        # 4. la pull request
        pr = await client.post(
            f"/repos/{repo}/pulls",
            json={
                "title": f"feat(graduation): {manifest['tool_name']} — learned tool → core (par Ely)",
                "head": branch,
                "base": base,
                "body": _pr_body(manifest),
            },
        )
        if pr.status_code == 422 and "already exists" in pr.text:
            # PR déjà ouverte pour cette branche (re-livraison) — la retrouver
            listing = await _call(
                "GET", f"/repos/{repo}/pulls",
                ok=(200,),
                params={"head": f"{repo.split('/')[0]}:{branch}", "state": "open"},
            )
            items = listing.json()
            if items:
                return {"status": "pr_created", "pr_url": items[0]["html_url"],
                        "branch": branch, "reused": True}
        if pr.status_code != 201:
            raise GitHubDeliveryError(
                f"GitHub create PR → {pr.status_code}: {pr.text[:300]}"
            )
        return {"status": "pr_created", "pr_url": pr.json()["html_url"],
                "branch": branch, "reused": False}


# ─────────────────────────────────────────────────────────────────────────
# Fallback export local
# ─────────────────────────────────────────────────────────────────────────


def _deliver_via_export(manifest: dict[str, Any], files: list[dict[str, Any]]) -> dict[str, Any]:
    """Sans token : matérialise les fichiers sous GRADUATION_EXPORT_DIR
    (volume persistant) avec le manifest et les instructions de PR
    manuelle. Les chemins relatifs au repo sont recréés tels quels."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    root = os.path.join(_export_dir(), f"{manifest['tool_name']}-{stamp}")
    for f in files:
        target = os.path.join(root, f["path"])
        os.makedirs(os.path.dirname(target), exist_ok=True)
        # create_only : on matérialise quand même (l'arbre exporté est
        # autonome) — c'est au moment du commit manuel que l'existant gagne.
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(f["content"])
    with open(os.path.join(root, "grad_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(root, "INSTRUCTIONS.md"), "w", encoding="utf-8") as fh:
        fh.write(
            "# Graduation export — livraison manuelle\n\n"
            "Aucun token GitHub configuré (system_config "
            f"`{TOKEN_CONFIG_KEY}`). Copier les fichiers ci-dessous dans le "
            "repo, ouvrir une branche + PR, coller grad_manifest.json dans "
            "le corps :\n\n"
            + "\n".join(f"- `{f['path']}`" for f in files)
            + "\n"
        )
    logger.info("graduation_delivery: exported %s to %s", manifest["tool_name"], root)
    return {"status": "exported", "export_path": root, "branch": None, "pr_url": None}


# ─────────────────────────────────────────────────────────────────────────
# Point d'entrée
# ─────────────────────────────────────────────────────────────────────────


async def deliver_graduation(
    *,
    manifest: dict[str, Any],
    files: list[dict[str, Any]],
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Livre une graduation prête : PR GitHub si un token est configuré,
    export local sinon. Le résultat dit toujours par quel canal."""
    token = await _token()
    if token:
        return await _deliver_via_github(
            token=token, manifest=manifest, files=files, transport=transport,
        )
    return _deliver_via_export(manifest, files)
