# Bench scenario A — résumé hebdomadaire dev
#
# Démontre l'orchestration multi-tool sur des sources sans Google
# credentials (github + memory + knowledge + past conversations).
# Le LLM aurait normalement enchaîné 5 tool_calls séquentiels, chacun
# polluant le contexte avec son résultat. Ici un seul tour LLM,
# stdout final seulement.
#
# Tools utilisés (5 sur 15 de l'allow-list V1) :
#   - github_repo_stats          → stars/issues/PR du repo
#   - github_traffic_stats       → clones/vues 14 derniers jours
#   - memory_recent              → 5 derniers faits archivés
#   - search_past_conversations_tool → résumé des conversations passées
#   - knowledge_search           → recherche dans les docs ingérés
from ely_tools import (
    github_repo_stats,
    github_traffic_stats,
    memory_recent,
    search_past_conversations_tool,
    knowledge_search,
)

print("=== Résumé hebdomadaire dev ELY ===\n")

# 1. État du repo
stats = github_repo_stats()
print(f"GitHub stats:\n{stats}\n")

# 2. Trafic 14 jours
traffic = github_traffic_stats()
print(f"GitHub traffic 14j:\n{traffic}\n")

# 3. Derniers faits projet en mémoire
projects = memory_recent(category="project", limit=5)
print(f"Projets récents en mémoire:\n{projects}\n")

# 4. Conversations passées sur Sprint 2.7
past = search_past_conversations_tool(query="sprint 2.7 orchestrate")
print(f"Conversations passées:\n{past}\n")

# 5. Docs indexés sur Hermes
hermes_docs = knowledge_search(query="hermes pattern")
print(f"Knowledge base — Hermes:\n{hermes_docs}\n")

print("=== Fin du résumé ===")
