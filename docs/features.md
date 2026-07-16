# ELY Agent — Fonctionnalités

## Assistant IA personnel sécurisé

ELY est un assistant IA personnel qui s'exécute sur votre propre infrastructure.
Il se connecte à vos services (email, calendrier, fichiers) et exécute des tâches
sur vos serveurs — tout en garantissant que vos données restent sous votre contrôle.

---

## Canaux de communication

| Canal | Statut | Description |
|---|---|---|
| Interface Web | ✅ Actif | Chat temps réel avec avatar 3D animé |
| Voix | ✅ Actif | Mot-clé « Éli » / « Ely », transcription Whisper + synthèse vocale (TTS), `/ws/voice` |
| Telegram | ✅ Actif | Bot privé (webhook), même agent, mêmes permissions |
| WhatsApp | ✅ Actif | Compte perso appairé par QR (neonize) + Meta Cloud API |
| Slack | ✅ Actif | Bot via Socket Mode |
| Discord | ✅ Actif | Bot privé |
| Notifications push ntfy | ✅ Actif | Alertes push via ntfy |
| PWA | ✅ Actif | Application web installable |
| App iOS | ✅ Actif | Application native iOS |
| App Android | ✅ Actif | Application native Android (push FCM) |
| API REST | ✅ Actif | Pour intégrations tierces |

## Google Workspace

ELY se connecte au compte Google de chaque utilisateur via OAuth2 :

| Service | Capacités |
|---|---|
| **Gmail** | Lire, chercher, envoyer des emails |
| **Google Calendar** | Consulter et créer des événements |
| **Google Drive** | Lecture / écriture, dont téléversement de fichiers locaux/binaires (captures, PNG/PDF) via `drive_upload_local_file` |
| **Google Docs** | Créer, lire, modifier des documents (≈ Word) |
| **Google Sheets** | Créer, lire, ajouter des lignes (≈ Excel) |
| **Google Tasks** | Lister, créer, compléter des tâches |
| **Google Contacts** | Lister, chercher, gérer les contacts |

≈ 75 outils Google au total, avec un escape hatch `raw_api_call` pour les appels API non couverts.

- Multi-profil : chaque utilisateur connecte son propre compte. Un même utilisateur ELY peut relier plusieurs comptes Google (multi-compte) et en cibler un via un alias `account`.
- Credentials OAuth app configurables via l'interface admin (pas de .env)
- L'agent n'accède aux services que sur demande explicite

## Exécution SSH

