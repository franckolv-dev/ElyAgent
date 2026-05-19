# TESTING.md — Guide de test d'Éli en local

Ce guide couvre **tout ce qu'il faut** pour tester Éli (le projet ELY / PhysicalAgent) sur sa machine de développement : configuration minimale, suite de tests automatisés, et procédures manuelles de smoke-test par fonctionnalité.

---

## 1. Prérequis

| Outil | Version | Utilité |
|---|---|---|
| Docker + Docker Compose v5 | 4.30+ | Stack complète (backend + frontend + qdrant + ollama) |
| Python | 3.12 | Backend en dev hors Docker |
| [uv](https://github.com/astral-sh/uv) | 0.5+ | Gestionnaire de dépendances Python (recommandé) |
| Node.js | 20+ | Frontend en dev hors Docker |
| Xcode | 15+ | App iOS (optionnel) |

### Clés API (toutes optionnelles mais au moins une)
- `ANTHROPIC_API_KEY` — Claude (provider par défaut pour la production)
- `GEMINI_API_KEY` — Gemini 2.5 Flash
- `MISTRAL_API_KEY`, `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`, `ZHIPU_API_KEY`
- Pour l'**Arena** il faut au moins **deux** providers configurés

### Fichier `.env` à la racine
Copier `.env.example` vers `.env` et remplir au minimum :
```bash
JWT_SECRET_KEY=change-me-in-prod
ANTHROPIC_API_KEY=sk-ant-xxx      # ou GEMINI_API_KEY
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

---

## 2. Démarrage local

### Via Docker (recommandé — tout en un)
```bash
make up           # Démarre backend, frontend, qdrant, ollama
make ps           # Voir l'état
make logs s=backend   # Suivre les logs
```
Puis ouvrir **http://localhost:3000**.

### Via dev hot-reload (plus rapide pour itérer)
Dans deux terminaux :
```bash
# Terminal 1 — backend
cd backend
uv run uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm install && npm run dev
```

---

## 3. Suite de tests automatisés

### Tests backend (92 tests — ELO, RAG, détecteurs, sécurité, etc.)
```bash
cd backend
uv run --with pytest --with pytest-asyncio pytest tests/ -v
```

Résultat attendu : `92 passed in ~1s`.

Par fichier :
```bash
# RAG agentique : détecteur de pertinence + tool `smart_knowledge_query`
uv run --with pytest --with pytest-asyncio pytest tests/test_rag_detector.py tests/test_agentic_rag_tool.py -v

# Arena : math ELO + flow match/vote
uv run --with pytest --with pytest-asyncio pytest tests/test_arena_service.py -v

# SecurityFilter : anonymisation PII (email, téléphone, carte, IBAN, token)
uv run --with pytest --with pytest-asyncio pytest tests/test_security_filter.py -v

# Intent router (classification rapide hors LLM)
uv run --with pytest --with pytest-asyncio pytest tests/test_intent_router.py -v
```

### Tests frontend
```bash
cd frontend
npm run lint       # ESLint + TypeScript
npm run build      # Vérifie que le build de prod passe
```

---

## 4. Smoke-test manuel par fonctionnalité

### 4.1 Chat de base
1. Ouvrir **http://localhost:3000**
2. Créer un compte (inscription)
3. Envoyer : *« Bonjour, tu es qui ? »* → Éli doit se présenter (féminin)
4. Vérifier que le WebSocket reste connecté (indicateur vert dans la sidebar)

### 4.2 RAG documentaire + RAG agentique (Phase 1.3 + 4.1)
1. Aller dans **Paramètres → Base de connaissances**
2. Uploader un PDF ou un `.txt` (ex : un contrat, une facture)
3. Attendre l'indexation (≈ 5-10 s pour un petit PDF)
4. Retourner au chat et poser une question qui **doit** déclencher la recherche :
   - *« Que dit le contrat sur la clause de résiliation ? »*
   - *« D'après le rapport, quel est le total ? »*
5. La réponse doit citer le nom du fichier et un score de pertinence.
6. Tester aussi une question **hors sujet** : *« Quel temps fait-il à Paris ? »* → Éli doit répondre normalement sans mentionner aucun document.

### 4.3 Mode voix (Phase 3.1)
1. Cliquer sur l'icône micro dans le chat, **ou** dire *« Éli »* (mot d'éveil)
2. L'overlay plein écran cyberpunk doit apparaître
3. Parler une phrase → Éli doit répondre à voix haute
4. La boucle STT → Agent → TTS doit enchaîner les tours sans interaction clavier
5. Fermer avec la croix ou dire *« stop »*

### 4.4 Mode Arena (Phase 4.2)
**Pré-requis** : 2 providers LLM configurés (ex : Anthropic + Gemini).

1. Aller sur **http://localhost:3000/arena** (ou via sidebar → Arena)
2. Entrer un prompt, ex : *« Explique la photosynthèse en trois phrases »*
3. Deux réponses s'affichent en aveugle (*Modèle A* / *Modèle B*)
4. Voter : **A**, **B**, **Égalité**, ou **Les deux mauvais**
5. Les modèles se révèlent + l'ELO se met à jour
6. Scroller pour voir le **classement ELO** global (démarrage à 1000, K=32)

### 4.5 PWA (Phase 4.3)
1. Build de prod : `cd frontend && npm run build && npm run start`
2. Ouvrir Chrome sur **http://localhost:3000**
3. Après 30 s, une **bannière d'installation** s'affiche
4. L'installer → l'app s'ouvre en fenêtre standalone
5. Couper Internet (DevTools → Network → Offline)
6. Rafraîchir : la page `/offline` dédiée doit s'afficher
7. Vérifier dans DevTools → Application → Service Workers : `ely-sw-v1` actif
8. Vérifier : les requêtes `/api/*`, `/ws/*`, `/auth/*` **ne sont jamais** mises en cache

### 4.6 Canaux de messagerie (Phase 1.1 + 1.2)

#### Slack (Socket Mode)
1. Renseigner dans `.env` : `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`
2. `make restart s=backend`
3. Envoyer un DM au bot Slack
4. Pour un outil critique (ex : *supprime mes emails*) → un Block Kit avec **Autoriser / Refuser** doit apparaître

#### Discord
1. Renseigner `DISCORD_BOT_TOKEN` dans `.env`
2. `make restart s=backend`
3. DM au bot **ou** mention dans un salon où il est présent
4. HITL via réactions emoji (✅ / ❌)

#### Telegram (déjà en place)
1. Renseigner `TELEGRAM_BOT_TOKEN`
2. `/start` au bot → Éli répond
3. HITL via inline keyboard

### 4.7 App iOS (Phase 3.2)
1. Ouvrir `ios/ELY.xcodeproj` dans Xcode
2. Compiler sur simulateur iOS 17+ ou device
3. Login avec les mêmes identifiants que le web
4. Vérifier : chat, voice mode, settings — tous utilisent le même backend via WebSocket

### 4.8 Page Sécurité (Phase 2.1) + Audit logging (Phase 2.3)
1. Aller sur **/security** (sidebar)
2. Vérifier les blocs : chiffrement, PII, self-hosting, audit
3. Déclencher une action critique (ex : envoyer un email via l'agent)
4. Aller sur **/security** → onglet audit → l'action doit apparaître
5. Exporter en CSV : le bouton export doit télécharger un fichier valide

### 4.9 Gestion des conversations (Phase 2.4)
1. Créer plusieurs conversations
2. Dans la sidebar : recherche par titre, renommer (double-clic), supprimer
3. Exporter une conversation (menu ⋮) → téléchargement JSON

---

## 5. Debugging

### Logs utiles
```bash
make logs s=backend        # Uvicorn + agent
make logs s=frontend       # Next.js
make logs s=qdrant         # Mémoire vectorielle
docker logs cyberentity-ollama -f      # SLM local
```

### Erreurs courantes

| Symptôme | Cause probable | Fix |
|---|---|---|
| `401` sur `/ws/chat` | JWT expiré | Déconnexion / reconnexion |
| Arena : *« Au moins deux modèles… »* | Moins de 2 providers configurés | Ajouter une clé dans `.env` + `make restart` |
| RAG : aucun résultat | Collection Qdrant vide | Re-uploader via Paramètres → Base de connaissances |
| Mode voix : pas de son | Navigateur bloque l'audio | Vérifier permissions microphone + autoplay |
| SW ne s'installe pas | Mode dev (désactivé exprès) | `npm run build && npm run start` |

### Réinitialiser la mémoire vectorielle
```bash
docker exec cyberentity-qdrant curl -X DELETE http://localhost:6333/collections/knowledge
# puis re-uploader vos documents
```

### Réinitialiser la base SQLite (dev uniquement !)
```bash
make down
rm -rf data/db/cyberentity.db
make up
```

---

## 6. Checklist avant déploiement VPS

- [ ] `uv run pytest tests/ -v` → 92 passed
- [ ] `npm run build` → 0 erreur
- [ ] Arena testé avec 2 providers minimum
- [ ] RAG testé avec au moins 1 document indexé
- [ ] Mode voix testé (mot d'éveil *« Éli »*)
- [ ] PWA : SW enregistré + page `/offline` accessible
- [ ] Page `/security` à jour
- [ ] `.env` **pas commité**
- [ ] README + memory/roadmap à jour
