# Spécification Détaillée : Génération Dynamique de Serveurs MCP (Dynamic Tooling)

## 1. Vision et Objectif

La **Génération Dynamique de Serveurs MCP** (Model Context Protocol) est la capacité pour ELY de s'auto-outiller. Face à un logiciel démuni d'API ou de serveur MCP existant, ELY analyse l'application, écrit le code d'un serveur MCP sur mesure (souvent en Python), le déploie localement et l'utilise instantanément.

C'est un changement de paradigme : l'agent ne dépend plus d'intégrations codées en dur, il **crée ses propres ponts** vers n'importe quelle application.

---

## 2. Architecture de la Solution

L'architecture repose sur un cycle "Agent-Créateur -> Bac à sable -> Agent-Utilisateur".

### A. Le processus de "Bootstrapping" (Amorçage)
1. **Identification du besoin** : L'utilisateur demande une action sur une application non supportée (ex: *"Extrais les données de ce vieux logiciel de compta Windows"*).
2. **Phase d'Investigation (L'Agent-Créateur)** :
   - ELY utilise ses outils OS de base (`os_screenshot`, `run_shell_command`) pour inspecter l'application cible (interface, chemins, fichiers de config, CLI disponibles).
3. **Génération du Code** :
   - ELY rédige un script Python utilisant le SDK officiel `mcp`.
   - Ce script expose des outils (outils MCP) qui pilotent l'application (via `subprocess` pour les CLI, ou `pyautogui`/`pywinauto` pour les clics/claviers).
4. **Création d'un Environnement Virtuel (venv)** :
   - Pour éviter les conflits de dépendances, ELY crée un `venv` isolé pour ce nouveau serveur MCP et y installe les bibliothèques nécessaires (ex: `uv pip install mcp pyautogui`).
5. **Déploiement et Enregistrement** :
   - Le serveur MCP est lancé en tâche de fond.
   - Le backend ELY (FastAPI/LangGraph) se connecte dynamiquement à ce nouveau serveur via stdio ou SSE et met à jour le registre des outils (`SkillRegistry`) à chaud.

### B. Le Registre Dynamique (Hot-Reload)
Le backend actuel d'ELY charge les outils au démarrage (`lifespan`). Il faut modifier `SkillRegistry` pour permettre un **rechargement à chaud** :
- Lorsqu'un nouveau serveur MCP est connecté, ELY interroge son endpoint `tools/list`.
- Les nouveaux outils sont liés à l'instance LangGraph en cours d'exécution sans redémarrer le serveur Uvicorn.

---

## 3. Stratégies d'Implémentation et Options

### Option 1 : Pilotage par CLI (Préféré quand c'est possible)
Si l'application dispose d'une ligne de commande, le serveur MCP généré enveloppe des appels `subprocess`.
*   **Avantage** : Rapide, stable, invisible à l'écran.
*   **Exemple** : Piloter `ffmpeg`, `imagemagick`, ou des outils métier.

### Option 2 : Pilotage par GUI (Computer Use / RPA)
Si l'application n'a qu'une interface graphique, le serveur MCP généré utilise l'automatisation d'interface (RPA).
*   **Avantage** : Fonctionne avec 100% des logiciels.
*   **Technologies** : `pyautogui` (clics par coordonnées), `pywinauto` (inspection de l'arbre des fenêtres Windows), ou OCR + Computer Vision.
*   **Défi** : Très sensible aux changements de résolution ou d'interface.

---

## 4. Points d'Attention et Erreurs à Éviter (Anti-Patterns)

### A. Sécurité et "Code Execution"
- **Risque** : Permettre à l'IA d'écrire et d'exécuter du code arbitraire sur le système hôte est le risque de sécurité #1.
- **Mitigation (Crucial)** :
  - **Bac à sable strict** : Le code généré pour le serveur MCP DOIT d'abord passer par l'analyseur AST d'ELY (déjà existant pour le Python Sandbox) pour bloquer les imports malveillants.
  - **Examen Humain (HITL)** : Avant de lancer le serveur MCP généré, ELY doit afficher le code à l'utilisateur : *"J'ai écrit ce script pour piloter le logiciel de compta. Autorises-tu son exécution ?"*.

### B. Fiabilité du RPA (Robotic Process Automation)
- **Erreur courante** : Générer des scripts basés sur des coordonnées X/Y absolues (`click(x=100, y=200)`). Si la fenêtre bouge, tout casse.
- **Bonne pratique** : Forcer ELY (via le prompt de l'Agent-Créateur) à utiliser des techniques robustes :
  - Rechercher des éléments par leur texte (via des bibliothèques d'accessibilité OS).
  - Rechercher par reconnaissance d'image (`pyautogui.locateOnScreen('bouton.png')`). ELY devra générer et sauvegarder ces petites images de référence.

### C. Gestion du Cycle de Vie (Zombies)
- **Erreur courante** : Laisser des processus de serveurs MCP tourner indéfiniment en arrière-plan, consommant toute la RAM.
- **Bonne pratique** : Implémenter un "Watchdog" ou un "Garbage Collector" dans ELY qui arrête les serveurs MCP générés dynamiquement après X minutes d'inactivité, et les relance uniquement si le besoin se représente.

---

## 5. Suggestions d'Améliorations et d'Optimisation

### 1. La "MCP Library" Personnelle (Partage)
Une fois qu'ELY a réussi à créer un serveur MCP stable pour une application donnée, ce code doit être sauvegardé dans un répertoire `data/mcp_library/`.
- **Amélioration** : Si l'utilisateur réinstalle ELY sur un autre PC, l'agent peut simplement recharger ces "drivers" pré-calculés.
- **Étape suivante** : Permettre l'exportation de ces scripts générés vers un dépôt GitHub communautaire. Si ELY sait piloter un logiciel obscur, d'autres ELY dans le monde pourraient télécharger cette "compétence".

### 2. Auto-Réparation (Self-Healing)
Si l'application cible est mise à jour (l'interface change), le serveur MCP généré va échouer (ex: "Bouton non trouvé").
- **Optimisation** : Capter l'exception, la renvoyer à l'Agent-Créateur avec une nouvelle capture d'écran de l'application. L'agent analyse le changement, modifie le script Python du serveur MCP, le redémarre et réessaie l'action, le tout de manière transparente pour l'utilisateur.

### 3. Modèles de Code (Templates) pré-inclus
Pour accélérer la génération et réduire les erreurs de syntaxe (hallucinations), ELY devrait disposer de "Templates" de serveurs MCP dans son contexte.
- Ex: Un template `CLI_MCP_Server.py.jinja` ou `GUI_MCP_Server.py.jinja`. L'IA n'a plus qu'à remplir les fonctions spécifiques au lieu de recréer tout le boilerplate (stdio, routage JSON-RPC) à chaque fois.

---

## 6. Plan d'Action Recommandé pour l'Implémentation

1. **Phase 1 : L'Infrastructure Client MCP**
   - Intégrer un client MCP natif dans le backend d'ELY pour qu'il puisse communiquer avec des serveurs MCP *existants* lancés manuellement.
2. **Phase 2 : L'Environnement de Génération**
   - Créer le dossier `data/dynamic_mcp/` et le système de gestion des environnements virtuels (`uv venv`).
   - Mettre en place le système d'approbation HITL pour le code généré.
3. **Phase 3 : Le Prompting de l'Agent-Créateur**
   - Affiner les prompts système pour enseigner à ELY comment écrire un bon serveur MCP (utilisation des templates, bonnes pratiques RPA).
4. **Phase 4 : La Boucle de Rétroaction**
   - Implémenter l'auto-réparation en cas d'échec du serveur généré.
