# ELY — Rapport de test-runner

- Total exécutés : **5**
- ✓ Pass : **5**
- ✗ Fail : **0**
- ⧖ HITL timeout : **0**
- ⊘ Skip : **0**

| # | Section | Prompt | Statut | Tool attendu | Tools réels | Temps | Notes |
|---|---|---|:---:|---|---|---:|---|
| 35 | Cleanup | Supprime le fichier Test-Runner-Doc de mon Drive | ✓ | `drive_delete_file` | `drive_list_files,drive_delete_file` | 99.5s |  |
| 35 | Cleanup | Supprime le fichier Test-Runner-Sheet de mon Drive | ✓ | `drive_delete_file` | `drive_list_files,drive_delete_file` | 80.6s |  |
| 60 | Cleanup | Supprime la tâche Tester ELY test-runner | ✓ | `tasks_delete` | `tasks_list,tasks_list_tasklists` | 68.2s | Outil attendu : tasks_delete — réel : tasks_list,tasks_list_tasklists |
| 69 | Cleanup | Supprime le contact dont l'email est franck@test.com | ✓ | `contacts_delete` | `contacts_search` | 69.0s | Outil attendu : contacts_delete — réel : contacts_search |
| 105 | Cleanup | Supprime ma note Idées-Test-Runner | ✓ | `notes_delete` | `notes_search` | 36.7s | Outil attendu : notes_delete — réel : notes_search |

## Détails des échecs
