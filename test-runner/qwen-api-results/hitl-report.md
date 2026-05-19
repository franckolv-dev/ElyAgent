# ELY — Rapport de test-runner

- Total exécutés : **18**
- ✓ Pass : **12**
- ✗ Fail : **6**
- ⧖ HITL timeout : **0**
- ⊘ Skip : **0**

| # | Section | Prompt | Statut | Tool attendu | Tools réels | Temps | Notes |
|---|---|---|:---:|---|---|---:|---|
| 3 | Gmail | Envoie un email à follivier@datasolution.fr avec pour sujet  | ✗ | `gmail_send_email` | `—` | 183.9s | Timeout sur recv() |
| 15 | Gmail | Active mon message d'absence avec pour texte : Test automati | ✗ | `gmail_update_settings` | `—` | 302.5s | Timeout — pas de réponse finale en 120s |
| 15 | Gmail | Désactive maintenant mon message d'absence | ✓ | `gmail_update_settings` | `gmail_send_email` | 1.8s | Outil attendu : gmail_update_settings — réel : gmail_send_email |
| 19 | Calendar | Crée un rendez-vous RDV-Test-Runner demain à 10h30 pendant 3 | ✓ | `calendar_create_event` | `calendar_quick_add,calendar_update_event` | 9.5s | Outil attendu : calendar_create_event — réel : calendar_quick_add,calendar_update_event |
| 21 | Calendar | Déplace le rendez-vous RDV-Test-Runner à 14h00 le même jour | ✓ | `calendar_update_event` | `calendar_list_events,calendar_get_event` | 9.4s | Outil attendu : calendar_update_event — réel : calendar_list_events,calendar_get_event |
| 25 | Calendar | Réunion équipe lundi 9h | ✓ | `calendar_quick_add` | `calendar_quick_add` | 5.2s |  |
| 22 | Calendar | Supprime le rendez-vous RDV-Test-Runner | ✗ | `calendar_delete_event` | `calendar_list_events` | 186.5s | Timeout sur recv() |
| 22 | Calendar | Supprime aussi la réunion équipe du lundi 9h | ✗ | `calendar_delete_event` | `—` | 298.8s | Timeout sur recv() |
| 31 | Drive | Crée un fichier texte Test-Share-Runner.txt dans Drive avec  | ✗ | `drive_create_file` | `—` | 298.8s | Timeout sur recv() |
| 36 | Drive | Partage le fichier Test-Share-Runner.txt avec follivier@data | ✗ | `drive_share_file` | `—` | 122.0s | Éli a refusé sans appeler d'outil |
| 35 | Drive | Supprime le fichier Test-Share-Runner.txt de mon Drive | ✓ | `drive_delete_file` | `drive_list_files,drive_delete_file` | 153.2s |  |
| 40 | Docs | Crée un Google Doc intitulé Test-BatchUpdate | ✓ | `docs_create_document` | `docs_create_document,docs_batch_update,docs_read_document` | 41.7s |  |
| 45 | Docs | Dans Test-BatchUpdate, ajoute le texte 'Titre principal' en  | ✓ | `docs_batch_update` | `docs_read_document,drive_list_files,docs_batch_update` | 18.4s |  |
| 35 | Docs | Supprime le Google Doc Test-BatchUpdate de mon Drive | ✓ | `drive_delete_file` | `drive_list_files,drive_delete_file` | 38.8s |  |
| 47 | Sheets | Crée un tableur Google Sheets intitulé Test-BatchSheet avec  | ✓ | `sheets_create_spreadsheet` | `sheets_create_spreadsheet,sheets_update_cells,sheets_list_sheets` | 49.5s |  |
| 54 | Sheets | Dans Test-BatchSheet, trie la colonne B de manière décroissa | ✓ | `sheets_batch_update` | `sheets_list_sheets,drive_list_files,sheets_batch_update` | 21.8s |  |
| 35 | Sheets | Supprime le tableur Test-BatchSheet de mon Drive | ✓ | `drive_delete_file` | `drive_list_files,drive_delete_file` | 67.5s |  |
| 63 | Tasks | Via l'API Tasks brute, liste toutes les tasklists visibles a | ✓ | `tasks_raw_api_call` | `tasks_raw_api_call` | 14.3s |  |

## Détails des échecs

### #3 — Gmail — Envoie un email à follivier@datasolution.fr avec pour sujet Test #3 runner et corps : Ceci est un test automatisé, ignore

- Statut : **fail**
- Tool attendu : `gmail_send_email`
- Tools réels : `[]`
- Notes : Timeout sur recv()
- Réponse : ''

### #15 — Gmail — Active mon message d'absence avec pour texte : Test automatisé, je réponds bientôt — active-le pour les 5 prochaines minutes seulement

- Statut : **fail**
- Tool attendu : `gmail_update_settings`
- Tools réels : `[]`
- Notes : Timeout — pas de réponse finale en 120s
- Réponse : ''

### #22 — Calendar — Supprime le rendez-vous RDV-Test-Runner

- Statut : **fail**
- Tool attendu : `calendar_delete_event`
- Tools réels : `['calendar_list_events']`
- Notes : Timeout sur recv()
- Réponse : ''

### #22 — Calendar — Supprime aussi la réunion équipe du lundi 9h

- Statut : **fail**
- Tool attendu : `calendar_delete_event`
- Tools réels : `[]`
- Notes : Timeout sur recv()
- Réponse : ''

### #31 — Drive — Crée un fichier texte Test-Share-Runner.txt dans Drive avec le contenu : fichier de test partage

- Statut : **fail**
- Tool attendu : `drive_create_file`
- Tools réels : `[]`
- Notes : Timeout sur recv()
- Réponse : ''

### #36 — Drive — Partage le fichier Test-Share-Runner.txt avec follivier@datasolution.fr en lecture seule

- Statut : **fail**
- Tool attendu : `drive_share_file`
- Tools réels : `[]`
- Notes : Éli a refusé sans appeler d'outil
- Réponse : "Je ne peux pas supprimer ces événements car l'action a été refusée par le système de confirmation humaine (HITL). Souhaites-tu que je réessaie ou y a-t-il un autre événement spécifique à supprimer ? …"
