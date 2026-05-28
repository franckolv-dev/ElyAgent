# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/image_skill.py
# @brief      Image generation skill — via Gemini Imagen 3
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
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Image generation skill — via Gemini Imagen 3.

Nécessite une clé API Gemini configurée (GEMINI_API_KEY dans .env ou Admin UI).
Retourne un bloc JSON spécial interprété par le frontend pour afficher l'image
directement dans la bulle de chat :
  {"type":"image","data":"<base64>","mime":"image/png","prompt":"..."}
"""
from __future__ import annotations

import base64
import json
import logging
from io import BytesIO

from langchain_core.tools import tool

from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)


@tool
async def generate_image(prompt: str) -> str:
    """Génère une image à partir d'une description textuelle via Gemini Imagen 3.
    Utilise cet outil quand l'utilisateur demande de créer, dessiner ou générer une image.

    Args:
        prompt: Description détaillée de l'image à générer (français ou anglais)
    """
    try:
        from app.config import get_settings
        settings = get_settings()

        if not settings.gemini_api_key:
            return (
                "Je n'ai pas encore de clé API Gemini configurée. "
                "Tu peux l'ajouter dans Paramètres → Clés API."
            )

        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key)

        imagen = genai.ImageGenerationModel("imagen-3.0-generate-001")

        import asyncio
        result = await asyncio.to_thread(
            imagen.generate_images,
            prompt=prompt,
            number_of_images=1,
            safety_filter_level="block_only_high",
            person_generation="allow_adult",
            aspect_ratio="1:1",
        )

        if not result.images:
            return "Je n'ai pas pu générer cette image. Essaie avec une description différente."

        pil_img = result.images[0]._pil_image
        buf = BytesIO()
        pil_img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return json.dumps({
            "type": "image",
            "data": b64,
            "mime": "image/png",
            "prompt": prompt,
        })

    except Exception as exc:
        logger.error("generate_image error: %s", exc)
        return f"Je n'ai pas pu générer cette image : {exc}"


get_skill_registry().register(Skill(
    name="image-generation",
    display_name="Génération d'images",
    description="Génère des images à partir d'une description textuelle via Gemini Imagen 3",
    icon="🎨",
    scopes=["internet"],
    domains=[Domain.CREATIVE],
    tools=[generate_image],
))
