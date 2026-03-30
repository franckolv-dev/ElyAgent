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
"""ELY Trainer skill — interactive desktop demonstration mode.

ELY prend le contrôle du poste de travail de l'utilisateur pour lui montrer
comment réaliser une action pas à pas, en capturant l'écran, en analysant
la situation et en effectuant les actions nécessaires (clics, saisies,
raccourcis) tout en narrant chaque étape.

Requires:
  - ELY Desktop daemon connected (for screen capture + input control)
  - A vision-capable LLM (Gemini 2.0 Flash or Claude with vision)

Daemon commands used (added in input.go):
  screenshot, mouse_click, mouse_move, type_text, hotkey, get_screen_size

Usage:
  "Montre-moi comment faire un filtre dans Excel"
  "Explique-moi comment créer un dossier sur le bureau"
  "Démontre comment copier-coller du texte"
"""
from __future__ import annotations

import base64
import logging
from typing import Annotated

from langchain_core.tools import tool

from app.skills.base import Skill
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)

# Maximum number of steps in a single training session to prevent infinite loops
MAX_TRAINER_STEPS = 20


# ---------------------------------------------------------------------------
# Low-level daemon bridge tools (used internally by the trainer agent)
# ---------------------------------------------------------------------------

@tool
async def trainer_screenshot(
    user_id: Annotated[str, "ID de l'utilisateur"] = "",
    delay_ms: Annotated[int, "Délai avant capture en ms (0-2000)"] = 300,
) -> dict:
    """Capture l'écran de l'utilisateur et retourne l'image en base64.
    Utilisé par ELY pour analyser l'état courant du poste de travail."""
    from app.services import desktop_registry
    if not desktop_registry.is_connected(user_id):
        return {"error": "ELY Desktop non connecté. Lancez le daemon depuis Paramètres > ELY Desktop."}
    try:
        result = await desktop_registry.send_command(
            user_id, "screenshot", {"delay_ms": delay_ms}, timeout=15.0
        )
        return result  # {"image_b64": "...", "media_type": "image/png", "size_bytes": N}
    except Exception as e:
        return {"error": str(e)}


@tool
async def trainer_click(
    x: Annotated[int, "Coordonnée X du clic (pixels depuis le coin supérieur gauche)"],
    y: Annotated[int, "Coordonnée Y du clic (pixels depuis le coin supérieur gauche)"],
    button: Annotated[str, "Bouton : 'left' (défaut), 'right', 'middle'"] = "left",
    double: Annotated[bool, "True pour un double-clic"] = False,
    user_id: Annotated[str, "ID de l'utilisateur"] = "",
) -> str:
    """Clique à une position précise sur l'écran de l'utilisateur.
    Utilisé pour démontrer comment cliquer sur un bouton, un menu, une cellule, etc."""
    from app.services import desktop_registry
    if not desktop_registry.is_connected(user_id):
        return "ELY Desktop non connecté."
    try:
        await desktop_registry.send_command(
            user_id, "mouse_click", {"x": x, "y": y, "button": button, "double": double}
        )
        action = "Double-clic" if double else "Clic"
        return f"{action} {button} effectué en ({x}, {y})"
    except Exception as e:
        return f"Erreur clic : {e}"


@tool
async def trainer_move(
    x: Annotated[int, "Coordonnée X cible"],
    y: Annotated[int, "Coordonnée Y cible"],
    user_id: Annotated[str, "ID de l'utilisateur"] = "",
) -> str:
    """Déplace le curseur vers une position pour attirer l'attention de l'utilisateur."""
    from app.services import desktop_registry
    if not desktop_registry.is_connected(user_id):
        return "ELY Desktop non connecté."
    try:
        await desktop_registry.send_command(user_id, "mouse_move", {"x": x, "y": y})
        return f"Curseur déplacé en ({x}, {y})"
    except Exception as e:
        return f"Erreur déplacement : {e}"


@tool
async def trainer_type(
    text: Annotated[str, "Texte à saisir au clavier"],
    user_id: Annotated[str, "ID de l'utilisateur"] = "",
) -> str:
    """Saisit du texte au clavier sur le poste de l'utilisateur.
    Utilisé pour montrer comment taper dans une cellule, un champ de recherche, etc."""
    from app.services import desktop_registry
    if not desktop_registry.is_connected(user_id):
        return "ELY Desktop non connecté."
    try:
        await desktop_registry.send_command(user_id, "type_text", {"text": text})
        return f"Texte saisi : {text!r}"
    except Exception as e:
        return f"Erreur saisie : {e}"


@tool
async def trainer_hotkey(
    keys: Annotated[str, "Raccourci clavier, ex: 'ctrl+c', 'ctrl+shift+l', 'alt+f4'"],
    user_id: Annotated[str, "ID de l'utilisateur"] = "",
) -> str:
    """Exécute un raccourci clavier sur le poste de l'utilisateur.
    Utilisé pour démontrer les raccourcis : Ctrl+C, Ctrl+Z, Alt+Tab, etc."""
    from app.services import desktop_registry
    if not desktop_registry.is_connected(user_id):
        return "ELY Desktop non connecté."
    try:
        await desktop_registry.send_command(user_id, "hotkey", {"keys": keys})
        return f"Raccourci exécuté : {keys}"
    except Exception as e:
        return f"Erreur raccourci : {e}"


