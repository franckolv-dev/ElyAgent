# ELY — Rapport de test-runner

- Total exécutés : **48**
- ✓ Pass : **48**
- ✗ Fail : **0**
- ⧖ HITL timeout : **0**
- ⊘ Skip : **0**

| # | Section | Prompt | Statut | Tool attendu | Tools réels | Temps | Notes |
|---|---|---|:---:|---|---|---:|---|
| 1 | Gmail | Montre-moi mes 5 derniers emails non lus | ✓ | `gmail_list_emails` | `gmail_list_emails,gmail_mark_read` | 19.9s |  |
| 2 | Gmail | Lis l'email de Google Play | ✓ | `gmail_read_email` | `gmail_list_emails,gmail_read_email` | 30.9s |  |
| 6 | Gmail | Montre-moi mes brouillons | ✓ | `gmail_list_drafts` | `gmail_list_drafts,gmail_read_email` | 27.3s |  |
| 9 | Gmail | Quels sont mes labels Gmail ? | ✓ | `gmail_list_labels` | `gmail_list_labels,save_user_preference` | 47.2s |  |
| 18 | Calendar | Quels sont mes rendez-vous cette semaine ? | ✓ | `calendar_list_events` | `calendar_list_events,calendar_get_event` | 13.7s |  |
| 23 | Calendar | Suis-je libre jeudi entre 14h et 16h ? | ✓ | `calendar_check_availability` | `calendar_check_availability` | 38.4s |  |
| 24 | Calendar | Liste mes calendriers Google | ✓ | `calendar_list_calendars` | `calendar_list_calendars,calendar_list_events` | 70.6s |  |
| 28 | Drive | Liste mes fichiers récents dans Drive | ✓ | `drive_list_files` | `drive_list_files` | 34.6s |  |
| 40 | Docs | Crée un Google Doc intitulé Test-Runner-Doc | ✓ | `docs_create_document` | `docs_create_document,save_user_preference` | 21.8s |  |
| 41 | Docs | Lis le contenu du document Test-Runner-Doc | ✓ | `docs_read_document` | `docs_read_document,drive_list_files` | 30.5s |  |
| 42 | Docs | Ajoute le texte : Ceci est un paragraphe de test à la fin du | ✓ | `docs_append_text` | `docs_read_document,drive_list_files,docs_append_text` | 32.7s |  |
| 43 | Docs | Remplace le mot 'test' par 'validation' dans le document Tes | ✓ | `docs_replace_text` | `docs_replace_text,drive_list_files` | 29.4s |  |
| 44 | Docs | Insère un tableau 3x3 dans le document Test-Runner-Doc | ✓ | `docs_insert_table` | `docs_read_document,docs_insert_table` | 23.2s |  |
| 47 | Sheets | Crée un tableur Google Sheets intitulé Test-Runner-Sheet | ✓ | `sheets_create_spreadsheet` | `sheets_create_spreadsheet,save_user_preference` | 25.8s |  |
| 49 | Sheets | Dans Test-Runner-Sheet, ajoute les lignes Janvier,1000,900 e | ✓ | `sheets_append_rows` | `sheets_read_spreadsheet,sheets_append_rows` | 27.8s |  |
| 50 | Sheets | Dans Test-Runner-Sheet, mets la cellule B2 à 1500 | ✓ | `sheets_update_cells` | `sheets_read_spreadsheet,drive_list_files,sheets_update_cells,sheets_list_sheets` | 66.6s |  |
| 52 | Sheets | Dans Test-Runner-Sheet, ajoute un onglet nommé Trimestre2 | ✓ | `sheets_add_sheet` | `drive_list_files,sheets_add_sheet` | 38.1s |  |
| 53 | Sheets | Liste les onglets de Test-Runner-Sheet | ✓ | `sheets_list_sheets` | `sheets_list_sheets,sheets_read_spreadsheet` | 28.6s |  |
| 56 | Tasks | Montre-moi mes tâches en cours | ✓ | `tasks_list` | `tasks_list` | 20.8s |  |
| 57 | Tasks | Crée la tâche : Tester ELY test-runner, à faire demain | ✓ | `tasks_create` | `tasks_create,tasks_list` | 20.3s |  |
| 61 | Tasks | Liste mes listes de tâches | ✓ | `tasks_list_tasklists` | `tasks_list_tasklists,tasks_list` | 20.4s |  |
| 62 | Tasks | Crée une nouvelle liste de tâches nommée Tests-Runner | ✓ | `tasks_create_tasklist` | `tasks_create_tasklist,tasks_list_tasklists` | 20.3s |  |
| 65 | Contacts | Liste mes 10 premiers contacts | ✓ | `contacts_list` | `contacts_list,contacts_get` | 22.3s |  |
| 72 | Web | Cherche les actualités sur l'IA générative | ✓ | `web_search` | `web_search_news,news_get_headlines` | 21.6s | Outil attendu : web_search — réel : web_search_news,news_get_headlines |
| 73 | Web | Dernières nouvelles en technologie | ✓ | `web_search_news` | `news_get_headlines` | 13.4s | Outil attendu : web_search_news — réel : news_get_headlines |
| 74 | Web | Va sur https://example.com et dis-moi ce qu'il y a | ✓ | `browser_navigate` | `browser_navigate` | 11.6s |  |
| 81 | Web | Cherche les actualités sur la tech en France | ✓ | `news_get_headlines` | `web_search_news` | 22.7s | Outil attendu : news_get_headlines — réel : web_search_news |
| 82 | Maps | Quelle est l'adresse de la Tour Eiffel ? | ✓ | `maps_geocode` | `web_search,save_user_preference` | 20.7s | Outil attendu : maps_geocode — réel : web_search,save_user_preference |
| 83 | Maps | Comment aller de Paris à Lyon en voiture ? | ✓ | `maps_directions` | `web_search` | 16.7s | Outil attendu : maps_directions — réel : web_search |
| 84 | Maps | Trouve les restaurants italiens près de la Place de la Répub | ✓ | `maps_nearby` | `web_search` | 22.4s | Outil attendu : maps_nearby — réel : web_search |
| 85 | Maps | Quelle adresse correspond à ces coordonnées : 48.8566, 2.352 | ✓ | `maps_reverse_geocode` | `maps_reverse_geocode,save_user_preference` | 16.2s |  |
| 86 | Météo | Quel temps fait-il à Lyon aujourd'hui ? | ✓ | `weather_get` | `weather_get,save_user_preference` | 19.8s |  |
| 87 | Traduction | Traduis en anglais : L'intelligence artificielle change le m | ✓ | `translate_text` | `translate_text,save_user_preference` | 19.3s |  |
| 88 | YouTube | Cherche des vidéos YouTube sur LangGraph | ✓ | `youtube_search` | `youtube_search` | 22.8s |  |
| 96 | QR | Génère un QR code pour https://github.com/franckolv-dev/Phys | ✓ | `qrcode_generate` | `qrcode_generate,save_user_preference` | 44.5s |  |
| 97 | QR | Crée un QR code WiFi pour le réseau MonWifi, mot de passe Te | ✓ | `qrcode_generate_wifi` | `qrcode_generate_wifi` | 27.0s |  |
| 98 | QR | Crée un QR code vCard pour Franck Ollivier, email franck@tes | ✓ | `qrcode_generate_vcard` | `contacts_search,contacts_create` | 69.3s | Outil attendu : qrcode_generate_vcard — réel : contacts_search,contacts_create |
| 99 | Memory | Souviens-toi que je préfère les réponses courtes | ✓ | `save_user_preference` | `save_user_preference` | 11.4s |  |
| 101 | Notes | Crée une note intitulée Idées-Test-Runner avec le contenu :  | ✓ | `notes_create` | `notes_create,notes_update` | 17.9s |  |
| 102 | Notes | Liste mes notes | ✓ | `notes_list` | `notes_list,notes_read` | 17.4s |  |
| 103 | Notes | Lis ma note Idées-Test-Runner | ✓ | `notes_read` | `notes_read,notes_list` | 23.3s |  |
| 106 | Notes | Cherche dans mes notes le mot test | ✓ | `notes_search` | `notes_search,notes_read` | 16.9s |  |
| 107 | RAG | Que contient ma base de connaissances ? | ✓ | `knowledge_list` | `knowledge_list` | 10.9s |  |
| 135 | Scheduler | Liste mes tâches planifiées | ✓ | `scheduler_list_tasks` | `scheduler_list_tasks` | 19.9s |  |
| 139 | Watchdog | Liste les sites que tu surveilles | ✓ | `watchdog_list` | `watchdog_list` | 17.2s |  |
| 141 | Python | Exécute ce code Python : print([x**2 for x in range(10)]) | ✓ | `python_execute` | `python_execute` | 18.7s |  |
| 144 | MCP | Liste les serveurs MCP disponibles dans ta bibliothèque | ✓ | `mcp_list_library` | `ssh_execute,system_info` | 18.9s | Outil attendu : mcp_list_library — réel : ssh_execute,system_info |
| 147 | Briefing | Génère mon briefing du matin | ✓ | `briefing_generate` | `briefing_generate` | 16.8s |  |

## Détails des échecs
