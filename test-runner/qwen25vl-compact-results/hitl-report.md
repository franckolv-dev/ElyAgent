# ELY — Rapport de test-runner

- Total exécutés : **18**
- ✓ Pass : **15**
- ✗ Fail : **3**
- ⧖ HITL timeout : **0**
- ⊘ Skip : **0**

| # | Section | Prompt | Statut | Tool attendu | Tools réels | Temps | Notes |
|---|---|---|:---:|---|---|---:|---|
| 3 | Gmail | Envoie un email à follivier@datasolution.fr avec pour sujet  | ✓ | `gmail_send_email` | `gmail_send_email` | 45.2s |  |
| 15 | Gmail | Active mon message d'absence avec pour texte : Test automati | ✓ | `gmail_update_settings` | `—` | 56.5s | Réponse texte sans outil (peut être OK si la question ne nécessite pas d'appel) |
| 15 | Gmail | Désactive maintenant mon message d'absence | ✗ | `gmail_update_settings` | `—` | 13.8s | Éli a refusé sans appeler d'outil |
| 19 | Calendar | Crée un rendez-vous RDV-Test-Runner demain à 10h30 pendant 3 | ✓ | `calendar_create_event` | `calendar_create_event` | 29.3s |  |
| 21 | Calendar | Déplace le rendez-vous RDV-Test-Runner à 14h00 le même jour | ✓ | `calendar_update_event` | `calendar_update_event` | 27.1s |  |
| 25 | Calendar | Réunion équipe lundi 9h | ✓ | `calendar_quick_add` | `calendar_create_meet_event` | 29.7s | Outil attendu : calendar_quick_add — réel : calendar_create_meet_event |
| 22 | Calendar | Supprime le rendez-vous RDV-Test-Runner | ✓ | `calendar_delete_event` | `calendar_delete_event` | 36.4s |  |
| 22 | Calendar | Supprime aussi la réunion équipe du lundi 9h | ✓ | `calendar_delete_event` | `calendar_delete_event` | 43.1s |  |
| 31 | Drive | Crée un fichier texte Test-Share-Runner.txt dans Drive avec  | ✓ | `drive_create_file` | `drive_create_file` | 27.5s |  |
| 36 | Drive | Partage le fichier Test-Share-Runner.txt avec follivier@data | ✓ | `drive_share_file` | `drive_share_file` | 43.5s |  |
| 35 | Drive | Supprime le fichier Test-Share-Runner.txt de mon Drive | ✓ | `drive_delete_file` | `—` | 12.4s | Réponse texte sans outil (peut être OK si la question ne nécessite pas d'appel) |
| 40 | Docs | Crée un Google Doc intitulé Test-BatchUpdate | ✓ | `docs_create_document` | `docs_create_document` | 25.1s |  |
| 45 | Docs | Dans Test-BatchUpdate, ajoute le texte 'Titre principal' en  | ✓ | `docs_batch_update` | `—` | 16.5s | Réponse texte sans outil (peut être OK si la question ne nécessite pas d'appel) |
| 35 | Docs | Supprime le Google Doc Test-BatchUpdate de mon Drive | ✓ | `drive_delete_file` | `—` | 19.2s | Réponse texte sans outil (peut être OK si la question ne nécessite pas d'appel) |
| 47 | Sheets | Crée un tableur Google Sheets intitulé Test-BatchSheet avec  | ✓ | `sheets_create_spreadsheet` | `—` | 14.0s | Réponse texte sans outil (peut être OK si la question ne nécessite pas d'appel) |
| 54 | Sheets | Dans Test-BatchSheet, trie la colonne B de manière décroissa | ✓ | `sheets_batch_update` | `—` | 59.0s | Réponse texte sans outil (peut être OK si la question ne nécessite pas d'appel) |
| 35 | Sheets | Supprime le tableur Test-BatchSheet de mon Drive | ✗ | `drive_delete_file` | `—` | 200.8s | Timeout sur recv() |
| 63 | Tasks | Via l'API Tasks brute, liste toutes les tasklists visibles a | ✗ | `tasks_raw_api_call` | `—` | 138.8s | Éli a refusé sans appeler d'outil |

## Détails des échecs

### #15 — Gmail — Désactive maintenant mon message d'absence

- Statut : **fail**
- Tool attendu : `gmail_update_settings`
- Tools réels : `[]`
- Notes : Éli a refusé sans appeler d'outil
- Réponse : "Je suis désolée, mais je ne peux pas accéder à votre boîte e-mail pour vous désactiver un message d'absence. Pour cela, je vous suggère de vous connecter à votre boîte e-mail et d'y procéder manuellement. Si vous avez besoin de m'aider à configurer une règle pour ne pas que vos e-mails d'absence soi"

### #35 — Sheets — Supprime le tableur Test-BatchSheet de mon Drive

- Statut : **fail**
- Tool attendu : `drive_delete_file`
- Tools réels : `[]`
- Notes : Timeout sur recv()
- Réponse : ''

### #63 — Tasks — Via l'API Tasks brute, liste toutes les tasklists visibles avec leurs métadonnées complètes

- Statut : **fail**
- Tool attendu : `tasks_raw_api_call`
- Tools réels : `[]`
- Notes : Éli a refusé sans appeler d'outil
- Réponse : 'Pour supprimer le tableur "Test-BatchSheet" de votre Google Drive, je vais appeler la fonction `drive_delete_file`.\n\nJe ne peux pas supprimer le tableur "Test-BatchSheet" car vous n\'avez pas donné l\'autorisation. Pourriez-vous me donner les détails ou confirmer que vous souhaitez vraiment supprimer '
