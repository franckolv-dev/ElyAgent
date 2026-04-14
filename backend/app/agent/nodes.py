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
import asyncio
import json
import logging

from langchain_core.messages import AIMessage, BaseMessage

from app.agent.state import AgentState
from app.services.hitl_manager import get_hitl_manager
from app.services.memory_manager import get_memory_manager
from app.services.llm_provider import get_llm, get_fallback_llms
from app.services.intent_router import get_intent_router
from app.services.security_filter import ALWAYS_CRITICAL_TOOLS, SecurityFilter

logger = logging.getLogger(__name__)


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

Format des réponses — IMPÉRATIF :
- Rédige TOUJOURS en texte naturel, comme si tu parlais à voix haute à quelqu'un
- N'utilise JAMAIS de markdown : aucun #, ##, **, *, `, ---, ni tiret de liste
- Pas de titres, pas de tableaux, pas de blocs de code dans les réponses conversationnelles
- Pour énumérer, utilise des formules orales : "premièrement... ensuite... enfin..."
- Tes réponses doivent être fluides et agréables à entendre lues à voix haute
- Exception : les URLs peuvent être données telles quelles pour que l'utilisateur puisse cliquer
"""


def _tool_result(content: str, tool_call_id: str) -> dict:
    return {"role": "tool", "content": content, "tool_call_id": tool_call_id}


# ------------------------------------------------------------------ #
# Tools that need automatic argument injection                        #
# ------------------------------------------------------------------ #

USER_ID_TOOLS = {
    "scheduler_list_tasks",
    "scheduler_create_task",
    "scheduler_delete_task",
    # Browser tools — each user has an isolated browser context
    "browser_navigate",
    "browser_search_web",
    "browser_get_text",
    "browser_screenshot",
    "browser_click",
    "browser_fill",
    "browser_close",
    # Watchdog tools
    "watchdog_add",
    "watchdog_list",
    "watchdog_remove",
    # Notes tools
    "notes_create",
    "notes_list",
    "notes_read",
    "notes_update",
    "notes_delete",
    "notes_search",
    # Desktop tools — need user_id to look up the daemon connection
    "desktop_list_dir",
    "desktop_read_file",
    "desktop_write_file",
    "desktop_move_file",
    "desktop_delete_file",
    "desktop_create_dir",
    "desktop_stat_file",
    "desktop_hash_file",
    "desktop_search_files",
    # Trainer tools — need user_id for desktop daemon connection
    "trainer_start",
    "trainer_screenshot",
    "trainer_click",
    "trainer_move",
    "trainer_type",
    "trainer_hotkey",
    "trainer_get_screen_size",
    # Memory / preferences tools
    "save_user_preference",
    "save_constraint",
    # Knowledge base tools
    "knowledge_search",
    "knowledge_list",
}

GOOGLE_TOOLS = {
    # Gmail
    "gmail_list_emails", "gmail_read_email", "gmail_send_email",
    "gmail_reply_email", "gmail_send_with_attachment",
    "gmail_mark_read", "gmail_mark_unread",
    "gmail_create_draft", "gmail_list_drafts",
    "gmail_list_labels", "gmail_create_label",
    "gmail_move_emails", "gmail_trash_emails", "gmail_search_for_cleanup",
    # Calendar
    "calendar_list_events", "calendar_create_event",
    "calendar_update_event", "calendar_delete_event",
    "calendar_check_availability", "calendar_list_calendars",
    # Drive
    "drive_list_files", "drive_read_file",
    "drive_create_folder", "drive_create_file",
    "drive_update_file", "drive_move_file",
    "drive_rename_file", "drive_delete_file",
    # Docs
    "docs_create_document", "docs_read_document", "docs_append_text",
    "docs_replace_text", "docs_insert_table",
    # Sheets
    "sheets_create_spreadsheet", "sheets_read_spreadsheet", "sheets_append_rows",
    "sheets_update_cells", "sheets_delete_rows",
    "sheets_add_sheet", "sheets_list_sheets",
    # Tasks
    "tasks_list", "tasks_create", "tasks_complete",
    "tasks_update", "tasks_delete",
    "tasks_list_tasklists", "tasks_create_tasklist",
    # Contacts (People API)
    "contacts_search", "contacts_list", "contacts_create",
    "contacts_get", "contacts_update", "contacts_delete",
}


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

    # LLM binding — cached per provider+model, rebuilt when either changes or tools change
    _llm_with_tools = None
    _llm_version = -1
    _llm_provider_key = ""   # "<provider>/<model>" — detect runtime switches

    async def agent_node(state: AgentState) -> dict:
        nonlocal _llm_with_tools, _llm_version, _llm_provider_key, _slm_with_tools, _slm_version
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

        # Hot-reload: rebuild LLM if provider/model changed OR tools changed
        current_version = registry.tools_version
        current_provider_key = f"{get_active_provider()}/{get_active_model()}"
        if _llm_with_tools is None or current_provider_key != _llm_provider_key or current_version != _llm_version:
            _llm_with_tools = get_llm().bind_tools(registry.all_tools)
            _llm_provider_key = current_provider_key
            _llm_version = current_version
            logger.info("LLM refreshed: %s (tools_v=%d)", current_provider_key, current_version)

        if _slm_with_tools is not None and current_version != _slm_version:
            try:
                from app.services.llm_provider import get_slm
                _slm_with_tools = get_slm().bind_tools(registry.all_tools)
                _slm_version = current_version
            except Exception:
                pass

        # ── Route first — avoids loading memory for SLM requests ──────────
        routing_score = 100
        model_used = f"llm:{get_active_provider()}/{get_active_model()}"
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
            constraints, memories, past_interactions, preferences = await asyncio.gather(
                memory.get_relevant_constraints(user_query, user_id),
                memory.get_relevant_memories(user_query, user_id),
                memory.get_relevant_interactions(user_query, user_id, limit=3),
                memory.get_user_preferences(user_id),
            )

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

            skills_list = registry.skills_summary()
            if skills_list:
                system += f"\n\nCapacités disponibles :\n{skills_list}\n"

            system += (
                f"\n\n📅 Date et heure actuelles : {date_str} (Europe/Paris)\n"
                "Utilise toujours le fuseau Europe/Paris pour les dates et heures.\n"
            )

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
        from app.services.context_manager import fit_messages_to_context
        from app.services.llm_provider import get_active_model

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
                constraints, memories, past_interactions, preferences = await asyncio.gather(
                    memory.get_relevant_constraints(user_query, user_id),
                    memory.get_relevant_memories(user_query, user_id),
                    memory.get_relevant_interactions(user_query, user_id, limit=3),
                    memory.get_user_preferences(user_id),
                )
                system = _SYSTEM_PROMPT_BASE
                skills_list = registry.skills_summary()
                if skills_list:
                    system += f"\n\nCapacités disponibles :\n{skills_list}\n"
                system += (
                    f"\n\n📅 Date et heure actuelles : {date_str} (Europe/Paris)\n"
                    "Utilise toujours le fuseau Europe/Paris pour les dates et heures.\n"
                )
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

            _fitted = fit_messages_to_context(
                messages=_sanitized,
                system_prompt=system,
                model=get_active_model(),
                reserve_for_response=1024,
            )
            _invoke_msgs = (
                [{"role": "system", "content": system}]
                + _fitted
            )
            try:
                response = await _llm_with_tools.ainvoke(_invoke_msgs)
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
                for fallback_label, fallback_llm in get_fallback_llms():
                    try:
                        fallback_with_tools = fallback_llm.bind_tools(registry.all_tools)
                        response = await fallback_with_tools.ainvoke(_invoke_msgs)
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
            try:
                from app.services.memory_service import extract_and_store_facts
                asyncio.ensure_future(
                    extract_and_store_facts(user_id, "", messages + [response])
                )
            except Exception as _mem_exc:
                logger.debug("Memory extraction skipped: %s", _mem_exc)

        return {"messages": [response], "model_used": model_used, "routing_score": routing_score}

    return agent_node


# ------------------------------------------------------------------ #
# Tool node                                                            #
# ------------------------------------------------------------------ #

async def tool_node(state: AgentState) -> dict:
    from app.skills import get_skill_registry

    last_message = state["messages"][-1]
    user_id = state.get("user_id", "")
    results = []

    tool_map = {t.name: t for t in get_skill_registry().all_tools}
    sf = SecurityFilter()
    hitl = get_hitl_manager()
    memory = get_memory_manager()

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

        # HITL check
        needs_hitl = (tool_name in ALWAYS_CRITICAL_TOOLS) or sf.is_critical(action_desc)
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
                result = await tool.ainvoke(args)
                results.append(_tool_result(str(result), tc_id))
            except Exception as exc:
                results.append(_tool_result(f"Erreur d'exécution: {exc}", tc_id))

    return {"messages": results}


# ------------------------------------------------------------------ #
# Router                                                               #
# ------------------------------------------------------------------ #

def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "end"
