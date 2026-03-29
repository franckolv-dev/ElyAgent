# ELY vs OpenClaw — Analyse Comparative

> Dernière mise à jour : mars 2026

---

## 1. Résumé Exécutif

OpenClaw est l'agent IA open source le plus populaire de l'histoire récente (247 000+ étoiles GitHub en 60 jours), conçu comme un assistant personnel mono-utilisateur piloté via messagerie. ELY est un agent IA personnel multi-utilisateur avec une architecture LangGraph superviseur + sous-agents, une interface web cyberpunk, un routing LLM intelligent par complexité, et des fonctionnalités d'entreprise légère (HITL, Vault, monitoring). Les deux projets se rejoignent sur le principe "self-hosted, privacy-first, multi-LLM" mais divergent radicalement sur l'architecture, la cible et les ambitions : OpenClaw vise le hacker solitaire qui veut un agent "qui fait des trucs", ELY vise un cercle restreint d'utilisateurs de confiance qui veulent un assistant structuré, sécurisé et extensible.

---

## 2. OpenClaw — Vue d'Ensemble

### Origine
Créé par Peter Steinberger (fondateur de PSPDFKit), lancé en novembre 2025 sous le nom Clawdbot, rebaptisé Moltbot puis OpenClaw après des problèmes de marque avec Anthropic. En février 2026, Steinberger a rejoint OpenAI et le projet a été confié à une fondation open source.

### Architecture
- **Runtime** : processus Node.js unique (le "Gateway") tournant sur `127.0.0.1:18789`
- **Langage** : JavaScript/TypeScript (~430 000 lignes)
- **Modèle** : mono-utilisateur par design, pas de multi-tenant
- **Stockage** : fichiers locaux (`~/.openclaw/`), pas de base de données structurée
- **Orchestration** : pas de framework agent formel (pas LangGraph), boucle d'exécution propriétaire
- **Sandbox** : optionnel via Docker (non activé par défaut)
- **Heartbeat** : daemon proactif qui s'exécute périodiquement pour vérifier des tâches planifiées

### Canaux supportés
WhatsApp, Telegram, Discord, Slack, Signal, iMessage, Teams, Google Chat, Matrix, IRC, LINE, WeChat, Zalo, Twitch, Nostr, Mattermost, Nextcloud Talk, BlueBubbles, WebChat (20+ canaux)

### Système de Skills
- Skills packagés comme fichiers Markdown (SOUL.md)
- ClawHub : registre public avec 13 729 skills communautaires (mars 2026)
- 5 200+ skills indexés dans le projet awesome-openclaw-skills
- Système de routing LLM par tâche (Ollama pour le simple, Claude/GPT-4 pour le complexe)

### Mémoire
- Court terme : session state via LangGraph/MemorySaver
- Long terme : embeddings vectoriels (Milvus compatible)
- Mémoire partagée inter-canaux (contexte unifié WhatsApp + Telegram)

