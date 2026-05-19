# ELY — Rapport de test-runner

- Total exécutés : **5**
- ✓ Pass : **5**
- ✗ Fail : **0**
- ⧖ HITL timeout : **0**
- ⊘ Skip : **0**

| # | Section | Prompt | Statut | Tool attendu | Tools réels | Temps | Notes |
|---|---|---|:---:|---|---|---:|---|
| 35 | Cleanup | Supprime le fichier Test-Runner-Doc de mon Drive | ✓ | `drive_delete_file` | `drive_list_files,drive_delete_file` | 30.3s |  |
| 35 | Cleanup | Supprime le fichier Test-Runner-Sheet de mon Drive | ✓ | `drive_delete_file` | `drive_list_files,drive_delete_file` | 12.6s |  |
| 60 | Cleanup | Supprime la tâche Tester ELY test-runner | ✓ | `tasks_delete` | `tasks_list,tasks_delete` | 7.4s |  |
| 69 | Cleanup | Supprime le contact dont l'email est franck@test.com | ✓ | `contacts_delete` | `contacts_search` | 12.8s | Outil attendu : contacts_delete — réel : contacts_search |
| 105 | Cleanup | Supprime ma note Idées-Test-Runner | ✓ | `notes_delete` | `notes_delete,notes_search` | 22.2s |  |

## Détails des échecs