- Commandes sur serveurs distants configurés
- Whitelist de commandes par hôte (pas d'exécution arbitraire)
- Exécution non-bloquante (asyncio)
- Validation humaine obligatoire

## Mémoire & Apprentissage

### Court terme
- Historique de conversation (40 derniers messages) injecté à chaque appel LLM
- L'agent se souvient de ce qui a été dit dans la conversation en cours

### Long terme (mémoire cognitive typée)
- Mémoire typée à 5 types : EPISODIC, SEMANTIC_USER, PROCEDURAL, ERROR, CONSTRAINT
- Stockage Qdrant local + recherche plein-texte SQLite FTS5
- Rappel via `memory_recall(type, query)`
- L'agent retrouve les informations pertinentes des conversations passées (cross-conversation)

### Apprentissage sécuritaire
- Les refus HITL deviennent des règles permanentes
- L'agent ne reproposera jamais une action bannie

## Autonomie

- **`delegate`** : lance 2 à 6 sous-tâches autonomes en parallèle (enfants HITL-bloqués, profondeur max 1)
- **Missions structurées YAML** : steps / foreach + gestion des cas limites avec `ask_user` (question multicanal, pause puis reprise)
- **Boucle d'auto-amélioration** : apprentissage de playbooks depuis les échecs + LLM-juge + page admin Incidents
- **`find_tool`** : découverte d'outils à la demande sur un catalogue de 190+ outils (≈ 196)

## Serveur MCP & clés API

- ELY s'expose **comme** serveur MCP sur `/api/mcp` (FastMCP Streamable-HTTP), authentifié par clé API personnelle.
- **Clés API personnelles** : Réglages → Clés API (`/settings/api-keys`), préfixe `ely_api_`, affichée en clair une seule fois (hash SHA-256), max 20 actives par utilisateur, révocable ; sert de bearer pour l'endpoint MCP.
- **4 outils MCP v1** : `ely_chat` (mode autonome-sûr, actions irréversibles bloquées), lister les tâches planifiées, créer une tâche planifiée, recherche mémoire.
- Permet de connecter Claude Desktop, Cursor, etc.
- ELY est aussi **client MCP (durci)** : elle consomme des serveurs MCP externes (config admin) — identifiants par-utilisateur chiffrés dans le Vault, garde SSRF/anti-DNS-rebinding, ACL/HITL par outil (lecture sans friction, écriture confirmée une fois), workflow quarantaine/confiance, recherche du registre MCP officiel. Connexion OAuth 2.1/PKCE, sandbox des serveurs stdio locaux et resources/prompts en lecture seule arrivent derrière des flags désactivés par défaut. Détails : [integrations/mcp-as-client.md](integrations/mcp-as-client.md).

## Actions réversibles (annuler)

- ELY enregistre une **action de compensation** pour ses opérations destructives → vous pouvez **annuler la dernière** (fichier Drive supprimé, renommé ou déplacé, remis à l'identique).
- Déclenchement en **chat** (« annule »), via l'**API**, ou depuis **`/me/reversible-actions`** (liste, Annuler en un clic, fenêtre d'expiration).
- Chaque annulation est **vérifiée** (ELY confirme que le retour arrière a eu lieu) ; les entrées se purgent automatiquement après leur fenêtre.

## Fournisseurs LLM

| Provider | Localisation | Tier RGPD |
|---|---|---|
| **Anthropic Claude** | USA | B/C |
| **Google Gemini** | USA | C |
| **OpenAI** | USA | C |
| **GPT-5.5** (via abonnement ChatGPT, sans clé API) | USA | C |
| **OpenRouter** | Agrégateur | variable |
| **Mistral AI** | France/Europe | A (RGPD) |
| **DeepSeek** | Chine | C |
| **Zhipu** | Chine | C |
| **Qwen** | Chine | C |
| **Moonshot** | Chine | C |
| **Ollama** (local) | Votre machine | A (100% local) |
| **LM Studio** (local) | Votre machine | A (100% local) |

≈ 12 fournisseurs au total. Le provider se configure par tier (A / B / C / IMG / SYS) dans Réglages → Modèles IA, avec auto-fallback par conversation.

## Interface utilisateur

- **Chat** : interface conversationnelle avec avatar 3D animé
- **Mode sombre / clair** : thème cyan adapté à chaque mode
- **Voix active** : synthèse vocale (TTS) des réponses
- **Responsive** : accessible sur mobile via Tailscale
- **Settings** : configuration LLM, connexion Google, hôtes SSH
- **Admin** : gestion utilisateurs, audit logs, configuration OAuth

## Fichiers & uploads

- Upload de fichiers dans le chat jusqu'à **50 Mo** (l'agent reçoit un chemin serveur et lit le contenu via ses outils PDF/vision).
- Quota ≈ 500 Mo par utilisateur, purge automatique après 90 jours.
- ⚠️ Gotcha : un `.zip` s'upload mais aucun outil ne le décompresse — l'agent ne peut pas lire son contenu. Envoyer les fichiers non zippés.

## Sécurité (voir security.md)

- Anonymisation des données sensibles avant envoi au LLM
- Validation humaine (HITL) pour toute action critique
- Apprentissage des refus (contraintes persistantes)
- JWT + cookie HttpOnly (pas de token en localStorage)
- SSH whitelisté par hôte et par commande
- Credentials Google jamais exposées (InjectedToolArg)

## Infrastructure

- **Self-hosted** : tourne sur votre machine (pas de cloud requis)
- **Docker Compose** (chemin canonique) : stack lancée via `make up` — backend FastAPI + frontend Next.js + nginx + Qdrant + proxy egress Squid + sandbox Python durcie
- **start.sh / nohup + PID** : chemin de dev bare-metal secondaire (survie aux déconnexions terminal)
- **Tailscale** : accès sécurisé depuis mobile sans port forwarding
- **SQLite** : base de données embarquée, pas de serveur DB
- **Qdrant** : base vectorielle pour la mémoire sémantique
