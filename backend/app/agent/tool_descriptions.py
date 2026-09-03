# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tool_descriptions.py
# @brief      Descriptions courtes destinées au MODÈLE, séparées des docstrings
#             destinées aux développeurs.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Budget de descriptions : ce qui part au modèle à CHAQUE tour.

**Le problème, mesuré le 26/07/2026.** Les 82 outils du profil ``default``
pesaient **15 486 tokens** de descriptions — 189 tokens par outil, contre 79
chez Hermes v0.19 pour 72 outils. Ce poids n'est pas payé une fois : il repart
à chaque appel de modèle, donc à chaque itération d'une boucle d'outils.

**La cause.** La docstring de développement servait AUSSI de description au
modèle. ``orchestrate`` (démantelé le 29/07) exposait 4 826 caractères, code et
sections de documentation compris — utiles à qui lit le source, inutiles à qui
choisit un outil.

**Le principe retenu.** Les docstrings restent intactes dans leurs modules ;
ce fichier ne fournit que la version courte envoyée au modèle. Une seule
adresse pour toutes les descriptions destinées au modèle, comme Hermes tient
les siennes dans ses schémas.

**Ce qu'une description doit contenir, et rien d'autre :**

1. ce que fait l'outil, en une phrase ;
2. **l'anti-déclencheur** — quand NE PAS l'appeler, et quoi appeler à la
   place, sous son nom exact. C'est ce qui empêche « 9 outils pour 1 besoin »
   (audit Opus 5) et la forme que Hermes soigne dans ses SKILL.md ;
3. les seules contraintes de paramètre **non devinables** depuis le schéma.

⚠️ Le point 3 compte : les schémas de paramètres d'Ely n'ont **aucune**
description (vérifié le 26/07). La prose est donc le seul endroit où le modèle
apprend qu'un ``folder_id`` est un identifiant et non un nom de dossier. On
coupe les exemples et la redite, pas ces contraintes-là.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# Descriptions courtes, par nom d'outil. Tout ce qui n'est pas ici garde sa
# docstring — le dégraissage vise les poids lourds, pas l'uniformité.
SLIM_DESCRIPTIONS: dict[str, str] = {


    "gmail_trash_by_category": (
        "Bulk-trash a whole Gmail CATEGORY in one atomic call.\n"
        "🛑 DO NOT USE when the user names a SENDER, brand, domain or person "
        "(« les mails AliExpress », « de Temu »): a category would either miss "
        "them or trash far too much. For a sender, chain instead: "
        "gmail_list_emails(query=\"from:<sender>\") → gmail_trash_emails(ids=[…]).\n"
        "category: promotions | social | forums | updates | purchases | spam | "
        "trash | newsletters | demarchage | all_cleanup | all_categories."
    ),

    "search_past_conversations_tool": (
        "Search the user's entire conversation history and summarise the most "
        "relevant exchanges.\n"
        "USE WHENEVER the user points at an earlier discussion: « tu te "
        "souviens… », « qu'est-ce qu'on avait dit sur… », « ça a donné quoi… », "
        "or any request whose answer lives in past turns rather than this one.\n"
        "Searches every conversation the user ever had with Ely, not just the "
        "current one."
    ),

    "scheduler_create_task": (
        "Create a scheduled task that runs automatically. The `prompt` is "
        "executed at the given schedule exactly as if the user had typed it in "
        "chat at that moment, and the result is delivered on `channel`.\n"
        "USE WHEN the user says « programme », « planifie », « rappelle-moi », "
        "« envoie plus tard », « notifie-moi dans X jours ».\n"
        "Write `prompt` as a STANDALONE instruction: the task runs with no "
        "memory of this conversation, so it must state its own goal, its files "
        "and its stopping condition."
    ),

    "browser_screenshot": (
        "Capture the current server-side browser page. Does NOT send the file — "
        "returns JSON with `local_path`, `attachment_id`, `data` (base64) and "
        "`mime`.\n"
        "You MUST then chain another tool to deliver it: drive_upload_local_file "
        "to store it, vision_analyze_image to read it, or an attachment tool to "
        "hand it to the user. Never claim the screenshot was sent."
    ),

    "drive_find_duplicates": (
        "Find duplicate files in a Google Drive folder, hashed server-side.\n"
        "USE WHENEVER the user wants to find, list or clean duplicates in Drive. "
        "NEVER emulate it with repeated drive_list_files plus manual comparison — "
        "that stops scaling past ~10 files and invents matches.\n"
        "folder_id: the Drive folder ID, NOT its name — resolve it first with "
        "drive_list_files(query=\"name='<folder>'\"). Use 'root' for My Drive."
    ),

    "memory_archive": (
        "Store a fact durably in permanent memory.\n"
        "CALL THIS as soon as the user says « retiens », « enregistre », "
        "« souviens-toi », « mémorise », « note pour plus tard » about a factual "
        "piece of information.\n"
        "Exemple typique — les URLs de profils sociaux : « retiens mon "
        "LinkedIn https://linkedin.com/in/… ». C'est le cas qui a échoué huit "
        "fois avant d'être épinglé.\n"
        "RÈGLE ABSOLUE : ne JAMAIS confirmer qu'une information est "
        "enregistrée sans avoir réellement appelé cet outil dans ce tour — "
        "une confirmation sans appel est un mensonge à l'utilisateur."
    ),

    "gmail_search_for_cleanup": (
        "Find emails worth cleaning up and return their IDs and summaries for "
        "review. Always show the results to the user BEFORE calling "
        "gmail_move_emails or gmail_trash_emails.\n"
        "category: newsletters | promotions | social | forums | updates | "
        "purchases | spam | trash | demarchage | all_cleanup | all_categories "
        "(singular/plural and FR/EN aliases are accepted)."
    ),

    "save_user_preference": (
        "Save a communication preference to permanent memory, immediately.\n"
        "USE AS SOON AS the user states how they want to be served: tone, "
        "format, style, answer length, language, emojis, markdown, level of "
        "detail.\n"
        "Pour un FAIT (une information à retenir), utilise memory_archive. "
        "Pour une règle née d'un refus ou d'une limite posée par l'utilisateur, "
        "utilise save_constraint."
    ),

    "browser_tab_click": (
        "Click an element in one of the user's Chrome tabs, by CSS selector.\n"
        "USE THIS to drive multi-step authenticated flows: Doctolib (open the "
        "booking, pick a reason, choose a slot), SNCF Connect, Booking, .gouv.fr "
        "forms, any SPA where a button must be pressed before the next data "
        "appears.\n"
        "Read the page first (browser_tab_read_text / _read_html) to find a "
        "selector that exists — a guessed selector fails silently."
    ),

    "gmail_update_settings": (
        "Update Gmail account settings: signature, vacation responder, filters, "
        "forwarding. Needs the 'gmail.settings.basic' scope.\n"
        "setting: 'vacation' | 'signature' | 'filter' | 'forwarding'.\n"
        "value_json: a JSON string whose shape depends on `setting` — e.g. "
        "vacation takes {\"enableAutoReply\": true, \"responseSubject\": …, "
        "\"responseBodyPlainText\": …}.\n"
        "⚠️ A filter rule persists and silently affects every future incoming "
        "mail; forwarding can leak the inbox to a third party."
    ),

    "gmail_trash_by_query": (
        "Trash every email matching an arbitrary Gmail search query.\n"
        "USE FOR complex deletions that no category covers: several senders "
        "combined with dates, custom labels, OR expressions, attachments. The "
        "syntax is exactly Gmail's search bar.\n"
        "For « vide une catégorie entière », prefer gmail_trash_by_category.\n"
        "⚠️ You build the query yourself: a loose one (e.g. \"from:gmail.com\") "
        "can match thousands of messages."
    ),

    "save_constraint": (
        "Save a permanent rule learned from a refusal or a limit THE USER set.\n"
        "⚠️ NEVER use it to record a limit YOU believe you have. If you think "
        "you cannot do something, it is usually a tool you have not found — "
        "call find_tool instead of engraving a false limit.\n"
        "For a preference about tone or format, use save_user_preference."
    ),

    "browser_open_tab": (
        "Open a URL in a NEW background Chrome tab in the user's own browser.\n"
        "The tab inherits the user's Chrome profile, cookies and logged-in "
        "sessions: LinkedIn, Doctolib, Gmail, Amazon open ALREADY SIGNED IN, "
        "with no login step.\n"
        "Chain with browser_tab_wait_loaded, then browser_tab_read_text.\n"
        "Prefer this over browser_navigate for anything behind authentication."
    ),

    "drive_upload_local_file": (
        "Upload a LOCAL file (binary or text) from the server's disk to Google "
        "Drive.\n"
        "This is how you deliver a screenshot: browser_screenshot returns a "
        "`local_path` such as /tmp/ely-screenshots/….png — pass that path here.\n"
        "Unlike drive_create_file, which writes text content you provide, this "
        "one uploads bytes that already exist on disk."
    ),

    "vision_analyze_image": (
        "Analyse an image — screenshot, photo, scanned document — with Gemini "
        "Vision.\n"
        "USE WHEN the message carries a path to a screenshot, when the user "
        "attaches an image and wants it described, or asks « regarde », "
        "« qu'est-ce qu'il y a sur », « lis ce document ».\n"
        "Accepts a local path or a URL."
    ),
}


