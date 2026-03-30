# Propositions d'Évolutions pour ELY Agent

Ce document détaille 6 pistes d'évolution stratégiques pour transformer ELY Agent en une assistante encore plus proactive, polyvalente et intelligente.

---

## 1. Assistance Proactive et "Daily Briefing" Dynamique
**Objectif** : Passer d'un modèle réactif (attend une commande) à un modèle proactif (anticipe les besoins).

### Implémentation :
- **Backend** : Créer un service `ProactiveService` lancé dans le `lifespan` de FastAPI.
- **Tâche planifiée** : Utiliser `apscheduler` pour exécuter une analyse toutes les heures (ou au réveil de l'utilisateur).
- **Logique** : L'agent appelle `gmail_list_emails` (filtre "important") et `calendar_list_events` (prochains rendez-vous). Un LLM "léger" (SLM) génère un court résumé si des éléments critiques sont détectés.
- **Notification** : Envoyer le message via le WebSocket existant ou via le service `ntfy` (déjà intégré pour les push mobiles).

---

## 2. Analyse de Documents Locaux et RAG (Knowledge Base)
**Objectif** : Permettre à ELY de répondre sur la base de documents personnels volumineux.

### Implémentation :
- **Backend** : 
    - Créer une nouvelle collection Qdrant `knowledge_base`.
    - Ajouter un service `IngestionService` qui découpe (chunking) les documents (PDF, Docx) et génère des embeddings.
- **Agent** : Ajouter un nœud `retriever` dans le graphe LangGraph. Avant l'appel au LLM, ce nœud cherche les passages pertinents dans la `knowledge_base`.
- **Frontend** : Ajouter une zone de "Drop" de fichiers dans les paramètres ou une page dédiée `/knowledge` pour gérer les documents indexés.

---

## 3. Système de "Plugins" Dynamiques (Custom Skills)
**Objectif** : Permettre d'ajouter des capacités sans toucher au cœur du code (système de plugins).

### Implémentation :
- **Backend** : 
    - Créer un dossier `backend/app/skills/custom/`.
    - Modifier le `SkillRegistry` pour scanner ce dossier au démarrage et importer dynamiquement les classes héritant de `BaseSkill` via `importlib`.
- **Sandboxing** : Appliquer les mêmes restrictions AST que pour l'outil Python aux plugins tiers pour garantir la sécurité.

---

## 4. Mode "Copilote de Navigation" Interactif
**Objectif** : Rendre l'utilisation du navigateur Playwright transparente et visuelle pour l'utilisateur.

### Implémentation :
- **Backend** : Modifier `browser_manager.py` pour capturer une image (screenshot) après chaque action (`click`, `fill`, `navigate`).
- **Communication** : Envoyer ces captures via le WebSocket en temps réel avec un type de message `browser_frame`.
- **Frontend** : Créer un composant `LiveBrowserPanel` qui s'affiche à la place de l'avatar quand une session de navigation est active, permettant de voir ce que l'agent fait.

---

## 5. Mémoire Émotionnelle et Apprentissage des Préférences
**Objectif** : Personnaliser le ton et le comportement d'ELY en fonction de l'utilisateur.

### Implémentation :
- **Backend** : 
    - Créer une collection Qdrant `user_profile`.
    - À la fin de chaque session, un "Summarizer" LLM extrait non seulement des faits, mais aussi des préférences : *"L'utilisateur préfère les réponses courtes le matin"*, *"L'utilisateur n'aime pas être tutoyé"*.
- **Prompting** : Injecter systématiquement ces préférences dans le `system_prompt` au début de chaque nouvelle conversation.

---

## 6. Extension "Vision" (Multi-modalité)
**Objectif** : Permettre à ELY d'analyser des images, des graphiques ou des photos de documents.

### Implémentation :
- **Frontend** : Ajouter un bouton "Upload Image" dans le `ChatInput` et envoyer le base64 via WebSocket.
- **Backend** : 
    - Mettre à jour `AgentState` pour accepter des messages contenant des blocs d'images.
    - Configurer le `llm_provider` pour utiliser des modèles multi-modaux (Claude 3.5 Sonnet ou Gemini 1.5 Pro).
- **Outil** : Créer un outil `vision_analyze` capable de décrire une image ou d'extraire des données d'un schéma complexe.
