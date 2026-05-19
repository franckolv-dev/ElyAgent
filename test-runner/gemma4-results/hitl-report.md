# ELY — Rapport de test-runner

- Total exécutés : **18**
- ✓ Pass : **16**
- ✗ Fail : **2**
- ⧖ HITL timeout : **0**
- ⊘ Skip : **0**

| # | Section | Prompt | Statut | Tool attendu | Tools réels | Temps | Notes |
|---|---|---|:---:|---|---|---:|---|
| 3 | Gmail | Envoie un email à follivier@datasolution.fr avec pour sujet  | ✗ | `gmail_send_email` | `—` | 283.2s | Timeout — pas de réponse finale en 120s |
| 15 | Gmail | Active mon message d'absence avec pour texte : Test automati | ✓ | `gmail_update_settings` | `—` | 20.4s | Réponse texte sans outil (peut être OK si la question ne nécessite pas d'appel) |
| 15 | Gmail | Désactive maintenant mon message d'absence | ✗ | `gmail_update_settings` | `—` | 47.9s | Éli a refusé sans appeler d'outil |
| 19 | Calendar | Crée un rendez-vous RDV-Test-Runner demain à 10h30 pendant 3 | ✓ | `calendar_create_event` | `calendar_quick_add,save_constraint` | 45.4s | Outil attendu : calendar_create_event — réel : calendar_quick_add,save_constraint |
| 21 | Calendar | Déplace le rendez-vous RDV-Test-Runner à 14h00 le même jour | ✓ | `calendar_update_event` | `calendar_list_events,save_constraint` | 44.9s | Outil attendu : calendar_update_event — réel : calendar_list_events,save_constraint |
| 25 | Calendar | Réunion équipe lundi 9h | ✓ | `calendar_quick_add` | `calendar_quick_add` | 28.6s |  |
| 22 | Calendar | Supprime le rendez-vous RDV-Test-Runner | ✓ | `calendar_delete_event` | `calendar_list_events,save_constraint` | 45.1s | Outil attendu : calendar_delete_event — réel : calendar_list_events,save_constraint |
| 22 | Calendar | Supprime aussi la réunion équipe du lundi 9h | ✓ | `calendar_delete_event` | `save_constraint` | 167.7s | Outil attendu : calendar_delete_event — réel : save_constraint |
| 31 | Drive | Crée un fichier texte Test-Share-Runner.txt dans Drive avec  | ✓ | `drive_create_file` | `drive_create_file,save_constraint` | 45.1s |  |
| 36 | Drive | Partage le fichier Test-Share-Runner.txt avec follivier@data | ✓ | `drive_share_file` | `drive_list_files,save_constraint` | 50.2s | Outil attendu : drive_share_file — réel : drive_list_files,save_constraint |
| 35 | Drive | Supprime le fichier Test-Share-Runner.txt de mon Drive | ✓ | `drive_delete_file` | `drive_list_files,save_constraint` | 44.8s | Outil attendu : drive_delete_file — réel : drive_list_files,save_constraint |
| 40 | Docs | Crée un Google Doc intitulé Test-BatchUpdate | ✓ | `docs_create_document` | `docs_create_document,save_constraint` | 44.2s |  |
| 45 | Docs | Dans Test-BatchUpdate, ajoute le texte 'Titre principal' en  | ✓ | `docs_batch_update` | `drive_list_files` | 104.6s | Outil attendu : docs_batch_update — réel : drive_list_files |
| 35 | Docs | Supprime le Google Doc Test-BatchUpdate de mon Drive | ✓ | `drive_delete_file` | `drive_list_files` | 56.7s | Outil attendu : drive_delete_file — réel : drive_list_files |
| 47 | Sheets | Crée un tableur Google Sheets intitulé Test-BatchSheet avec  | ✓ | `sheets_create_spreadsheet` | `sheets_create_spreadsheet,save_constraint` | 56.6s |  |
| 54 | Sheets | Dans Test-BatchSheet, trie la colonne B de manière décroissa | ✓ | `sheets_batch_update` | `drive_list_files` | 156.9s | Outil attendu : sheets_batch_update — réel : drive_list_files |
| 35 | Sheets | Supprime le tableur Test-BatchSheet de mon Drive | ✓ | `drive_delete_file` | `drive_list_files,save_constraint` | 66.1s | Outil attendu : drive_delete_file — réel : drive_list_files,save_constraint |
| 63 | Tasks | Via l'API Tasks brute, liste toutes les tasklists visibles a | ✓ | `tasks_raw_api_call` | `save_constraint` | 33.2s | Outil attendu : tasks_raw_api_call — réel : save_constraint |

## Détails des échecs

### #3 — Gmail — Envoie un email à follivier@datasolution.fr avec pour sujet Test #3 runner et corps : Ceci est un test automatisé, ignore

- Statut : **fail**
- Tool attendu : `gmail_send_email`
- Tools réels : `[]`
- Notes : Timeout — pas de réponse finale en 120s
- Réponse : ''

### #15 — Gmail — Désactive maintenant mon message d'absence

- Statut : **fail**
- Tool attendu : `gmail_update_settings`
- Tools réels : `[]`
- Notes : Éli a refusé sans appeler d'outil
- Réponse : "Je suis désolée, mais je n'ai pas les permissions nécessaires pour modifier ou désactiver ton message d'absence directement via l'API Gmail. Tu devras le faire manuellement dans les paramètres de ton compte Gmail. …"
