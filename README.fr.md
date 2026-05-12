<div align="center">

<a href="README.md">English</a> · <a href="README.fr.md">Français</a>

<img src="https://agent-ely.fr/ely-logo.jpeg" alt="ELY — agent IA souverain" width="200" />

# ELY

### Un agent IA auto-hébergé qui anonymise les données sensibles *avant* tout appel LLM.

Multi-utilisateur · multi-canal · RGPD natif · validation humaine sur chaque action irréversible.
Conçu pour les particuliers, les familles et les PME qui ne peuvent pas se permettre de fuiter leurs données vers une IA tierce.

[**Site web**](https://agent-ely.fr) ·
[**Documentation**](./docs/START_HERE.md) ·
[**Tarifs**](https://agent-ely.fr/pricing.html) ·
[**Discussions**](https://github.com/franckolv-dev/ElyAgent/discussions)

[![Source-available](https://img.shields.io/badge/source--available-PolyForm%20Strict%201.0-13bbc2?style=flat-square)](LICENSE)
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

> **À propos de la licence.** ELY est **source-available**, et non open-source au sens OSI. Le code source est intégralement publié, auditable et gratuit pour un usage personnel, familial et éducatif. Tout déploiement commercial nécessite une [licence commerciale](https://agent-ely.fr/pricing.html). Ce modèle nous permet de pérenniser le projet sans capital-risque ni risque d'arrêt.

---

## Pourquoi ELY

La plupart des agents IA envoient vos données brutes — e-mails, IBAN, noms de clients, notes médicales — directement à un LLM tiers. L'écosystème des agents a grandi vite en 2025-2026 ; la sécurité, non. ELY repose sur trois choix de conception non négociables :

<table>
<tr>
<td width="50%" valign="top">

### Les données sensibles n'atteignent jamais le LLM
E-mails, IBAN, cartes bancaires, jetons d'API, numéros de téléphone, SIRET — détectés et remplacés par des placeholders déterministes **avant** la construction du prompt. Le modèle voit `[EMAIL_0]`. Vous voyez la vraie valeur. **Natif, pas un plugin. Ne peut pas être désactivé silencieusement.**

</td>
<td width="50%" valign="top">

### Validation humaine sur chaque action irréversible
Envoi de mail, suppression de fichier, commande SSH, partage — chaque outil destructif est mis en pause pour validation explicite. Même UX sur web, Telegram, Slack, Outlook, push mobile. Autoriser une fois · refuser une fois · **bannir définitivement**, persisté entre toutes les sessions.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### Multi-utilisateur, natif
Un seul déploiement sert une famille, une équipe ou une PME. Chaque utilisateur a sa propre mémoire, son coffre de secrets, sa file de validation. Le mappage des canaux empêche l'usurpation d'identité entre plateformes de messagerie.

</td>
<td width="50%" valign="top">

### ⚡ Routage hybride local / cloud
Les tâches simples et moyennes sont traitées par votre modèle local (Ollama, LM Studio MLX). Les tâches complexes appellent une API cloud — uniquement après masquage des PII. **Configurable par tier de complexité, sans code, sans redémarrage.**

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
| Licence commerciale disponible | ✅ | Variable | N/A |

> **Notre lecture honnête.** D'autres agents auto-hébergés ont des communautés plus larges et plus d'adaptateurs de canaux. **Si vous traitez des données que vous ne pouvez pas vous permettre de fuiter — les vôtres, celles de votre famille, celles de vos clients — le pipeline d'anonymisation et le HITL structurel d'ELY sont les raisons qui vous le feront choisir face aux alternatives.**

---

## À qui s'adresse ELY

ELY est conçu pour deux audiences distinctes. Toutes deux exécutent le même code.

**Particuliers et familles soucieux de leur vie privée** — vous voulez un assistant IA puissant mais vous refusez d'envoyer votre boîte mail, vos relevés bancaires et votre historique médical à OpenAI ou Anthropic. Gratuit sous la licence personnelle. Jusqu'à 4 membres de la famille sur un déploiement.

**PME en secteurs réglementés** *(licence commerciale)* — cabinets d'avocats, expertise comptable, cabinets médicaux, conseil RH, notaires, collectivités. Vous traitez des données couvertes par le secret professionnel ou le RGPD. Le pipeline d'anonymisation d'ELY fait la différence entre *« on a envisagé l'IA »* et *« on a déployé l'IA »*.

→ Personas détaillés, scénarios de déploiement et tarifs sur **[agent-ely.fr](https://agent-ely.fr)**.

---

## Démarrage rapide

**Pré-requis :** Docker · Docker Compose · 16 Go RAM (32 Go pour les LLM locaux) · 20 Go disque.

```bash
# 1. Cloner
git clone https://github.com/franckolv-dev/ElyAgent.git
cd ElyAgent

# 2. Configurer — minimum requis : un secret JWT
cp .env.example .env
echo "JWT_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')" >> .env

# 3. Lancer la stack
make up

# 4. Ouvrir http://localhost:3000 — la première inscription devient admin
```

→ **[Guide d'installation complet pour non-développeurs →](./docs/START_HERE.md)**
Quatre scénarios, du POC local en 30 minutes (Scénario A) au déploiement à distance complet avec Cloudflare Tunnel et tous les canaux de messagerie (Scénario D). Aucune connaissance préalable de Docker, Google Cloud ou des API n'est requise.

---

## Ce qu'ELY sait faire

Une vraie UI produit sur chaque surface — **pas un terminal déguisé en site web.** Beaucoup d'agents auto-hébergés sont d'abord des outils en ligne de commande ; ELY traite l'UI comme un citoyen de première classe, y compris pour les utilisateurs non techniques.

<details>
<summary><strong>🔒 Pipeline de sécurité</strong> — masquage PII · HITL · coffre · journal d'audit</summary>

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

## Licence & usage commercial

**Code source** — [PolyForm Strict License 1.0.0](LICENSE)

✅ **Gratuit pour :** usage personnel · usage familial · apprentissage · recherche non commerciale
❌ **Nécessite une licence commerciale :** tout déploiement générant du revenu · intégration dans un produit payant · redistribution de versions modifiées · entraînement d'autres IA sur ce code

Tarification annuelle transparente, par organisation, sans coût par utilisateur ni par appel LLM :

| Palier | Périmètre | Tarif |
|--------|-----------|-------|
| **Personnel** | Famille, apprentissage, évaluation | **Gratuit** |
| **Pro** | 1 organisation · jusqu'à 5 utilisateurs | **490 € / an** |
| **Business** | 1 organisation · jusqu'à 25 utilisateurs · SSO inclus | **1 990 € / an** |
| **Enterprise** | Multi-instance · utilisateurs illimités · SLA 4 h | Sur devis |

→ [FAQ complète sur la licence + contrat type →](https://agent-ely.fr/pricing.html)

**Marques.** Le nom **Ely** (acronyme de *« Exactly Like You »*, prononcé « Éli »), **agent-ely.fr**, l'avatar 3D et le logo éclair sont protégés indépendamment du code. [Politique de marques →]

**Contact :** [contact@agent-ely.fr](mailto:contact@agent-ely.fr) — réponse sous 48 h, toujours.

---

<div align="center">

**Construit en Nouvelle-Aquitaine, France **

[Site web](https://agent-ely.fr) · [Documentation](./docs/START_HERE.md) · [Newsletter](https://agent-ely.fr/newsletter.html)

</div>
