# ELY — Rapport de test-runner

- Total exécutés : **48**
- ✓ Pass : **48**
- ✗ Fail : **0**
- ⧖ HITL timeout : **0**
- ⊘ Skip : **0**

| # | Section | Prompt | Statut | Tool attendu | Tools réels | Temps | Notes |
|---|---|---|:---:|---|---|---:|---|
| 1 | Gmail | Montre-moi mes 5 derniers emails non lus | ✓ | `gmail_list_emails` | `gmail_list_emails` | 68.6s |  |
| 2 | Gmail | Lis l'email de Google Play | ✓ | `gmail_read_email` | `gmail_list_emails` | 68.0s | Outil attendu : gmail_read_email — réel : gmail_list_emails |
| 6 | Gmail | Montre-moi mes brouillons | ✓ | `gmail_list_drafts` | `gmail_list_drafts` | 61.7s |  |
| 9 | Gmail | Quels sont mes labels Gmail ? | ✓ | `gmail_list_labels` | `gmail_list_labels` | 42.3s |  |
| 18 | Calendar | Quels sont mes rendez-vous cette semaine ? | ✓ | `calendar_list_events` | `calendar_list_events` | 32.7s |  |
| 23 | Calendar | Suis-je libre jeudi entre 14h et 16h ? | ✓ | `calendar_check_availability` | `calendar_check_availability` | 95.8s |  |
| 24 | Calendar | Liste mes calendriers Google | ✓ | `calendar_list_calendars` | `calendar_list_calendars` | 155.7s |  |
| 28 | Drive | Liste mes fichiers récents dans Drive | ✓ | `drive_list_files` | `drive_list_files` | 38.9s |  |
| 40 | Docs | Crée un Google Doc intitulé Test-Runner-Doc | ✓ | `docs_create_document` | `docs_create_document` | 30.5s |  |
| 41 | Docs | Lis le contenu du document Test-Runner-Doc | ✓ | `docs_read_document` | `drive_list_files,docs_read_document` | 42.5s |  |
| 42 | Docs | Ajoute le texte : Ceci est un paragraphe de test à la fin du | ✓ | `docs_append_text` | `drive_list_files,docs_append_text` | 41.6s |  |
| 43 | Docs | Remplace le mot 'test' par 'validation' dans le document Tes | ✓ | `docs_replace_text` | `drive_list_files,docs_replace_text` | 45.9s |  |
| 44 | Docs | Insère un tableau 3x3 dans le document Test-Runner-Doc | ✓ | `docs_insert_table` | `drive_list_files,save_constraint` | 43.1s | Outil attendu : docs_insert_table — réel : drive_list_files,save_constraint |
| 47 | Sheets | Crée un tableur Google Sheets intitulé Test-Runner-Sheet | ✓ | `sheets_create_spreadsheet` | `sheets_create_spreadsheet,save_constraint` | 54.6s |  |
| 49 | Sheets | Dans Test-Runner-Sheet, ajoute les lignes Janvier,1000,900 e | ✓ | `sheets_append_rows` | `sheets_append_rows,save_constraint` | 67.0s |  |
| 50 | Sheets | Dans Test-Runner-Sheet, mets la cellule B2 à 1500 | ✓ | `sheets_update_cells` | `sheets_update_cells,save_constraint` | 68.2s |  |
| 52 | Sheets | Dans Test-Runner-Sheet, ajoute un onglet nommé Trimestre2 | ✓ | `sheets_add_sheet` | `sheets_add_sheet` | 51.9s |  |
| 53 | Sheets | Liste les onglets de Test-Runner-Sheet | ✓ | `sheets_list_sheets` | `sheets_list_sheets,save_constraint` | 50.4s |  |
| 56 | Tasks | Montre-moi mes tâches en cours | ✓ | `tasks_list` | `tasks_list` | 26.9s |  |
| 57 | Tasks | Crée la tâche : Tester ELY test-runner, à faire demain | ✓ | `tasks_create` | `tasks_create,save_constraint` | 40.2s |  |
| 61 | Tasks | Liste mes listes de tâches | ✓ | `tasks_list_tasklists` | `tasks_list_tasklists` | 38.2s |  |
| 62 | Tasks | Crée une nouvelle liste de tâches nommée Tests-Runner | ✓ | `tasks_create_tasklist` | `tasks_create_tasklist` | 38.6s |  |
| 65 | Contacts | Liste mes 10 premiers contacts | ✓ | `contacts_list` | `contacts_list,save_constraint` | 40.1s |  |
| 72 | Web | Cherche les actualités sur l'IA générative | ✓ | `web_search` | `web_search_news` | 56.3s | Outil attendu : web_search — réel : web_search_news |
| 73 | Web | Dernières nouvelles en technologie | ✓ | `web_search_news` | `web_search_news` | 35.6s |  |
| 74 | Web | Va sur https://example.com et dis-moi ce qu'il y a | ✓ | `browser_navigate` | `browser_navigate` | 32.2s |  |
| 81 | Web | Cherche les actualités sur la tech en France | ✓ | `news_get_headlines` | `web_search_news` | 44.4s | Outil attendu : news_get_headlines — réel : web_search_news |
| 82 | Maps | Quelle est l'adresse de la Tour Eiffel ? | ✓ | `maps_geocode` | `maps_geocode` | 50.6s |  |
| 83 | Maps | Comment aller de Paris à Lyon en voiture ? | ✓ | `maps_directions` | `maps_directions` | 23.6s |  |
| 84 | Maps | Trouve les restaurants italiens près de la Place de la Répub | ✓ | `maps_nearby` | `maps_nearby,web_search` | 55.8s |  |
| 85 | Maps | Quelle adresse correspond à ces coordonnées : 48.8566, 2.352 | ✓ | `maps_reverse_geocode` | `maps_reverse_geocode` | 37.7s |  |
| 86 | Météo | Quel temps fait-il à Lyon aujourd'hui ? | ✓ | `weather_get` | `weather_get` | 33.6s |  |
| 87 | Traduction | Traduis en anglais : L'intelligence artificielle change le m | ✓ | `translate_text` | `translate_text` | 41.6s |  |
| 88 | YouTube | Cherche des vidéos YouTube sur LangGraph | ✓ | `youtube_search` | `youtube_search` | 42.4s |  |
| 96 | QR | Génère un QR code pour https://github.com/franckolv-dev/Phys | ✓ | `qrcode_generate` | `qrcode_generate` | 56.8s |  |
| 97 | QR | Crée un QR code WiFi pour le réseau MonWifi, mot de passe Te | ✓ | `qrcode_generate_wifi` | `qrcode_generate_wifi,save_user_preference` | 68.1s |  |
| 98 | QR | Crée un QR code vCard pour Franck Ollivier, email franck@tes | ✓ | `qrcode_generate_vcard` | `qrcode_generate_vcard` | 67.8s |  |
| 99 | Memory | Souviens-toi que je préfère les réponses courtes | ✓ | `save_user_preference` | `save_user_preference` | 23.9s |  |
| 101 | Notes | Crée une note intitulée Idées-Test-Runner avec le contenu :  | ✓ | `notes_create` | `notes_create` | 25.8s |  |
| 102 | Notes | Liste mes notes | ✓ | `notes_list` | `notes_list` | 39.5s |  |
| 103 | Notes | Lis ma note Idées-Test-Runner | ✓ | `notes_read` | `notes_search,notes_read` | 32.8s |  |
| 106 | Notes | Cherche dans mes notes le mot test | ✓ | `notes_search` | `notes_search` | 24.9s |  |
| 107 | RAG | Que contient ma base de connaissances ? | ✓ | `knowledge_list` | `knowledge_list` | 22.2s |  |
| 135 | Scheduler | Liste mes tâches planifiées | ✓ | `scheduler_list_tasks` | `scheduler_list_tasks` | 48.5s |  |
| 139 | Watchdog | Liste les sites que tu surveilles | ✓ | `watchdog_list` | `watchdog_list` | 26.8s |  |
| 141 | Python | Exécute ce code Python : print([x**2 for x in range(10)]) | ✓ | `python_execute` | `python_execute` | 32.6s |  |
| 144 | MCP | Liste les serveurs MCP disponibles dans ta bibliothèque | ✓ | `mcp_list_library` | `mcp_list_library` | 45.2s |  |
| 147 | Briefing | Génère mon briefing du matin | ✓ | `briefing_generate` | `briefing_generate` | 31.5s |  |

## Détails des échecs
