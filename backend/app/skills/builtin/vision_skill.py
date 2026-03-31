# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
"""Vision skill — analyser des images avec Gemini multimodal.

vision_analyze_image    Analyse une image locale ou URL et répond à une question
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from langchain_core.tools import tool

from app.skills.base import Skill
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)

# Répertoires autorisés pour les fichiers locaux (contre LFI)
_ALLOWED_ROOTS = ("/app/uploads", "/tmp")

_MIME_MAP: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}


def _safe_read(path: str) -> tuple[bytes, str]:
    """Lit un fichier image local après vérification du chemin (anti-LFI)."""
    p = Path(path).resolve()
    if not any(str(p).startswith(root) for root in _ALLOWED_ROOTS):
        raise ValueError(
            f"Chemin non autorisé : {path}. "
            f"Seuls les chemins dans {_ALLOWED_ROOTS} sont acceptés."
        )
    if not p.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    mime = _MIME_MAP.get(p.suffix.lower().lstrip("."), "image/jpeg")
    return p.read_bytes(), mime


@tool
async def vision_analyze_image(
    image_path: str,
    question: str = "Décris en détail ce que tu vois sur cette image.",
) -> str:
    """Analyser une image (capture d'écran, photo, document) avec Gemini Vision.

    Utilise cet outil quand :
    - Le message contient un chemin vers une capture d'écran (📸 Capture d'écran partagée →)
    - L'utilisateur a joint une image et veut qu'Ély la décrive ou l'analyse
    - L'utilisateur demande : 'regarde mon écran', 'qu'est-ce que tu vois',
      'analyse cette image', 'que dit ce document visuel'

    Args:
        image_path: Chemin local (/app/uploads/…) ou URL https:// de l'image
        question:   Question précise sur l'image (par défaut : description générale)
    """
    try:
        from app.config import get_settings
        settings = get_settings()

        if not settings.gemini_api_key:
            return (
                "Je n'ai pas de clé API Gemini configurée — la vision nécessite Gemini. "
                "Tu peux ajouter la clé dans Paramètres → Clés API."
            )

        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel("gemini-1.5-flash-latest")

        if image_path.startswith(("http://", "https://")):
            # Image distante — on la télécharge nous-mêmes pour rester dans les limites d'upload
            import httpx
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(image_path)
                resp.raise_for_status()
                mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
                if not mime.startswith("image/"):
                    return f"L'URL ne pointe pas vers une image valide (MIME : {mime})."
                data = resp.content
        else:
            data, mime = await asyncio.to_thread(_safe_read, image_path)

        img_part = {"mime_type": mime, "data": data}

        response = await asyncio.to_thread(
            model.generate_content,
            [img_part, question],
        )

        return response.text.strip() if response.text else "Je n'ai pas pu analyser cette image."

    except Exception as exc:
        logger.error("vision_analyze_image error: %s", exc)
        return f"Je n'ai pas pu analyser l'image : {exc}"


get_skill_registry().register(Skill(
    name="vision",
    display_name="Vision IA",
    description=(
        "Analyse des images avec Gemini Vision : captures d'écran partagées, photos jointes, "
        "documents visuels. Ély peut décrire, lire du texte ou répondre à des questions "
        "sur n'importe quelle image."
    ),
    icon="👁️",
    scopes=["local"],
    tools=[vision_analyze_image],
))
