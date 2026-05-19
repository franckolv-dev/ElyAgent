# ELY — Rapport de test-runner

- Total exécutés : **3**
- ✓ Pass : **3**
- ✗ Fail : **0**
- ⧖ HITL timeout : **0**
- ⊘ Skip : **0**

| # | Section | Prompt | Statut | Tool attendu | Tools réels | Temps | Notes |
|---|---|---|:---:|---|---|---:|---|
| 101 | Notes | Crée une note intitulée Backlog-Fix-Note avec le contenu : t | ✓ | `notes_create` | `notes_create,save_user_preference` | 5.1s |  |
| 105 | Notes | Supprime ma note Backlog-Fix-Note | ✓ | `notes_delete` | `notes_search,notes_delete` | 7.7s |  |
| 86 | Météo | Quel temps fait-il à Paris aujourd'hui ? | ✓ | `weather_get` | `weather_get` | 8.3s |  |

## Détails des échecs