def apply_slim_descriptions() -> int:
    """Remplace la description ENVOYÉE AU MODÈLE pour les outils listés.

    Les docstrings des modules ne sont pas touchées : seul l'attribut
    ``description`` de l'outil bindé change. Retourne le nombre d'outils
    effectivement raccourcis.

    Ne lève jamais : un nom absent du catalogue (outil renommé, module non
    chargé) est journalisé et ignoré — un budget de tokens ne doit pas
    empêcher Ely de démarrer.
    """
    try:
        from app.skills import get_skill_registry

        by = {t.name: t for t in get_skill_registry().all_tools}
    except Exception as exc:  # noqa: BLE001
        logger.warning("descriptions courtes non appliquées : %s", exc)
        return 0

    extras: dict[str, str] = {}
    skip: set[str] = set()

    # #260 — les outils qui naviguent SANS session portent un avertissement
    # ajouté à leur description au chargement de `browser_skill`. Remplacer la
    # description ici l'effacerait : on le réapplique. Il est importé plutôt
    # que recopié, pour qu'une seule formulation existe.
    try:
        from app.skills.builtin.browser_skill import _NO_SESSION_NOTICE
        sessionless = {"browser_navigate", "browser_get_text", "browser_screenshot"}
    except Exception:  # noqa: BLE001
        _NO_SESSION_NOTICE, sessionless = "", set()

    applied = 0
    for name, slim in SLIM_DESCRIPTIONS.items():
        tool = by.get(name)
        if tool is None or name in skip:
            logger.debug("description courte ignorée : %s", name)
            continue
        try:
            tool.description = (
                slim
                + extras.get(name, "")
                + (_NO_SESSION_NOTICE if name in sessionless else "")
            )
            applied += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("description courte refusée pour %s : %s", name, exc)
    return applied