@tool
async def trainer_get_screen_size(
    user_id: Annotated[str, "ID de l'utilisateur"] = "",
) -> dict:
    """Retourne les dimensions de l'écran principal de l'utilisateur (en pixels).
    Utilisé pour calculer des positions relatives (centre de l'écran, etc.)."""
    from app.services import desktop_registry
    if not desktop_registry.is_connected(user_id):
        return {"error": "ELY Desktop non connecté."}
    try:
        return await desktop_registry.send_command(user_id, "get_screen_size", {})
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# High-level trainer orchestrator tool
# ---------------------------------------------------------------------------

@tool
async def trainer_start(
    goal: Annotated[str, "Ce que l'utilisateur veut apprendre à faire, ex: 'faire un filtre dans Excel'"],
    user_id: Annotated[str, "ID de l'utilisateur"] = "",
) -> str:
    """Lance une session de formation interactive où ELY prend le contrôle du
    poste de travail pour montrer pas à pas comment réaliser une tâche.

    ELY capture l'écran, analyse la situation, effectue les actions nécessaires
    (clics, saisies, raccourcis) et narre chaque étape à l'utilisateur.

    Exemples d'utilisation :
    - "Montre-moi comment faire un filtre dans Excel"
    - "Comment créer un dossier sur le bureau ?"
    - "Démontre comment utiliser la mise en forme conditionnelle dans Excel"
    - "Montre-moi comment copier une formule sur plusieurs cellules"
    """
    from app.services import desktop_registry
    from app.services.llm_provider import get_llm_for_tier, ComplexityTier

    if not desktop_registry.is_connected(user_id):
        return (
            "❌ **ELY Desktop n'est pas connecté.**\n\n"
            "Pour utiliser le mode formateur, lancez le daemon ELY Desktop sur votre machine :\n"
            "1. Allez dans **Paramètres → ELY Desktop**\n"
            "2. Téléchargez le daemon pour votre système\n"
            "3. Lancez-le — il se connectera automatiquement"
        )

    logger.info("Trainer session started for user=%s goal=%r", user_id, goal)

    # Get vision-capable LLM (Gemini 2.0 Flash preferred — best multimodal support)
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from app.services.llm_provider import _runtime, get_settings
        settings = get_settings()
        gemini_key = _runtime.get("key_gemini") or settings.gemini_api_key
        if gemini_key:
            vision_llm = ChatGoogleGenerativeAI(
                model="gemini-2.0-flash",
                google_api_key=gemini_key,
                max_output_tokens=1024,
                temperature=0.3,
            )
        else:
            # Fallback: current LLM (may not support vision)
            vision_llm = get_llm_for_tier(ComplexityTier.COMPLEX)
    except Exception:
        vision_llm = get_llm_for_tier(ComplexityTier.COMPLEX)

    # System prompt for the vision analysis LLM
    vision_system = (
        "Tu es un assistant formateur qui aide un utilisateur en analysant son écran. "
        "Tes réponses doivent être concises et précises. "
        "Quand on te montre un screenshot, tu identifies les éléments UI visibles "
        "et tu décides de la prochaine action à effectuer pour démontrer la tâche demandée."
    )

    steps_log: list[str] = []
    step = 0

    # ── Step 0: Get screen size ───────────────────────────────────────────
    try:
        screen = await desktop_registry.send_command(user_id, "get_screen_size", {})
        screen_w = screen.get("width", 1920)
        screen_h = screen.get("height", 1080)
    except Exception:
        screen_w, screen_h = 1920, 1080

    # ── Initial screenshot ────────────────────────────────────────────────
    try:
        shot = await desktop_registry.send_command(
            user_id, "screenshot", {"delay_ms": 500}, timeout=15.0
        )
        image_b64 = shot.get("image_b64", "")
    except Exception as e:
        return f"❌ Impossible de capturer l'écran : {e}"

    if not image_b64:
        return "❌ Capture d'écran vide — vérifiez que ELY Desktop est bien connecté."

    # ── Main trainer loop ─────────────────────────────────────────────────
    intro = (
        f"🎓 **Mode Formateur activé** — je vais vous montrer comment : **{goal}**\n\n"
        f"📐 Résolution détectée : {screen_w}×{screen_h}px\n\n"
    )
    steps_log.append(intro)

    while step < MAX_TRAINER_STEPS:
        step += 1

        # Build vision prompt
        analysis_prompt = (
            f"L'utilisateur veut apprendre : « {goal} »\n"
            f"Étape actuelle : {step}/{MAX_TRAINER_STEPS}\n\n"
            "Analyse ce screenshot et réponds en JSON strict :\n"
            "{\n"
            '  "observation": "Ce que tu vois à l\'écran (1-2 phrases)",\n'
            '  "action": "click|double_click|right_click|type|hotkey|move|done|error",\n'
            '  "x": 0,\n'
            '  "y": 0,\n'
            '  "text": "",\n'
            '  "keys": "",\n'
            '  "narration": "Explication à voix haute de cette étape pour l\'utilisateur (1-2 phrases claires)",\n'
            '  "done": false\n'
            "}\n\n"
            "Règles :\n"
            "- action='done' quand la démonstration est complète\n"
            "- action='error' si l'application cible n'est pas visible à l'écran\n"
            "- Pour click/double_click/right_click : fournis x,y en pixels\n"
            "- Pour type : fournis text\n"
            "- Pour hotkey : fournis keys (ex: 'ctrl+shift+l')\n"
            "- Pour move : déplace le curseur pour pointer un élément\n"
            "- narration doit être en français, pédagogique et concis\n"
            "RÉPONDS UNIQUEMENT EN JSON VALIDE, sans markdown."
        )

        # Call vision LLM with screenshot
        try:
            from langchain_core.messages import HumanMessage
            msg = HumanMessage(content=[
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{image_b64}",
                }},
                {"type": "text", "text": analysis_prompt},
            ])
            response = await vision_llm.ainvoke(
                [{"role": "system", "content": vision_system}, msg],
                config={"callbacks": []},
            )
            raw = response.content.strip()
        except Exception as e:
            steps_log.append(f"\n⚠️ Erreur analyse LLM à l'étape {step} : {e}")
            break

        # Parse JSON decision
        import json as _json
        import re as _re
        try:
            # Strip markdown code blocks if present
            raw_clean = _re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=_re.MULTILINE).strip()
            decision = _json.loads(raw_clean)
        except Exception:
            logger.warning("Trainer LLM returned non-JSON: %s", raw[:200])
            steps_log.append(f"\n⚠️ Réponse LLM non parseable à l'étape {step}.")
            break

        action     = decision.get("action", "done")
        narration  = decision.get("narration", "")
        observation = decision.get("observation", "")
        x          = int(decision.get("x", 0))
        y          = int(decision.get("y", 0))
        text       = decision.get("text", "")
        keys       = decision.get("keys", "")
        is_done    = decision.get("done", False) or action == "done"

        # Log step narration
        step_text = f"**Étape {step}** — {narration}"
        if observation:
            step_text = f"**Étape {step}** — _{observation}_\n👉 {narration}"
        steps_log.append(f"\n{step_text}")

        if action == "error":
            steps_log.append(
                f"\n⚠️ {narration}\n"
                "Assurez-vous que l'application cible est ouverte et visible."
            )
            break

        if is_done:
            steps_log.append(f"\n✅ **Démonstration terminée !** La tâche « {goal} » a été réalisée.")
            break

        # Execute the action
        try:
            if action in ("click", "left_click"):
                await desktop_registry.send_command(
                    user_id, "mouse_click", {"x": x, "y": y, "button": "left", "double": False}
                )
            elif action == "double_click":
                await desktop_registry.send_command(
                    user_id, "mouse_click", {"x": x, "y": y, "button": "left", "double": True}
                )
            elif action == "right_click":
                await desktop_registry.send_command(
                    user_id, "mouse_click", {"x": x, "y": y, "button": "right", "double": False}
                )
            elif action == "type":
                await desktop_registry.send_command(user_id, "type_text", {"text": text})
            elif action == "hotkey":
                await desktop_registry.send_command(user_id, "hotkey", {"keys": keys})
            elif action == "move":
                await desktop_registry.send_command(user_id, "mouse_move", {"x": x, "y": y})
        except Exception as e:
            steps_log.append(f"\n⚠️ Erreur lors de l'exécution ({action}) : {e}")
            break

        # Take next screenshot to observe the result
        import asyncio as _asyncio
        await _asyncio.sleep(0.8)  # let the UI settle
        try:
            shot = await desktop_registry.send_command(
                user_id, "screenshot", {"delay_ms": 200}, timeout=15.0
            )
            image_b64 = shot.get("image_b64", "")
        except Exception as e:
            steps_log.append(f"\n⚠️ Impossible de capturer l'écran à l'étape {step} : {e}")
            break

    else:
        steps_log.append(f"\n⏹️ Limite de {MAX_TRAINER_STEPS} étapes atteinte.")

    return "\n".join(steps_log)


# ---------------------------------------------------------------------------
# Skill registration
# ---------------------------------------------------------------------------

_TRAINER_TOOLS = [
    trainer_start,
    trainer_screenshot,
    trainer_click,
    trainer_move,
    trainer_type,
    trainer_hotkey,
    trainer_get_screen_size,
]


def register_trainer_skill() -> None:
    registry = get_skill_registry()
    skill = Skill(
        name="trainer",
        display_name="ELY Formateur",
        description=(
            "Mode formateur interactif : ELY prend le contrôle du poste de travail "
            "pour démontrer des tâches pas à pas (clics, saisies, raccourcis). "
            "Requiert ELY Desktop connecté."
        ),
        icon="🎓",
        tools=_TRAINER_TOOLS,
    )
    registry.register(skill)
    logger.info("Trainer skill registered (%d tools)", len(_TRAINER_TOOLS))
