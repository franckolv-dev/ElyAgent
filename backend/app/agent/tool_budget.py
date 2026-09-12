"""Bound tool descriptions while retaining discovery and explicitly needed tools."""
import json
from app.services.memory.selection import tokens

CORE = {"find_tool", "skill_view", "memory_recall", "ask_user"}


def fit_tool_schemas(tools: list, query: str, protected: set[str], budget: int = 8000) -> list:
    from langchain_core.utils.function_calling import convert_to_openai_tool
    from app.agent.capability_binding import requested_action_names
    from app.services.memory_service import _recall_tokens
    mandatory = CORE | protected | requested_action_names(query, tools, CORE | protected)
    query_words = _recall_tokens(query)
    ranked = []
    for tool in tools:
        try:
            cost = tokens(json.dumps(convert_to_openai_tool(tool), ensure_ascii=False))
        except Exception:
            # Unknown schemas are retained: never silently hide a required capability.
            cost = 0
            mandatory.add(tool.name)
        score = len(query_words & _recall_tokens(f"{tool.name} {tool.description}"))
        ranked.append((tool, cost, score))
    chosen = [t for t, _, _ in ranked if t.name in mandatory]
    spent = sum(cost for t, cost, _ in ranked if t.name in mandatory)
    for tool, cost, _ in sorted(ranked, key=lambda row: -row[2]):
        if tool.name not in mandatory and spent + cost <= budget:
            chosen.append(tool)
            spent += cost
    # Deterministic registry order preserves the schema prefix cache.
    names = {t.name for t in chosen}
    return [t for t in tools if t.name in names]
