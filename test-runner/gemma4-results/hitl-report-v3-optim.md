# ELY — Rapport de test-runner

- Total exécutés : **18**
- ✓ Pass : **8**
- ✗ Fail : **10**
- ⧖ HITL timeout : **0**
- ⊘ Skip : **0**

| # | Section | Prompt | Statut | Tool attendu | Tools réels | Temps | Notes |
|---|---|---|:---:|---|---|---:|---|
| 3 | Gmail | Envoie un email à follivier@datasolution.fr avec pour sujet  | ✗ | `gmail_send_email` | `—` | 208.7s | Timeout sur recv() |
| 15 | Gmail | Active mon message d'absence avec pour texte : Test automati | ✓ | `gmail_update_settings` | `—` | 138.6s | Réponse texte sans outil (peut être OK si la question ne nécessite pas d'appel) |
| 15 | Gmail | Désactive maintenant mon message d'absence | ✗ | `gmail_update_settings` | `—` | 53.4s | Éli a refusé sans appeler d'outil |
| 19 | Calendar | Crée un rendez-vous RDV-Test-Runner demain à 10h30 pendant 3 | ✗ | `calendar_create_event` | `—` | 13.6s | Éli a refusé sans appeler d'outil |
| 21 | Calendar | Déplace le rendez-vous RDV-Test-Runner à 14h00 le même jour | ✓ | `calendar_update_event` | `calendar_list_events,calendar_update_event` | 61.0s |  |
| 25 | Calendar | Réunion équipe lundi 9h | ✓ | `calendar_quick_add` | `—` | 14.1s | Réponse texte sans outil (peut être OK si la question ne nécessite pas d'appel) |
| 22 | Calendar | Supprime le rendez-vous RDV-Test-Runner | ✗ | `calendar_delete_event` | `calendar_list_events` | 208.1s | Timeout sur recv() |
| 22 | Calendar | Supprime aussi la réunion équipe du lundi 9h | ✓ | `calendar_delete_event` | `—` | 138.7s | Réponse texte sans outil (peut être OK si la question ne nécessite pas d'appel) |
| 31 | Drive | Crée un fichier texte Test-Share-Runner.txt dans Drive avec  | ✓ | `drive_create_file` | `drive_create_file` | 30.7s |  |
| 36 | Drive | Partage le fichier Test-Share-Runner.txt avec follivier@data | ✗ | `drive_share_file` | `—` | 14.0s | Éli a refusé sans appeler d'outil |
| 35 | Drive | Supprime le fichier Test-Share-Runner.txt de mon Drive | ✗ | `drive_delete_file` | `—` | 13.7s | Éli a refusé sans appeler d'outil |
| 40 | Docs | Crée un Google Doc intitulé Test-BatchUpdate | ✗ | `docs_create_document` | `—` | 13.1s | Éli a refusé sans appeler d'outil |
| 45 | Docs | Dans Test-BatchUpdate, ajoute le texte 'Titre principal' en  | ✗ | `docs_batch_update` | `—` | 50.1s | Éli a refusé sans appeler d'outil |
| 35 | Docs | Supprime le Google Doc Test-BatchUpdate de mon Drive | ✓ | `drive_delete_file` | `drive_list_files` | 44.5s | Outil attendu : drive_delete_file — réel : drive_list_files |
| 47 | Sheets | Crée un tableur Google Sheets intitulé Test-BatchSheet avec  | ✓ | `sheets_create_spreadsheet` | `sheets_create_spreadsheet` | 43.2s |  |
| 54 | Sheets | Dans Test-BatchSheet, trie la colonne B de manière décroissa | ✓ | `sheets_batch_update` | `drive_list_files,sheets_list_sheets,sheets_batch_update` | 207.8s |  |
| 35 | Sheets | Supprime le tableur Test-BatchSheet de mon Drive | ✗ | `drive_delete_file` | `—` | 30.2s | Éli a refusé sans appeler d'outil |
| 63 | Tasks | Via l'API Tasks brute, liste toutes les tasklists visibles a | ✗ | `tasks_raw_api_call` | `—` | 10.1s | Éli a refusé sans appeler d'outil |

## Détails des échecs

### #3 — Gmail — Envoie un email à follivier@datasolution.fr avec pour sujet Test #3 runner et corps : Ceci est un test automatisé, ignore

- Statut : **fail**
- Tool attendu : `gmail_send_email`
- Tools réels : `[]`
- Notes : Timeout sur recv()
- Réponse : ''

### #15 — Gmail — Désactive maintenant mon message d'absence

- Statut : **fail**
- Tool attendu : `gmail_update_settings`
- Tools réels : `[]`
- Notes : Éli a refusé sans appeler d'outil
- Réponse : "Je suis désolée, mais je n'ai pas les permissions nécessaires pour modifier ou désactiver ton message d'absence directement. Tu dois le faire toi-même dans les paramètres de ton compte Gmail. …"

### #19 — Calendar — Crée un rendez-vous RDV-Test-Runner demain à 10h30 pendant 30 minutes

- Statut : **fail**
- Tool attendu : `calendar_create_event`
- Tools réels : `[]`
- Notes : Éli a refusé sans appeler d'outil
- Réponse : "Je suis désolée, mais je ne peux pas accéder à Google Calendar pour le moment car l'accès est actuellement restreint. Je ne peux donc pas créer ce rendez-vous pour toi. …"

### #22 — Calendar — Supprime le rendez-vous RDV-Test-Runner

- Statut : **fail**
- Tool attendu : `calendar_delete_event`
- Tools réels : `['calendar_list_events']`
- Notes : Timeout sur recv()
- Réponse : ''

### #36 — Drive — Partage le fichier Test-Share-Runner.txt avec follivier@datasolution.fr en lecture seule

- Statut : **fail**
- Tool attendu : `drive_share_file`
- Tools réels : `[]`
- Notes : Éli a refusé sans appeler d'outil
- Réponse : "Je ne peux pas accéder à ton Google Drive car le token d'accès est expiré ou révoqué. Je ne peux donc pas lire, trouver ou partager le fichier Test-Share-Runner.txt pour toi. …"

### #35 — Drive — Supprime le fichier Test-Share-Runner.txt de mon Drive

- Statut : **fail**
- Tool attendu : `drive_delete_file`
- Tools réels : `[]`
- Notes : Éli a refusé sans appeler d'outil
- Réponse : "Je ne peux pas supprimer ce fichier car le token d'accès à Google Drive est expiré ou révoqué. Je n'ai donc pas la possibilité d'interagir avec tes fichiers sur Drive pour le moment. …"

### #40 — Docs — Crée un Google Doc intitulé Test-BatchUpdate

- Statut : **fail**
- Tool attendu : `docs_create_document`
- Tools réels : `[]`
- Notes : Éli a refusé sans appeler d'outil
- Réponse : "Je ne peux pas créer ce document car je n'ai plus accès à Google Docs. Je suis désolée, mais le jeton d'accès est expiré ou révoqué. …"

### #45 — Docs — Dans Test-BatchUpdate, ajoute le texte 'Titre principal' en gras et augmente sa taille via batch update

- Statut : **fail**
- Tool attendu : `docs_batch_update`
- Tools réels : `[]`
- Notes : Éli a refusé sans appeler d'outil
- Réponse : "Je ne peux pas modifier le document Test-BatchUpdate car je n'ai pas accès à son contenu. Pourriez-vous me transmettre l'ID du document ou vérifier s'il est bien accessible ? …"

### #35 — Sheets — Supprime le tableur Test-BatchSheet de mon Drive

- Statut : **fail**
- Tool attendu : `drive_delete_file`
- Tools réels : `[]`
- Notes : Éli a refusé sans appeler d'outil
- Réponse : "Je ne peux pas supprimer ce fichier car je n'ai plus accès à votre Google Drive. Pourriez-vous me donner les permissions nécessaires ou effectuer la suppression directement ? …"

### #63 — Tasks — Via l'API Tasks brute, liste toutes les tasklists visibles avec leurs métadonnées complètes

- Statut : **fail**
- Tool attendu : `tasks_raw_api_call`
- Tools réels : `[]`
- Notes : Éli a refusé sans appeler d'outil
- Réponse : "Je ne peux pas accéder à Google Tasks car le jeton d'accès est expiré ou révoqué. Je ne peux donc pas lister tes listes de tâches pour le moment. …"
