<div align="center">

<a href="README.md">English</a> · <a href="README.fr.md">Français</a>

<img src="https://agent-ely.fr/ely-logo.jpeg" alt="ELY — agent IA souverain" width="200" />

# ELY

### Un agent IA auto-hébergé qui anonymise les données sensibles *avant* tout appel LLM.

Auto-hébergé · RGPD natif · multi-LLM · **auto-amélioration** · 10 canaux · 190+ outils intégrés.
Tourne sur votre matériel, masque les données sensibles avant tout appel modèle, demande avant chaque action irréversible.

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

> **À propos de la licence.** ELY est sous **[Elastic License v2](LICENSE)** — gratuit pour tout usage personnel ET tout usage professionnel interne, quelle que soit la taille de l'organisation. Code source intégralement publié et auditable.

---

## Pourquoi ELY existe

Les agents IA cloud — ChatGPT, Claude, Gemini, le futur Google Remy, OpenAI Operator, Microsoft Copilot — sont puissants, mais ils partagent tous la même architecture : **vos données brutes partent vers un serveur tiers aux États-Unis.** E-mails, IBAN, noms de clients, dossiers médicaux, projets de contrats — tout transite par des modèles que vous ne contrôlez pas, dans des juridictions qui ne sont pas la vôtre.

Pour la plupart des services cloud, c'est un compromis accepté. **Dès que vous manipulez ce que vous préféreriez ne pas confier à un serveur américain — votre boîte mail, vos finances, les données de votre famille — ça ne l'est plus.**

ELY est un agent IA **personnel** **qui tourne sur votre matériel, masque les données sensibles avant tout appel modèle, demande l'autorisation avant chaque action irréversible, et garde les données dans l'UE par défaut.** C'est un projet perso non-commercial sous Elastic License v2 — et cette licence couvre aussi l'usage professionnel interne, gratuitement.

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
**Les données sensibles sont masquées avant l'envoi à un LLM cloud. Les actions irréversibles ne s'exécutent jamais sans autorisation.**

