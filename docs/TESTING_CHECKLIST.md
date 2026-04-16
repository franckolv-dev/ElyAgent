# ✅ ELY — Liste de tests complète (148 outils)

> Coche chaque case au fur et à mesure. Toutes les phrases peuvent être envoyées telles quelles dans le chat ELY.
>
> **Légende :**
> - ⚠️ **HITL** — ELY demandera ta confirmation avant d'exécuter
> - 🔌 **Desktop** — Requiert ELY Desktop installé et connecté (`cd desktop && ./ely-desktop`)
> - 🔑 **Config** — Requiert une clé API ou un host configuré dans `.env`
> - 📄 **RAG** — Requiert au moins un document uploadé via la page Connaissances

---

## 📧 1. Gmail (17 outils)

- [ ] **1.** "Montre-moi mes 5 derniers emails non lus" → `gmail_list_emails`
- [ ] **2.** "Lis l'email de [expéditeur récent]" → `gmail_read_email`
- [ ] **3.** "Envoie un email à ton-adresse@test.com avec pour sujet Test ELY et corps : Ça fonctionne" → `gmail_send_email` ⚠️ HITL
- [ ] **4.** "Réponds à cet email en disant que je l'ai bien reçu" *(après lecture d'un mail)* → `gmail_reply_email` ⚠️ HITL
- [ ] **5.** "Crée un brouillon pour alice@test.com : sujet Réunion vendredi" → `gmail_create_draft`
- [ ] **6.** "Montre-moi mes brouillons" → `gmail_list_drafts`
- [ ] **7.** "Marque cet email comme lu" → `gmail_mark_read`
- [ ] **8.** "Marque cet email comme non lu" → `gmail_mark_unread`
- [ ] **9.** "Quels sont mes labels Gmail ?" → `gmail_list_labels`
- [ ] **10.** "Crée un label nommé ELY-Test" → `gmail_create_label`
- [ ] **11.** "Déplace les emails de newsletter@xxx.com dans les Promotions" → `gmail_move_emails` ⚠️ HITL
- [ ] **12.** "Supprime les emails de plus de 6 mois dans Promotions" → `gmail_trash_emails` ⚠️ HITL
- [ ] **13.** "Cherche mes emails contenant le mot facture du mois dernier" → `gmail_search_for_cleanup`
- [ ] **14.** "Archive les 10 derniers emails de mon dossier Promotions" → `gmail_batch_modify` ⚠️ HITL
- [ ] **15.** "Active mon message d'absence : je suis en vacances jusqu'au 30" → `gmail_update_settings` ⚠️ HITL
- [ ] **16.** "Envoie-moi le fichier [ID Drive] en pièce jointe par email" → `gmail_send_with_attachment` ⚠️ HITL
- [ ] **17.** "Utilise l'API Gmail brute pour lister mes paramètres de signature" → `gmail_raw_api_call`

---

## 📅 2. Google Calendar (10 outils)

- [ ] **18.** "Quels sont mes rendez-vous cette semaine ?" → `calendar_list_events`
- [ ] **19.** "Crée un rendez-vous dentiste vendredi à 10h30 pendant 45 min" → `calendar_create_event` ⚠️ HITL
- [ ] **20.** "Lis les détails de mon prochain rendez-vous" → `calendar_get_event`
- [ ] **21.** "Déplace mon rendez-vous de vendredi à lundi 9h" → `calendar_update_event` ⚠️ HITL
- [ ] **22.** "Supprime le rendez-vous dentiste" → `calendar_delete_event` ⚠️ HITL
- [ ] **23.** "Suis-je libre jeudi entre 14h et 16h ?" → `calendar_check_availability`
- [ ] **24.** "Liste mes calendriers Google" → `calendar_list_calendars`
- [ ] **25.** "Réunion équipe lundi 9h" *(langage naturel court)* → `calendar_quick_add` ⚠️ HITL
- [ ] **26.** "Crée une réunion Google Meet avec ton-email@test.com mardi à 14h" → `calendar_create_meet_event` ⚠️ HITL
- [ ] **27.** "Via l'API brute Calendar, montre-moi les ACL de mon calendrier principal" → `calendar_raw_api_call`

---

## 🗂 3. Google Drive (12 outils)

- [ ] **28.** "Liste mes fichiers récents dans Drive" → `drive_list_files`
- [ ] **29.** "Lis le contenu du fichier [nom ou ID]" → `drive_read_file`
- [ ] **30.** "Crée un dossier nommé ELY-Tests dans Drive" → `drive_create_folder`
- [ ] **31.** "Crée un fichier texte test.txt dans Drive avec contenu : Bonjour ELY" → `drive_create_file`
- [ ] **32.** "Mets à jour le fichier test.txt avec le contenu : Mis à jour par ELY" → `drive_update_file`
- [ ] **33.** "Déplace test.txt dans le dossier ELY-Tests" → `drive_move_file` ⚠️ HITL
- [ ] **34.** "Renomme test.txt en test-ely.txt" → `drive_rename_file`
- [ ] **35.** "Supprime le fichier test-ely.txt" → `drive_delete_file` ⚠️ HITL
- [ ] **36.** "Partage le dossier ELY-Tests avec alice@test.com en lecture seule" → `drive_share_file` ⚠️ HITL
- [ ] **37.** "Duplique ce document en nommant la copie Copie-Test" → `drive_copy_file`
- [ ] **38.** "Exporte ce Google Doc en PDF" → `drive_export_file`
- [ ] **39.** "Via l'API Drive brute, liste les révisions du fichier [ID]" → `drive_raw_api_call`

---

## 📝 4. Google Docs (7 outils)

- [ ] **40.** "Crée un Google Doc intitulé Test ELY" → `docs_create_document`
- [ ] **41.** "Lis le contenu du document Test ELY" → `docs_read_document`
- [ ] **42.** "Ajoute le texte : Ceci est un paragraphe de test à la fin du document" → `docs_append_text`
- [ ] **43.** "Remplace le mot 'test' par 'validation' dans le document" → `docs_replace_text`
- [ ] **44.** "Insère un tableau 3x3 dans le document" → `docs_insert_table`
- [ ] **45.** "Mets le titre en gras et augmente sa taille via batch update" → `docs_batch_update` ⚠️ HITL
- [ ] **46.** "Via l'API Docs brute, liste les styles de ce document" → `docs_raw_api_call`

---

## 📊 5. Google Sheets (9 outils)

- [ ] **47.** "Crée un tableur Google Sheets intitulé Budget ELY" → `sheets_create_spreadsheet`
- [ ] **48.** "Lis la plage A1:C5 de ce tableur" → `sheets_read_spreadsheet`
- [ ] **49.** "Ajoute les lignes : Janvier, 1000, 900 et Février, 1200, 1100" → `sheets_append_rows`
- [ ] **50.** "Mets la cellule B2 à 1500" → `sheets_update_cells`
- [ ] **51.** "Supprime la ligne 3" → `sheets_delete_rows`
- [ ] **52.** "Ajoute un onglet nommé Trimestre2" → `sheets_add_sheet`
- [ ] **53.** "Liste les onglets de ce tableur" → `sheets_list_sheets`
- [ ] **54.** "Trie la colonne B de manière décroissante via batch update" → `sheets_batch_update` ⚠️ HITL
- [ ] **55.** "Via l'API Sheets brute, récupère les métadonnées du tableur" → `sheets_raw_api_call`

---

## ✅ 6. Google Tasks (8 outils)

- [ ] **56.** "Montre-moi mes tâches en cours" → `tasks_list`
- [ ] **57.** "Crée la tâche : Tester ELY complètement, à faire demain" → `tasks_create`
- [ ] **58.** "Marque la tâche Tester ELY comme terminée" → `tasks_complete`
- [ ] **59.** "Modifie la tâche pour la déplacer à lundi" → `tasks_update`
- [ ] **60.** "Supprime la tâche Tester ELY" → `tasks_delete` ⚠️ HITL
- [ ] **61.** "Liste mes listes de tâches" → `tasks_list_tasklists`
- [ ] **62.** "Crée une nouvelle liste de tâches nommée Tests ELY" → `tasks_create_tasklist`
- [ ] **63.** "Via l'API Tasks brute, déplace cette tâche en haut de la liste" → `tasks_raw_api_call`

---

## 👤 7. Google Contacts (8 outils)

- [ ] **64.** "Cherche le contact Alice dans mes contacts Google" → `contacts_search`
- [ ] **65.** "Liste mes 10 premiers contacts" → `contacts_list`
- [ ] **66.** "Crée un contact : Test ELY, email test-ely@example.com, tél 0600000000" → `contacts_create`
- [ ] **67.** "Affiche les détails complets du contact Test ELY" → `contacts_get`
- [ ] **68.** "Mets à jour le numéro de téléphone du contact Test ELY en 0611111111" → `contacts_update`
- [ ] **69.** "Supprime le contact Test ELY" → `contacts_delete` ⚠️ HITL
- [ ] **70.** "Crée ces 3 contacts en lot : [liste JSON]" → `contacts_batch_operations` ⚠️ HITL
- [ ] **71.** "Via l'API Contacts brute, liste les groupes de contacts" → `contacts_raw_api_call`

---

## 🌐 8. Navigation web & Recherche (10 outils)

- [ ] **72.** "Cherche les actualités sur l'IA générative" → `web_search`
- [ ] **73.** "Dernières nouvelles en technologie" → `web_search_news`
- [ ] **74.** "Va sur https://example.com et dis-moi ce qu'il y a" → `browser_navigate`
- [ ] **75.** "Cherche des images de couchers de soleil" → `browser_search_images`
- [ ] **76.** "Extrais le texte de la page actuelle" → `browser_get_text`
- [ ] **77.** "Prends une capture d'écran du navigateur" → `browser_screenshot`
- [ ] **78.** "Clique sur le premier lien de la page" → `browser_click` ⚠️ HITL
- [ ] **79.** "Remplis le champ de recherche avec ELY agent" → `browser_fill` ⚠️ HITL
- [ ] **80.** "Ferme le navigateur" → `browser_close`
- [ ] **81.** "Cherche les actualités sur la tech en France" → `news_get_headlines`

---

## 📍 9. Maps & Géolocalisation (4 outils)

- [ ] **82.** "Quelle est l'adresse de la Tour Eiffel ?" → `maps_geocode`
- [ ] **83.** "Comment aller de Paris à Lyon en voiture ?" → `maps_directions`
- [ ] **84.** "Trouve les restaurants italiens près de la Place de la République Paris" → `maps_nearby`
- [ ] **85.** "Quelle adresse correspond à ces coordonnées : 48.8566, 2.3522 ?" → `maps_reverse_geocode`

---

## ☁️ 10. Météo & Traduction (2 outils)

- [ ] **86.** "Quel temps fait-il à Lyon aujourd'hui ?" → `weather_get`
- [ ] **87.** "Traduis en anglais : L'intelligence artificielle change le monde" → `translate_text`

---

## 📺 11. YouTube (3 outils)

- [ ] **88.** "Cherche des vidéos YouTube sur LangGraph" → `youtube_search`
- [ ] **89.** "Donne-moi la transcription de cette vidéo YouTube : [URL]" → `youtube_transcript`
- [ ] **90.** "Infos sur cette vidéo YouTube : [URL]" → `youtube_video_info`

---

## 📄 12. PDF & Vision (4 outils)

- [ ] **91.** "Lis ce PDF" *(joindre un PDF via le trombone)* → `pdf_read`
- [ ] **92.** "Donne-moi les infos de ce PDF (pages, taille, auteur)" → `pdf_info`
- [ ] **93.** "Analyse cette image" *(joindre une image)* → `vision_analyze_image`
- [ ] **94.** "Analyse ce PDF avec la vision IA" *(joindre un PDF avec images)* → `pdf_analyze_with_vision`

---

## 🖼 13. Génération d'images & QR codes (4 outils)

- [ ] **95.** "Génère une image d'un agent IA cyberpunk" → `generate_image`
- [ ] **96.** "Génère un QR code pour https://github.com/franckolv-dev/PhysicalAgent" → `qrcode_generate`
- [ ] **97.** "Crée un QR code WiFi pour le réseau MonWifi, mot de passe : Test1234" → `qrcode_generate_wifi`
- [ ] **98.** "Crée un QR code vCard pour Franck Ollivier, email franck@test.com" → `qrcode_generate_vcard`

---

## 💾 14. Mémoire & Notes (8 outils)

- [ ] **99.** "Souviens-toi que je préfère les réponses courtes" → `save_user_preference`
- [ ] **100.** "N'oublie jamais : je ne veux pas d'emails envoyés sans confirmation" → `save_constraint`
- [ ] **101.** "Crée une note intitulée Idées produit avec le contenu : [texte libre]" → `notes_create`
- [ ] **102.** "Liste mes notes" → `notes_list`
- [ ] **103.** "Lis ma note Idées produit" → `notes_read`
- [ ] **104.** "Mets à jour ma note Idées produit en ajoutant : ELY est génial" → `notes_update`
- [ ] **105.** "Supprime la note Idées produit" → `notes_delete`
- [ ] **106.** "Cherche dans mes notes le mot IA" → `notes_search`

---

## 📚 15. Base de connaissances RAG (3 outils)

> 📄 Prérequis : uploader au moins un document via **Settings → Connaissances**

- [ ] **107.** "Que contient ma base de connaissances ?" → `knowledge_list`
- [ ] **108.** "Cherche dans ma base de connaissances : [sujet d'un document uploadé]" → `knowledge_search`
- [ ] **109.** "Réponds à ma question en consultant mes documents : [question sur un doc]" → `smart_knowledge_query`

---

## 🖥 16. ELY Desktop — Fichiers locaux (9 outils)

> 🔌 Prérequis : ELY Desktop lancé (`cd desktop && ./ely-desktop`) et connecté

- [ ] **110.** "Liste les fichiers dans mon dossier Documents" → `desktop_list_dir`
- [ ] **111.** "Lis le fichier ~/Desktop/test.txt" → `desktop_read_file`
- [ ] **112.** "Écris Bonjour ELY dans le fichier ~/Desktop/ely-test.txt" → `desktop_write_file` ⚠️ HITL
- [ ] **113.** "Déplace ~/Desktop/ely-test.txt vers ~/Documents/" → `desktop_move_file` ⚠️ HITL
- [ ] **114.** "Supprime ~/Documents/ely-test.txt" → `desktop_delete_file` ⚠️ HITL
- [ ] **115.** "Crée un dossier ELY-Tests sur le Bureau" → `desktop_create_dir`
- [ ] **116.** "Quelle est la taille du fichier ~/Desktop/ely-test.txt ?" → `desktop_stat_file`
- [ ] **117.** "Calcule le hash MD5 de ce fichier" → `desktop_hash_file`
- [ ] **118.** "Cherche les fichiers .py dans ~/Documents/" → `desktop_search_files`

---

## 🎓 17. ELY Trainer — Guidage visuel (7 outils)

> 🔌 Prérequis : ELY Desktop + skill `os-control` activé dans Settings

- [ ] **119.** "Montre-moi comment ouvrir le Terminal sur Mac" → `trainer_start`
- [ ] **120.** "Prends une capture d'écran de mon bureau" → `trainer_screenshot`
- [ ] **121.** "Clique en position 500, 300 sur l'écran" → `trainer_click` ⚠️ HITL
- [ ] **122.** "Déplace la souris vers le centre de l'écran" → `trainer_move` ⚠️ HITL
- [ ] **123.** "Tape le texte : Bonjour depuis ELY" → `trainer_type` ⚠️ HITL
- [ ] **124.** "Exécute le raccourci Cmd+Space" → `trainer_hotkey` ⚠️ HITL
- [ ] **125.** "Quelle est la résolution de mon écran ?" → `trainer_get_screen_size`

---

## 🖱 18. Contrôle OS (6 outils)

> 🔌 Prérequis : ELY Desktop + skill `os-control` activé dans Settings

- [ ] **126.** "Prends une capture d'écran de mon ordinateur" → `os_screenshot`
- [ ] **127.** "Déplace la souris en position 500, 300" → `os_mouse_move` ⚠️ HITL
- [ ] **128.** "Clique en position 500, 300" → `os_click` ⚠️ HITL
- [ ] **129.** "Tape le texte 'test ELY' sur le clavier" → `os_type_text` ⚠️ HITL
- [ ] **130.** "Appuie sur Cmd+C" → `os_hotkey` ⚠️ HITL
- [ ] **131.** "Quelle application est active en ce moment ?" → `os_get_active_window`

---

## 🔧 19. Infrastructure & SSH (3 outils)

> 🔑 `ssh_execute` requiert un host configuré dans Settings → Hôtes SSH

- [ ] **132.** "Exécute df -h sur mon serveur [nom configuré]" → `ssh_execute` ⚠️ HITL
- [ ] **133.** "Analyse ce fichier" *(joindre un fichier log, image ou autre)* → `analyze_file`
- [ ] **134.** "Infos système sur cette machine (CPU, RAM, disque)" → `system_info`

---

## ⏰ 20. Tâches planifiées (3 outils)

- [ ] **135.** "Liste mes tâches planifiées" → `scheduler_list_tasks`
- [ ] **136.** "Rappelle-moi tous les lundis à 9h de consulter mon agenda" → `scheduler_create_task`
- [ ] **137.** "Supprime la tâche planifiée [nom]" → `scheduler_delete_task`

---

## 👁 21. Surveillance de sites web (3 outils)

- [ ] **138.** "Surveille le site https://ely.catalogmaker.fr et alerte-moi s'il tombe" → `watchdog_add`
- [ ] **139.** "Liste les sites que tu surveilles" → `watchdog_list`
- [ ] **140.** "Arrête de surveiller https://ely.catalogmaker.fr" → `watchdog_remove`

---

## 🐍 22. Sandbox Python (1 outil)

- [ ] **141.** "Exécute ce code Python : print([x\*\*2 for x in range(10)])" → `python_execute`

---

## 📢 23. WhatsApp (2 outils)

> 🔑 Requiert Meta Cloud API configurée dans `.env` (`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`)

- [ ] **142.** "Envoie un WhatsApp à +33XXXXXXXXX : Test ELY" → `whatsapp_send` ⚠️ HITL
- [ ] **143.** "Envoie le template WhatsApp hello_world au +33XXXXXXXXX" → `whatsapp_send_template` ⚠️ HITL

---

## 🧩 24. MCP — Génération dynamique de serveurs (3 outils)

- [ ] **144.** "Liste les serveurs MCP disponibles dans ta bibliothèque" → `mcp_list_library`
- [ ] **145.** "Génère un serveur MCP pour interagir avec l'API Stripe" → `mcp_generate_server`
- [ ] **146.** "Valide et déploie le serveur MCP généré" → `mcp_validate_and_deploy` ⚠️ HITL

---

## ☀️ 25. Briefing matinal (1 outil)

- [ ] **147.** "Génère mon briefing du matin" → `briefing_generate`

---

## 🏟 26. Arena LLM — Comparaison en aveugle (via UI)

- [ ] **148.** Aller sur **/arena** dans la sidebar → lancer un match → voter pour le meilleur modèle

---

## 📊 Récapitulatif

| Catégorie | Outils | Statut |
|---|---|---|
| Google Workspace | 54 | — |
| Web, Maps, Météo, Traduction | 16 | — |
| YouTube, PDF, Vision, Images, QR | 12 | — |
| Mémoire, Notes, RAG | 11 | — |
| Desktop & Contrôle OS | 22 | 🔌 Desktop requis |
| Infrastructure, SSH, Scheduler | 6 | — |
| Watchdog, Python, WhatsApp | 6 | — |
| MCP, Briefing, Arena | 5 | — |
| **TOTAL** | **148** | |

| Indicateur | Nombre |
|---|---|
| ⚠️ Actions HITL (confirmation requise) | ~30 |
| 🔌 Nécessite ELY Desktop | 22 |
| 🔑 Nécessite clé API / host configuré | ~5 |
| 📄 Nécessite document uploadé | 3 |
| ✅ Testables sans prérequis | ~88 |

---

*Généré le 2026-04-16 — ELY v1.1.0 — 32 skills, 148 outils*
