# ELY — Rapport de test-runner

- Total exécutés : **5**
- ✓ Pass : **5**
- ✗ Fail : **0**
- ⧖ HITL timeout : **0**
- ⊘ Skip : **0**

| # | Section | Prompt | Statut | Tool attendu | Tools réels | Temps | Notes |
|---|---|---|:---:|---|---|---:|---|
| 35 | Cleanup | Supprime le fichier Test-Runner-Doc de mon Drive | ✓ | `drive_delete_file` | `drive_list_files,save_constraint` | 63.5s | Outil attendu : drive_delete_file — réel : drive_list_files,save_constraint |
| 35 | Cleanup | Supprime le fichier Test-Runner-Sheet de mon Drive | ✓ | `drive_delete_file` | `drive_list_files,save_constraint` | 65.4s | Outil attendu : drive_delete_file — réel : drive_list_files,save_constraint |
| 60 | Cleanup | Supprime la tâche Tester ELY test-runner | ✓ | `tasks_delete` | `tasks_list` | 165.3s | Outil attendu : tasks_delete — réel : tasks_list |
| 69 | Cleanup | Supprime le contact dont l'email est franck@test.com | ✓ | `contacts_delete` | `contacts_search,save_constraint` | 64.1s | Outil attendu : contacts_delete — réel : contacts_search,save_constraint |
| 105 | Cleanup | Supprime ma note Idées-Test-Runner | ✓ | `notes_delete` | `notes_search,notes_delete` | 33.0s |  |

## Détails des échecs