### Points Faibles Connus
- 9+ CVEs identifiés en 2 mois d'existence
- 42 665 instances exposées publiquement sur internet
- Vulnérable au prompt injection
- Plugins malveillants (341 skills malicieux documentés sur ClawHub)
- Pas de guardrails natifs (cas d'usage : agent ayant acheté une voiture de façon autonome)
- Pas d'interface web native (pilotage uniquement par messagerie)
- Mono-utilisateur : pas prévu pour partager avec d'autres personnes

### Adoption
- 247 000+ étoiles GitHub en ~60 jours
- Intégration officielle par Tencent (WeChat), NemoClaw par Nvidia
- Subventions gouvernementales en Chine pour les entreprises utilisant OpenClaw

---

## 3. ELY — Vue d'Ensemble

### Origine
Projet personnel de Franck, agent IA self-hosted conçu pour un usage multi-utilisateurs restreint (3-4 personnes de confiance). Architecture pensée dès le départ pour la robustesse, la sécurité et l'extensibilité.

### Architecture
- **Framework** : LangGraph (Python) avec pattern superviseur + 6 sous-agents spécialisés
- **Langage** : Python 3.12 (backend), Next.js 14 (frontend)
- **Runtime** : Docker + FastAPI sur VPS auto-hébergé
- **Multi-utilisateur** : oui, support natif 3-4 utilisateurs par instance
- **Interface web** : UI cyberpunk 3D (Three.js) avec avatar TTS animé
- **Base de données** : SQLModel (structuré)
- **HITL** : validation humaine pour les actions sensibles
- **Vault** : gestion sécurisée des clés API

### Canaux supportés
Web UI (Next.js), Telegram, WhatsApp

### Routing LLM par Complexité
- Simple → Ollama (local, gratuit, privé)
- Moyen → Mistral
- Complexe → Claude / Gemini / DeepSeek

### Intégrations
Google Workspace complet (Gmail, Drive, Calendar, Contacts), MCP (Model Context Protocol)

### Mémoire
- Court terme : mémoire épisodique par utilisateur
- Long terme : consolidation structurée par utilisateur

### Système de Skills
- Skills extensibles
- Support MCP pour l'intégration d'outils tiers standardisés

### Monitoring
- Watchdog intégré
- Tâches planifiées
- Système de santé des services

---

## 4. Tableau Comparatif — 20 Fonctionnalités

| Fonctionnalité | ELY | OpenClaw |
|---|---|---|
| **Licence** | À définir | MIT |
| **Langage principal** | Python 3.12 | JavaScript/TypeScript |
| **Framework agent** | LangGraph (multi-agent superviseur) | Boucle propriétaire Node.js |
| **Architecture multi-agent** | ✅ Superviseur + 6 sous-agents | ❌ Agent unique |
| **Multi-utilisateur** | ✅ 3-4 users par instance | ❌ Mono-utilisateur par design |
| **Interface web** | ✅ UI cyberpunk Next.js 14 | ❌ Pas d'interface web native |
| **Avatar 3D / TTS** | ✅ Three.js + voix | ❌ Non |
| **Déploiement** | ✅ Docker + VPS (production-ready) | ⚠️ Node.js natif (Docker optionnel) |
| **Routing LLM par complexité** | ✅ 4 niveaux (Ollama→Claude) | ✅ Configurable par tâche |
| **Support Ollama (LLM local)** | ✅ | ✅ |
| **Support multi-LLM** | ✅ Claude, Mistral, Gemini, DeepSeek, Ollama | ✅ OpenAI, Claude, Gemini, Ollama, etc. |
| **HITL (Human-In-The-Loop)** | ✅ Validation actions sensibles | ❌ Pas de guardrails natifs |
| **Vault / gestion sécurisée des clés** | ✅ Service Vault dédié | ❌ .env fichiers exposés |
| **Canaux de messagerie** | ✅ Web, Telegram, WhatsApp | ✅ 20+ canaux (WhatsApp, Telegram, Discord, Slack...) |
| **Skills / plugins extensibles** | ✅ Système de skills + MCP | ✅ 13 729 skills (ClawHub) |
| **Registre de skills communautaire** | ❌ Non (prévu) | ✅ ClawHub actif |
| **Intégration Google Workspace** | ✅ Gmail, Drive, Calendar, Contacts | ⚠️ Via skills tiers |
| **MCP (Model Context Protocol)** | ✅ Support natif | ⚠️ Via plugins tiers |
| **Mémoire court/long terme** | ✅ Par utilisateur, structurée | ✅ Partagée inter-canaux |
| **Watchdog / monitoring** | ✅ Intégré | ⚠️ Heartbeat basique |
| **Tâches planifiées** | ✅ | ✅ (heartbeat + HEARTBEAT.md) |
| **Sécurité / sandboxing** | ✅ Docker isolé, HITL, Vault | ⚠️ Risques documentés, 9+ CVEs |
| **Sandbox prompt injection** | ✅ Architecture structurée | ❌ Vulnérable |
| **Setup technique requis** | Moyen (Docker + VPS) | Faible (npm install) |
| **Stars GitHub** | Projet privé | 247 000+ |

---

## 5. Points Forts d'ELY face à OpenClaw

### Sécurité et Fiabilité
ELY est conçu pour tourner en production sur un VPS avec Docker, isolation des services, HITL pour les actions critiques, et un Vault pour les secrets. OpenClaw présente 9+ CVEs documentés, des milliers d'instances exposées sur internet, et aucun guardrail natif. Pour un usage réel avec des données personnelles sensibles, ELY est incomparablement plus sûr.

### Architecture Multi-Agent Structurée
Le pattern LangGraph superviseur + 6 sous-agents spécialisés permet à ELY de gérer des tâches complexes avec une traçabilité claire, des états bien définis, et une capacité de debugging que la boucle propriétaire d'OpenClaw ne peut pas offrir.

### Multi-Utilisateur Natif
OpenClaw est fondamentalement mono-utilisateur. ELY supporte nativement plusieurs utilisateurs avec mémoire séparée, ce qui correspond à un vrai cas d'usage famille/équipe restreinte.

### Interface Web & Expérience Utilisateur
L'UI cyberpunk avec avatar 3D TTS offre une expérience immersive qu'OpenClaw n'a pas. Les utilisateurs non-techniques peuvent interagir via le web sans configurer Telegram ou WhatsApp.

### Intégrations Natives Structurées
L'intégration Google Workspace (Gmail, Drive, Calendar, Contacts) est native dans ELY, pas dépendante d'un skill communautaire potentiellement non maintenu.

### MCP Support Natif
ELY supporte le Model Context Protocol dès le départ, permettant une compatibilité standardisée avec l'écosystème croissant d'outils MCP.

---

## 6. Faiblesses d'ELY face à OpenClaw

### Écosystème de Skills
OpenClaw dispose de 13 729 skills communautaires sur ClawHub. ELY n'a pas (encore) de registre public. C'est le gap le plus significatif en termes de valeur immédiate pour les utilisateurs.

### Canaux de Messagerie
OpenClaw supporte 20+ canaux (Discord, Slack, Signal, Teams, Matrix, IRC, LINE, WeChat...). ELY se limite à Web, Telegram, WhatsApp. Pour les utilisateurs Discord ou Slack, ELY ne répond pas au besoin.

### Facilité d'Installation
`npm install` vs Docker + VPS + configuration complète. OpenClaw gagne sur la friciton d'onboarding. ELY demande une compétence technique plus élevée.

### Maturité et Communauté
247 000 étoiles GitHub, couverture media mondiale, intégrations enterprise (Tencent, Nvidia). ELY est un projet personnel émergent. La différence de visibilité est abyssale.

### Proactivité (Heartbeat)
Le système heartbeat d'OpenClaw (daemon qui vérifie une checklist toutes les 30 minutes) est élégant pour les rappels et alertes proactives. ELY dispose de tâches planifiées mais l'approche heartbeat-as-markdown est particulièrement simple et puissante.

### Routing LLM Granulaire
OpenClaw permet une configuration très fine du modèle par tâche, par agent. ELY a un système de tiers mais OpenClaw a une granularité supérieure sur ce point.

---

## 7. Différenciateurs Uniques d'ELY

Ces éléments n'existent nulle part ailleurs dans le paysage des agents IA open source :

1. **Avatar 3D TTS Cyberpunk** : Une interface incarnée avec une présence visuelle unique. Aucun projet concurrent ne propose cela en self-hosted open source.

2. **Architecture LangGraph Multi-Agent Structurée pour Usage Personnel** : La plupart des projets utilisent soit LangGraph pour l'entreprise (CrewAI, AutoGen) soit une boucle simple (OpenClaw). ELY applique la rigueur de LangGraph à un usage personnel/famille.

3. **HITL Intégré par Design** : Pas une option, une philosophie. ELY valide les actions sensibles avant de les exécuter, ce qui le rend utilisable avec des données réelles sans risque de "l'agent a acheté une voiture tout seul".

4. **Vault de Secrets** : Service dédié à la gestion des clés API, absent de tous les projets concurrents à ce niveau de sophistication.

5. **Routing LLM par Complexité + Priorité Privacy** : Envoyer les requêtes simples sur Ollama local (aucune donnée ne quitte la machine) et seulement les complexes vers des LLMs cloud est une approche privacy-first que peu de projets implémentent nativement.

6. **Multi-Utilisateur avec Mémoire Isolée** : Chaque utilisateur a sa propre mémoire épisodique et long terme. Aucun projet self-hosted de niveau personnel ne gère ça proprement.

---

## 8. Chevauchement de Cible

### Utilisateurs qui choisiraient OpenClaw
- Développeurs solo voulant automatiser leur workflow immédiatement
- Hackers voulant explorer les capacités d'un agent sans friction
- Utilisateurs avec besoin de canaux exotiques (Discord, Slack, Signal, Teams)
- Personnes qui veulent parcourir un énorme catalogue de skills communautaires
- Profils "tinkerer" qui acceptent les risques de sécurité

### Utilisateurs qui choisiraient ELY
- Personnes voulant un agent pour un cercle de confiance (famille, équipe restreinte)
- Utilisateurs sensibles à la sécurité et à la vie privée (HITL, Vault, isolation Docker)
- Profils voulant une expérience utilisateur soignée (UI web, avatar TTS)
- Développeurs Python/LangGraph qui veulent comprendre et modifier l'architecture
- Utilisateurs intensifs de Google Workspace
- Personnes voulant un agent stable en production (pas d'expérimentation)

### Zone de Chevauchement
Les deux projets attirent des développeurs techniques, privacy-conscious, qui veulent contrôler leur stack IA. La différence : OpenClaw accepte le chaos pour gagner en facilité, ELY accepte la complexité pour gagner en robustesse.

---

## 9. Implications pour la Roadmap d'ELY

### Priorité Haute — Combler les Gaps Critiques

**[P0] Registre de Skills / Plugin Store**
C'est le gap le plus visible. Même un registre minimal avec 20-30 skills de qualité serait un argument marketing fort. Format inspiré de ClawHub mais avec validation obligatoire (pas de skills malveillants).

**[P0] Canaux Additionnels**
Discord et Slack sont utilisés par la cible développeur. Ajouter au moins Discord serait un signal fort pour la communauté tech.

**[P1] Onboarding Simplifié**
Un script `install.sh` ou un `docker-compose up` one-liner réduirait la friction d'installation. ELY ne pourra jamais égaler `npm install` mais peut améliorer significativement.

### Priorité Moyenne — Renforcer les Avantages

**[P1] Heartbeat Proactif Structuré**
S'inspirer du concept heartbeat d'OpenClaw mais avec une interface HITL pour valider les actions proactives avant exécution.

**[P1] Documentation Architecture**
Le deep-dive architecture d'OpenClaw (blog posts, diagrammes) a généré beaucoup d'attention. ELY devrait publier un document technique détaillé de son architecture LangGraph.

**[P2] Benchmark Sécurité Public**
Publier un audit de sécurité comparatif (ELY vs OpenClaw) serait un différenciateur marketing puissant étant donné les 9 CVEs d'OpenClaw.

### Priorité Basse — Avantages Compétitifs à Long Terme

**[P2] Support MCP Étendu**
Capitaliser sur le support MCP natif avec des exemples d'intégrations prêts à l'emploi.

**[P2] Mode "Famille/Team"**
Documenter et démontrer le cas d'usage multi-utilisateur (3-4 personnes) que OpenClaw ne peut pas faire.

---

## 10. Conclusion

ELY et OpenClaw ne sont pas des projets concurrents au sens strict : ils répondent à des besoins différents avec des philosophies différentes. OpenClaw a gagné la course à la popularité virale grâce à une friciton d'installation minimale et un écosystème de skills massif. ELY mise sur la robustesse, la sécurité, et une expérience utilisateur unique.

Le risque pour ELY n'est pas d'être éclipsé par OpenClaw — c'est de ne pas être connu. La stratégie doit donc être de capitaliser sur les faiblesses structurelles d'OpenClaw (sécurité catastrophique, mono-utilisateur, pas d'UI) pour se positionner comme "l'alternative adulte" : l'agent IA que vous pouvez donner à votre famille sans craindre qu'il achète une voiture tout seul.

**Slogan potentiel** : *"ELY : l'agent IA self-hosted qui fait ce que vous lui demandez — pas plus."*

---

*Sources de recherche : [OpenClaw GitHub](https://github.com/openclaw/openclaw) · [OpenClaw Docs](https://docs.openclaw.ai) · [KDnuggets](https://www.kdnuggets.com/openclaw-explained-the-free-ai-agent-tool-going-viral-already-in-2026) · [DigitalOcean](https://www.digitalocean.com/resources/articles/what-is-openclaw) · [Neurohive](https://neurohive.io/en/guides/openclaw-the-lobster-that-took-over-the-world-how-one-developer-built-the-most-popular-open-source-ai-agent-in-history/) · [Milvus Blog](https://milvus.io/blog/openclaw-formerly-clawdbot-moltbot-explained-a-complete-guide-to-the-autonomous-ai-agent.md) · [DataCamp Alternatives](https://www.datacamp.com/blog/openclaw-alternatives) · [Fast.io Top 10](https://fast.io/resources/top-10-open-source-ai-agents/)*
