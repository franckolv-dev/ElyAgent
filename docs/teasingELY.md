# Plan Marketing & Communication — Lancement Public ELY

> Document stratégique pour la mise en public du dépôt GitHub ELY
> Rédigé en mars 2026 — à activer quand le repo passe en public

---

## 🎯 Accroche Centrale

> **ELY — l'agent qui agit *Exactly Like You***

Le nom ELY est un acronyme : **E**xactly **L**ike **Y**ou.
Cette accroche est le fil directeur de toute la communication :
- *Exactly* → précision, fiabilité, anti-hallucination ("il fait exactement ce que tu lui dis")
- *Like* → il apprend, il s'adapte, il te ressemble (mémoire évolutive par utilisateur)
- *You* → self-hosted, tes données, ton serveur, ton agent

**Tagline principale :** `ELY — Your AI agent. Exactly Like You.`
**Version française :** `ELY — Votre agent IA. Exactement comme vous.`
**Tagline UI (sous l'avatar, police cyberpunk) :** `ELY :: EXACTLY LIKE YOU`

---

## 1. Positionnement & Messaging

### Elevator Pitch — 1 Phrase
**ELY — Exactly Like You : l'agent IA personnel open source, self-hosted et multi-utilisateur, qui apprend qui vous êtes, orchestre plusieurs LLMs intelligemment, et ne fait jamais rien sans votre accord.**

### Elevator Pitch — 1 Paragraphe
ELY est votre assistant IA personnel qui tourne sur votre propre serveur, parle à toute votre famille, et ne partage jamais vos données avec personne. Son nom dit tout : *Exactly Like You* — il apprend vos habitudes, s'adapte à votre style, mémorise vos projets, et devient plus pertinent à chaque échange. Basé sur LangGraph avec une architecture superviseur + 6 agents spécialisés, ELY route intelligemment vos requêtes : les simples restent sur Ollama (100% local), les complexes vont vers Claude ou Gemini. Il s'intègre nativement avec Gmail, Google Drive, Calendar et Contacts, valide les actions sensibles avant de les exécuter (HITL), et dispose d'une interface web cyberpunk avec un avatar 3D animé et synthèse vocale. ELY n'est pas un chatbot de plus — c'est une infrastructure IA pour votre vie numérique, qui vous ressemble.

### Propositions de Valeur Clés (5-7 bullets)

1. **Vos données restent chez vous** — Self-hosted, aucune donnée envoyée sans votre contrôle. Les requêtes simples ne quittent jamais votre machine (Ollama local).
2. **Multi-utilisateur par design** — ELY gère plusieurs utilisateurs avec mémoire isolée. Partagez l'agent avec votre famille ou votre équipe sans mélanger les contextes.
3. **N'importe quel LLM, intelligemment routé** — Claude pour le raisonnement, Mistral pour l'usage quotidien, Ollama pour le local. ELY choisit automatiquement selon la complexité.
4. **Il demande avant d'agir** — HITL (Human-In-The-Loop) natif : ELY ne supprime pas vos emails, n'achète pas de choses, et ne modifie pas vos fichiers sans votre consentement.
5. **Architecture sérieuse** — LangGraph, FastAPI, Docker, SQLModel. Pas un script Python de 200 lignes : une stack production-ready que vous pouvez auditer, forker et modifier.
6. **Google Workspace intégré** — Gmail, Drive, Calendar, Contacts. Pas via un plugin tiers non maintenu — natif, structuré, validé.
7. **Une expérience unique** — Interface web cyberpunk avec avatar 3D animé et TTS. Votre agent IA a un visage.

### Personas Cibles

**Persona 1 : Le Dev Privacy-Conscious**
- 28-40 ans, développeur backend ou full-stack
- Utilise déjà Ollama, a essayé OpenClaw mais a été effrayé par les CVEs
- Self-héberge Nextcloud, Vaultwarden, Jellyfin
- Veut automatiser ses workflows sans envoyer ses données à OpenAI
- Canaux : Reddit r/selfhosted, r/LocalLLaMA, Hacker News

**Persona 2 : Le Bidouilleur IA Curieux**
- 22-35 ans, développeur ou étudiant en informatique
- Suit l'actualité LLM, a joué avec LangChain et LangGraph
- Cherche un projet concret pour apprendre l'architecture multi-agent
- Veut quelque chose à mettre sur son CV / portfolio
- Canaux : GitHub, Discord communautés IA, Twitter/X

**Persona 3 : Le Tech Lead Famille**
- 30-45 ans, profil technique qui veut déployer un agent pour sa famille
- Cherche une alternative à ChatGPT que sa femme/ses enfants peuvent utiliser sans risque
- Sensible à la vie privée des données familiales
- Canaux : LinkedIn, Reddit r/homelab, forums français

**Persona 4 : Le Contributeur Open Source**
- Développeur Python expérimenté qui connaît LangGraph/FastAPI
- Cherche un projet ambitieux à contribuer
- Valorise une architecture propre et documentée
- Canaux : GitHub, HN, Dev.to

### Ton de Voix
- **Direct et technique** : parler à des développeurs, pas à des managers
- **Honnête sur les limites** : ne pas prétendre être OpenClaw en termes de stars ou d'écosystème
- **Fier de la différence** : la sécurité et le multi-utilisateur ne sont pas des options, c'est le design
- **Cyberpunk mais sérieux** : l'esthétique est assumée, la substance prime
- **Pas de hype vide** : montrer du code, des screenshots, des architectures — pas des buzzwords

---

## 2. Checklist Pré-Lancement (avant de rendre le repo public)

### README.md
- [ ] Hero section avec screenshot de l'UI cyberpunk
- [ ] GIF de démonstration (15-30 secondes, avatar + conversation)
- [ ] Badges : version Python, Docker, license, dernière mise à jour
- [ ] Diagramme d'architecture LangGraph (image SVG ou PNG)
- [ ] Section "Features" avec icônes/emoji pour lisibilité
- [ ] Section "Quick Start" : `git clone` → `docker-compose up` en moins de 5 commandes
- [ ] Section "Why ELY?" avec comparaison implicite (sans nommer les concurrents)
- [ ] Liens vers la documentation complète
- [ ] Section Contributing + Code of Conduct
- [ ] Section Roadmap (montrer que le projet est vivant et a une vision)

### Fichiers Repo Obligatoires
- [ ] `LICENSE` (MIT recommandé pour la visibilité / CC BY-NC 4.0 ?)
- [ ] `CONTRIBUTING.md` (comment contribuer, standard de code, process PR)
- [ ] `CODE_OF_CONDUCT.md`
- [ ] `SECURITY.md` (comment reporter une vulnérabilité — contraste fort avec OpenClaw)
- [ ] `.github/ISSUE_TEMPLATE/` (bug report, feature request)
- [ ] `.github/PULL_REQUEST_TEMPLATE.md`
- [ ] `CHANGELOG.md` ou releases GitHub documentées
- [ ] `docker-compose.yml` à la racine (must-have pour l'onboarding)
- [ ] `.env.example` complet et documenté

### Démonstration Visuelle
- [ ] **Screenshot 1** : Interface web principale (chat + avatar 3D)
- [ ] **Screenshot 2** : Architecture/Dashboard (si existant)
- [ ] **Screenshot 3** : Conversation Telegram ou WhatsApp
- [ ] **GIF animé** : démonstration d'une tâche complète (ex: "résume mes emails du jour")
- [ ] **Diagramme architecture** : superviseur + 6 sous-agents + routing LLM

### Documentation Minimum Viable
- [ ] Guide d'installation complet (Docker, VPS recommandé)
- [ ] Configuration `.env` documentée (toutes les variables)
- [ ] Guide des canaux (Telegram bot setup, WhatsApp)
- [ ] Guide intégration Google Workspace (OAuth, scopes)
- [ ] Architecture overview (comment LangGraph est utilisé)
- [ ] FAQ : "Mes données sont-elles en sécurité ?" (réponse détaillée)

### Technique Avant Lancement
- [ ] CI/CD GitHub Actions (tests + lint au minimum)
- [ ] Docker image publiée sur Docker Hub ou GitHub Container Registry
- [ ] Version taggée (v0.1.0 minimum)
- [ ] Pas de secrets commités dans l'historique git (audit complet)
- [ ] Dépendances Python dans `requirements.txt` ou `pyproject.toml` avec versions fixées

---

## 3. Plan Jour de Lancement (J-Day)

### Timing Recommandé
- **Heure cible** : mardi ou mercredi, 14h00-16h00 heure de Paris (8h-10h EST) — pic d'activité HN et Reddit
- **Ne pas lancer** : vendredi soir, week-end, veille de fête

### Séquence de Publication (ordre chronologique)

**J -24h** : Préparer tous les posts, vérifier les liens, tester le repo depuis zéro sur une machine vierge

**J 00:00** : Rendre le repo GitHub public

**J +0h** : Post Hacker News "Show HN"

**J +30min** : Thread Twitter/X

**J +1h** : Post Reddit r/selfhosted

**J +1h30** : Post Reddit r/LocalLLaMA

**J +2h** : Post LinkedIn

**J +3h** : Post Reddit r/MachineLearning + r/artificial

**J +6h** : Post Reddit r/programming (si les autres ont bien démarré)

**J +24h** : Soumission Product Hunt

---

### Templates Posts

#### Twitter/X — Thread (7 tweets)

**Tweet 1 (accroche)**
```
I've been building my own AI agent for the past year.

Today I'm making it open source. 🦾

Meet ELY — a self-hosted, multi-user AI agent with LangGraph, multi-LLM routing, and a cyberpunk 3D avatar.

Here's what makes it different 🧵
```

**Tweet 2 (architecture)**
```
ELY uses LangGraph with a supervisor + 6 specialized sub-agents.

Not a chatbot loop. An actual agent architecture.

Simple tasks → Ollama (local, your machine, zero data leaving).
Complex tasks → Claude or Gemini.

You control what goes where.
```

**Tweet 3 (sécurité / HITL)**
```
ELY never does anything without asking first.

HITL (Human-In-The-Loop) is built-in by design — not an option.

No surprise emails sent. No files deleted. No autonomous purchases.

(Yes, this is a dig at the agents that bought cars by themselves 🦞)
```

**Tweet 4 (multi-user)**
```
ELY supports 3-4 users per instance, each with isolated memory.

Run it for your whole family. Share it with a small team.

Every user has their own episodic + long-term memory. No context mixing.

Self-hosted AI agents shouldn't be single-user only.
```

**Tweet 5 (intégrations)**
```
ELY integrates natively with:

→ Gmail, Google Drive, Calendar, Contacts
→ Telegram + WhatsApp
→ MCP (Model Context Protocol)
→ Any Ollama-compatible local model

Stack: Python 3.12 · FastAPI · LangGraph · Next.js 14 · Docker
```

**Tweet 6 (UI + avatar)**
```
Oh and the UI.

Cyberpunk aesthetic. 3D animated avatar with TTS.
Built with Three.js.

Your AI assistant has a face now.

[screenshot/GIF here]
```

**Tweet 7 (CTA)**
```
ELY is open source, self-hosted, privacy-first.

⭐ GitHub: [LINK]
📖 Docs: [LINK]

If you've been looking for a serious alternative to ChatGPT that you actually own — this is it.

RT appreciated 🙏
```

---

#### LinkedIn Post

```
J'ai passé un an à construire mon agent IA personnel. Aujourd'hui, je le rends open source.

ELY est un agent IA self-hosted, multi-utilisateur, avec une architecture LangGraph superviseur + 6 sous-agents spécialisés.

Pourquoi ?

Parce que je voulais un assistant IA qui :
✅ Tourne sur mon propre serveur (VPS + Docker)
✅ Ne partage aucune donnée sans mon accord
✅ Peut servir toute ma famille (multi-utilisateurs, mémoire isolée)
✅ Route intelligemment les requêtes : simple → Ollama local, complexe → Claude/Gemini/Mistral/DeepSeek
✅ Valide les actions sensibles avant de les exécuter (HITL natif)
✅ S'intègre avec Gmail, Drive, Calendar, Contacts

Stack technique : Python 3.12 · FastAPI · LangGraph · Next.js 14 · Three.js · Docker

C'est le genre de projet dont je suis fier non pas parce qu'il a 200k étoiles, mais parce qu'il tourne tous les jours chez moi, que ma femme l'utilise, et qu'il n'a jamais acheté de voiture sans me demander.

Le repo est disponible ici : [LINK]

Si vous construisez des agents IA, travaillez avec LangGraph ou êtes simplement curieux — je suis preneur de feedback, de retours, et de contributions.

#OpenSource #AI #LLM #SelfHosted #LangGraph #Python #AgentIA
```

---

#### Reddit — r/selfhosted (post complet)

**Titre** : `I built a self-hosted multi-user AI agent with LangGraph, multi-LLM routing, HITL validation, and a cyberpunk 3D avatar. Open sourcing it today.`

**Corps**
```
Hey r/selfhosted,

I've been lurking here for years, self-hosting everything from Nextcloud to Vaultwarden.
This year I decided to build something bigger: my own AI agent.

**What is ELY?**

ELY is a self-hosted, multi-user AI agent built on:
- LangGraph (supervisor + 6 specialized sub-agents)
- FastAPI backend + Next.js 14 frontend
- Docker deployment on VPS
- Multi-LLM routing: simple → Ollama (local), medium → Mistral, complex → Claude/Gemini

**Why not just use OpenClaw?**

I looked at OpenClaw. Great project, insane growth. But:
- It's single-user by design
- 9+ CVEs in its first 2 months
- No web UI (only messaging apps)
- No built-in HITL (it once bought a car autonomously for someone)
- Node.js, not Python (personal preference)

**What makes ELY different:**

✅ **Multi-user** — 3-4 users per instance, isolated memory per user
✅ **HITL native** — ELY asks before doing anything sensitive
✅ **Privacy routing** — Simple queries stay on Ollama (never leave your machine)
✅ **Google Workspace** — Gmail, Drive, Calendar, Contacts — natively
✅ **MCP support** — Model Context Protocol for extensibility
✅ **Vault** — Dedicated secret management service
✅ **Web UI** — Cyberpunk interface with a 3D animated avatar + TTS
✅ **Production-ready** — Docker, SQLModel, proper architecture

**Tech stack:**
Python 3.12 · FastAPI · LangGraph · SQLModel · Next.js 14 · Three.js · Docker

**GitHub:** [LINK]
**Docs:** [LINK]

Happy to answer questions about the architecture, the LangGraph implementation, or the deployment setup. Feedback welcome!
```

---

#### Reddit — r/LocalLLaMA

**Titre** : `ELY: open source self-hosted agent with intelligent LLM routing — simple queries stay on Ollama, complex ones go to Claude/Gemini`

**Corps**
```
Built an agent that routes by complexity:

- Simple queries → Ollama (100% local, zero data leaves your machine)
- Medium → Mistral
- Complex reasoning → Claude / Gemini / DeepSeek

Architecture: LangGraph supervisor + 6 sub-agents. FastAPI + Docker.

Multi-user (3-4 per instance), HITL for sensitive actions, Google Workspace integration, MCP support.

The routing logic is configurable. You can define what "simple" means for your use case.

Repo: [LINK]

Curious if anyone has experimented with similar routing strategies — happy to discuss the implementation.
```

---

#### Hacker News — Show HN

**Titre** : `Show HN: ELY – Self-hosted multi-user AI agent with LangGraph, multi-LLM routing, and HITL validation`

**Corps**
```
I've been building ELY for about a year as a personal project, and I'm open-sourcing it today.

ELY is a self-hosted AI agent designed for a small group of trusted users (family/small team),
not just a single developer.

Key design decisions that differ from similar projects:

1. **Multi-user by default** — 3-4 users per instance, isolated episodic + long-term memory per user. Most self-hosted agents (including the current most popular one) are single-user by design.

2. **HITL is not optional** — Human-In-The-Loop validation for sensitive actions is built into the architecture, not a plugin. The agent asks before it acts.

3. **LLM routing by complexity** — Simple queries stay on local Ollama (no external calls), medium go to Mistral, complex go to Claude/Gemini. Privacy-first by default.

4. **LangGraph multi-agent** — Supervisor + 6 specialized sub-agents. Stateful, traceable, debuggable.

5. **Vault service** — Dedicated secret management instead of .env files.

Stack: Python 3.12, FastAPI, LangGraph, SQLModel, Next.js 14, Three.js, Docker.

It integrates natively with Google Workspace (Gmail, Drive, Calendar, Contacts), Telegram, WhatsApp, and supports MCP.

The UI is a cyberpunk-themed web interface with a 3D animated avatar and TTS — which I know is unusual for this type of project, but it's been a surprisingly important factor in getting non-technical family members to actually use it.

GitHub: [LINK]
Docs: [LINK]

I'm particularly interested in feedback on the LangGraph architecture and the multi-user memory isolation approach.
```

---

#### GitHub Awesome Lists — Soumissions Recommandées

- `awesome-selfhosted` — catégorie "Personal Dashboards / Automation"
- `awesome-llm-apps` — catégorie "AI Agents"
- `awesome-langgraph` — si existant
- `awesome-local-ai` — catégorie "Agents"
- `awesome-chatbots` — catégorie "Self-hosted"

---

## 4. Calendrier de Contenu — 4 Premières Semaines

### Semaine 1 : Launch Blitz (J à J+7)

| Jour | Action | Canal |
|---|---|---|
| J | Lancement GitHub public | GitHub |
| J | Show HN | Hacker News |
| J | Thread Twitter/X | Twitter/X |
| J | Post r/selfhosted | Reddit |
| J | Post r/LocalLLaMA | Reddit |
| J+1 | Post LinkedIn | LinkedIn |
| J+1 | Post r/MachineLearning | Reddit |
| J+2 | Post r/artificial | Reddit |
| J+3 | Répondre à tous les commentaires/issues | GitHub + Reddit + HN |
| J+4 | Post Dev.to : "Why I built my own AI agent" | Dev.to |
| J+5 | Soumission Product Hunt | Product Hunt |
| J+7 | Thread Twitter recap "Week 1 stats" | Twitter/X |

### Semaine 2 : Deep-Dive Technique (J+8 à J+14)

| Action | Canal |
|---|---|
| Article : "How I implemented LangGraph multi-agent for a personal assistant" | Dev.to / Hashnode |
| Thread Twitter : diagramme architecture LangGraph | Twitter/X |
| Post r/programming : "Building a production-ready self-hosted AI agent" | Reddit |
| Répondre à toutes les issues GitHub ouvertes | GitHub |
| Article : "LLM routing by complexity — implementation details" | Dev.to |
| Discord serverside : partager dans servers LangGraph et LocalAI | Discord |

### Semaine 3 : Démonstrations Use Case (J+15 à J+21)

| Action | Canal |
|---|---|
| GIF/Video : "ELY gère mes emails du matin en 30 secondes" | Twitter/X + LinkedIn |
| Post : "How I use ELY with my family (multi-user setup)" | Reddit r/homelab |
| Article : "Google Workspace integration — technical walkthrough" | Dev.to |
| Thread : "HITL in practice — the actions ELY refuses to do alone" | Twitter/X |
| Post r/selfhosted : update semaine 3, nouvelles features | Reddit |

### Semaine 4 : Community Building (J+22 à J+28)

| Action | Canal |
|---|---|
| Créer/Annoncer channel Discord ELY | Discord |
| "Good first issues" taggés sur GitHub (5-10 issues) | GitHub |
| Post : "What I learned from 4 weeks of open source" | Dev.to / LinkedIn |
| Appel à contributions : "Looking for help with X" | Twitter/X + GitHub |
| Première release publique avec changelog | GitHub |
| Soumission aux newsletters (TLDR, Bytes, etc.) | Email |

---

## 5. Stratégie par Canal

### GitHub
- **Effort** : Élevé (préparation), puis moyen (maintenance)
- **Reach attendu** : Source principale de trafic organique long terme
- **Type de contenu** : Code, documentation, releases, issues, discussions
- **Fréquence** : Continue (commits, réponses issues)
- **Objectif J+30** : 200-500 étoiles (projet de niche technique)
- **Actions clés** : Tags, releases documentées, bon README, CI vert

### Twitter/X
- **Effort** : Moyen
- **Reach attendu** : Viral potentiel si RT par des comptes IA (>10k followers)
- **Type de contenu** : Threads techniques, GIFs, réponses à des discussions IA
- **Fréquence** : 3-5 posts/semaine le premier mois, puis 1-2/semaine
- **Stratégie** : Taguer des comptes pertinents (@LangChainAI, @karpathy si pertinent, etc.), utiliser #OpenSource #LocalLLM #SelfHosted

### LinkedIn
- **Effort** : Faible (1 post bien rédigé suffit)
- **Reach attendu** : Faible en volume mais forte qualité (développeurs seniors, tech leads)
- **Type de contenu** : Posts narratifs sur le "pourquoi", retours d'expérience
- **Fréquence** : 1 post/semaine maximum

### Reddit r/selfhosted
- **Effort** : Moyen
- **Reach attendu** : Fort pour le projet (communauté exactement ciblée, ~2,2M membres)
- **Type de contenu** : Posts descriptifs avec liste features, réponses aux questions
- **Fréquence** : 1 post au lancement + updates mensuels
- **Règle importante** : Ne pas spammer — un post de qualité vaut mieux que 5 posts moyens

### Reddit r/LocalLLaMA
- **Effort** : Moyen
- **Reach attendu** : Fort pour l'angle LLM routing / Ollama
- **Type de contenu** : Focus technique sur l'implémentation LLM
- **Fréquence** : 1 post au lancement + posts thématiques sur des sujets LLM

### Reddit r/MachineLearning
- **Effort** : Faible
- **Reach attendu** : Moyen (communauté plus académique, moins sensible au self-hosting)
- **Type de contenu** : Angle architecture LangGraph
- **Fréquence** : 1 post au lancement

### Reddit r/artificial + r/programming
- **Effort** : Faible
- **Reach attendu** : Variable
- **Fréquence** : 1 post chacun au lancement

### Hacker News
- **Effort** : Élevé (le post doit être parfait)
- **Reach attendu** : Très élevé si page d'accueil (10 000+ visiteurs en 24h)
- **Type de contenu** : Show HN technique, honnête sur les limites
- **Conseil** : Poster le mardi/mercredi matin EST, répondre à TOUS les commentaires dans les 2 premières heures
- **Fréquence** : 1 fois au lancement (ne pas spammer HN)

### Discord Servers Recommandés
- `LangChain / LangGraph` (officiel Langchain)
- `LocalAI Community`
- `Ollama`
- `r/selfhosted Discord`
- `AI Agents Community`
- `Python Discord` (channel #showcase)
- `Hugging Face`
- **Règle** : Toujours lire les règles du channel avant de poster — certains interdisent les "promotions" dans les channels généraux

### YouTube
- **Effort** : Élevé
- **Reach attendu** : Fort long terme (SEO vidéo)
- **Type de contenu** : Vidéo démo (5-10 min) : installation complète + démonstration features
- **Timing** : Préparer pour J+14 maximum
- **Titre suggéré** : "ELY: Build Your Own Self-Hosted AI Agent (Open Source) — Full Demo"

### Dev.to / Hashnode
- **Effort** : Moyen
- **Reach attendu** : Moyen (audience développeur anglophone)
- **Type de contenu** : Articles techniques approfondis
- **Fréquence** : 1 article/semaine le premier mois
- **Sujets** : Architecture LangGraph, LLM routing, HITL implementation, Google Workspace integration

### Product Hunt
- **Effort** : Moyen (préparation des assets)
- **Reach attendu** : Variable — fort si "Product of the Day"
- **Timing** : J+5 (laisser les premiers jours Reddit/HN construire du momentum)
- **Assets requis** : Logo, header image (1270x760), screenshots, 3 points "tagline", description 260 chars

---

## 6. Community Building

### Attirer les Early Adopters

**"Scratching your own itch" narrative** : Raconter honnêtement pourquoi ELY a été construit (pas de marketing bullshit — une vraie histoire). Les early adopters sont attirés par l'authenticité.

**Cible les "power users" de Self-Hosted** : Ce sont des personnes qui ont déjà Docker, Nginx, et une opinion sur les bases de données. Ne pas simplifier excessivement — parler leur langage.

**"Showcase builds"** : Encourager les premiers utilisateurs à partager leur configuration (comment ils ont déployé ELY, quelles skills ils ont créées). Retweeter / partager ces stories.

**"Build in public" sur Twitter/X** : Partager les prochaines features en cours de développement, demander des votes sur les priorités. Ça crée de l'attachement avant même la sortie de la feature.

### Setup Communautaire Discord

Structure recommandée pour un Discord ELY :
```
# BIENVENUE
  ├── #rules
  ├── #announcements
  └── #introductions

# SUPPORT
  ├── #installation-help
  ├── #configuration
  └── #bugs-report

# DEVELOPMENT
  ├── #roadmap-discussion
  ├── #feature-requests
  └── #contributors

# SHOWCASE
  ├── #deployments
  ├── #skills-sharing
  └── #use-cases

# GENERAL
  ├── #general-chat
  └── #off-topic
```

**Ne pas créer le Discord dès le lancement** — attendre d'avoir 50+ étoiles GitHub pour ne pas avoir un Discord vide qui nuit à l'image.

### Gestion Issues / PRs

**Issues** :
- Répondre dans les 24h les 2 premières semaines (critique pour la réputation)
- Utiliser des labels clairs : `bug`, `enhancement`, `good first issue`, `help wanted`, `documentation`
- Fermer les doublons proprement avec un lien vers l'issue parent
- Remercier systématiquement les reporters (même pour les mauvais rapports)

**PRs** :
- Template de PR avec checklist
- Review dans les 48-72h
- Mentionner les contributeurs dans le CHANGELOG
- Créer un fichier `CONTRIBUTORS.md` ou utiliser la feature GitHub automatique

### Incentives Contributeurs
- Mention dans le README (`## Contributors` section avec avatars GitHub)
- Badge "ELY Core Contributor" sur Discord
- Tag @contributor sur Twitter quand leur PR est mergée
- Pour les contributions majeures : feature release nommée en leur honneur ("The @username Update")

---

## 7. Métriques Clés à Suivre

### Stars GitHub
| Période | Objectif Minimal | Objectif Réaliste | Objectif Ambitieux |
|---|---|---|---|
| J+1 (24h) | 50 | 150 | 400 |
| J+7 | 100 | 300 | 800 |
| J+30 | 200 | 500 | 1 500 |
| J+90 | 350 | 1 000 | 3 000 |

**Référence** : AutoGPT avait ~500 étoiles après 1 semaine avant de décoller. OpenClaw 9 000 en 24h (exception absolue). Un projet sérieux et de niche peut espérer 200-500 étoiles en 30 jours avec une bonne communication.

### Autres Métriques
- **Forks** : Objectif J+30 : 20-50 (signe d'intention d'utilisation/modification)
- **Issues ouvertes** : 10-30 (signe de communauté active)
- **PRs reçues** : 3-10 en J+30 (signe de contributeurs)
- **Traffic GitHub** : Vues uniques, clones — visible dans Insights
- **Discord membres** : Objectif J+30 (si créé) : 50-100 membres actifs
- **Reddit upvotes** : Objectif par post : 50-200 upvotes
- **HN points** : 50+ points pour atteindre la page principale

### Tools de Suivi
- [Star History](https://star-history.com) — courbe d'étoiles GitHub
- GitHub Insights (trafic, referrers)
- Reddit post analytics (upvotes, comments, crosspost)

---

## 8. Budget

### Tactiques Zéro Budget (100% Organique)

Tout ce qui est décrit dans ce document peut être fait gratuitement :
- Posts Reddit, HN, Twitter, LinkedIn → 0€
- Discord → 0€ (tier gratuit suffisant pour démarrer)
- Dev.to / Hashnode → 0€
- GitHub → 0€
- Product Hunt → 0€

**Seul coût réel** : temps. Compter 2-3h pour le lancement jour J, puis 5-7h/semaine le premier mois.

### Budget Faible (50-200€)

- **Boost Reddit** (50-100€) : Sponsored post sur r/selfhosted ou r/LocalLLaMA. Rarement nécessaire si le contenu est bon, mais peut aider à lancer le momentum initial.
- **Boost Twitter** (50-100€) : Promouvoir le tweet d'annonce auprès d'une audience "developers + AI + self-hosted". ROI variable.
- **Logo / Design** (50-100€) : Si besoin d'un logo professionnel ou d'une image Product Hunt qualité.

### Budget Moyen (500€+)

- **Vidéo YouTube professionnelle** (200-500€) : Montage vidéo qualité par un freelance si la vidéo DIY ne convainc pas.
- **Sponsorship newsletter** (300-800€) : TLDR Newsletter (~500k abonnés dev), Bytes (~150k abonnés JS dev). ROI potentiellement excellent pour un lancement.
- **Hébergement demo public** (20-50€/mois) : Instance ELY demo accessible publiquement pour que les gens testent sans installer. Très impactant pour la conversion.

**Recommandation** : commencer à zéro budget. Si le lancement génère de l'intérêt mais pas de stars, investir 100-200€ en boost newsletter ciblée.

---

## 9. Hooks de Messaging

### L'Angle "Privacy-First"
```
"Your AI agent shouldn't know more about you than your bank does.
ELY routes simple queries to local Ollama — nothing leaves your machine."
```
*Cible* : Utilisateurs sensibles RGPD, paranoïaques des données, communauté self-hosted

### L'Angle "Your AI, Your Data"
```
"You pay for ChatGPT. ChatGPT trains on your conversations.
ELY costs you a $5/month VPS and keeps everything yours."
```
*Cible* : Ex-utilisateurs ChatGPT déçus, communauté anti-BigTech

### L'Angle "Works with Any LLM"
```
"Ollama, Claude, Mistral, Gemini, DeepSeek — ELY talks to all of them.
No vendor lock-in. Switch models in one config line."
```
*Cible* : Développeurs LLM, communauté r/LocalLLaMA

### L'Angle "Cyberpunk Aesthetic"
```
"Most AI agents look like a terminal from 1995.
ELY has a 3D animated avatar and a cyberpunk web UI.
Because your AI assistant deserves a face."
```
*Cible* : Développeurs qui valorisent l'UX, community tech Twitter, makers

### L'Angle "Multi-User / Famille"
```
"OpenClaw is single-user by design.
ELY runs for your whole family — each with their own memory, their own context.
Self-hosted AI for the people you trust."
```
*Cible* : Parents tech, r/homelab community, tech leads

### L'Angle "Never Acts Alone"
```
"ELY has HITL built in. It asks before it sends emails,
deletes files, or makes API calls.
No autonomous purchases. No surprise actions.
Your agent, not a rogue process."
```
*Cible* : Personnes ayant suivi les news sur les agents IA "going rogue", entreprises

---

## 10. Assets de Contenu Prêts à Publier

### 5 Tweets Prêts

**Tweet A — Lancement**
```
I just open-sourced ELY — my self-hosted AI agent built on LangGraph.

What makes it different:
→ Multi-user (3-4 per instance)
→ HITL: asks before acting on anything sensitive
→ LLM routing: simple queries stay on local Ollama
→ Google Workspace native
→ Cyberpunk 3D avatar + TTS

[link] 🦾
```

**Tweet B — Angle Sécurité**
```
While everyone's running AI agents with root access and no sandboxing...

ELY asks before it does anything sensitive.

HITL (Human-In-The-Loop) is built into the architecture.
Not a plugin. Not an option. The default.

Self-hosted AI that doesn't go rogue: [link]
```

**Tweet C — Angle Technique**
```
The ELY architecture in one diagram:

Supervisor agent
├── Research agent
├── Calendar agent
├── Email agent
├── Files agent
├── Web agent
└── Notifications agent

LangGraph. Python 3.12. FastAPI. Docker.

Each agent has a defined scope. No spaghetti.

Open source: [link]
```

**Tweet D — Angle Privacy**
```
With ELY, simple queries never leave your machine.

Complexity routing:
Simple → Ollama (local)
Medium → Mistral
Complex → Claude/Gemini

You decide where your data goes.

Self-hosted AI agent, open source: [link]
```

**Tweet E — Angle Famille**
```
Most AI agents are single-user.
ELY supports 3-4 users per instance with isolated memory.

I run it for my family.
My wife uses the web UI.
I use Telegram.
Kids can use WhatsApp.

One agent, your whole household.

[link]
```

---

### Post Reddit r/selfhosted — Prêt à Publier

**Titre** : `Show r/selfhosted: I built ELY — a self-hosted multi-user AI agent (LangGraph + multi-LLM routing + HITL). Open sourcing today.`

**Corps** :
```
Hey r/selfhosted,

Long-time lurker, first time posting a project.

After about a year of building, I'm open sourcing ELY — my personal AI agent designed from the ground up for self-hosters.

**What it is:**
A multi-user AI agent (3-4 users per instance) built on LangGraph with a supervisor + 6 specialized sub-agents. Deployed via Docker on a VPS.

**Why I built it instead of using existing solutions:**
- OpenClaw: amazing growth, but single-user, 9+ CVEs in 2 months, no web UI, Node.js (not Python)
- AutoGPT: great but overkill for personal use, complex to self-host
- n8n: workflow automation, not an agent
- I wanted something production-ready, not experimental

**Key features:**
- Multi-user with isolated episodic + long-term memory per user
- HITL (Human-In-The-Loop): the agent validates sensitive actions before executing
- LLM routing by complexity: simple queries stay on local Ollama, complex go to Claude/Gemini
- Google Workspace native: Gmail, Drive, Calendar, Contacts
- MCP support
- Vault service for secret management (no .env files with credentials)
- Cyberpunk web UI with 3D avatar + TTS (unexpected hit with non-technical family members)
- Telegram + WhatsApp channels

**Stack:**
Python 3.12 · FastAPI · LangGraph · SQLModel · Next.js 14 · Three.js · Docker

**GitHub:** [LINK]
**Docs:** [LINK]

Feedback, questions, and brutal criticism all welcome. Happy to discuss architecture decisions, particularly around the LangGraph multi-agent setup.
```

---

### Post Show HN — Prêt à Publier

**Titre** : `Show HN: ELY – Open source self-hosted AI agent, multi-user, LangGraph, HITL-first`

**Corps** :
```
ELY is a self-hosted AI agent I've been building for personal use over the past year,
now open-sourcing.

Design goals that drove the architecture:

1. Multi-user (3-4 trusted users, isolated memory per user) — I want to use this with family, not just solo
2. HITL-first — the agent validates sensitive actions before executing. Built into the supervisor layer, not optional.
3. Privacy-by-routing — simple queries go to local Ollama, complex ones to Claude/Gemini. Configurable.
4. Production deployment — Docker, FastAPI, SQLModel, proper secrets management (Vault service)

Architecture: LangGraph supervisor + 6 specialized sub-agents (research, calendar, email, files, web, notifications). Python 3.12, FastAPI backend, Next.js 14 frontend.

Integrations: Google Workspace (Gmail, Drive, Calendar, Contacts), Telegram, WhatsApp, MCP.

The UI is a cyberpunk-themed web interface with a Three.js 3D avatar and TTS — unusual for this category, but important for getting non-technical family members to actually use it daily.

GitHub: [LINK]
Docs: [LINK]

Technical questions I'm most interested in discussing: LangGraph multi-agent patterns, LLM routing strategies, multi-user memory isolation approaches.
```

---

### Post LinkedIn — Prêt à Publier

```
Un an de travail. Aujourd'hui, je l'open source.

ELY est mon agent IA personnel — self-hosted, multi-utilisateur, privacy-first.

Voici ce que j'ai voulu construire et pourquoi ça n'existait pas :

Un assistant IA qui tourne sur mon propre serveur. Qui peut servir toute ma famille (3-4 personnes, chacun avec sa propre mémoire). Qui route les requêtes simples vers Ollama local (rien ne quitte la machine). Qui valide les actions sensibles avant de les exécuter. Qui s'intègre avec Gmail, Drive, Calendar. Et qui a un vrai design — pas un terminal des années 90.

Architecture technique :
→ LangGraph (superviseur + 6 sous-agents spécialisés)
→ FastAPI + Next.js 14 + Docker
→ Routing LLM : Ollama → Mistral → Claude/Gemini selon la complexité
→ HITL natif (Human-In-The-Loop)
→ Interface web cyberpunk avec avatar 3D (Three.js) + TTS

Ce que j'ai appris en construisant ça :

La plupart des agents IA open source sont soit des projets "proof of concept" soit des monstres trop complexes à déployer. Il manquait quelque chose au milieu : une architecture sérieuse, production-ready, pensée pour un usage réel et quotidien.

Si vous travaillez sur des agents IA, que vous utilisez LangGraph, ou que vous cherchez à reprendre le contrôle de vos données — le code est disponible.

GitHub : [LINK]
Docs : [LINK]

Toujours preneur de feedback, d'échanges et de contributions. 🙏

#IA #OpenSource #SelfHosted #LangGraph #Python #AgentIA #Privacy
```

---

### README Hero Section — Texte

```markdown
<div align="center">

# ELY — Your Self-Hosted AI Agent

**Multi-user · Privacy-first · LangGraph · Multi-LLM · HITL**

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](docker-compose.yml)

[Getting Started](#installation) · [Documentation](docs/) · [Discord](#community) · [Roadmap](#roadmap)

---

*Your AI. Your server. Your data.*

ELY is an open source AI agent that runs on your own VPS, serves your whole family (up to 4 users with isolated memory), and never does anything without asking first.

Built on **LangGraph** with a supervisor + 6 specialized sub-agents. Supports **Ollama** (local), **Mistral**, **Claude**, **Gemini**, and **DeepSeek**. Routes queries by complexity — simple ones never leave your machine.

[Screenshot or GIF here]

</div>

## Why ELY?

| | ELY | OpenClaw | AutoGPT |
|---|---|---|---|
| Multi-user | ✅ 3-4 users | ❌ Single user | ❌ Single user |
| HITL validation | ✅ Built-in | ❌ None | ⚠️ Optional |
| Local LLM first | ✅ Ollama native | ✅ | ✅ |
| Web UI | ✅ Cyberpunk + 3D | ❌ | ⚠️ Basic |
| Production-ready | ✅ Docker + VPS | ⚠️ Node.js | ⚠️ |
| Security | ✅ Vault + isolation | ⚠️ 9+ CVEs | ⚠️ |
```

---

*Ce document est confidentiel et destiné à guider la stratégie de lancement ELY. À réviser avant utilisation pour mettre à jour les liens [LINK] avec les URLs réelles.*
---

## 11. Roadmap Pré-Lancement — Les 5 Chantiers Prioritaires

> Classés par ordre d'impact sur l'adoption et la crédibilité du projet.

---

### 🥇 Priorité 1 — Documentation utilisateur intégrée à l'UI

**Pourquoi en premier :** Un script d'installation performant peut attirer des profils non-techniques. Sans documentation contextuelle dans l'interface, ils seront perdus dès la première configuration.

**Ce qu'il faut construire :**

- **Wizard de configuration guidé** : au premier lancement, ELY détecte qu'aucune clé API n'est configurée et propose un guide pas-à-pas intégré à l'UI
- **URLs directes intégrées** : chaque étape contient le lien exact vers la page de création de clé (ex: "Créer votre clé Mistral → [mistral.ai/account/api-keys](https://console.mistral.ai/api-keys)")
- **Documentation contextuelle** : une icône `?` sur chaque champ de configuration ouvre une explication avec captures d'écran

**Sur l'idée d'autorisation Google sans Google Console :**

C'est faisable avec deux approches :

*Option A — OAuth app partagée "ELY Agent"* : le développeur enregistre une seule fois l'app dans Google Cloud. Les utilisateurs voient uniquement la popup "ELY souhaite accéder à Gmail..." → ils cliquent Autoriser. Zéro configuration Google Console pour eux. Nécessite une soumission à la vérification Google pour les scopes sensibles (Gmail).

*Option B — ELY prend le contrôle du poste* : ELY utilise Playwright (déjà intégré) pour ouvrir les pages de configuration dans le navigateur de l'utilisateur, remplir les formulaires, et récupérer les tokens générés. L'utilisateur regarde ELY travailler, et ELY le sollicite uniquement aux étapes qui exigent une action humaine (ex: "Cliquez sur 'Créer le projet' maintenant"). Cette approche est la plus ambitieuse mais offrirait une expérience unique dans l'écosystème des agents IA.

**Recommandation :** Option A d'abord (rapide), Option B comme feature showcase pour le lancement.

---

### 🥈 Priorité 2 — Documentation d'installation et de configuration

**Pourquoi en deuxième :** La documentation doit exister avant que le script soit publié — les utilisateurs qui rencontrent un problème avec le script doivent pouvoir s'y référer.

**Structure recommandée :**

```
docs/
├── getting-started.md       # Guide complet du débutant (30 min de A à Z)
├── installation/
│   ├── requirements.md      # Prérequis (VPS, OS, ports)
│   ├── docker.md            # Installation Docker step-by-step
│   ├── vps-setup.md         # Configuration VPS recommandée
│   └── tailscale.md         # Configuration réseau privé
├── configuration/
│   ├── llm-providers.md     # Créer et configurer les clés API (Claude, Mistral, Gemini, Ollama)
│   ├── google-workspace.md  # OAuth Google étape par étape (avec captures d'écran)
│   ├── telegram.md          # Créer et connecter le bot Telegram
│   └── whatsapp.md          # Configuration WhatsApp Business API
├── architecture/
│   ├── overview.md          # Vue d'ensemble LangGraph + superviseur + sous-agents
│   └── sub-agents.md        # Détail des 6+1 sous-agents
└── faq.md                   # Questions fréquentes + dépannage
```

**Format :** Markdown avec captures d'écran, GIFs pour les étapes complexes, commandes copiables en un clic.

---

### 🥉 Priorité 3 — Script d'installation complet (`install.sh`)

**Objectif :** `curl -fsSL https://get.ely.ai | bash` — une commande, tout est fait.

**Ce que le script doit faire :**

```bash
# Étape 1 — Vérification de l'environnement
- Détection de l'OS (Ubuntu 22.04/24.04, Debian 12, macOS)
- Vérification de la RAM disponible (minimum 4 Go recommandé)
- Vérification du stockage disponible (minimum 20 Go)
- Vérification Docker : installé ? version ? → sinon, proposition d'installation automatique

# Étape 2 — Installation des dépendances
- Docker + Docker Compose (si absent)
- Tailscale (optionnel, avec demande à l'utilisateur)
- git (si absent)

# Étape 3 — Téléchargement d'ELY
- Clone du repo GitHub
- Sélection de la version (stable / latest)

# Étape 4 — Configuration interactive
- Demande du domaine ou IP du VPS
- Génération automatique des secrets (JWT_SECRET, clés de chiffrement)
- Menu interactif : "Quels LLMs voulez-vous utiliser ?"
  → Ollama local : téléchargement automatique du modèle recommandé (qwen2.5:7b)
  → Mistral : "Collez votre clé API Mistral : "
  → Claude : "Collez votre clé API Anthropic : "
  → Gemini : "Collez votre clé API Google AI : "
- Configuration Tailscale (si choisi) : ouverture du navigateur pour authentification

# Étape 5 — Démarrage
- docker compose up -d
- Vérification de la santé des services
- Affichage de l'URL d'accès

# Étape 6 — Compte administrateur
- Création du premier compte utilisateur admin
- Lancement du wizard de configuration Google OAuth (option A ou B)

# Étape 7 — Résumé
- Récapitulatif de ce qui est configuré / ce qui reste à faire
- Liens vers la documentation pour les étapes optionnelles
```

**Point important sur la sécurité du script :** Le script ne doit jamais stocker les clés API en clair dans des fichiers temporaires. Il doit écrire directement dans le `.env` avec les permissions appropriées (`chmod 600`).

---

### 4️⃣ Priorité 4 — Registre de Skills avec analyse de sécurité

**Concept :** Une place de marché de skills (comme l'App Store, mais pour les capacités d'ELY).

**Architecture proposée :**

- **Format de skill** : fichier YAML + Python (ou YAML seul pour les skills simples)
- **Registre central** : dépôt GitHub `ely-agent/skills` avec structure validée
- **ClawHub-inspired mais sécurisé** : contrairement à OpenClaw qui a eu 341 skills malicieux, ELY impose une validation obligatoire

**Pipeline de sécurité avant installation :**

```
Téléchargement du skill
        ↓
Analyse statique AST (Python)
  - Détection d'imports dangereux (os.system, subprocess, eval, exec)
  - Détection d'URLs hardcodées (exfiltration potentielle)
  - Détection de tentatives d'accès fichiers sensibles (.env, ~/.ssh)
        ↓
Analyse du prompt système (si présent)
  - Détection de patterns de jailbreak
  - Détection d'instructions d'override
  - Détection de tentatives d'extraction de mémoire
        ↓
Sandbox d'exécution (Docker isolé)
  - Test fonctionnel dans un environnement sans réseau
  - Vérification que le skill ne tente pas d'accès réseau non déclaré
        ↓
Score de confiance (0-100)
  - 80+ : installation automatique proposée
  - 50-79 : installation avec avertissement
  - < 50 : bloqué, rapport détaillé affiché
        ↓
Validation HITL (pour les skills avec accès réseau ou système)
  - L'utilisateur voit exactement ce que le skill peut faire
  - Confirmation explicite requise
```

**Différenciateur fort vs OpenClaw :** Ce pipeline de sécurité est à mentionner explicitement dans le README — c'est l'argument décisif pour les utilisateurs qui ont été brûlés par les 341 skills malicieux d'OpenClaw.

---

### 5️⃣ Priorité 5 — Discord : Communauté, pas Canal

**Clarification importante :** Discord n'est pas prioritaire comme *canal de messagerie pour ELY* (peu d'intérêt si votre entourage utilise Telegram/WhatsApp). En revanche, Discord est *la* plateforme de référence pour construire une communauté open source tech.

**Ce que Discord apporterait au projet ELY :**

| Usage | Valeur |
|-------|--------|
| Support communautaire | Les utilisateurs s'entraident sans surcharger les GitHub Issues |
| Annonces de versions | Notification instantanée aux early adopters |
| Partage de skills/configs | Les utilisateurs partagent leurs configurations et skills |
| Feedback produit | Canal dédié aux suggestions de fonctionnalités |
| Recrutement de contributeurs | Les développeurs intéressés trouvent où s'impliquer |

**Recommandation :** Créer le serveur Discord *au moment du lancement* (pas avant — inutile vide). Structure minimale :
- `#annonces` (readonly)
- `#installation-help`
- `#skills-partage`
- `#idées-fonctionnalités`
- `#général`

**Pour toi personnellement :** Tu n'as pas besoin d'utiliser Discord toi-même au quotidien. Un bot Discord (ironiquement, ELY lui-même pourrait le gérer) peut relayer les annonces GitHub automatiquement.

---

### 📊 Récapitulatif Roadmap

| Priorité | Chantier | Effort | Impact Adoption |
|----------|----------|--------|-----------------|
| 1 | Documentation UI + Wizard | Moyen | 🔴 Critique |
| 2 | Documentation installation | Faible | 🔴 Critique |
| 3 | Script `install.sh` | Élevé | 🟠 Fort |
| 4 | Registre de skills sécurisé | Très élevé | 🟡 Moyen (long terme) |
| 5 | Serveur Discord communauté | Faible | 🟡 Moyen (long terme) |

> **Note :** Les priorités 1 et 2 sont des prérequis au lancement public. Les priorités 3, 4 et 5 peuvent être annoncées comme "coming soon" dans le README initial pour montrer que le projet est vivant et ambitieux.

