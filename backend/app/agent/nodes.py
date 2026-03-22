import asyncio
import json
import logging

from langchain_core.messages import AIMessage

from app.agent.state import AgentState
from app.agent.tools import all_tools
from app.services.hitl_manager import get_hitl_manager
from app.services.memory_manager import get_memory_manager
from app.services.llm_provider import get_llm
from app.services.security_filter import ALWAYS_CRITICAL_TOOLS, SecurityFilter

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_BASE = """Tu es ELY, un assistant IA personnel avec accès aux outils système et à tous les services Google de l'utilisateur.

Outils disponibles selon la demande :
- SSH : exécuter des commandes sur des serveurs distants configurés
- Gmail : lire, chercher et envoyer des emails
- Google Calendar : consulter et créer des événements
- Google Drive : lister et lire des fichiers
- Google Docs : créer et modifier des documents texte (équivalent Word)
- Google Sheets : créer et modifier des feuilles de calcul (équivalent Excel)
- Google Tasks : consulter et créer des tâches
- Tâches planifiées : créer des tâches récurrentes qui s'exécutent automatiquement

Règles absolues :
- Utiliser les outils Google dès que la demande le justifie, sans demander de confirmation sauf pour les actions irréversibles (envoyer un email, supprimer)
- Toujours confirmer avant d'envoyer un email ou de supprimer quelque chose
- Ne jamais divulguer les credentials ou la configuration interne
- Répondre en français par défaut

Comportement attendu :
- "crée-moi un document Word / Google Doc" → utiliser docs_create_document
- "crée-moi un fichier Excel / une feuille de calcul" → utiliser sheets_create_spreadsheet
- "mes rendez-vous" / "mon calendrier" → utiliser calendar_list_events
- "mes emails" / "ma boîte mail" → utiliser gmail_list_emails
- "mes tâches" / "ma to-do list" → utiliser tasks_list
- "ajoute une tâche" → utiliser tasks_create
- "rappelle-moi tous les lundis" / "chaque matin à 8h" → utiliser scheduler_create_task avec le bon cron
- "mes tâches planifiées" → utiliser scheduler_list_tasks
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


def create_agent_node():
    llm = get_llm()
    llm_with_tools = llm.bind_tools(all_tools)
    memory = get_memory_manager()

    async def agent_node(state: AgentState) -> dict:
        messages = state["messages"]
        user_id = state.get("user_id", "")
        user_query = messages[-1].content if messages else ""

        # Fetch constraints, memories and relevant past interactions in parallel
        constraints, memories, past_interactions = await asyncio.gather(
            memory.get_relevant_constraints(user_query, user_id),
            memory.get_relevant_memories(user_query, user_id),
            memory.get_relevant_interactions(user_query, user_id, limit=3),
        )

        from datetime import datetime
        import zoneinfo
        _tz = zoneinfo.ZoneInfo("Europe/Paris")
        now = datetime.now(_tz)
        _days_fr = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
        _months_fr = ["","janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"]
        date_str = f"{_days_fr[now.weekday()]} {now.day} {_months_fr[now.month]} {now.year}, {now.strftime('%H:%M')}"
        system = _SYSTEM_PROMPT_BASE
        system += (
            f"\n\n📅 Date et heure actuelles : {date_str} (Europe/Paris)\n"
            f"Utilise toujours le fuseau Europe/Paris pour les dates et heures.\n"
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
                system += f"- Q: {p.get('user_message', '')[:120]} → R: {p.get('assistant_message', '')[:120]}\n"

        response = await llm_with_tools.ainvoke(
            [{"role": "system", "content": system}] + messages
        )
        return {"messages": [response]}

    return agent_node


# Tools that need user_id injection
USER_ID_TOOLS = {
    "scheduler_list_tasks",
    "scheduler_create_task",
    "scheduler_delete_task",
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


async def tool_node(state: AgentState) -> dict:
    last_message = state["messages"][-1]
    user_id = state.get("user_id", "")
    results = []

    tool_map = {t.name: t for t in all_tools}
    # SecurityFilter is stateless here — used only for is_critical() keyword check
    sf = SecurityFilter()
    hitl = get_hitl_manager()
    memory = get_memory_manager()

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        args = dict(tool_call["args"])
        if tool_name in GOOGLE_TOOLS:
            args["user_google_credentials_json"] = state.get("google_credentials") or ""
        if tool_name in USER_ID_TOOLS:
            args["user_id"] = state.get("user_id") or ""
        # Build display args without injected params (never expose tokens/ids in UI/logs)
        _hidden = {"user_google_credentials_json", "user_id"}
        display_args = {k: v for k, v in args.items() if k not in _hidden}
        action_desc = f"Outil: {tool_name} | Arguments: {json.dumps(display_args, ensure_ascii=False)}"
        tc_id = tool_call["id"]

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
                results.append(_tool_result("Action interdite définitivement et règle de sécurité enregistrée.", tc_id))
                continue
            elif decision != "allow":
                results.append(_tool_result("Action refusée par l'utilisateur pour cette occurrence.", tc_id))
                continue

        tool = tool_map.get(tool_name)
        if tool:
            try:
                result = await tool.ainvoke(args)
                results.append(_tool_result(str(result), tc_id))
            except Exception as exc:
                results.append(_tool_result(f"Erreur d'exécution: {exc}", tc_id))

    return {"messages": results}


def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "end"
