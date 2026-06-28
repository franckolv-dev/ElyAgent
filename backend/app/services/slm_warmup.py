# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/slm_warmup.py
# @brief      SLM warm-up — send a minimal request at startup to load the model into RAM
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""SLM warm-up — send a minimal request at startup to load the model into RAM.

Without this, the first real user request triggers a 3-5s model load.
With OLLAMA_KEEP_ALIVE=-1 the model stays loaded until Ollama is restarted.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def warmup_slm() -> None:
    """Send a minimal prompt to Ollama so the model is resident in RAM
    before the first real user message.  Retries up to 5 times with
    exponential back-off to survive race conditions at container startup.
    Silently skipped if SLM is disabled or Ollama stays unreachable.
    """
    from app.config import get_settings
    settings = get_settings()

    if not settings.slm_enabled:
        return

    import httpx

    for attempt in range(1, 6):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(
                    f"{settings.ollama_base_url}/api/generate",
                    json={"model": settings.slm_model, "prompt": "hi", "stream": False},
                )
            if resp.status_code == 200:
                logger.info(
                    "SLM warm-up complete (attempt %d): model=%s loaded into RAM",
                    attempt, settings.slm_model,
                )
                return
            logger.warning("SLM warm-up HTTP %d (attempt %d)", resp.status_code, attempt)
        except Exception as exc:
            logger.warning("SLM warm-up attempt %d failed: %s", attempt, exc)

        await asyncio.sleep(2 ** attempt)   # 2, 4, 8, 16, 32s

    logger.warning("SLM warm-up gave up after 5 attempts — first request will have cold-start")