- **Anonymisation PII native** — e-mails, IBAN, cartes bancaires, jetons d'API, numéros de téléphone, SIRET masqués par regex avant la construction du prompt sur le chemin agent. Couverture, couche NER optionnelle et limites détaillées dans [docs/security.md](docs/security.md).
- **HITL structurel** — chaque outil irréversible (envoi de mail, suppression, SSH, partage) attend une validation explicite. Autoriser une fois · refuser une fois · **bannir définitivement**.
- Coffre chiffré côté serveur (AES-256-GCM, clé dérivée du mot de passe maître par Argon2id) pour les identifiants.
- Journal d'audit immuable — chaque validation tracée, exportable pour la conformité.
- **Approbations infalsifiables** — l'action que vous validez au HITL est cryptographiquement celle qui s'exécute (empreinte fail-closed) ; les mutations externes ne sont jamais rejouées deux fois (clés d'idempotence).

</td>
</tr>
<tr>
<td width="50%" valign="top">

### Intégration
**Branché sur les outils que vous utilisez déjà.**

- **Google Workspace complet** — Gmail, Calendar, Drive, Docs, Sheets, Tasks, Contacts (75 outils, lecture/écriture intégrale avec HITL sur chaque action destructive) · multi-comptes (liez plusieurs boîtes Google à un même utilisateur, sélection via un alias `account`) · `drive_upload_local_file` pour enregistrer un fichier local/binaire (PNG/JPG/PDF, ex. une capture) sur Drive
- 10 canaux — Web · Voix (mot-clé « Éli ») · PWA · iOS natif · Android natif · Telegram · WhatsApp · Slack · Discord · push ntfy
- Notifications push natives pour les validations HITL (FCM + APNs) — la plupart des concurrents ne proposent qu'un proxy via bot de messagerie
- 190+ outils sur web automation, système, RAG, coffre, missions, auto-amélioration

</td>
<td width="50%" valign="top">

### Architecture
**Multi-utilisateur. Multi-LLM. Conçu pour passer d'une personne à un foyer.**

- **Multi-utilisateur natif — et durci pour ça** *(campagne juin 2026 : 11 releases)* — un déploiement vous sert, vous ou votre foyer. Chaque utilisateur a sa mémoire, son coffre, sa file de validation, **son budget LLM quotidien**, ses quotas et limites de débit. Secrets chiffrés au repos, migrations Alembic, sauvegardes nocturnes, healthchecks profonds.
- **Multi-LLM avec tiers de complexité** — assignez des modèles différents aux Tiers A (rapide) / B (standard) / C (profond) / IMG / SYS. Local pour les tâches simples, Mistral ou Anthropic pour les complexes — votre choix, sans redémarrage.
- 12 fournisseurs LLM supportés · bascule automatique en cas de panne (chaîne par-conversation, retour auto au primaire après cooldown)
- Mappage canal-utilisateur empêchant l'usurpation entre plateformes

</td>
</tr>
</table>

---

## Ce qui rend ELY différent : elle s'améliore toute seule

La plupart des agents sont statiques. **ELY observe ses propres échecs et progresse — en toute transparence, avec vous aux commandes.**

- **Elle apprend des playbooks réutilisables de ses propres erreurs — toute seule.** Quand une tâche échoue (action refusée, blocage d'hallucination, mission mal notée), ELY transforme l'échec en un court **playbook** Markdown — *« quand tu vois X, fais Y, jamais Z »* — le fait noter par un modèle-juge séparé, et **crée + active les bons d'elle-même**, sans clic admin. La bibliothèque démarre avec des playbooks de base (utile dès le jour 1), et vous pouvez **importer des playbooks communautaires** (`SKILL.md`) directement depuis une URL dans la file de revue.
- **Elle diagnostique ses propres « succès en façade ».** Une boucle de fond vérifie, après chaque exécution autonome, si l'agent a *vraiment* fait ce qu'il prétend — détecte le *« réussi annoncé, aucun effet réel »* — puis **diagnostique la cause** et propose un **correctif validable** sur une page admin Incidents. ELY mesure son taux de réussite réel, pas déclaré.
- **Missions structurées qui demandent au lieu de deviner** *(v1.17)*. Décrivez un workflow multi-étapes en YAML simple — `steps`, `foreach` sur les résultats d'un step précédent, et des **handlers d'edge-case** : `on_ambiguous: ask_user("…")`, `on_not_found: skip_with_note("…")`. Quand ELY hésite, elle **vous ping** (web, push, Telegram), vous répondez, elle reprend — pendant que les autres items continuent. Un viewer liste vivant montre chaque step et item (✓ ⏳ ⏸ ⊝) avec réponse inline.
- **Transparence radicale.** Deux tableaux de bord — `/me/learning` et `/me/state` — vous montrent exactement ce qu'ELY a appris de vous et le modèle qu'elle se fait de vous (humeur, focus, dossiers ouverts). Lisibles, modifiables, supprimables, jamais cachés.
- **Annuler — ELY peut revenir sur ce qu'elle vient de faire.** Dites *« annule »* (ou cliquez **Annuler** dans `/me/reversible-actions`) et ELY défait sa dernière action — un fichier Drive supprimé, renommé ou déplacé, remis à l'identique — en chat, via l'API ou l'UI, avec vérification que l'annulation a bien pris.
- **Mémoire cognitive typée.** Cinq types de mémoire (épisodique · sémantique · procédurale · erreur · contrainte) au lieu d'un blob opaque — rappelés par type, entre conversations, 100 % en local.
- **Client MCP — durci.** Consommez n'importe quel serveur Model Context Protocol (config admin) : identifiants par-utilisateur chiffrés dans votre Vault, garde SSRF / anti-DNS-rebinding, et ACL/HITL par outil — lecture sans friction, écriture confirmée une fois puis mémorisée ; un workflow quarantaine/confiance et la recherche du registre MCP étendent l'outillage sans changement de code. *(Connexion OAuth 2.1/PKCE, sandbox pour les serveurs stdio locaux, et resources/prompts en lecture seule arrivent derrière leurs propres flags, désactivés par défaut.)*
- **Banc de régression 50 scénarios + CI nocturne.** L'auto-amélioration ne ship en sécurité que parce que chaque sous-système est verrouillé par un banc déterministe, par-dessus 2 000+ tests automatisés.

> *Expérimental, désactivé par défaut :* ELY peut aussi générer des **outils Python** exécutables depuis une description (garde AST → ruff → mypy → smoke test sandboxé → revue admin → canary HITL), y compris une variante réseau « io » derrière un proxy egress filtrant avec domaines déclarés et secrets injectés du Vault. Pour un assistant mono-utilisateur ça paye rarement (un bon modèle fait la tâche triviale en ligne), donc la boucle se concentre désormais sur les playbooks ; la génération de code reste derrière un flag.

---

## ELY face aux alternatives — comparatif honnête

Nous respectons ce que les autres projets font bien. Nous sommes explicites sur ce qui nous distingue.

| | **ELY** | Autres agents auto-hébergés | Assistants IA hébergés |
|---|:---:|:---:|:---:|
| Auto-hébergé sur votre matériel | ✅ | ✅ | ❌ |
| **PII anonymisées avant l'appel LLM** | ✅ Natif | ⚠️ Plugin ou absent | ❌ |
| **HITL actif par défaut (préférences par outil ; noyau interdit verrouillé sous mandat autonome)** | ✅ Structurel | ⚠️ Configurable | N/A |
| **Multi-utilisateur (une personne ou un foyer)** | ✅ | ❌ Souvent mono-user | ✅ (cloud éditeur) |
| **Routage hybride local / cloud** | ✅ Tiers explicites | ⚠️ Manuel / partiel | ❌ |
| Apps mobiles natives (iOS + Android) | ✅ | ❌ Rare | ✅ |
| Coffre chiffré côté serveur | ✅ AES-256-GCM | ❌ Rare | ❌ |
| Interface française complète | ✅ | ⚠️ Souvent EN only | ⚠️ Partielle |
| Licence | Elastic v2 (usage interne gratuit, pas de revente SaaS) | Variable | Propriétaire |

> **Notre lecture honnête.** D'autres agents auto-hébergés ont des communautés plus larges et plus d'adaptateurs de canaux. **Si vous traitez des données que vous ne pouvez pas vous permettre de divulguer — les vôtres, celles de votre famille, celles de vos clients — le pipeline d'anonymisation et le HITL structurel d'ELY sont les raisons qui vous le feront choisir face aux alternatives.**

---

## À qui s'adresse ELY

**Particuliers et familles soucieux de leur vie privée** — vous voulez un assistant IA puissant mais vous refusez d'envoyer votre boîte mail, vos relevés bancaires et votre historique médical à OpenAI, Google ou Anthropic. Tournez ELY sur votre matériel. Gratuit sous la licence Elastic v2.

ELY est un **projet perso non-commercial**. Cela dit, la licence Elastic v2 couvre aussi l'**usage professionnel interne**, gratuitement et sans contrat additionnel — donc si c'est utile au sein de votre propre structure, c'est autorisé.

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

- **Pipeline de masquage PII.** Détection regex déterministe : e-mails, IBAN, cartes bancaires, jetons d'API, numéros de téléphone (tous les formats français), SIRET, identifiants salariés. Placeholders déterministes, restitués uniquement à l'affichage côté utilisateur. Cette couche regex est la frontière de confidentialité active. (Une couche NER locale pour les noms/orgs en texte libre a été construite et benchée, mais reste **désactivée par défaut** — trop perturbante pour un usage agentique ; voir [docs/security.md](docs/security.md).)
- **Validation humaine.** Bloque par défaut plus de 30 catégories d'outils. Trois actions : autoriser une fois, refuser une fois, **bannir définitivement** (persisté entre toutes les sessions futures).
- **Coffre chiffré.** AES-256-GCM, clé dérivée du mot de passe utilisateur. Zero-knowledge — le serveur ne peut rien lire après verrouillage. Stocke clés API, jetons OAuth, identifiants de canaux.
- **Journal d'audit.** Chaque décision de validation est journalisée de manière immuable (JSON Lines). Exportable pour la conformité.

[Modèle de sécurité complet →](./docs/security.md)

</details>

<details>
<summary><strong>Moteur multi-LLM</strong> — vos clés, routage par complexité</summary>

Configurez les fournisseurs dans **Réglages → Modèles IA**. Assignez chaque tier (A/B/C/IMG/SYS) à un modèle. Changez à tout moment, sans redémarrage. Les modèles locaux (Ollama, LM Studio) bénéficient de prompts compacts auto-détectés pour que les modèles 7B obéissent réellement à `tool_choice="required"`.

- **Cloud :** OpenAI · GPT-5.5 / 5.6 (via votre abonnement ChatGPT, sans clé API) · Anthropic · Gemini · Qwen API · Moonshot Kimi K2.x · Mistral · DeepSeek · Zhipu · OpenRouter
- **Local :** Ollama · LM Studio (MLX sur Apple Silicon)
- **Bascule automatique** si un fournisseur tombe — désactivable par tier pour des tests 100 % locaux.
- **Préfixe système cacheable** séparé du contenu dynamique, pour réduire le coût d'entrée multi-tours sur les fournisseurs qui cachent le préfixe.

</details>

<details>
<summary><strong>Missions</strong> — boucle orientée objectif, persistante entre redémarrages</summary>

Donnez un objectif à ELY — elle le décompose en étapes, choisit les outils, exécute, évalue, replanifie en cas d'échec et vous notifie quand c'est terminé. Survit aux redémarrages backend (checkpointer LangGraph SQLite).

Cinq garde-fous : budget de tokens · budget d'itérations · deadline optionnelle · HITL sur outils critiques · anti-boucle après 3 échecs consécutifs. Notifications en parallèle : web · DM Telegram · push ntfy. Les missions échouées sont systématiquement notées par un **LLM-juge** externe qui détecte le « succès en façade » ; les réussites sont contrôlées par échantillonnage (1 sur 5).

**Missions structurées** *(v1.17)* — remplacez le prompt monolithe par une spec YAML :

```yaml
version: 1
steps:
  - id: enrich
    foreach: "{{ read_companies.output }}"
    do: "Trouve le dirigeant de {{ item }} sur LinkedIn."
    on_ambiguous: ask_user("Plusieurs résultats pour {{ item }} — lequel ?")
    on_not_found: skip_with_note("Introuvable")
    on_error: resume_next
```

Le LLM reste dans la boucle (la spec *cadre* l'exécution, elle ne remplace pas le raisonnement) ; les cas d'edge déclarés sont **signalés, pas improvisés** ; `ask_user` met l'item en pause, vous ping sur tous vos canaux et reprend sur votre réponse pendant que les autres items continuent. Viewer liste vivant avec réponses inline. Terminaison déterministe — plus de « fini » jugé par le LLM. Les missions texte libre existantes sont inchangées.

**Sous-tâches parallèles** — l'outil `delegate` lance 2 à 6 sous-tâches indépendantes en simultané via des sous-agents autonomes (enfants HITL-bloqués) puis renvoie une synthèse.

</details>

<details>
<summary><strong>Boucle d'apprentissage & skills</strong> — ELY transforme ses erreurs en playbooks réutilisables</summary>

Les signaux d'échec (refus HITL, blocages d'hallucination, critiques de mission, « capacité manquante ») alimentent une boucle d'apprentissage centrée sur les **playbooks Markdown** — de courtes procédures lisibles *« quand X, fais Y, jamais Z »* que l'agent suit :

- **Capture autonome.** Une passe de fond transforme les échecs récents en playbook, un juge externe le note, et les bons sont **créés et activés automatiquement** — sans clic admin. La bibliothèque est **amorcée** (utile dès le jour 1).
- **Import.** Importez des playbooks communautaires au format ouvert `SKILL.md` directement depuis une URL — ils atterrissent dans la **file de revue** admin (le contenu externe n'est jamais auto-activé) avant que vous ne les promouviez.
- **Auto-diagnostic.** Après chaque exécution autonome, une boucle vérifie si l'agent a *vraiment* fait ce qu'il prétend (détection du *« succès en façade »*), diagnostique la cause, et propose un **correctif validable** sur une page admin Incidents.

Tout reste auditable et réversible — les playbooks sont de la prose que vous pouvez lire, modifier, archiver. Un banc de régression 50 scénarios + CI nocturne garde la boucle honnête.

> *Expérimental, désactivé par défaut :* ELY peut aussi générer des **outils Python** exécutables depuis une description (garde AST → ruff → mypy → smoke test sandboxé → revue admin → canary HITL), y compris une variante réseau « io » derrière un proxy egress filtrant. Pour un assistant mono-utilisateur ça paye rarement, donc la boucle se concentre sur les playbooks ; la génération de code reste derrière un flag.

</details>

<details>
<summary><strong>Transparence radicale</strong> — voyez ce qu'ELY a appris de vous, et changez-le</summary>

`/me/learning` montre les signaux d'échec + verdicts qu'ELY a enregistrés ; `/me/state` montre le modèle vivant qu'elle a de vous (humeur, focus, sujets récents, dossiers ouverts, énergie). Tout est lisible, modifiable et supprimable par l'utilisateur — aucun profilage caché.

</details>

<details>
<summary><strong>Annuler — actions réversibles</strong> — revenir sur la dernière suppression / renommage / déplacement</summary>

ELY enregistre une action de compensation pour les opérations destructives qu'elle exécute : vous pouvez donc défaire la dernière — un fichier Drive supprimé, renommé ou déplacé est remis exactement dans son état d'origine. Déclenchez-la en chat (*« annule ça »*), via l'API, ou depuis la page **`/me/reversible-actions`** (liste, Annuler en un clic, fenêtre d'expiration). Chaque annulation est **vérifiée** — ELY confirme que le retour arrière a bien eu lieu — et les entrées se purgent automatiquement après leur fenêtre.

</details>

<details>
<summary><strong>Canaux</strong> — 10 façons de joindre ELY</summary>

Web · Voix (mot-clé « Éli ») · PWA · iOS natif · Android natif · Telegram · WhatsApp · Slack · Discord · push ntfy.

Même agent, même mémoire, même sécurité sur toutes les surfaces. Apps natives iOS (SwiftUI) et Android (Kotlin/Compose) avec push FCM/APNs pour les validations HITL — la plupart des concurrents ne proposent qu'un proxy via bot de messagerie.

</details>

<details>
<summary><strong>Serveur MCP & clés API</strong> — pilotez ELY depuis vos clients MCP</summary>

ELY est exposée **comme** un serveur MCP sur `/api/mcp` (FastMCP en Streamable-HTTP). Connectez Claude Desktop / Cursor et pilotez ELY avec quatre outils v1 : `ely_chat` (chat en un tour, mode autonome-sûr) · `ely_list_scheduled_tasks` · `ely_create_scheduled_task` · `ely_memory_search` (recherche mémoire).

L'accès se fait par **clé API personnelle** créée dans **Réglages → Clés API** (`/settings/api-keys`) : préfixe `ely_api_` suivi de 64 caractères hex, **affichée en clair une seule fois** (stockée hachée en SHA-256), max 20 clés actives par utilisateur, révocable à tout moment. Passez-la en `Authorization: Bearer ely_api_…` sur l'endpoint MCP.

</details>

<details>
<summary><strong>Mémoire & RAG</strong> — Qdrant local + SQLite FTS5</summary>

PDF · TXT · Markdown · CSV · JSON · DOCX. fastembed + Qdrant pour la recherche sémantique, SQLite FTS5 pour le mot-clé. ELY décide elle-même si une recherche est utile avant de répondre, classe les résultats, cite les sources. Aucune donnée envoyée à des services d'embeddings distants — tout est local.

Joignez aussi un fichier directement dans le chat (jusqu'à **50 Mo**) — l'upload renvoie un chemin serveur et ELY lit le fichier via ses outils PDF/vision. Note : un `.zip` s'envoie mais n'est **pas** déballé (aucun outil de décompression) — envoyez les fichiers non zippés.

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
│                                          (Ollama)    (190+)   (PII- │
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
| Fournisseurs LLM | 12 (cloud + local) |
| Mémoire | Qdrant · SQLite FTS5 · fastembed |
| Automation navigateur | Playwright |
| STT / TTS | faster-whisper · edge-tts |
| Auth | JWT HS256 · Argon2id · cookie HttpOnly |
| Coffre | AES-256-GCM, dérivation de clé par utilisateur |
| Push | FCM · APNs · Telegram · WebSocket |
| Infra | Docker Compose · nginx · Cloudflare Tunnel |

---

## Roadmap

**Livré** *(juillet 2026)*
- **Passerelle d'outils unifiée** — le chat, les missions autonomes et les tâches planifiées exécutent désormais chaque outil via un pipeline commun (filtre sécurité → HITL → frontière PII → journal d'actions réversibles) : une garantie ajoutée une fois vaut pour les trois surfaces ([#190](https://github.com/franckolv-dev/ElyAgent/pull/190), [#195](https://github.com/franckolv-dev/ElyAgent/pull/195)–[#197](https://github.com/franckolv-dev/ElyAgent/pull/197))
- **Missions autonomes : mandat activé par l'humain + carnet de mission** — le mandat d'une mission (budget de tokens, tier LLM, outils autorisés) doit être explicitement activé par un humain, son budget et son tier sont réellement appliqués, et le viewer affiche un carnet vivant de ce que la mission a fait ; toujours derrière un flag désactivé par défaut ([#191](https://github.com/franckolv-dev/ElyAgent/pull/191), [#194](https://github.com/franckolv-dev/ElyAgent/pull/194))
- **GPT-5.6 via votre abonnement ChatGPT** — catalogue terra / sol / luna ajouté à côté de GPT-5.5, sélectionnable par instance LLM ([#189](https://github.com/franckolv-dev/ElyAgent/pull/189))
- **Auto-diagnostic : incidents récurrents dédupliqués** — un échec qui se répète se replie en un seul incident avec compteur d'occurrences au lieu d'inonder la page admin ([#188](https://github.com/franckolv-dev/ElyAgent/pull/188))
- **ELY Desktop : résiliente aux coupures du tunnel** — un reset du tunnel Cloudflare (le daemon se reconnecte en ~2 s) n'avorte plus une tâche en cours : les outils attendent la reconnexion (grâce de 15 s) et les commandes en vol re-tentent une fois sur la nouvelle connexion ([#198](https://github.com/franckolv-dev/ElyAgent/pull/198))

**Livré** *(mai–juin 2026)*
- **Boucle de skills auto-améliorante** *(v2.2)* — ELY transforme ses vrais échecs en playbooks Markdown et les **crée + active toute seule** ; bibliothèque amorcée ; **import de `SKILL.md` communautaires depuis une URL** dans la file de revue
- **Boucle d'auto-diagnostic** *(v2.2)* — détecte le « succès en façade », diagnostique la cause, propose un correctif validable sur une page admin Incidents
- **Tâches planifiées plus malines** *(v2.2)* — `[SILENT]` (les veilles ne spamment plus quand rien ne change), vrai one-shot `@once` (exécuté une fois puis supprimé), modifier/lancer une tâche sans la recréer
- **Affordances de chat** *(v2.2)* — titres de conversation générés par LLM, régénérer une réponse, éditer-et-renvoyer le dernier message
- **Missions structurées** *(v1.17)* — specs YAML avec `foreach` + handlers d'edge-case ; `ask_user` met en pause, vous ping, reprend sur votre réponse ; viewer liste vivant
- **Campagne de durcissement multi-utilisateur** *(11 releases, v1.14.x)* — audit d'isolation cross-user, budgets/quotas/limites par utilisateur, secrets chiffrés au repos, migrations Alembic, sauvegardes nocturnes, healthchecks profonds
- **Mémoire cognitive typée** — 5 types de mémoire, rappel transversal entre conversations
- **Transparence radicale** — tableaux de bord `/me/learning` + `/me/state`
- **Annuler / actions réversibles** — revenir sur la dernière suppression, renommage ou déplacement (Drive) depuis le chat · l'API · `/me/reversible-actions`, avec vérification
- **Client MCP, durci** — consommer n'importe quel serveur MCP avec identifiants par-utilisateur dans le Vault, garde SSRF et ACL/HITL par outil ; workflow quarantaine/confiance + recherche de registre (connexion OAuth, sandbox des serveurs locaux et resources/prompts en lecture seule arrivent derrière des flags désactivés par défaut)
- **GPT-5.5 via votre abonnement ChatGPT** — l'utiliser comme tier LLM sans clé API (import de tokens + rafraîchissement auto), avec bascule de secours au quota
- **Serveur MCP** *(juin 2026)* — ELY est exposée **comme** un serveur MCP sur `/api/mcp` (FastMCP Streamable-HTTP), authentifié par clés API personnelles. Pilotez-la depuis Claude Desktop / Cursor : chat en un tour (mode autonome-sûr), lister/créer des tâches planifiées, recherche mémoire.
- **Banc de régression 50 scénarios** + CI nocturne · 2 000+ tests automatisés

**Peut-être ensuite** *(optionnel — projet perso, pas de pression de roadmap)*
- **Marqueurs de cache de prompt Anthropic** — réduire le coût d'entrée multi-tours sur le tier Anthropic.

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

En langage clair (informatif — le fichier [LICENSE](LICENSE) fait foi) :

**Vous êtes libre de** — utiliser ELY pour tout usage personnel (foyer, famille) · l'utiliser pour tout usage professionnel interne, quelle que soit la taille de l'organisation · modifier le code source et exécuter votre version · le redistribuer (modifié ou non) en conservant le LICENSE + les notices de copyright.

**Vous ne pouvez pas** — proposer ELY comme service hébergé / managé à des tiers (pas de revente SaaS) · retirer ou masquer les notices de copyright / licence · désactiver ou contourner un éventuel mécanisme de clé de licence.

→ [Résumé en langage clair sur le site officiel →](https://agent-ely.fr/pricing.html)

**Marques.** Le nom **Ely** (acronyme de *« Exactly Like You »*, prononcé « Éli »), **agent-ely.fr**, l'avatar 3D et le logo éclair sont protégés indépendamment du code.

**Contact :** [contact@agent-ely.fr](mailto:contact@agent-ely.fr) — réponse sous 48 h, toujours.

---

<div align="center">

**Construit en Nouvelle-Aquitaine, France **

[Site web](https://agent-ely.fr) · [Documentation](./docs/START_HERE.md) · [Newsletter](https://agent-ely.fr/newsletter.html)

</div>
