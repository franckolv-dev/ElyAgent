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
| Telegram | 🚧 En cours | Bot privé, même agent, mêmes permissions |
| WhatsApp | 📋 Prévu | Via WhatsApp Business API |
| API REST | ✅ Actif | Pour intégrations tierces |

## Google Workspace

ELY se connecte au compte Google de chaque utilisateur via OAuth2 :

| Service | Capacités |
|---|---|
| **Gmail** | Lire, chercher, envoyer des emails |
| **Google Calendar** | Consulter et créer des événements |
| **Google Drive** | Lister et lire des fichiers |
| **Google Docs** | Créer, lire, modifier des documents (≈ Word) |
| **Google Sheets** | Créer, lire, ajouter des lignes (≈ Excel) |
| **Google Tasks** | Lister, créer, compléter des tâches |

- Multi-profil : chaque utilisateur connecte son propre compte
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

### Long terme (Qdrant)
- Résumé automatique à la fin de chaque session
- Extraction de faits sur l'utilisateur (préférences, habitudes, contacts)
- Recherche sémantique cross-conversation
- L'agent retrouve les informations pertinentes des conversations passées

### Apprentissage sécuritaire
- Les refus HITL deviennent des règles permanentes
- L'agent ne reproposera jamais une action bannie

## Fournisseurs LLM

| Provider | Localisation | Tier RGPD |
|---|---|---|
| **Anthropic Claude** | USA | B/C |
| **Mistral AI** | France/Europe | A (RGPD) |
| **Ollama** (local) | Votre machine | A (100% local) |
| **DeepSeek** | Chine | C |

Configurable à chaud via `.env` — pas de redémarrage nécessaire.

## Interface utilisateur

- **Chat** : interface conversationnelle avec avatar 3D animé
- **Mode sombre / clair** : thème cyan adapté à chaque mode
- **Voix active** : synthèse vocale (TTS) des réponses
- **Responsive** : accessible sur mobile via Tailscale
- **Settings** : configuration LLM, connexion Google, hôtes SSH
- **Admin** : gestion utilisateurs, audit logs, configuration OAuth

## Sécurité (voir security.md)

- Anonymisation des données sensibles avant envoi au LLM
- Validation humaine (HITL) pour toute action critique
- Apprentissage des refus (contraintes persistantes)
- JWT + cookie HttpOnly (pas de token en localStorage)
- SSH whitelisté par hôte et par commande
- Credentials Google jamais exposées (InjectedToolArg)

## Infrastructure

- **Self-hosted** : tourne sur votre machine (pas de cloud requis)
- **Tailscale** : accès sécurisé depuis mobile sans port forwarding
- **start.sh** : démarrage/arrêt simplifié des deux services
- **nohup + PID** : survie aux déconnexions terminal
- **SQLite** : base de données embarquée, pas de serveur DB
- **Qdrant** : base vectorielle pour la mémoire sémantique
