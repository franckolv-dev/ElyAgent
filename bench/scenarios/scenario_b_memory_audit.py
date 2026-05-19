# Bench scenario B — audit mémoire toutes catégories
#
# Démontre la boucle "for cat in categories" — un pattern impossible
# pour un LLM en mode séquentiel (qui devrait écrire 8 tool_calls
# séparés). Ici Python fait la boucle, le LLM ne voit que le résumé.
#
# Tools utilisés (2 sur 15) :
#   - memory_recent  (×7 — une fois par catégorie)
#   - search_past_conversations_tool
from ely_tools import memory_recent, search_past_conversations_tool

# Toutes les catégories memory exposées par le memgpt_tool.
CATEGORIES = ["fact", "preference", "project", "contact",
              "task", "event", "constraint"]

print("=== Audit mémoire — derniers faits par catégorie ===\n")

audit = {}
for cat in CATEGORIES:
    result = memory_recent(category=cat, limit=3)
    audit[cat] = result
    print(f"--- {cat} ---")
    print(result)
    print()

# Croiser avec les conversations passées pour repérer les sujets actifs
recent_topics = search_past_conversations_tool(
    query="dernières discussions"
)
print("=== Sujets récents en conversation ===")
print(recent_topics)

# Synthèse côté script (impossible côté LLM sans encore 1 tour)
print("\n=== Synthèse ===")
total_lines = sum(len(str(v).splitlines()) for v in audit.values())
print(f"Total lignes auditées : {total_lines}")
print(f"Catégories non vides  : {sum(1 for v in audit.values() if 'Aucun' not in str(v))}/{len(CATEGORIES)}")
