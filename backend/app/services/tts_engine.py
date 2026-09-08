# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/tts_engine.py
# @brief      D'où vient la voix d'Ely : le service local XTTS (voix clonée)
#             ou edge-tts, avec repli de l'un vers l'autre.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Deux fournisseurs, un seul point d'entrée (08/09/2026).

- ``xtts`` : le service local ``voice/xtts`` (XTTS-v2, voix clonée). Le texte
  lu ne quitte pas la machine. Réglages : ``TTS_PROVIDER=xtts``, ``XTTS_URL``,
  ``XTTS_VOICE``.
- ``edge`` : edge-tts, les voix Microsoft — l'historique, et le REPLI quand le
  service local ne répond pas. Une voix qui se tait n'est jamais un progrès :
  on préfère la voix synthétique au silence, et on le dit dans le journal.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def _synthetiser_edge(texte: str, voix: str, debit: str) -> tuple[bytes, str]:
    import edge_tts

    communicate = edge_tts.Communicate(texte, voix, rate=debit)
    tampon = io.BytesIO()
    async for morceau in communicate.stream():
        if morceau["type"] == "audio":
            tampon.write(morceau["data"])
    return tampon.getvalue(), "audio/mpeg"


async def _synthetiser_xtts(texte: str, voix: Optional[str], client: httpx.AsyncClient) -> tuple[bytes, str]:
    s = get_settings()
    corps: dict = {"text": texte, "language": "fr"}
    if voix:
        corps["voice"] = voix
    reponse = await client.post(
        f"{s.xtts_url.rstrip('/')}/speak", json=corps, timeout=s.xtts_timeout_s,
    )
    reponse.raise_for_status()
    return reponse.content, reponse.headers.get("content-type", "audio/wav").split(";")[0]


async def synthetiser(
    texte: str,
    voix: Optional[str] = None,
    debit: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[bytes, str]:
    """L'audio de ``texte`` et son type MIME, par le fournisseur configuré.

    ``voix`` et ``debit`` sont ceux d'edge-tts (nom de voix Microsoft, « +10% »).
    Pour XTTS, la voix vient de ``XTTS_VOICE`` — ou du défaut du service.
    """
    s = get_settings()
    voix_edge = voix or s.tts_voice
    debit_edge = debit or s.tts_rate
    if (s.tts_provider or "edge").lower() != "xtts":
        return await _synthetiser_edge(texte, voix_edge, debit_edge)

    proprietaire = client is None
    client = client or httpx.AsyncClient()
    try:
        return await _synthetiser_xtts(texte, s.xtts_voice or None, client)
    except Exception as exc:  # noqa: BLE001 — le repli est le contrat
        logger.warning("voix locale XTTS indisponible (%s) — repli sur edge-tts", exc)
        return await _synthetiser_edge(texte, voix_edge, debit_edge)
    finally:
        if proprietaire:
            await client.aclose()


async def etat(client: Optional[httpx.AsyncClient] = None) -> dict:
    """Le fournisseur en vigueur, et ce que le service local dit de lui."""
    s = get_settings()
    resultat: dict = {
        "provider": (s.tts_provider or "edge").lower(),
        "voice": s.xtts_voice if (s.tts_provider or "").lower() == "xtts" else s.tts_voice,
        "xtts": {"reachable": False, "voices": [], "default_voice": "", "device": ""},
    }
    proprietaire = client is None
    client = client or httpx.AsyncClient()
    try:
        r = await client.get(f"{s.xtts_url.rstrip('/')}/health", timeout=3)
        r.raise_for_status()
        sante = r.json()
        resultat["xtts"] = {
            "reachable": bool(sante.get("ok")),
            "voices": list(sante.get("voices") or []),
            "default_voice": str(sante.get("default_voice") or ""),
            "device": str(sante.get("device") or ""),
        }
    except Exception as exc:  # noqa: BLE001 — un état, pas une panne
        logger.debug("service XTTS injoignable : %s", exc)
    finally:
        if proprietaire:
            await client.aclose()
    return resultat


__all__ = ["etat", "synthetiser"]
