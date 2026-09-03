# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/candidate_notify.py
# @brief      Notification push « une candidate t'attend » (C4-2) — pattern
#             ntfy inline des missions, best-effort, jamais bloquant.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.0.0
# @link       https://github.com/franckolv-dev/ElyAgent
# =============================================================================
"""Push ntfy quand l'apprentissage produit quelque chose à voir.

Constat C4 (carte 19/07) : AUCUNE notification n'existait quand une candidate
attendait validation — l'admin devait consulter les pages à la main. La boucle
« elle crée → te soumet → tu valides » exige que le « te soumet » sonne.

Deux usages :
  - ``notify_candidate`` : un outil candidate vient d'être généré → à VALIDER
    (la promotion reste humaine, arbitrage 19/07).
  - ``notify_playbook_activated`` : un playbook auto-promu par le cron
    skill_autocreate → information (l'auto-promotion des playbooks est
    conservée, mais elle ne doit plus être silencieuse).

Même pattern que mission_heartbeat : ``NTFY_URL`` en env, httpx 5 s,
best-effort — un échec de push ne casse jamais la génération.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


async def _push(title: str, body: str, *, tags: str, priority: str = "default") -> None:
    ntfy_url = os.environ.get("NTFY_URL")
    if not ntfy_url:
        return
    try:
        import httpx

        from app.services.ntfy_headers import ascii_header

        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(
                ntfy_url,
                headers={
                    # ascii_header : httpx encode les en-têtes en ASCII — un
                    # « — » a tué le tout premier push candidate (19/07).
                    "Title": ascii_header(title)[:120],
                    "Tags": tags,
                    "Priority": priority,
                },
                content=body[:500].encode("utf-8"),
            )
        logger.info("candidate_notify: push envoyé (%s)", title[:60])
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("candidate_notify: push échoué: %s", exc)


async def notify_candidate(tool_name: str, capability: str) -> None:
    """Un outil candidate attend validation dans « Compétences à valider »."""
    await _push(
        f"Ely — outil candidat à valider : {tool_name}",
        f"Généré depuis la capacité manquante « {capability[:200]} ». "
        "À revoir puis promouvoir dans Compétences à valider.",
        tags="hammer_and_wrench",
        priority="high",
    )


async def notify_playbook_activated(count: int) -> None:
    """Information : le cron a auto-promu des playbooks (texte, faible risque)."""
    if count <= 0:
        return
    await _push(
        f"Ely — {count} playbook(s) auto-activé(s)",
        "Le cron d'auto-apprentissage a promu des playbooks depuis des échecs "
        "récurrents. Consultables dans Compétences apprises.",
        tags="books",
    )
