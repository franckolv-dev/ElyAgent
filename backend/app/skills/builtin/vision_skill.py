# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/vision_skill.py
# @brief      Vision skill — analyser des images et des PDF avec Gemini multimodal
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
"""Vision skill — analyser des images et des PDF avec Gemini multimodal.

vision_analyze_image        Analyse une image locale ou URL et répond à une question
pdf_analyze_with_vision     Analyse un PDF avec Gemini Vision (layout, tableaux, catalogues)
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
        model = genai.GenerativeModel("gemini-2.5-flash")

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


@tool
async def pdf_analyze_with_vision(
    pdf_path: str,
    question: str = "Décris le contenu structuré de ce document.",
) -> str:
    """Analyser un PDF avec Gemini Vision — PRÉFÉRER cet outil pour les catalogues, factures et documents structurés.

    Utilise cet outil PLUTÔT QUE pdf_read quand :
    - Le fichier est un catalogue produit, une facture, un bon de commande, un tarif
    - La mise en page est complexe : tableaux, colonnes multiples, images avec texte
    - L'utilisateur demande d'extraire des données structurées (références, prix, libellés)
    - Le message contient "📎 Fichiers joints" avec un fichier .pdf
    - pdf_read retourne un texte confus, vide ou mal formaté

    Gemini comprend la mise en page visuelle du PDF, pas seulement le texte brut.

    Args:
        pdf_path: Chemin local du PDF (ex: /app/uploads/user_id/fichier.pdf)
        question: Question précise sur le contenu (ex: "Liste tous les produits avec référence et prix")
    """
    try:
        from app.config import get_settings
        settings = get_settings()

        if not settings.gemini_api_key:
            return (
                "Je n'ai pas de clé API Gemini configurée — la vision PDF nécessite Gemini. "
                "Tu peux ajouter la clé dans Paramètres → Clés API."
            )

        # Vérification du chemin (anti-LFI)
        p = Path(pdf_path).resolve()
        if not any(str(p).startswith(root) for root in _ALLOWED_ROOTS):
            return f"Chemin non autorisé : {pdf_path}. Seuls les chemins dans {_ALLOWED_ROOTS} sont acceptés."
        if not p.exists():
            return f"Fichier introuvable : {pdf_path}"
        if p.suffix.lower() != ".pdf":
            return f"Ce fichier n'est pas un PDF : {pdf_path}"

        pdf_bytes = await asyncio.to_thread(p.read_bytes)

        # Envoi direct à Gemini via langchain_google_genai (supporte application/pdf nativement)
        import base64
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=settings.gemini_api_key,
            max_output_tokens=8192,
            temperature=0.2,
        )

        message = HumanMessage(content=[
            {
                "type": "media",
                "mime_type": "application/pdf",
                "data": base64.b64encode(pdf_bytes).decode(),
            },
            {
                "type": "text",
                "text": question,
            },
        ])

        response = await llm.ainvoke([message])
        text = response.content if isinstance(response.content, str) else str(response.content)
        return text.strip() if text else "Je n'ai pas pu analyser ce PDF."

    except Exception as exc:
        logger.error("pdf_analyze_with_vision error: %s", exc)
        return f"Erreur lors de l'analyse du PDF : {exc}"


get_skill_registry().register(Skill(
    name="vision",
    display_name="Vision IA",
    description=(
        "Analyse des images et des PDF avec Gemini Vision : captures d'écran partagées, photos jointes, "
        "documents visuels, catalogues produits, factures. Ély peut décrire, lire du texte, "
        "extraire des données structurées ou répondre à des questions sur n'importe quelle image ou PDF."
    ),
    icon="👁️",
    scopes=["local"],
    tools=[vision_analyze_image, pdf_analyze_with_vision],
))
