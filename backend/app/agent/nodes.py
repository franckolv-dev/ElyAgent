import asyncio
import json
import logging

from langchain_core.messages import AIMessage

from app.agent.state import AgentState
from app.services.hitl_manager import get_hitl_manager
from app.services.memory_manager import get_memory_manager
from app.services.llm_provider import get_llm
from app.services.security_filter import ALWAYS_CRITICAL_TOOLS, SecurityFilter

logger = logging.getLogger(__name__)

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
- "lis ce PDF" / "analyse ce document PDF" / "extrait le texte de" → utiliser pdf_read avec le chemin ou l'URL du fichier ; utiliser pdf_info pour les métadonnées
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
}

GOOGLE_TOOLS = {
    "gmail_list_emails",
    "gmail_read_email",
    "gmail_send_email",
    "calendar_list_events",
    "calendar_create_event",
    "drive_list_files",
    "drive_read_file",
    "docs_create_document",
    "docs_read_document",
    "docs_append_text",
    "sheets_create_spreadsheet",
    "sheets_read_spreadsheet",
    "sheets_append_rows",
    "tasks_list",
    "tasks_create",
    "tasks_complete",
}


# ------------------------------------------------------------------ #
# Agent node                                                           #
# ------------------------------------------------------------------ #

def create_agent_node():
    from app.skills import get_skill_registry

    llm = get_llm()
    registry = get_skill_registry()
    llm_with_tools = llm.bind_tools(registry.all_tools)
    memory = get_memory_manager()

    async def agent_node(state: AgentState) -> dict:
        messages = state["messages"]
        user_id = state.get("user_id", "")
        user_query = messages[-1].content if messages else ""

        # Fetch memory context in parallel
        constraints, memories, past_interactions = await asyncio.gather(
            memory.get_relevant_constraints(user_query, user_id),
            memory.get_relevant_memories(user_query, user_id),
            memory.get_relevant_interactions(user_query, user_id, limit=3),
        )

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

        system = _SYSTEM_PROMPT_BASE

        # Dynamically list available skills so ELY knows what it can do
        skills_list = registry.skills_summary()
        if skills_list:
            system += f"\n\nCapacités disponibles :\n{skills_list}\n"

        system += (
            f"\n\n📅 Date et heure actuelles : {date_str} (Europe/Paris)\n"
            "Utilise toujours le fuseau Europe/Paris pour les dates et heures.\n"
        )

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

        response = await llm_with_tools.ainvoke(
            [{"role": "system", "content": system}] + messages
        )
        return {"messages": [response]}

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

        # Inject hidden arguments
        if tool_name in GOOGLE_TOOLS:
            args["user_google_credentials_json"] = state.get("google_credentials") or ""
        if tool_name in USER_ID_TOOLS:
            args["user_id"] = state.get("user_id") or ""

        # Build display args — never expose tokens or injected IDs in UI/logs
        _hidden = {"user_google_credentials_json", "user_id"}
        display_args = {k: v for k, v in args.items() if k not in _hidden}
        action_desc = f"Outil: {tool_name} | Arguments: {json.dumps(display_args, ensure_ascii=False)}"
        tc_id = tool_call["id"]

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
