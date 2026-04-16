# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/image_tool.py
# @brief      Outil de génération d'image via Gemini Imagen 3
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""
Outil de génération d'image via Gemini Imagen 3.

Retourne un bloc JSON spécial que le frontend interprète pour afficher l'image
directement dans la bulle de chat :
  {"type": "image", "data": "<base64>", "mime": "image/png", "prompt": "..."}
"""

import base64
import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def generate_image(prompt: str) -> str:
    """Génère une image à partir d'une description textuelle en utilisant Gemini Imagen.
    Utilise cet outil quand l'utilisateur demande de créer, dessiner ou générer une image.
    Retourne l'image encodée en base64 pour affichage dans le chat.

    Args:
        prompt: Description détaillée de l'image à générer (en français ou en anglais)
    """
    try:
        from app.config import get_settings
        settings = get_settings()

        if not settings.gemini_api_key:
            return "Je n'ai pas de clé API Gemini configurée. Tu peux l'ajouter dans les paramètres."

        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key)

        imagen = genai.ImageGenerationModel("imagen-3.0-generate-001")
        result = imagen.generate_images(
            prompt=prompt,
            number_of_images=1,
            safety_filter_level="block_only_high",
            person_generation="allow_adult",
            aspect_ratio="1:1",
        )

        if not result.images:
            return "Je n'ai pas pu générer cette image. Essaie avec une description différente."

        image_bytes = result.images[0]._pil_image.tobytes()
        # Convertir via PIL en PNG
        from io import BytesIO
        from PIL import Image as PILImage
        pil_img = result.images[0]._pil_image
        buf = BytesIO()
        pil_img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        # Retourne un bloc JSON spécial interprété par le frontend
        return json.dumps({
            "type": "image",
            "data": b64,
            "mime": "image/png",
            "prompt": prompt,
        })

    except Exception as e:
        logger.error(f"generate_image error: {e}")
        return f"Je n'ai pas pu générer cette image : {str(e)}"
