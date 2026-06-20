# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_results.py
# @brief      Normalisation des résultats MCP (CallToolResult) — bornée, sûre.
# @license    Elastic License 2.0
# =============================================================================
"""Normalisation des ``CallToolResult`` MCP avant restitution au modèle.

Invariants (cadrage §8.8) :

* **Tous** les blocs de contenu sont traités : texte, structuré, image, audio,
  resource link, embedded resource.
* Les binaires (image/audio/blob) sont stockés **hors contexte** dans
  ``/tmp/ely-attachments`` ; le modèle ne reçoit qu'une référence + le MIME.
* ``_meta`` n'est **jamais** transmis au modèle.
* La taille totale est **bornée** (troncature explicite).
* ``isError`` est signalé, sans retry aveugle.
* Le contenu d'un serveur est une donnée **non fiable** : on l'étiquette.

Le module n'importe rien de lourd ; ``mcp`` n'est pas requis (on lit les blocs
par attributs / discriminant ``.type``), ce qui rend la fonction testable avec
de simples objets factices.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import uuid

logger = logging.getLogger(__name__)

# Caps (cadrage Q5) : 256 Ko de texte/JSON au modèle, 1 Mo dur tous blocs.
DEFAULT_MAX_TEXT_BYTES = 256 * 1024
HARD_MAX_BYTES = 1024 * 1024
ATTACHMENT_DIR = "/tmp/ely-attachments"

# MIME → extension pour les pièces binaires sauvegardées.
_MIME_EXT = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
    "image/webp": ".webp", "audio/mpeg": ".mp3", "audio/wav": ".wav",
    "audio/ogg": ".ogg", "application/pdf": ".pdf",
}


def _save_binary(data_b64: str, mime: str | None) -> str | None:
    """Décode et stocke un binaire hors-contexte. Renvoie le chemin ou None."""
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except Exception:
        return None
    if len(raw) > HARD_MAX_BYTES:
        logger.warning("MCP binary > %d bytes — dropped", HARD_MAX_BYTES)
        return None
    os.makedirs(ATTACHMENT_DIR, exist_ok=True)
    ext = _MIME_EXT.get((mime or "").lower(), ".bin")
    path = os.path.join(ATTACHMENT_DIR, f"mcp_{uuid.uuid4().hex}{ext}")
    try:
        with open(path, "wb") as fh:
            fh.write(raw)
    except OSError as exc:  # pragma: no cover — disque
        logger.warning("MCP binary save failed: %s", exc)
        return None
    return path


def _block_type(block) -> str:
    return getattr(block, "type", "") or ""


def _normalize_block(block) -> str:
    """Un bloc de contenu MCP → texte (ou référence pour un binaire)."""
    btype = _block_type(block)

    if btype == "text" or hasattr(block, "text") and not hasattr(block, "resource"):
        return getattr(block, "text", "") or ""

    if btype == "image":
        path = _save_binary(getattr(block, "data", ""), getattr(block, "mimeType", None))
        mime = getattr(block, "mimeType", "image")
        return f"[image MCP enregistrée : {path} | {mime}]" if path else "[image MCP illisible]"

    if btype == "audio":
        path = _save_binary(getattr(block, "data", ""), getattr(block, "mimeType", None))
        mime = getattr(block, "mimeType", "audio")
        return f"[audio MCP enregistré : {path} | {mime}]" if path else "[audio MCP illisible]"

    if btype == "resource_link":
        uri = getattr(block, "uri", "")
        name = getattr(block, "name", "")
        return f"[lien ressource MCP : {name or uri} <{uri}>]"

    if btype == "resource":
        # EmbeddedResource : .resource porte .text (texte) ou .blob (binaire).
        res = getattr(block, "resource", None)
        uri = getattr(res, "uri", "")
        mime = getattr(res, "mimeType", None)
        text = getattr(res, "text", None)
        if text is not None:
            return f"[ressource MCP {uri} (contenu non vérifié)]\n{text}"
        blob = getattr(res, "blob", None)
        if blob is not None:
            path = _save_binary(blob, mime)
            return f"[ressource binaire MCP enregistrée : {path} | {mime}]" if path else "[ressource MCP illisible]"
        return f"[ressource MCP {uri}]"

    # Type inconnu : on ne devine pas, on signale.
    return f"[bloc MCP de type {btype!r} non rendu]"


def normalize_call_result(
    result,
    *,
    local_name: str = "mcp",
    max_text_bytes: int = DEFAULT_MAX_TEXT_BYTES,
) -> str:
    """``CallToolResult`` → texte borné, sûr, à passer au modèle.

    Ne lève jamais : un résultat MCP malformé devient un message d'erreur
    stable plutôt qu'une exception."""
    parts: list[str] = []

    # 1. Blocs de contenu.
    content = getattr(result, "content", None) or []
    for block in content:
        try:
            parts.append(_normalize_block(block))
        except Exception as exc:  # pragma: no cover — défensif
            parts.append(f"[bloc MCP illisible : {exc}]")

    # 2. structuredContent (sérialisé, borné). Validé vs outputSchema en amont.
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        try:
            parts.append("[structuredContent]\n" + json.dumps(structured, ensure_ascii=False)[:max_text_bytes])
        except (TypeError, ValueError):
            parts.append("[structuredContent non sérialisable]")

    text = "\n".join(p for p in parts if p)

    # 3. isError : on préfixe, sans retry aveugle (cadrage §8.8).
    if getattr(result, "isError", False):
        text = f"⚠️ L'outil MCP `{local_name}` a renvoyé une erreur :\n{text}"

    # 4. Cap de taille (troncature explicite).
    encoded = text.encode("utf-8")
    if len(encoded) > max_text_bytes:
        text = encoded[:max_text_bytes].decode("utf-8", errors="ignore")
        text += f"\n…[tronqué — résultat MCP > {max_text_bytes} octets]"

    # 5. _meta n'est JAMAIS inclus (on ne l'a tout simplement pas lu).
    return text or "(résultat MCP vide)"
