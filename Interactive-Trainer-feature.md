# Spécification Technique : ELY Interactive Trainer (Tuteur OS & Logiciel)

Cette fonctionnalité transforme ELY d'une simple assistante textuelle en un **tuteur interactif** capable de voir votre écran, de comprendre l'interface de logiciels complexes (Blender, suite Adobe, IDE) et de réaliser des démonstrations en direct en manipulant la souris et le clavier.

---

## 1. Architecture Technologique : Le Pivot MCP

Pour dépasser les limites de Playwright (cantonné au Web), ELY doit devenir un **Client MCP (Model Context Protocol)**. 

### Pourquoi MCP ?
- **Standard Ouvert** : Permet de connecter ELY à des "serveurs" de capacités sans coder chaque intégration manuellement.
- **Contrôle Desktop** : Utilisation de serveurs MCP comme `desktop-control` qui exposent des outils de capture d'écran, de clic et de saisie clavier au niveau du système d'exploitation (OS).
- **Écosystème Gratuit** : Des dizaines de serveurs MCP open-source sont déjà disponibles (Filesystem, Google Maps, Slack, GitHub, etc.).

---

## 2. Le Workflow de Formation "Show & Tell"

Lorsqu'un utilisateur pose une question sur un logiciel (ex: *"Comment déplier les UV dans Blender ?"*), ELY suit ce cycle :

1.  **Vision (Capture d'Écran)** : ELY utilise un outil MCP pour prendre une capture de la fenêtre active ou de l'écran complet.
2.  **Analyse d'Interface** : La capture est envoyée à un LLM multi-modal (Claude 3.5 Sonnet, GPT-4o ou Gemini 1.5 Pro) qui identifie les menus, les boutons et l'état actuel du projet.
3.  **Planification** : ELY décompose la tâche en étapes élémentaires.
4.  **Démonstration (Contrôle Direct)** :
    - ELY demande l'autorisation (HITL) : *"Je vais te montrer. Je déplace la souris sur l'onglet 'UV Editing', d'accord ?"*.
    - Après validation, ELY envoie les commandes de clic et de mouvement via le serveur MCP.
5.  **Vérification** : Après l'action, ELY reprend une capture pour vérifier que le résultat est correct et guide l'utilisateur pour la suite.

---

## 3. Cas Particulier : L'Intégration Blender (Python API)

Blender est extrêmement puissant car il est entièrement pilotable en Python.
- **Solution Autonome** : ELY peut générer des scripts Python Blender.
- **Exécution via MCP** : Un serveur MCP local peut faire le pont entre ELY et la console Python de Blender.
- **Avantage** : Au lieu de simuler des clics (parfois imprécis), ELY exécute des commandes mathématiques parfaites pour créer des zones UV, modifier des meshs ou gérer des matériaux.

---

## 4. Composants à Implémenter dans ELY

### A. Backend : Client MCP Universel
- Intégrer une bibliothèque client MCP (ex: `mcp-python-sdk`).
- Gérer la configuration des serveurs locaux dans `system_config` (ex: chemins vers les exécutables des serveurs).

### B. Outils de Vision & Automation (via MCP)
- `os_screenshot` : Capture l'écran complet ou une fenêtre ciblée.
- `os_mouse_move(x, y)` : Déplace le curseur.
- `os_click(button, clicks)` : Simule un clic.
- `os_type_text(text)` : Simule la saisie clavier.

### C. Frontend : Overlay de Formation
- Ajouter un mode "Tuteur" qui peut afficher des **indicateurs visuels** sur l'écran (ex: un cercle rouge autour du bouton sur lequel l'utilisateur doit cliquer) si le serveur MCP supporte le dessin d'overlay.

---

## 5. Sécurité et Éthique (HITL Strict)

Le contrôle de l'OS est une capacité "critique" (Niveau 3) :
- **Validation Systématique** : Aucune action sur la souris ou le clavier ne peut être faite sans un clic "Autoriser" de l'utilisateur sur l'interface ELY.
- **Mode Observation seule** : L'utilisateur peut choisir de laisser ELY "regarder" et "expliquer" sans lui donner le droit de cliquer.
- **Confidentialité Visuelle** : ELY doit avertir l'utilisateur avant de prendre une capture d'écran pour éviter de capturer des informations sensibles (mots de passe, emails) ouvertes dans d'autres fenêtres.

---

## 6. Conclusion : Un Game Changer face à OpenClaw

Alors qu'OpenClaw se concentre sur l'accès distant (caméra du téléphone), ELY devient un **expert métier résidant sur votre ordinateur**. Cette capacité de formation interactive fait d'ELY non pas un simple outil, mais un véritable **binôme de travail** capable d'enseigner des compétences complexes en temps réel.
