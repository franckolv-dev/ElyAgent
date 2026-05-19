# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/nodes.py
# @brief      LangGraph agent node definitions
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
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
import asyncio
import json
import logging
import re

from langchain_core.messages import AIMessage, BaseMessage

from app.agent.state import AgentState
from app.services.hitl_manager import get_hitl_manager
from app.services.memory_manager import get_memory_manager
from app.services.llm_provider import get_llm, get_fallback_llms
from app.services.intent_router import get_intent_router
from app.services.security_filter import ALWAYS_CRITICAL_TOOLS, SecurityFilter

logger = logging.getLogger(__name__)


async def _no_interactions() -> list[dict]:
    """Cheap placeholder for get_relevant_interactions on the first turn."""
    return []


def _sanitize_messages_for_mistral(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Fix Mistral-specific constraint: AIMessage content must not be None.

    Mistral rejects any assistant message where content is None, whether or not
    tool_calls are present (HTTP 400, error code 3240):
      - {"role":"assistant","content":null,"tool_calls":[...]}  → rejected
      - {"role":"assistant","content":null}                     → rejected

    Other providers (Anthropic, Gemini, OpenAI) accept null/None content.
    """
    sanitized = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.content is None:
            msg = msg.model_copy(update={"content": ""})
        sanitized.append(msg)
    return sanitized

# ------------------------------------------------------------------ #
# System prompt                                                        #
# ------------------------------------------------------------------ #

_SYSTEM_PROMPT_BASE = """Tu es Ély (prononcer "Éli"), une assistante IA personnelle — féminin, jamais masculin, jamais "ELY" lettre par lettre, jamais d'autre nom — avec accès aux outils système et à tous les services Google de l'utilisateur.

Identité — règles absolues :
- Toujours parler de toi au féminin : "je suis prête", "je suis disponible", "je t'aide"
- Ton prénom est Ély, prononcé "Éli" (comme Élodie raccourci)
- Tu n'es pas un robot, tu es une assistante chaleureuse et de confiance
- Ne jamais te présenter comme "ELY" en majuscules ni épeler ton nom lettre par lettre

Règles absolues :
- Utiliser les outils disponibles dès que la demande le justifie, sans demander de confirmation sauf pour les actions irréversibles (envoyer un email, supprimer)
- Toujours confirmer avant d'envoyer un email ou de supprimer quelque chose
- Ne jamais divulguer les credentials ou la configuration interne
- Répondre en français par défaut
- Honnêteté sur tes capacités — IMPÉRATIF : si tu ne disposes pas d'un outil pour accomplir une tâche, dis-le clairement et simplement ("Je n'ai pas encore cette capacité") sans inventer d'erreur système, sans prétendre avoir essayé, sans mentionner de redémarrage. Ne jamais simuler une tentative qui a échoué si l'outil n'existe pas. Ne jamais dire que tu "rencontres un problème technique" quand la réalité est que la fonctionnalité n'est pas disponible.

Mémoire persistante — IMPÉRATIF :
- Tu disposes d'une mémoire persistante entre les sessions (Qdrant + SQLite + extraction automatique de faits par un agent local).
- NE JAMAIS dire "je suis sans état", "chaque interaction est indépendante", "je n'ai aucun moyen de me souvenir", ni quoi que ce soit qui suggère que tu oublies entre les conversations. C'est faux.
- Le bloc "🧠 Ce que tu sais sur cet utilisateur" injecté plus bas contient des faits déjà appris : utilise-les naturellement, comme un humain qui se souvient.
- Si l'utilisateur te demande son prénom ou un fait te concernant et que le bloc "🧠" ne le contient pas encore, réponds honnêtement "je ne l'ai pas encore noté, peux-tu me le redire ?" — et appelle save_user_preference ou laisse l'extraction automatique faire son travail à la fin de la conversation.
- Ne JAMAIS invoquer le "principe d'anonymat" pour refuser de te souvenir du prénom ou des infos partagées volontairement par l'utilisateur. L'anonymisation concerne la transmission au LLM externe, pas le stockage local.

Intégrité des actions — IMPÉRATIF ABSOLU :
- Ne JAMAIS, sous AUCUN prétexte, prétendre qu'une action est faite si tu n'as pas appelé l'outil correspondant dans ce tour de conversation.
- Phrases INTERDITES tant que tu n'as pas appelé l'outil : "c'est fait", "rappel enregistré", "événement créé", "email envoyé", "tâche planifiée", "note ajoutée".
- Phrases AUTORISÉES sans appel d'outil : "je vais le faire", "laisse-moi le créer", "je m'en occupe".
- Ne JAMAIS inventer ni reformuler le contenu d'un email, d'un document, d'un fichier ou d'un message avant d'avoir appelé l'outil de lecture. Si tu n'as pas encore appelé gmail_read_email / docs_read_document / drive_read_file / notes_read, tu n'as PAS le contenu — n'en affiche AUCUN extrait. Les fausses paraphrases « plausibles » sont strictement interdites.
- Pour appeler un outil, utilise l'API de tool-calling native. N'écris JAMAIS de blocs `<function_calls>`, `<tool_use>`, de JSON de function call, ni de pseudo-code Python dans le texte de tes messages. Ces formats sont du charabia affiché à l'utilisateur, pas exécutés. Si tu ne peux pas appeler un outil via l'API native, dis-le plutôt que de faire semblant.
- Retour d'outil = vérité absolue. Quand le ToolMessage commence par « Erreur », « Erreur :", « Error », « HttpError », « échec », « not found », « File not found », « not supported », etc., l'action a ÉCHOUÉ. Tu ne dois JAMAIS annoncer un succès (« généré », « créé », « envoyé », « supprimé », « exporté ») dans ce cas. Reprends le message d'erreur tel quel, explique-le brièvement en français, et propose soit une correction, soit une alternative, soit demande une info manquante. Les phrases « le PDF a été généré », « le fichier est créé », « le message est envoyé » sur un retour d'erreur sont des HALLUCINATIONS strictement interdites.
- Pour un rappel quotidien/hebdomadaire/récurrent : utilise scheduler_create_task avec la bonne expression cron, pas calendar_create_event (Calendar est pour un événement unique).
- Pour un événement unique dans un calendrier Google : calendar_create_event.
- Pour un rappel déclenché par l'application ELY (notification push) : scheduler_create_task avec channel="app".
- Si un outil échoue, dis-le clairement avec le code d'erreur plutôt que d'inventer un succès.
- Quand l'utilisateur te dit "oui" pour confirmer, regarde le tour précédent : si tu as proposé une action, APPELLE L'OUTIL IMMÉDIATEMENT sans repasser par une phrase d'annonce. N'attends pas.

Interprétations par défaut — NE PAS DEMANDER, agir directement :
- "mail/email/courriel" → Gmail (gmail_*)
- "brouillon/draft" → Gmail (gmail_create_draft)
- "document/doc/google doc" → Google Docs (docs_*)
- "tableur/feuille de calcul/sheet/spreadsheet" → Google Sheets (sheets_*)
- "note/notes" → notes locales ELY (notes_create/list/search)
- "tâche/to-do" sans autre précision → Google Tasks (tasks_*)
- "fichier sur mon drive" → Google Drive (drive_*)
- "événement ponctuel avec date précise" (ex: "RDV dentiste mardi 14h") → calendar_create_event
- "rappel récurrent" (chaque/tous les/hebdo/quotidien) → scheduler_create_task

Cas qui nécessitent VRAIMENT une question de clarification :
- "Envoie ça à Alice" → mail ou WhatsApp ou Telegram ? (plusieurs canaux crédibles)
- "Cherche ce document" → dans mon Drive ou sur le web ?
- "Rappelle-moi de faire X demain à 14h" → événement ponctuel Calendar OU une seule exécution scheduler ? (cas limite — choisir Calendar par défaut car plus léger)

Règle générale :
- Si l'interprétation par défaut ci-dessus couvre la demande → AGIS, ne demande pas.
- Si plusieurs canaux/destinations crédibles coexistent → pose une question de 10 mots.
- N'invente JAMAIS un succès. Si erreur d'outil, dis-le clairement.

Comportement attendu :
- "crée-moi un document Word / Google Doc" → utiliser docs_create_document
- "crée-moi un fichier Excel / une feuille de calcul" → utiliser sheets_create_spreadsheet
- "mes rendez-vous" / "mon calendrier" → utiliser calendar_list_events
- "mes emails" / "ma boîte mail" → utiliser gmail_list_emails
- "mes tâches" / "ma to-do list" → utiliser tasks_list
- "ajoute une tâche" → utiliser tasks_create
- "rappelle-moi tous les lundis" / "chaque matin à 8h" → utiliser scheduler_create_task avec le bon cron
- "mes tâches planifiées" → utiliser scheduler_list_tasks
- "quel temps fait-il" / "météo à [ville]" → utiliser weather_get
- "traduis [texte] en [langue]" → utiliser translate_text
- "actualités" / "news" / "les titres du jour" → utiliser web_search_news ou news_get_headlines
- "cherche sur le web" / "google [sujet]" / "trouve le site de" / "restaurants à" / "commerces à" / "horaires de" → utiliser web_search EN PREMIER (fiable, pas de blocage bot) — TOUJOURS inclure la ville et le pays dans la requête pour les recherches locales
- "va sur [url]" / "ouvre le site" / "lis cette page" → utiliser browser_navigate puis browser_get_text si besoin
- Pour réserver sur un site : web_search pour trouver l'URL, puis browser_navigate + browser_fill + browser_click
- "prends une capture d'écran" → utiliser browser_screenshot (s'affiche directement dans le chat)
- "montre-moi une image de" / "trouve une photo de" / "cherche une image de" → utiliser browser_search_images (photos réelles depuis le web, pas une image générée)
- "surveille ce site" / "veille sur" / "préviens-moi si" → utiliser watchdog_add
- "mes surveillances" / "mes veilles" → utiliser watchdog_list
- "arrête de surveiller" → utiliser watchdog_remove
- "briefing du matin" / "mon briefing" → utiliser briefing_generate puis calendar_list_events + gmail_list_emails
- "génère une image" / "crée une image" / "dessine" / "illustre" → utiliser generate_image avec une description détaillée en anglais pour de meilleurs résultats
- "mes contacts" / "cherche le contact" / "numéro de [personne]" / "email de [personne]" → utiliser contacts_search ou contacts_list
- "ajoute un contact" / "crée un contact" → utiliser contacts_create
- "calcule" / "code python" / "exécute" / "analyse ces données" / "fais un graphique" → utiliser python_execute avec du code Python complet utilisant print() pour les résultats
- quand le message contient "📎 Fichiers joints" avec un fichier .pdf et [PDF — utilise pdf_analyze_with_vision] → utiliser IMMÉDIATEMENT pdf_analyze_with_vision (Gemini lit le PDF visuellement, comprend les tableaux et la mise en page)
- "lis ce PDF" / "analyse ce document PDF" / catalogue / facture / tableau → utiliser pdf_analyze_with_vision ; réserver pdf_read uniquement aux PDF texte simple (rapport, article sans mise en page complexe)
- "extrait le texte de" (PDF simple) → utiliser pdf_read avec le chemin ou l'URL du fichier ; utiliser pdf_info pour les métadonnées
- "regarde mon écran" / "qu'est-ce que tu vois" / "analyse cette image" / "que dit ce document" / quand le message contient "📸 Capture d'écran partagée →" → utiliser vision_analyze_image avec le chemin fourni et la question de l'utilisateur
- "montre-moi comment faire" / "démontre" / "tuteur" / "apprends-moi à utiliser" / "fais une démo de" → utiliser os_screenshot pour voir l'écran, puis expliquer ou démontrer avec os_click/os_type_text (après validation HITL)
- "prends une capture de mon écran" / "screenshot de l'écran" (PAS du navigateur) → utiliser os_screenshot
- "connecte-toi à [logiciel/service]" / "crée un connecteur pour" / "intègre [outil non supporté]" → utiliser mcp_generate_server pour générer le code, puis mcp_validate_and_deploy pour le déployer (avec HITL obligatoire)
- "mes connecteurs MCP" / "outils générés" → utiliser mcp_list_library
- "prends une note" / "note ça" / "mémorise" / "ajoute au presse-papier" → utiliser notes_create
- "mes notes" / "liste mes notes" → utiliser notes_list
- "cherche dans mes notes" / "trouve la note sur" → utiliser notes_search
- "lis la note" / "affiche la note" → utiliser notes_read
- "modifie la note" / "mets à jour la note" → utiliser notes_update
- "supprime la note" → utiliser notes_delete
- "itinéraire de [A] à [B]" / "comment aller à" / "trajet" → utiliser maps_directions
- "où se trouve" / "coordonnées de" / "localise" → utiliser maps_geocode
- "restaurants / pharmacies / ATM / hôtels près de" → utiliser maps_nearby
- "quelle adresse correspond à ces coordonnées" → utiliser maps_reverse_geocode
- "cherche la vidéo" / "trouve sur YouTube" / "video youtube" → utiliser youtube_search
- "transcription de la vidéo" / "sous-titres de" / "que dit cette vidéo" → utiliser youtube_transcript
- "infos sur cette vidéo YouTube" / "durée / vues de la vidéo" → utiliser youtube_video_info
- "génère un QR code" / "crée un QR code pour" → utiliser qrcode_generate
- "QR code Wi-Fi" / "QR code pour se connecter au réseau" → utiliser qrcode_generate_wifi
- "QR code contact" / "QR code vCard" → utiliser qrcode_generate_vcard
- "envoie un WhatsApp à" / "envoie un message WhatsApp" → utiliser whatsapp_send (toujours confirmer avant d'envoyer)
- Donner l'URL cliquable après chaque création de document ou feuille

Utilisation des tools — PRIORITÉ ABSOLUE :
- Dès que la demande correspond à un tool, APPELLE-le immédiatement via function calling.
- Ne JAMAIS annoncer l'appel ("je vais chercher...", "je lance..." etc.) — appelle direct.
- N'écris JAMAIS du code Python pour simuler un tool call.

Format des réponses TEXTE (seulement quand aucun tool n'est pertinent) :
- Texte naturel en français, sans markdown (aucun #, ##, **, *, `, ---, ni tirets de liste).
- Pour énumérer, utilise des formules orales : "premièrement... ensuite... enfin...".
- Les URLs peuvent être données telles quelles (pour être cliquables).
- Aucun emoji par défaut sauf préférence explicite de l'utilisateur.
"""


def _tool_result(content: str, tool_call_id: str) -> dict:
    return {"role": "tool", "content": content, "tool_call_id": tool_call_id}


# ------------------------------------------------------------------ #
# Tools that need automatic argument injection                        #
# ------------------------------------------------------------------ #
# Canonical sets live in tool_sets.py — import from there.

from app.agent.tool_sets import GOOGLE_TOOLS, USER_ID_TOOLS  # noqa: E402


# ------------------------------------------------------------------ #
# Lightweight system prompt for SLM (simple tasks, no memory needed) #
# ------------------------------------------------------------------ #

_SYSTEM_PROMPT_SLM = """Tu es Ély (prononcer "Éli"), une assistante IA personnelle — féminin, chaleureuse et directe.

Règles :
- Répondre en français, en texte naturel sans markdown
- Utiliser les outils disponibles dès que la demande le justifie
- Réponses courtes et claires pour les tâches simples
- Honnêteté sur tes capacités — ne jamais simuler une tentative échouée

📅 Date et heure : {date_str} (Europe/Paris)
"""


# ------------------------------------------------------------------ #
# Agent node                                                           #
# ------------------------------------------------------------------ #

def create_agent_node():
    from app.skills import get_skill_registry
    from app.config import get_settings
    from app.services.llm_provider import get_active_provider, get_active_model

    settings = get_settings()
    registry = get_skill_registry()
    memory = get_memory_manager()
    intent_router = get_intent_router()

    # Pre-build SLM if enabled — cached in closure but re-bound when tools change
    _slm_with_tools = None
    _slm_version = -1
    if settings.slm_enabled:
        try:
            from app.services.llm_provider import get_slm
            _slm_with_tools = get_slm().bind_tools(registry.all_tools)
            _slm_version = registry.tools_version
            logger.info("SLM pre-built: model=%s, threshold=%d", settings.slm_model, settings.slm_complexity_threshold)
        except Exception as exc:
            logger.warning("SLM init failed: %s — all requests will use LLM", exc)

    # Tier-based LLM cache: { tier_value → llm_with_tools }
    # Invalidated when the tool registry version changes (new skill installed).
    _tier_llm_cache: dict = {}
    _tier_cache_version = [-1]  # list so inner fn can mutate without nonlocal

    async def agent_node(state: AgentState) -> dict:
        import time as _t
        _gt_start = _t.monotonic()
        logger.warning("⏱ TIMING[general] starting")
        nonlocal _slm_with_tools, _slm_version
        # _tier_llm_cache / _tier_cache_version are dicts/lists mutated in-place — no nonlocal needed
        messages = state["messages"]
        user_id = state.get("user_id", "")
        # Defensive: LangGraph may pass messages as dicts (serialized form)
        # when a node receives state that was built outside the graph runner.
        _last = messages[-1] if messages else None
        if isinstance(_last, dict):
            user_query = _last.get("content") or ""
            if isinstance(user_query, list):  # multi-block content
                user_query = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in user_query
                )
        else:
            _c = _last.content if _last else ""
            user_query = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in _c
            ) if isinstance(_c, list) else (_c or "")

        # Hot-reload: clear tier cache when tool registry changes (new skill installed)
        current_version = registry.tools_version
        if current_version != _tier_cache_version[0]:
            _tier_llm_cache.clear()
            _tier_cache_version[0] = current_version
            logger.info("Tier LLM cache invalidated (tools_v=%d)", current_version)

        if _slm_with_tools is not None and current_version != _slm_version:
            try:
                from app.services.llm_provider import get_slm
                _slm_with_tools = get_slm().bind_tools(registry.all_tools)
                _slm_version = current_version
            except Exception:
                pass

        # ── Route first — avoids loading memory for SLM requests ──────────
        routing_score = 100
        model_used = "llm:tier-routed"  # updated once tier is selected below
        response = None

        from app.services.intent_router import ModelTier
        use_slm = False
        decision = None
        if _slm_with_tools is not None:
            decision = intent_router.route(user_query, history=messages[:-1])
            routing_score = decision.score
            use_slm = (decision.tier == ModelTier.SLM)

        # Current date/time in French (Europe/Paris)
        from datetime import datetime
        import zoneinfo
        _tz = zoneinfo.ZoneInfo("Europe/Paris")
        now = datetime.now(_tz)
        _days_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        _months_fr = ["", "janvier", "février", "mars", "avril", "mai", "juin",
                      "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        date_str = (
            f"{_days_fr[now.weekday()]} {now.day} {_months_fr[now.month]} "
            f"{now.year}, {now.strftime('%H:%M')}"
        )

        if use_slm:
            # ── Lightweight path: minimal prompt, no memory queries ────────
            # Fetching Qdrant memory adds ~150-300ms and is useless for simple tasks
            system = _SYSTEM_PROMPT_SLM.format(date_str=date_str)
        else:
            # ── Full path: complete prompt + memory context ────────────────
            from app.services.memory_service import get_user_context
            # PERF: skip get_relevant_interactions for the very first turn of a
            # conversation — nothing to find yet, and the Qdrant search +
            # FTS + embedding costs ~100-200ms. Only fetch when we have history.
            # We fetch history starting from the 2nd user turn (conversation has
            # at least one prior user+assistant pair).
            _history_msgs_count = sum(
                1 for m in messages if getattr(m, 'type', None) in ('human', 'ai')
            )
            _needs_interactions = _history_msgs_count > 1
            _past_interactions_task = (
                memory.get_relevant_interactions(user_query, user_id, limit=3)
                if _needs_interactions
                else _no_interactions()
            )
            constraints, memories, past_interactions, preferences, user_profile = await asyncio.gather(
                memory.get_relevant_constraints(user_query, user_id),
                memory.get_relevant_memories(user_query, user_id),
                _past_interactions_task,
                memory.get_user_preferences(user_id),
                get_user_context(user_id),
            )

            # ── Compact prompt mode for local LLMs ─────────────────────────
            # For small local models (LM Studio, llama.cpp on localhost),
            # replace the full ELY prompt with a ~300-token compact one
            # that puts tool-calling priority first. Cloud frontier models
            # keep the full prompt.
            from app.services.qwen_no_think import is_local_openai_llm
            from app.agent.compact_prompt import build_compact_system_prompt

            # Safe detection: try to instantiate the currently active LLM.
            # Wrapped in try/except because get_llm() can raise if no
            # provider is configured yet (first-boot scenarios).
            try:
                _llm_for_detect = get_llm()
            except Exception:
                _llm_for_detect = None
            if _llm_for_detect is not None and is_local_openai_llm(_llm_for_detect):
                system = build_compact_system_prompt(
                    agent_name="general",
                    date_str=date_str,
                    user_ctx=user_profile or "",
                    memories=memories,
                    constraints=constraints,
                )
                logger.info("[general] compact prompt mode active (%d chars)", len(system))
                # Skip the rest of the verbose injection — jump directly to the
                # inference block. We still need to go through context_manager
                # below, so we just let `system` stay as the compact string.
                _use_compact = True
            else:
                _use_compact = False

            if not _use_compact:
                system = _SYSTEM_PROMPT_BASE

                # ── Inject active LLM info (transparency / self-awareness) ──────
                _provider = get_active_provider()
                _model    = get_active_model()
                _slm_info = ""
                if settings.slm_enabled:
                    _slm_info = (
                        f" Pour les requêtes simples, tu utilises en priorité le modèle local "
                        f"{settings.slm_model} via Ollama (rapide, données non envoyées dans le cloud)."
                    )
                system += (
                    f"\n\nModèle IA actif : {_model} (fournisseur : {_provider}).{_slm_info}\n"
                    "Si l'utilisateur te demande quel LLM tu utilises, donne cette information précise.\n"
                )

            # NOTE: skills_summary() was injected here historically but produced a
            # ~20k-char block (148 tool names + descriptions) that was redundant with
            # bind_tools() and drastically slowed qwen3:4b / small models. Removed —
            # the LLM sees tool schemas via bind_tools when needed.

            if not _use_compact:
                system += (
                    f"\n\n📅 Date et heure actuelles : {date_str} (Europe/Paris)\n"
                    "Utilise toujours le fuseau Europe/Paris pour les dates et heures.\n"
                )

                # ── Inject the consolidated user profile FIRST (most important) ──
                # These are facts Éli has learned about the user from past conversations,
                # consolidated nightly into user_profiles table. Without this block, the
                # agent would answer "je n'ai aucun moyen de me souvenir…" even though
                # 5+ profile facts exist in SQL.
                if user_profile:
                    system += f"\n\n🧠 {user_profile}\n"

                if preferences:
                    system += (
                        "\n\n👤 RÈGLES DE COMMUNICATION PERSONNALISÉES — OBLIGATOIRES :\n"
                        "⚠️ Ces règles ont la même priorité que les règles absolues ci-dessus.\n"
                        "Elles s'appliquent à CHAQUE réponse, sans exception, même si tu penses\n"
                        "qu'une réponse plus longue serait plus utile. Respecte-les strictement.\n"
                    )
                    system += "\n".join(f"- {p}" for p in preferences)
                if constraints:
                    system += "\n\n🛡️ CONTRAINTES DE SÉCURITÉ PERMANENTES (apprises de tes refus) :\n"
                    system += "\n".join(f"- {c}" for c in constraints)
                if memories:
                    system += "\n\n💾 CONTEXTE MÉMORISÉ :\n"
                    system += "\n".join(f"- {m}" for m in memories)
                if past_interactions:
                    system += "\n\n🔁 INTERACTIONS PASSÉES PERTINENTES :\n"
                    for p in past_interactions:
                        system += (
                            f"- Q: {p.get('user_message', '')[:120]} "
                            f"→ R: {p.get('assistant_message', '')[:120]}\n"
                        )

        # ── Context fitting (prevent overflow) ────────────────────────────
        # NOTE: get_active_model is imported at create_agent_node() scope (line ~167).
        # Re-importing it here would shadow the closure and trigger UnboundLocalError
        # at the earlier usage line 271 (_model = get_active_model()).
        from app.services.context_manager import fit_messages_to_context

        _sanitized = _sanitize_messages_for_mistral(messages)

        # ── Inference ──────────────────────────────────────────────────────
        if use_slm:
            try:
                _slm_fitted = fit_messages_to_context(
                    messages=_sanitized,
                    system_prompt=system,
                    model=settings.slm_model,
                    reserve_for_response=1024,
                )
                response = await asyncio.wait_for(
                    _slm_with_tools.ainvoke(
                        [{"role": "system", "content": system}]
                        + _slm_fitted
                    ),
                    timeout=settings.slm_timeout,
                )
                model_used = f"slm:{settings.slm_model}"
                logger.info(
                    "SLM answered (score=%d, model=%s, reason=%s)",
                    decision.score, settings.slm_model, decision.reason,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "SLM timeout after %.1fs (score=%d) — falling back to LLM",
                    settings.slm_timeout, decision.score,
                )
            except Exception as exc:
                logger.warning(
                    "SLM error (score=%d): %s — falling back to LLM",
                    decision.score, exc,
                )

        if response is None:
            # LLM path (or SLM fallback) — needs full system prompt if not built yet
            if use_slm:
                # SLM failed: rebuild full system prompt for LLM fallback
                from app.services.memory_service import get_user_context as _guc
                constraints, memories, past_interactions, preferences, user_profile = await asyncio.gather(
                    memory.get_relevant_constraints(user_query, user_id),
                    memory.get_relevant_memories(user_query, user_id),
                    memory.get_relevant_interactions(user_query, user_id, limit=3),
                    memory.get_user_preferences(user_id),
                    _guc(user_id),
                )
                system = _SYSTEM_PROMPT_BASE
                skills_list = registry.skills_summary()
                if skills_list:
                    system += f"\n\nCapacités disponibles :\n{skills_list}\n"
                system += (
                    f"\n\n📅 Date et heure actuelles : {date_str} (Europe/Paris)\n"
                    "Utilise toujours le fuseau Europe/Paris pour les dates et heures.\n"
                )
                if user_profile:
                    system += f"\n\n🧠 {user_profile}\n"
                if preferences:
                    system += (
                        "\n\n👤 RÈGLES DE COMMUNICATION PERSONNALISÉES — OBLIGATOIRES :\n"
                        "⚠️ Ces règles s'appliquent à CHAQUE réponse, sans exception.\n"
                    )
                    system += "\n".join(f"- {p}" for p in preferences)
                if constraints:
                    system += "\n\n🛡️ CONTRAINTES DE SÉCURITÉ PERMANENTES :\n"
                    system += "\n".join(f"- {c}" for c in constraints)
                if memories:
                    system += "\n\n💾 CONTEXTE MÉMORISÉ :\n"
                    system += "\n".join(f"- {m}" for m in memories)

            # Tier routing: pick the right local/cloud model based on complexity.
            # CRITICAL PERF: the "general" node has access to ALL ~148 tools, which
            # makes bind_tools + the first inference extremely slow (the prompt grows
            # by ~30k tokens with 148 tool schemas). The supervisor already routes
            # tool-needing queries to sub-agents (workspace, infra…), so general is
            # mostly used for chitchat and quick facts that don't need tools. We only
            # bind tools when the query likely needs one (COMPLEX tier, or detected
            # tool keywords).
            from app.services.llm_provider import classify_complexity, get_llm_for_tier, ComplexityTier
            _tier = classify_complexity(user_query)
            # Bind tools only for COMPLEX queries OR when the query explicitly mentions
            # tool-related actions. SIMPLE/MEDIUM small-talk and quick facts skip binding.
            _tool_kw = re.compile(
                r"\b(envoie|crée|liste|cherche|trouve|génère|exécute|lance|"
                r"planifie|programme|note|enregistre|sauvegarde|"
                r"mail|email|calendrier|drive|sheet|doc|tâche|rappel|note|"
                r"fichier|capture|screenshot|météo|news|traduis)\b",
                re.IGNORECASE,
            )
            _bind_tools_flag = (
                _tier == ComplexityTier.COMPLEX or
                bool(_tool_kw.search(user_query))
            )
            _tier_key = _tier.value
            # Cache key differentiates with/without tools bound
            _cache_key = f"{_tier_key}:{'tools' if _bind_tools_flag else 'notools'}"
            # Keep a reference to the UNBOUND base LLM — needed later to
            # detect whether it's a Qwen variant (for /no_think injection).
            # When the cache is already warm, the cached entry may be the
            # tool-bound wrapper, which can hide the underlying provider;
            # we therefore cache _base_llm under a second key to always
            # have it on hand.
            _base_cache_key = f"{_tier_key}:base"
            if _cache_key not in _tier_llm_cache:
                _bind_start = _t.monotonic()
                _base_llm = get_llm_for_tier(_tier)
                _tier_llm_cache[_base_cache_key] = _base_llm
                _tier_llm_cache[_cache_key] = (
                    _base_llm.bind_tools(registry.all_tools) if _bind_tools_flag else _base_llm
                )
                logger.warning("⏱ TIMING[general.bind] %.2fs — tier=%s, bind_tools=%s (tools_v=%d)",
                    _t.monotonic() - _bind_start, _tier_key, _bind_tools_flag, current_version)
            _base_llm = _tier_llm_cache.get(_base_cache_key) or _tier_llm_cache[_cache_key]
            _llm_with_tools_req = _tier_llm_cache[_cache_key]
            model_used = f"llm:tier-{_tier_key}{'+tools' if _bind_tools_flag else ''}"

            _fitted = fit_messages_to_context(
                messages=_sanitized,
                system_prompt=system,
                model=_tier_key,
                reserve_for_response=1024,
            )
            _invoke_msgs = (
                [{"role": "system", "content": system}]
                + _fitted
            )
            try:
                _infer_t = _t.monotonic()
                from app.services.qwen_no_think import (
                    inject_no_think, is_qwen_llm, strip_no_think, strip_think_block,
                )
                # Only Qwen understands /no_think; other models would echo it.
                if is_qwen_llm(_base_llm):
                    _invoke_msgs = inject_no_think(_invoke_msgs)
                response = await _llm_with_tools_req.ainvoke(_invoke_msgs)
                # Strip any <think> block that slipped through
                if hasattr(response, 'content') and isinstance(response.content, str):
                    response.content = strip_think_block(response.content)
                logger.warning("⏱ TIMING[general.infer] %.2fs — tier=%s, tool_calls=%d",
                    _t.monotonic() - _infer_t, _tier_key, len(getattr(response, 'tool_calls', []) or []))
            except Exception as primary_exc:
                # Detect recoverable API errors: quota exhausted, rate limit,
                # authentication failure, service unavailable.
                _exc_str = str(primary_exc).lower()
                _recoverable = any(k in _exc_str for k in (
                    "429", "rate", "quota", "insuffi", "401", "403", "404",
                    "not_found", "not found", "overloaded", "503", "unavailable",
                    "deprecated", "no longer available",
                    "invalid_argument", "bad request", "400",
                ))
                if not _recoverable:
                    raise

                logger.warning(
                    "Primary LLM failed (%s): %s — trying fallbacks",
                    type(primary_exc).__name__, primary_exc,
                )
                response = None
                # Fallback models (Claude, Gemini, Mistral…) are NOT Qwen; strip
                # any /no_think marker that was injected for the primary call.
                _fallback_msgs = strip_no_think(_invoke_msgs)
                for fallback_label, fallback_llm in get_fallback_llms():
                    try:
                        fallback_with_tools = fallback_llm.bind_tools(registry.all_tools)
                        response = await fallback_with_tools.ainvoke(_fallback_msgs)
                        logger.info("Fallback succeeded with %s", fallback_label)
                        break
                    except Exception as fallback_exc:
                        logger.warning(
                            "Fallback %s also failed: %s", fallback_label, fallback_exc
                        )

                if response is None:
                    raise primary_exc

        # Fire-and-forget: extract facts from this exchange for user memory
        if user_id:
            from app.services.memory_service import extract_and_store_facts

            async def _safe_memory_extract(uid, msgs):
                try:
                    await extract_and_store_facts(uid, "", msgs)
                except Exception as exc:
                    logger.debug("Memory extraction failed: %s", exc)

            asyncio.create_task(_safe_memory_extract(user_id, messages + [response]))

        # Phase 5A — record token usage (observability only, no hard cap yet)
        if user_id:
            from app.services.budget_guard import (
                record_llm_usage, extract_usage_from_response,
            )
            in_tok, out_tok = extract_usage_from_response(response)
            if in_tok or out_tok:
                _provider = get_active_provider()
                _model = get_active_model()
                asyncio.create_task(record_llm_usage(
                    user_id=user_id,
                    provider=_provider,
                    model=_model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    conversation_id=state.get("conversation_id"),
                    channel=state.get("channel", "web"),
                ))

        return {"messages": [response], "model_used": model_used, "routing_score": routing_score}

    return agent_node


# ------------------------------------------------------------------ #
# Tool node                                                            #
# ------------------------------------------------------------------ #

async def tool_node(state: AgentState) -> dict:
    from app.skills import get_skill_registry
    from app.services.tool_policy_service import get_tool_policy_service

    last_message = state["messages"][-1]
    user_id = state.get("user_id", "")
    results = []

    tool_map = {t.name: t for t in get_skill_registry().all_tools}
    sf = SecurityFilter()
    hitl = get_hitl_manager()
    memory = get_memory_manager()
    policy = get_tool_policy_service()

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        args = dict(tool_call["args"])

        # Inject hidden arguments — credentials are fetched from the server-side
        # store (never stored in graph state) to prevent exposure in logs/events.
        if tool_name in GOOGLE_TOOLS:
            from app.services.credential_store import get_credential_store
            _uid = state.get("user_id") or ""
            args["user_google_credentials_json"] = get_credential_store().get(_uid) or ""
        if tool_name in USER_ID_TOOLS:
            args["user_id"] = state.get("user_id") or ""

        # Build display args — never expose tokens or injected IDs in UI/logs
        _hidden = {"user_google_credentials_json", "user_id"}
        display_args = {k: v for k, v in args.items() if k not in _hidden}
        action_desc = f"Outil: {tool_name} | Arguments: {json.dumps(display_args, ensure_ascii=False)}"
        tc_id = tool_call["id"]

        # ── Vault: resolve vault://label references in args ───────────────
        vault_refs_found = any(
            isinstance(v, str) and v.startswith("vault://")
            for v in args.values()
        )
        if vault_refs_found:
            from app.services.vault_service import get_vault_service
            vault = get_vault_service()
            if vault.is_locked(user_id):
                results.append(_tool_result(
                    "⛔ Vault verrouillé — déverrouillez votre coffre-fort dans Paramètres > Vault "
                    "pour utiliser ce secret.", tc_id
                ))
                continue
            try:
                args, _resolved = await vault.resolve_vault_refs(user_id, args)
                if _resolved:
                    logger.info("Resolved vault refs %s for tool %s", _resolved, tool_name)
            except KeyError as exc:
                results.append(_tool_result(f"⛔ Secret introuvable dans le Vault : {exc}", tc_id))
                continue

        # ── Declarative tool policy (Phase 5A) ────────────────────────────
        # Per-user policies override the default HITL behaviour. Modes:
        #   - "deny"         → refuse the action without prompting
        #   - "allow"        → execute without HITL even if normally critical
        #   - "require_hitl" → force HITL even if not in ALWAYS_CRITICAL_TOOLS
        #   - None           → fall back to legacy logic below
        policy_mode = await policy.evaluate(user_id, tool_name)
        if policy_mode == "deny":
            logger.info("Tool '%s' denied by policy for user %s", tool_name, user_id)
            results.append(_tool_result(
                "Action refusée par votre politique d'outils. Modifiez la règle "
                "dans Paramètres > Politique d'outils pour l'autoriser.", tc_id
            ))
            continue

        # HITL check — combines legacy criticality with the optional policy override
        legacy_needs_hitl = (
            tool_name in ALWAYS_CRITICAL_TOOLS
        ) or sf.is_critical(action_desc)
        if policy_mode == "allow":
            needs_hitl = False
        elif policy_mode == "require_hitl":
            needs_hitl = True
        else:
            needs_hitl = legacy_needs_hitl

        if needs_hitl:
            logger.info("HITL required for action: %s", action_desc)
            decision, reason = await hitl.request_validation(
                description=action_desc,
                user_id=user_id,
            )
            if decision == "ban":
                rule = f"INTERDICTION PERMANENTE: {action_desc}"
                if reason:
                    rule += f" — Raison: {reason}"
                await memory.store_constraint(rule, user_id)
                results.append(_tool_result(
                    "Action interdite définitivement et règle de sécurité enregistrée.", tc_id
                ))
                continue
            elif decision != "allow":
                results.append(_tool_result(
                    "Action refusée par l'utilisateur pour cette occurrence.", tc_id
                ))
                continue

        tool = tool_map.get(tool_name)
        if tool:
            try:
                import time as _tt
                _ts = _tt.monotonic()
                result = await tool.ainvoke(args)
                logger.warning("⏱ TIMING[tool:%s] %.2fs", tool_name, _tt.monotonic() - _ts)
                results.append(_tool_result(str(result), tc_id))
            except Exception as exc:
                logger.warning("Tool %s failed: %s", tool_name, exc)
                results.append(_tool_result(f"Erreur d'exécution: {exc}", tc_id))
        else:
            from langchain_core.messages import ToolMessage
            results.append(ToolMessage(
                content=f"Outil '{tool_name}' non disponible.",
                tool_call_id=tc_id,
            ))

    return {"messages": results}


# ------------------------------------------------------------------ #
# Router                                                               #
# ------------------------------------------------------------------ #

def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "end"
