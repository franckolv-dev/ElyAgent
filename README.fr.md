<div align="center">

<a href="README.md">English</a> · <a href="README.fr.md">Français</a>

<img src="https://agent-ely.fr/ely-logo.jpeg" alt="ELY — agent IA souverain" width="200" />

# ELY

### Un agent IA auto-hébergé qui anonymise les données sensibles *avant* tout appel LLM.

Multi-utilisateur · multi-canal · RGPD natif · validation humaine sur chaque action irréversible.
Conçu pour les particuliers, les familles et les PME qui ne peuvent pas se permettre de fuiter leurs données vers une IA tierce.

[**Site web**](https://agent-ely.fr) ·
[**Documentation**](./docs/START_HERE.md) ·
[**Licence**](https://agent-ely.fr/pricing.html) ·
[**Discussions**](https://github.com/franckolv-dev/ElyAgent/discussions)

[![Elastic License v2](https://img.shields.io/badge/license-Elastic%20License%20v2-13bbc2?style=flat-square)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/franckolv-dev/ElyAgent?style=flat-square&color=13bbc2)](https://github.com/franckolv-dev/ElyAgent/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/franckolv-dev/ElyAgent/ci.yml?style=flat-square&label=tests)](https://github.com/franckolv-dev/ElyAgent/actions)
[![Stars](https://img.shields.io/github/stars/franckolv-dev/ElyAgent?style=flat-square&color=13bbc2)](https://github.com/franckolv-dev/ElyAgent/stargazers)
[![Discussions](https://img.shields.io/github/discussions/franckolv-dev/ElyAgent?style=flat-square&color=13bbc2)](https://github.com/franckolv-dev/ElyAgent/discussions)

[![Python](https://img.shields.io/badge/Python-3.12+-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000?style=flat-square&logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0-orange?style=flat-square)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docs.docker.com/compose/)

</div>

> **À propos de la licence.** ELY est sous **[Elastic License v2](LICENSE)** — gratuit pour tout usage personnel ET tout usage professionnel interne, quelle que soit la taille de l'organisation. Vous pouvez exécuter, modifier, redistribuer. La seule restriction : pas de revente comme service hébergé / managé à des tiers (pas de SaaS). Code source intégralement publié et auditable.

---

## Pourquoi ELY existe

Les agents IA cloud — ChatGPT, Claude, Gemini, le futur Google Remy, OpenAI Operator, Microsoft Copilot — sont puissants, mais ils partagent tous la même architecture : **vos données brutes partent vers un serveur tiers aux États-Unis.** E-mails, IBAN, noms de clients, dossiers médicaux, projets de contrats — tout transite par des modèles que vous ne contrôlez pas, dans des juridictions qui ne sont pas la vôtre.

Pour un particulier curieux, c'est un compromis. **Pour un cabinet d'avocats, un cabinet médical, une PME qui traite des contrats ou des dossiers clients — c'est un non-sujet.** Le secret professionnel, le RGPD, les secteurs réglementés ne permettent pas ce compromis.

ELY est la réponse pour les particuliers et les organisations qui ont besoin d'un agent IA **qui tourne sur leur matériel, anonymise les données sensibles avant tout appel modèle, demande l'autorisation avant chaque action irréversible, et respecte la souveraineté européenne par défaut.**

---

## Les quatre piliers

<table>
<tr>
<td width="50%" valign="top">

### Souveraineté
**Votre matériel. Vos données. Votre juridiction.**

- Auto-hébergé sur Mac, serveur, NAS, on-premise ou cloud souverain
- Routage local-first — les tiers simples/moyens utilisent votre modèle local (Ollama, LM Studio MLX). Mistral privilégié pour le tier C cloud, données conservées dans l'UE.
- RGPD natif par construction · DPA disponible · modèle d'AIPD fourni
- Zéro télémétrie · zéro phone-home · aucune dépendance cloud forcée
- Code source auditable (Elastic License v2)

</td>
<td width="50%" valign="top">

### Sécurité
**Les données sensibles n'atteignent jamais le LLM. Les actions irréversibles ne s'exécutent jamais sans autorisation.**

- **Anonymisation PII native** — e-mails, IBAN, cartes bancaires, jetons d'API, numéros de téléphone, SIRET, identifiants salariés masqués avant la construction du prompt. Non désactivable silencieusement.
- **HITL structurel** — chaque outil irréversible (envoi de mail, suppression, SSH, partage) attend une validation explicite. Autoriser une fois · refuser une fois · **bannir définitivement**.
- Coffre chiffré (AES-256-GCM, zero-knowledge) pour les identifiants.
- Journal d'audit immuable — chaque validation tracée, exportable pour la conformité.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### Intégration
**Branché sur les outils que vos équipes utilisent déjà.**

- **Google Workspace complet** — Gmail, Calendar, Drive, Docs, Sheets, Tasks, Contacts (76 outils, lecture/écriture intégrale avec HITL sur chaque action destructive)
- 10 canaux — Web · Voix (mot-clé « Éli ») · PWA · iOS natif · Android natif · Telegram · WhatsApp · Slack · Discord · push ntfy
- Notifications push natives pour les validations HITL (FCM + APNs) — la plupart des concurrents ne proposent qu'un proxy via bot de messagerie
- 148 outils sur web automation, système, RAG, coffre, missions

</td>
<td width="50%" valign="top">

### Architecture
**Multi-utilisateur. Multi-LLM. Conçu pour passer à l'échelle d'une famille ou d'une organisation.**

- **Multi-utilisateur natif** — un déploiement sert une famille, une équipe, une PME. Chaque utilisateur a sa mémoire, son coffre, sa file de validation.
- **Multi-LLM avec tiers de complexité** — assignez des modèles différents aux Tiers A (rapide) / B (standard) / C (profond) / IMG / SYS. Local pour les tâches simples, Mistral ou Anthropic pour les complexes — votre choix, sans redémarrage.
- 11 fournisseurs LLM supportés · bascule automatique en cas de panne · cache de prompt Anthropic activé
- Mappage canal-utilisateur empêchant l'usurpation entre plateformes

</td>
</tr>
</table>

---

## ELY face aux alternatives — comparatif honnête

Nous respectons ce que les autres projets font bien. Nous sommes explicites sur ce qui nous distingue.

| | **ELY** | Autres agents auto-hébergés | Assistants IA hébergés |
|---|:---:|:---:|:---:|
| Auto-hébergé sur votre matériel | ✅ | ✅ | ❌ |
| **PII anonymisées avant l'appel LLM** | ✅ Natif | ⚠️ Plugin ou absent | ❌ |
| **HITL actif par défaut, non désactivable** | ✅ Structurel | ⚠️ Configurable | N/A |
| **Multi-utilisateur (famille / équipe / PME)** | ✅ | ❌ Souvent mono-user | ✅ (cloud éditeur) |
| **Routage hybride local / cloud** | ✅ Tiers explicites | ⚠️ Manuel / partiel | ❌ |
| Apps mobiles natives (iOS + Android) | ✅ | ❌ Rare | ✅ |
| Coffre chiffré (zero-knowledge) | ✅ AES-256-GCM | ❌ Rare | ❌ |
| Interface française complète | ✅ | ⚠️ Souvent EN only | ⚠️ Partielle |
| Licence | Source-available | Variable | Propriétaire |

> **Notre lecture honnête.** D'autres agents auto-hébergés ont des communautés plus larges et plus d'adaptateurs de canaux. **Si vous traitez des données que vous ne pouvez pas vous permettre de divulguer — les vôtres, celles de votre famille, celles de vos clients — le pipeline d'anonymisation et le HITL structurel d'ELY sont les raisons qui vous le feront choisir face aux alternatives.**

---

## À qui s'adresse ELY

ELY est conçu pour deux audiences distinctes. Toutes deux exécutent le même code.

**Particuliers et familles soucieux de leur vie privée** — vous voulez un assistant IA puissant mais vous refusez d'envoyer votre boîte mail, vos relevés bancaires et votre historique médical à OpenAI ou Anthropic. Gratuit sous la licence personnelle. Jusqu'à 4 membres de la famille sur un déploiement.

**PME en secteurs réglementés** — cabinets d'avocats, expertise comptable, cabinets médicaux, conseil RH, notaires, collectivités. Vous traitez des données couvertes par le secret professionnel ou le RGPD. Le pipeline d'anonymisation d'ELY fait la différence entre *« on a envisagé l'IA »* et *« on a déployé l'IA »*. L'usage professionnel interne est entièrement couvert par la licence Elastic v2 — aucun contrat additionnel requis.

→ Personas détaillés et scénarios de déploiement sur **[agent-ely.fr](https://agent-ely.fr)**.

---

## Démarrage rapide

**Pré-requis :** Docker · Docker Compose · 16 Go RAM (32 Go pour les LLM locaux) · 20 Go disque · `make` (préinstallé sur Mac et la plupart des Linux) · `openssl` (préinstallé partout).

```bash
# 1. Cloner
git clone https://github.com/franckolv-dev/ElyAgent.git
cd ElyAgent

# 2. Configurer — minimum requis : un secret JWT
cp .env.example .env
# Génère un secret hex de 64 caractères et remplace le placeholder dans .env :
sed -i.bak "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$(openssl rand -hex 32)|" .env && rm .env.bak

# 3. Choisir un fournisseur LLM (OBLIGATOIRE — sans ça, ELY ne peut rien répondre)
# Option gratuite la plus simple : clé Google Gemini (Anthropic / Mistral / OpenAI marchent aussi)
# 1. Récupérer une clé gratuite sur https://aistudio.google.com/apikey
# 2. La coller dans .env sur la ligne GEMINI_API_KEY=
# 3. Changer ACTIVE_LLM_PROVIDER de "ollama" à "gemini" dans .env
#
# Liste complète des fournisseurs et liens de configuration : docs/SETUP_AI_PROVIDERS.md

# 4. Lancer la stack (le premier `make up` télécharge ~2 Go d'images, durée 5-10 min)
make up

# 5. Surveiller les logs jusqu'à ce que le backend soit prêt
make logs s=backend     # ctrl-C dès que tu vois "Application startup complete"

# 6. Ouvrir http://localhost:3000 — la première inscription devient admin
#    Politique de mot de passe : min 12 caractères, au moins 1 majuscule + 1 caractère spécial (!@#$%^&*…)
```

> **Sans clé LLM** : ELY démarre mais chaque message de chat échouera avec
> une erreur de connexion. La valeur par défaut `ACTIVE_LLM_PROVIDER=ollama`
> suppose qu'un Ollama tourne en local sur la machine hôte — installe-le
> depuis https://ollama.ai ou bascule sur un fournisseur cloud dans `.env`.

→ **[Guide d'installation complet pour non-développeurs →](./docs/START_HERE.md)**
Quatre scénarios, du POC local en 30 minutes (Scénario A) au déploiement à distance complet avec Cloudflare Tunnel et tous les canaux de messagerie (Scénario D).

→ **[Configuration de l'extension navigateur →](./extension/chrome/README.md)** pour qu'ELY agisse dans tes vrais onglets Chrome (LinkedIn, Gmail, GitHub, Amazon…) avec tes sessions existantes. Optionnel mais c'est la fonctionnalité tueuse.

→ **[Dépannage →](./docs/TROUBLESHOOTING.md)** si `make up` plante, le premier chat échoue ou des ports sont déjà occupés.

---

## Ce qu'ELY sait faire

Une vraie UI produit sur chaque surface — **pas un terminal déguisé en site web.** Beaucoup d'agents auto-hébergés sont d'abord des outils en ligne de commande ; ELY traite l'UI comme un citoyen de première classe, y compris pour les utilisateurs non techniques.

<details>
<summary><strong>Pipeline de sécurité</strong> — masquage PII · HITL · coffre · journal d'audit</summary>

- **Pipeline de masquage PII.** Détection regex + heuristiques ML pour e-mails, IBAN, cartes bancaires, jetons d'API, numéros de téléphone, SIRET, identifiants salariés. Placeholders déterministes. Restitution uniquement à l'affichage côté utilisateur.
- **Validation humaine.** Bloque par défaut plus de 30 catégories d'outils. Trois actions : autoriser une fois, refuser une fois, **bannir définitivement** (persisté entre toutes les sessions futures).
- **Coffre chiffré.** AES-256-GCM, clé dérivée du mot de passe utilisateur. Zero-knowledge — le serveur ne peut rien lire après verrouillage. Stocke clés API, jetons OAuth, identifiants de canaux.
- **Journal d'audit.** Chaque décision de validation est journalisée de manière immuable (JSON Lines). Exportable pour la conformité.

[Modèle de sécurité complet →](./docs/security.md)

</details>

<details>
<summary><strong>Moteur multi-LLM</strong> — vos clés, routage par complexité</summary>

Configurez les fournisseurs dans **Réglages → Modèles IA**. Assignez chaque tier (A/B/C/IMG/SYS) à un modèle. Changez à tout moment, sans redémarrage. Les modèles locaux (Ollama, LM Studio) bénéficient de prompts compacts auto-détectés pour que les modèles 7B obéissent réellement à `tool_choice="required"`.

- **Cloud :** OpenAI · Anthropic · Gemini · Qwen API · Moonshot Kimi K2.x · Mistral · DeepSeek · Zhipu · OpenRouter
- **Local :** Ollama · LM Studio (MLX sur Apple Silicon)
- **Bascule automatique** si un fournisseur tombe — désactivable par tier pour des tests 100 % locaux.
- **Cache de prompt Anthropic** activé là où c'est supporté (jusqu'à 90 % de réduction de coût).

</details>

<details>
<summary><strong>Missions</strong> — boucle orientée objectif, persistante entre redémarrages</summary>

Donnez un objectif à ELY — elle le décompose en étapes, choisit les outils, exécute, évalue, replanifie en cas d'échec et vous notifie quand c'est terminé. Survit aux redémarrages backend (checkpointer LangGraph SQLite).

Cinq garde-fous : budget de tokens · budget d'itérations · deadline optionnelle · HITL sur outils critiques · anti-boucle après 3 échecs consécutifs. Notifications en parallèle : web · DM Telegram · push ntfy.

</details>

<details>
<summary><strong>Canaux</strong> — 10 façons de joindre ELY</summary>

Web · Voix (mot-clé « Ély ») · PWA · iOS natif · Android natif · Telegram · WhatsApp · Slack · Discord · push ntfy.

Même agent, même mémoire, même sécurité sur toutes les surfaces. Apps natives iOS (SwiftUI) et Android (Kotlin/Compose) avec push FCM/APNs pour les validations HITL — la plupart des concurrents ne proposent qu'un proxy via bot de messagerie.

</details>

<details>
<summary><strong>Mémoire & RAG</strong> — Qdrant local + SQLite FTS5</summary>

PDF · TXT · Markdown · CSV · JSON · DOCX. fastembed + Qdrant pour la recherche sémantique, SQLite FTS5 pour le mot-clé. ELY décide elle-même si une recherche est utile avant de répondre, classe les résultats, cite les sources. Aucune donnée envoyée à des services d'embeddings distants — tout est local.

</details>

<details>
<summary><strong>Arena LLM</strong> — comparatif aveugle avec classement ELO</summary>

Choisissez deux fournisseurs configurés. Votez sans savoir lequel est lequel. Classement ELO K=32. Les fournisseurs locaux sont pingés avant d'être ajoutés — plus de matchs `[connection failed]`.

</details>

<details>
<summary><strong>ELY Desktop</strong> — daemon Go natif pour l'automatisation locale</summary>

Connexion WebSocket sortante — votre poste n'a jamais besoin d'être joignable depuis l'extérieur. Capacités : capture d'écran · clavier/souris · lanceur d'app · presse-papier · opérations fichiers locales (HITL) · infos système.

</details>

<details>
<summary><strong>Smart File Manager (Android)</strong> — nettoyage on-device</summary>

Détection de doublons exacts par MD5 (élagage par taille), doublons visuels par dHash perceptuel (Hamming ≤ 6), filtres déclaratifs (taille/âge/catégorie/extension). **Les fichiers ne transitent jamais par le backend** — tout reste sur votre téléphone.

</details>

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  ENTRÉE  ─→  SecurityFilter (masquage PII)  ─→  Routeur complexité   │
│                                                          │           │
│  RÉPONSE ←─  Restitution réelle  ←─  HITL  ←─  LangGraph             │
│                                                          │           │
│                                              ┌───────────┼─────────┐ │
│                                              ▼           ▼         ▼ │
│                                          LLM local    Outils     Cloud│
│                                          (Ollama)     (148)    (PII- │
│                                                                masqué)│
└──────────────────────────────────────────────────────────────────────┘
```

Un agent multi-canal, multi-utilisateur, hybride local/cloud bâti sur FastAPI + LangGraph (backend), Next.js 16 (frontend), clients natifs iOS/Android et un daemon desktop en Go.

→ [Architecture complète](./docs/architecture.md) · [Modèle de sécurité](./docs/security.md)

---

## Stack

| Couche | Technologie |
|--------|-------------|
| Backend | Python 3.12 · FastAPI · LangGraph · uv |
| Frontend | Next.js 16 · TypeScript · Tailwind · Three.js |
| Mobile | iOS SwiftUI · Android Kotlin/Compose |
| Daemon desktop | Go (Linux · macOS · Windows) |
| Fournisseurs LLM | 11 (cloud + local) |
| Mémoire | Qdrant · SQLite FTS5 · fastembed |
| Automation navigateur | Playwright |
| STT / TTS | faster-whisper · edge-tts |
| Auth | JWT HS256 · Argon2id · cookie HttpOnly |
| Coffre | AES-256-GCM, dérivation de clé par utilisateur |
| Push | FCM · APNs · Telegram · WebSocket |
| Infra | Docker Compose · nginx · Cloudflare Tunnel |

---

## Roadmap

**Sprint 0** *Mai 2026* — Ouverture du dépôt public. Refonte UI, routage multi-domaines, bascule mono-agent, garde-fous anti-hallucination, 92/92 tests verts.

**Sprint 1** *Juin 2026* — Mémoire transversale entre conversations (FTS5 + résumé LLM à la demande). Le sprint avec le meilleur ratio valeur perçue / effort de l'année.

**Sprint 2** *Juin 2026* — Registre d'outils auto-découvert (décorateur `@register` avec analyse AST).

**Sprint 3** *Juillet 2026* — Vecteur d'état utilisateur (humeur · focus actuel · dossiers ouverts · budget d'attention) — équivalent fonctionnel le plus proche d'un World Model transparent.

**Sprint 4** *Août 2026* — MCP client + serveur. Consommer n'importe quel serveur MCP (Claude Desktop, Cursor, Zed). Exposer ELY comme serveur MCP également.

→ [Roadmap publique complète avec efforts annoncés →](https://agent-ely.fr/roadmap.html)

[Envie d'influencer la roadmap ? Ouvrez une discussion →](https://github.com/franckolv-dev/ElyAgent/discussions)

---

## Contribuer

ELY est source-available. Les contributions sont bienvenues dans le cadre de la licence :

✅ Corrections de bugs · documentation · traductions · adaptateurs de canaux · améliorations de performance · couverture de tests
⚠️ Changements architecturaux — ouvrez d'abord une issue
❌ Les forks sans accord préalable, les suppression des en-têtes de licence et le code désactivant HITL par défaut ne sont pas autorisés

[Guide de contribution complet →](./CONTRIBUTING.md) · [Code de conduite →](./CODE_OF_CONDUCT.md) · [Politique de sécurité →](./SECURITY.md) (merci de signaler les vulnérabilités par e-mail, pas en issue publique)

---

## Licence

**Code source** — [Elastic License v2](LICENSE)

ELY est gratuit pour tout usage personnel et tout usage professionnel interne, quelle que soit la taille de l'organisation. La seule restriction : pas de revente d'ELY comme service hébergé / managé à des tiers (pas de SaaS).

→ [Résumé en langage clair sur le site officiel →](https://agent-ely.fr/pricing.html)

**Marques.** Le nom **Ely** (acronyme de *« Exactly Like You »*, prononcé « Éli »), **agent-ely.fr**, l'avatar 3D et le logo éclair sont protégés indépendamment du code.

**Contact :** [contact@agent-ely.fr](mailto:contact@agent-ely.fr) — réponse sous 48 h, toujours.

---

<div align="center">

**Construit en Nouvelle-Aquitaine, France **

[Site web](https://agent-ely.fr) · [Documentation](./docs/START_HERE.md) · [Newsletter](https://agent-ely.fr/newsletter.html)

</div>
