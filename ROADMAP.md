# ELY Roadmap

> **TL;DR** — ELY converge sur ce que personne d'autre n'offre dans le monde des agents IA personnels : un agent **self-hosted** qui combine la **surface produit grand public** (UI riche sur tous les canaux) avec un **moat technique unique** (modèle qui apprend et qui appartient au user). Ce document liste les chantiers, leur ordre, et leur valeur différenciatrice.
>
> Last updated: **May 15, 2026** — aligné sur les livraisons des sprints 0.5 + extension Chrome.
> Maintainer: [Franck OLLIVIER](mailto:contact@agent-ely.fr).

---

## Vision

Trois principes immuables guident ce qu'on construit et ce qu'on refuse :

1. **Le user possède son agent.** Pas de SaaS, pas de cloud forcé, pas de modèle qu'on peut nous éteindre. Hardware du user → données du user → modèle du user.
2. **L'UI doit être un game-changer.** Si grand-mère ne peut pas l'utiliser, c'est pas fini. Web + mobile natif + voix + multi-canal, polish absolu sur chaque surface.
3. **L'agent doit être agentique pour de vrai.** HITL avant l'irréversible, missions goal-driven, sub-agents quand utile, auto-amélioration mesurable.

Tout chantier qui contredit l'un de ces principes est rejeté, peu importe l'effet de mode.

---

## Comment lire cette roadmap

| Légende | Sens |
|---|---|
| 🟢 **Standard** | Catch-up sur ce qui existe ailleurs, table-stakes |
| 🟡 **Hermes-parity** | Pattern technique éprouvé chez Hermes Agent ou similaire qu'on adopte |
| 🔴 **Unique to ELY** | Différenciateur que personne d'autre n'offre — *le moat* |
| 🔬 **Research** | Exploratoire, ne sera shippé que si ça bat la baseline en éval |

| Effort | Sens |
|---|---|
| **S** | < 1 semaine |
| **M** | 1-3 semaines |
| **L** | 1-2 mois |
| **XL** | 2-4 mois |
| **XXL** | trimestre+ |

---

## Sprint 0 — Public launch ✅ *Mai 2026*

L'objectif a été : ouvrir le repo sans honte ni faille. Catalogue final livré ce jour :

- ✅ Refonte UI complète (Claude.ai handoff, oklch, Inter, dark+light)
- ✅ Multi-domain routing fix (queries croisant 2+ specialists → general)
- ✅ Mode mono-agent (toggle admin pour bypasser le router)
- ✅ Provider Moonshot Kimi K2.x (avec fix température=1 sur reasoning models)
- ✅ Self-improving keyword router (Phase 1 : DB + cache + endpoints, Phase 2 : auto-detection des reformulations via job MAINTENANCE)
- ✅ API key validator côté backend (URL/whitespace/length checks)
- ✅ Anti-hallucination guards (workspace + general prompts)
- ✅ Specialists honor tier config partout
- ✅ README final avec emphase UI graphique différenciante
- ✅ 92/92 pytest, smoke tests OK, no committed secrets

---

## Sprint 0.5 — Extension Chrome ELY ✅ *14-15 mai 2026*

> Livrée en 2 itérations sur 2 jours, en réponse au feedback usage réel : *« ELY prend une autre dimension avec l'extension Chrome, mais c'est de la bidouille de devoir coller un JWT depuis DevTools, et elle se déconnecte toutes les heures. »*

- ✅ **Tokens longue durée** (`ely_ext_<48 hex>`, 192 bits d'entropie) — fini le JWT 60 min et la copie depuis DevTools. Token affiché une seule fois, hash SHA-256 + last_4 stockés côté serveur, révocation depuis Settings → Extension navigateur.
- ✅ **REST `/api/extension/tokens`** (POST create / GET list / DELETE revoke) + page Settings dédiée.
- ✅ **Handshake WebSocket dual-protocol** : accepte JWT classique (legacy) ET tokens `ely_ext_*` (lookup par hash, bump `last_used_at`).
- ✅ **Sprint 1 interactivité** dans la foulée : tools `browser_tab_click`, `browser_tab_fill`, `browser_tab_navigate` (implémentation React-aware : native value setter + dispatchEvent input/change pour les inputs contrôlés, MouseEvent + native click pour les boutons React).
- ✅ **Anti-hallucination prompt v3** (6 règles structurées) : refus dur sur patterns suspects, sanity-check temporel obligatoire avant proposition de dates, vision interdite pour lecture de valeurs numériques précises.
- ✅ **Pattern C system prompt** pour workflows multi-étapes (Doctolib, SNCF, Booking…) avec recette détaillée cartes pliables → click chevron → wait_for_selector → read scoped.

**Différenciateur produit fort** : seul agent en **code source ouvert et auditable** qui agit dans le **vrai navigateur de l'utilisateur** avec ses sessions, ses cookies, ses préférences — pas dans un Playwright headless serveur aveugle aux logins. RGPD-compatible par construction (les cookies n'arrivent jamais sur le serveur).

---

## Sprint 1 — Memory recall ✅ *Mai 2026* (livré en v1.1.2)

| # | Item | Type | Effort | Source d'inspiration |
|---|---|---|---|---|
| 1 | **Session search FTS5 + résumé LLM auxiliaire** — Ely retrouve « tu te souviens du projet X il y a 3 mois ? ». Table FTS5 sur SQLite, tool LLM-callable `search_past_conversations(query, limit=3)` qui groupe par conversation, charge le contexte centré sur les matches, résume via Ministral 3B local. | 🟡 Hermes-parity | M | `hermes_state.py:36-180` + `tools/session_search_tool.py` |

**Pourquoi en premier** : c'est le plus gros gain perçu utilisateur pour l'effort le plus modeste. Aucun agent personnel grand public n'a ça de façon cross-conversation. A ouvert la voie à *"v1.1 — Memory recall"* qui fait du buzz.

**Livrables effectifs (v1.1.2, PR #2)** :
- ✅ `backend/app/services/messages_fts_store.py` — table FTS5 `messages_fts` avec tokenizer `unicode61` + `messages_fts_trigram` (CJK)
- ✅ `backend/app/services/messages_fts_indexer.py` — hook SQLAlchemy `after_insert` pour indexation automatique des nouveaux messages
- ✅ `backend/app/services/session_search.py` avec `search_past_conversations()` (grouping par conv, ranking BM25 cumulé, dump tronqué, résumé Ministral 3B local, fallback prose)
- ✅ `backend/app/agent/tools/session_search_tool.py` — tool LangChain `@tool` avec `InjectedToolArg` pour `user_id`
- ✅ Skill `memory_recall` enregistré dans `memory_skill.py` (tool exposé à 65 outils du profil par défaut)
- ✅ `backend/scripts/backfill_messages_fts.py` — backfill batch idempotent (1862/2468 messages historiques indexés)
- ✅ Anti-hallucination « RÈGLE 0 » universelle ajoutée à `_SYSTEM_PROMPT_BASE` + `_SYSTEM_PROMPT_SLM` (refus de fabriquer du contenu sans appel d'outil)
- ✅ Tests unitaires (`backend/tests/test_session_search.py` : grouping, JSON extraction, content normalization, flatten, tunables)
- ✅ Validation end-to-end croisée : Haiku, Qwen, Mistral Large, Kimi K2.6, DeepSeek pro — tous appellent le tool correctement et restituent les résumés
- ✅ Tagué `v1.1.2` + GitHub Release publiée (16 mai 2026)

**Résidu cosmétique accepté** : les LLM cloud (DeepSeek, Haiku, Qwen, Mistral Large, Kimi) laissent parfois le JSON du tool_call visible dans la réponse finale au lieu de la pure prose. Universel post-training, non-bloquant, sera adressé dans un refactor v1.2+ « bypass renderer pour tool results ».

---

## Sprint 2 — Developer experience ✅ *17 mai 2026* (livré en v1.2.0)

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 2 | **Tool registry auto-discovery** — un tool s'auto-déclare avec `@register(domain=Domain.WORKSPACE, skill_name=…)`. Le scanner runtime importe `backend/app/agent/tools/`, lit les décorateurs, groupe par `skill_name` et enregistre les `Skill` dans le registry global. Élimine la double-registration tool→skill, supporte les deux patterns (legacy + décorateur) en parallèle pour migration progressive. | 🟡 Hermes-parity | S-M | `hermes-agent-main/tools/registry.py:30-72` |

**Pourquoi maintenant** : confort dev quotidien pour Franck + futur·e·s contributeur·rices. Réduit les bugs « tool invisible ». **Pré-requis bloquant** pour le Sprint 2.5 (mémoire procédurale a besoin d'une source unique de vérité sur les tools).

**Choix d'implémentation acté** : runtime introspection (`importlib.walk_packages`) plutôt que parsing AST. Pattern standard Python (Flask blueprints / FastAPI routers / pytest fixtures), ~30 lignes au lieu de ~150, erreurs claires au démarrage (ImportError au lieu d'un tool silencieusement absent), perf négligeable (5-20 ms au boot).

**Livrables effectifs (v1.2.0)** :
- ✅ `backend/app/skills/decorator.py` — décorateur `@register` avec validation des arguments (domain valide, skill_name non-vide, etc.) + buffer module-level `_PENDING`
- ✅ `backend/app/skills/auto_discover.py` — scanner runtime qui importe les modules, draine `_PENDING`, groupe par `skill_name`, crée les `Skill` automatiques, **skippe les `skill_name` déjà enregistrés** (legacy wins pour migration progressive sans casse)
- ✅ `backend/app/skills/builtin/__init__.py` — hook `auto_discover_tools()` appelé après les enregistrements manuels existants. Robuste : si l'auto-discovery plante, l'app continue à démarrer avec les skills legacy
- ✅ `backend/tests/test_auto_discover.py` — 13 tests dédiés (décorateur, scanner E2E, groupement, idempotence, gestion erreur d'import, package inexistant)
- ✅ `backend/app/agent/tools/session_search_tool.py` — **migration de validation E2E** : `search_past_conversations_tool` désormais auto-enregistré via `@register`. Suppression de l'entrée manuelle correspondante dans `memory_skill.py`. Comportement runtime strictement identique (vérifié par les tests existants).
- ✅ Guide « ajouter un outil » rédigé (exemple bout-en-bout + section migration legacy→décorateur) — doc interne, le pattern vivant est dans `backend/app/skills/builtin/`
- ✅ 432/432 tests verts, zéro régression

**Ce qui n'est PAS dans ce sprint (différé volontairement)** :
- Migration en masse des 65 tools existants vers le décorateur — fait au fil de l'eau, sans rush, deux patterns coexistant sans conflit
- Auto-génération de `_DEFAULT_TOOLS` depuis le registry — nice-to-have, pas bloquant ; la liste reste manuelle pour le moment

---

## Sprint 2.5 — Architecture mémoire cognitive multi-typée ⏳ *Juin-Juillet 2026*

> **Pourquoi ce sprint maintenant** : on vient de shipper la mémoire épisodique (Sprint 1 / FTS5 sur conversations passées). Généraliser à 5 types de mémoire derrière une interface unique transforme un coup ponctuel en *architecture de mémoire cohérente*. Et la **mémoire procédurale**, c'est précisément l'antidote structurel à l'hallucination d'outil inexistant qu'on a colmaté à coup de prompt (RÈGLE 0) — au lieu de demander au LLM de « ne pas inventer », on lui donne la primitive `memory_recall("procedural", "envoyer email")` qui retourne le tool réel.

> **Dépendance stricte au Sprint 2 (registry)** : sans source unique de vérité sur les tools, la mémoire procédurale créerait une 4ᵉ source en plus des 3 actuelles (`_DOMAIN_DESCRIPTIONS` / `_SPECIALIST_PROMPTS` / `_WORKSPACE_SKILLS`). Ce serait payer la dette technique deux fois.

| # | Sous-item | Type | Effort | Détail |
|---|---|---|---|---|
| 2.5.1 | **Interface unique `memory_recall(type, query)`** | 🔴 Unique to ELY | S | Tool LLM-callable unifié. `type` ∈ `{episodic, procedural, spatial, semantic, constraints}`. Dispatch vers le bon back-end selon le type. Réponse normalisée (liste de résultats + métadonnées). Inspirable de la psychologie cognitive (Atkinson-Shiffrin, Tulving). |
| 2.5.2 | **Mémoire procédurale** | 🔴 Unique to ELY | S-M | Catalogue des tools disponibles, requêtable en langage naturel. Construit *à partir du registry du Sprint 2* (source unique). « comment envoyer un mail ? » → `gmail_send_email`. Élimine la classe entière des hallucinations « j'ai utilisé `send_message_to_telegram` » alors que le tool n'existe pas. |
| 2.5.3 | **Mémoire spatiale** | 🟡 Hermes-parity | S | Géolocalisation user (ville, fuseau, lieux récurrents : domicile/travail/famille). Requêtable : « où sont les pizzerias près de chez moi ? ». Stocké chiffré, RGPD-explicit opt-in. |
| 2.5.4 | **Mémoire sémantique** | 🟡 Hermes-parity | M | Faits sur l'utilisateur extraits au fil des conversations : profession, famille, préférences durables, anniversaires. Distinct de l'épisodique (faits indépendants du contexte conversationnel). Stockage SQLite + index vectoriel. Inspectable et corrigeable. |
| 2.5.5 | **Mémoire des contraintes (déjà partiellement présente)** | 🟢 Standard | S | Unifie le `save_constraint` existant sous l'interface `memory_recall("constraints", ...)`. Liste les règles tacites que le user a posées (« ne jamais envoyer d'email après 22h », « toujours mettre Marc en copie sur les sujets X »). |
| 2.5.6 | **UI Réglages → Mes mémoires** | 🟢 Standard | S | Inspection complète des 5 types, recherche, bouton « oublier ». Cohérent avec la philosophie #1 du projet (« le user possède son agent »). |

**Livrables mesurables** :
- Tool `memory_recall(type, query)` callable par l'agent depuis tous les tiers (A/B/C)
- 5 back-ends fonctionnels, chacun avec test unitaire dédié
- Mémoire procédurale qui interroge le registry du Sprint 2 (preuve : ajouter un tool dans le code → visible automatiquement dans `memory_recall("procedural")`)
- Page UI Réglages → Mes mémoires avec audit et bouton « oublier »
- **Zéro hallucination de tool inexistant** sur l'eval harness à venir (Sprint 3.7) — objectif vérifiable

**Pourquoi unique** : aucun agent personnel commercial n'expose une architecture de mémoire structurée par types et inspectable. Hermes Agent l'a (référencé dans `hermes_state.py:36-180`), Cursor/Cline/Claude Desktop ne l'ont pas. C'est l'aboutissement narratif du fil mémoire commencé au Sprint 1.

---

## Sprint 3 — User State Vector ⏳ *Juin-Juillet 2026*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 3 | **User State Vector** — état JSON structuré (`mood`, `current_focus`, `recent_topics`, `open_loops`, `energy_budget`) mis à jour toutes les N messages par le LLM MAINTENANCE. Injecté en début de prompt système. Interrogeable depuis l'UI (« Que penses-tu de moi ? »). C'est l'équivalent fonctionnel d'un *World Model* sans Mamba. | 🔴 Unique to ELY | M | Inspiration LeCun + analyse interne ELY |

**Pourquoi unique** : aucun agent personnel n'expose un état utilisateur structuré et inspectable. Combiné avec l'UI ELY, ça donne un *« profil dynamique »* visible dans Settings → Mon profil ELY. Game-changer pour la perception de personnalisation.

---

## Sprint 3.7 — Boucle d'auto-amélioration mesurée ⏳ *Juillet 2026*

> **Pourquoi maintenant et pas plus tard** : sans cette boucle, toute amélioration ELY (prompts système, sélection d'outils, classement des skills) repose sur l'intuition de Franck. Avec elle, ELY commence à apprendre **de l'usage réel de chaque utilisateur**, en se mesurant à elle-même. C'est le préalable indispensable au Sprint 6.5 (Self-reflection mid-mission) et au Sprint 9 (LoRA personnel) — les deux supposent un signal d'apprentissage qualifié que seul ce sprint produit.

| # | Sous-item | Type | Effort | Détail |
|---|---|---|---|---|
| 3.7.1 | **Détection automatique des HITL refusés** | 🔴 Unique to ELY | S-M | Chaque refus user (« non, n'envoie pas cet email », « non, ne supprime pas ce fichier ») est journalisé avec le contexte complet (tool appelé, arguments, état conversation). Aggregat par pattern → règles tacites apprises (« ne plus proposer X dans contexte Y »). Injectées dans le prompt système per-user via le `frozen_memory_block`. |
| 3.7.2 | **Post-mission critic LLM-as-judge** | 🔴 Unique to ELY | M | À la fin de chaque mission goal-driven (ou conversation jugée complète par le router), un LLM auxiliaire (Tier B Mistral Small 4 ou local) note : (a) la mission a-t-elle atteint son but ? (b) combien d'itérations inutiles ? (c) le user a-t-il dû reformuler ? (d) un outil meilleur existait-il ? Sortie : score 0-100 + 1-3 critiques actionnables stockées dans `mission_post_mortems`. |
| 3.7.3 | **Eval harness reproductible** | 🟡 Hermes-parity | M | 50 missions canoniques en YAML (`backend/evals/canonical_missions/`) qui couvrent les use-cases majeurs (memory recall, web automation, gmail send avec HITL, drive cleanup, planning, etc.). Run nocturne automatique → métriques succès/échec/durée/coût stockées en SQLite. Dashboard simple. Sans ça, l'optimisation est à l'aveugle. |
| 3.7.4 | **A/B testing automatique des prompts système** | 🔴 Unique to ELY | M | Le `_SYSTEM_PROMPT_BASE` et les prompts spécialistes deviennent versionnés. Une variante candidate (proposée par Franck ou par le critic 3.7.2) tourne sur 10% du trafic pendant 2 semaines, comparée à la baseline sur l'eval harness 3.7.3 + métriques live (taux de HITL refusé, durée moyenne mission, satisfaction implicite). Promotion automatique si gain ≥ 5%, rollback automatique si perte ≥ 3%. |
| 3.7.5 | **Dashboard « Auto-amélioration »** | 🟢 Standard | S | Page Settings → Auto-amélioration : top 10 patterns appris des HITL refusés (avec bouton « oublier celui-ci »), score moyen post-mission par tier LLM, A/B en cours et leur statut. **Transparence radicale** : le user voit ce qu'ELY apprend, peut auditer, peut corriger. C'est ce qui distingue ce sprint d'une boîte noire SaaS. |

**Livrables mesurables** :
- 50 missions canoniques en YAML qui tournent en CI nocturne sans intervention
- Métrique baseline produite : « ELY v1.4 réussit X missions canoniques sur 50, Y itérations moyennes, Z€ coût »
- Au moins **2 patterns concrets** appris des HITL refusés en 2 semaines d'usage Franck (validation qualitative + UI affiche les patterns)
- **Premier A/B test gagnant** sur une variante de prompt système (preuve que la machinerie tient)

**Pourquoi unique** : aucun agent personnel ne donne au user un dashboard inspectable de ce que son agent apprend de lui — c'est soit opaque (SaaS), soit absent (open-source artisanal). C'est le pendant du principe #1 (« le user possède son agent ») appliqué à l'apprentissage : *« tu vois ce qu'il apprend, tu peux corriger »*.

---

## Sprint 3.5 — Web Automation suite headless ⏳ *Juillet 2026*

> **Note 2026-05-15** : le Sprint 0.5 a livré l'extension Chrome avec actions interactives. Ce sprint 3.5 reste pertinent pour les use cases **non-interactifs / batch** où on n'a pas besoin de la session utilisateur (capture périodique d'un site public, conversion de documents, monitoring de pages publiques en cron).

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 3.5 | **Web Automation tools (Playwright headless serveur)** — tools complémentaires à l'extension Chrome pour les contextes batch / autonomes : `web_screenshot` (full-page sites publics), `web_to_pdf`, `web_extract` (CSS/XPath ou auto-LLM), `web_compare` (diff visuel pour monitoring), `web_record_session` (vidéo MP4 pour rapports), `attachment_to_pdf` (.docx/.html/.xlsx → PDF). | 🔴 Unique to ELY | M | Playwright déjà en backend — manque la surface d'exposition propre |

**Pourquoi ces tools restent utiles malgré l'extension** : l'extension exige que l'utilisateur ait Chrome ouvert et l'extension connectée. Pour les cas *« tous les lundis matin à 6h, capture le site X et envoie-moi le PDF »*, on ne peut pas dépendre de la présence de l'utilisateur — il faut du headless serveur. Les deux mondes sont complémentaires : extension Chrome = action **interactive avec session user** ; Web Automation = action **batch sur sites publics**.

**Couplage avec Sprint 6 (scheduler) et Sprint 7 (predictive gate)** : ces tools alimentent des missions périodiques où l'agent capture et résume sans intervention humaine.

---

## Sprint 4 — Écosystème MCP ⏳ *Juillet-Août 2026*

> **Objectif** : faire d'ELY un citoyen de premier rang de l'écosystème MCP, dans les deux sens — **consommer** ce que la communauté offre (capacités gratuites), **exposer** ce qu'elle apporte (différenciation produit forte). Effet réseau gratuit dans les deux directions.

| # | Sous-item | Type | Effort | Détail |
|---|---|---|---|---|
| 4.1 | **ELY consomme des serveurs MCP externes** | 🟡 Hermes-parity | M | Configuration utilisateur d'une liste de serveurs MCP (stdio + HTTP+SSE). ELY les charge au démarrage, fusionne leurs tools/resources dans son toolset profile actif, applique son HITL gating dessus. Sécurité : sandbox env (`_build_safe_env()`), validation des packages npx/uvx contre la DB OSV, allowlist explicite par user. **Premiers serveurs cibles** : `mcp-server-fetch`, `mcp-server-filesystem`, `mcp-server-github`, `mcp-server-postgres`, `mcp-server-time`, `mcp-server-puppeteer`. Pour chacun, doc d'install + cas d'usage typique dans `docs/integrations/mcp-clients/`. |
| 4.2 | **ELY s'expose comme serveur MCP** | 🔴 Unique to ELY | M | Wrap les 30-40 tools les plus utiles d'ELY (memory_*, knowledge_*, gmail_*, calendar_*, drive_*, contacts_*, scheduler_*, save_constraint, save_user_preference) dans un serveur MCP standard. Authentification via les tokens longue durée du Sprint 0.5. Donne à l'utilisateur : *« mon ELY accessible depuis Claude Desktop / Cursor / Zed / VS Code Copilot / ChatGPT (quand support)»*. **Aucun agent personnel auto-hébergé sous licence permissive n'expose un MCP server aujourd'hui** — vraie différenciation produit : *« ton agent perso, branchable partout ».* |
| 4.3 | **UI Settings → MCP (entrée + sortie)** | 🟢 Standard | S | Liste des MCP servers connectés (entrants + sortants), toggle activation par tool, indicateur de santé (last_ping, error_rate), bouton « tester la connexion ». Sépare clairement les deux directions pour éviter la confusion. |
| 4.4 | **OAuth manager pour MCP authentifiés** | 🟡 Hermes-parity | S-M | Certains serveurs MCP officiels (Slack, Notion, Linear, Atlassian) exigent OAuth. Centraliser le flow, stocker les tokens chiffrés via le vault ELY existant, refresh automatique avant expiration. |

**Livrables mesurables** :
- Charger 5 MCP serveurs externes sans crash, leurs tools visibles dans le toolset profile et appelables par l'agent
- Lancer Claude Desktop avec `ely` dans son `claude_desktop_config.json` → l'agent Claude voit les tools ELY et peut interroger la mémoire ELY de l'utilisateur
- Page Settings → MCP fonctionnelle avec les deux directions clairement distinctes
- Doc d'intégration *« branche ELY à ton Cursor »* dans `docs/integrations/mcp-as-client.md` + *« expose ELY à tes autres agents »* dans `docs/integrations/mcp-as-server.md`
- 4 tests d'intégration : (1) MCP externe loaded, (2) MCP externe tool callable, (3) ELY MCP server répond aux requêtes Claude Desktop, (4) auth OAuth round-trip OK

**Cible commerciale** : la combinaison 4.1 + 4.2 transforme ELY en *« hub d'agents personnels »* — c'est probablement l'argument commercial le plus fort vis-à-vis des entreprises qui ont déjà investi dans Claude Enterprise, Cursor, ou des forks internes.

---

## Sprint 4.5 — Photos & Souvenirs ⏳ *Août 2026*

> **Idée d'origine** : Franck a vu sa femme submergée par les milliers de photos sur son téléphone et sur Drive, doublons visuels partout, impossible à trier manuellement. Le sprint répond à un besoin universel des familles avec un téléphone moderne — et c'est exactement le genre de tâche qu'un agent cloud ne peut pas faire (toutes les photos resteraient locales).

| # | Sous-item | Type | Effort | Détail |
|---|---|---|---|---|
| 4.5.1 | **Scanner + index visuel local** | 🔴 Unique to ELY | M | Trois niveaux d'indexation : (a) MD5 hash (existe déjà via `drive_find_duplicates`), (b) perceptual hash pHash/dHash pour les quasi-doublons (recadrage, recompression, ajustement luminosité), (c) embeddings CLIP locaux pour la similarité sémantique (mêmes personnes, mêmes lieux, mêmes scènes). Stockage Faiss + SQLite. **100% local** sur le hardware du user — les photos ne quittent jamais la machine, garantie produit majeure. |
| 4.5.2 | **Accès Google Photos** | 🟡 Hermes-parity | S-M | OAuth scope `photoslibrary.readonly` ajouté au flow Google existant. Tools `photos_list_albums`, `photos_list_in_album`, `photos_download_for_dedup`, `photos_delete_batch`. Pour les téléphones modernes (Android avec sync auto, iPhone avec Google Photos installé), ça couvre 95% des photos sans effort utilisateur. |
| 4.5.3 | **UI galerie + actions de groupe** | 🟢 Standard | M | Nouvelle page Settings → Photos. Liste des clusters de similaires (vignettes côte-à-côte), preview taille / date / dimensions / résolution, sélection multiple. Actions : « garder toutes », « garder la meilleure (suggestion auto) », « tout supprimer ». HITL obligatoire avant chaque suppression (rappel : le sprint vise des photos personnelles, irréversibles). |
| 4.5.4 | **Suggestion « meilleure photo » par cluster** | 🔴 Unique to ELY | S | Heuristique simple en V1 : score combiné (netteté Laplacien + luminosité normale + détection visage si présent + résolution). LLM local optionnel pour les cas ambigus. Le user garde toujours le dernier mot. |

**Livrables mesurables** :
- Scanner 20 000 photos en < 45 minutes sur Mac Studio M1 Max
- Détecter 80%+ des doublons visuels que DupeGuru détecte (benchmark de référence)
- Récupérer typiquement 30-50% de l'espace de stockage sur une bibliothèque famille (mesure réelle à valider chez les premiers users)
- Aucune photo n'est jamais envoyée à un service externe (cf. anonymisation native + tier A local du routing)

**Pourquoi c'est un sprint stratégique** :
1. **Démontrable en 30 secondes** dans une vidéo (avant/après mesuré : « 32 000 photos → 11 000 doublons éliminés → 18 Go récupérés »)
2. **Touche un besoin universel** que tout le monde a, mais que personne ne résout bien avec garantie privacy
3. **Impossible avec un agent cloud** — toute solution SaaS impliquerait d'uploader les photos vers leurs serveurs
4. **Aucun concurrent open-source ne le fait** au niveau d'intégration agent-conversationnel (il existe DupeGuru, Czkawka, etc. en outils standalone, mais aucun n'est piloté par un agent IA souverain)
5. **Bénéfice utilisateur immédiat et mesurable** (Go récupérés, temps gagné), pas un truc abstrait

**Ouverture future** : ce sprint pose les fondations d'un *« Family Memory »* plus large que le Sprint 5 (Personal Knowledge Graph) pourra exploiter — détection automatique d'événements (« vacances été 2025 »), de personnes récurrentes, suggestion d'albums thématiques. Le KG photo nourrirait la mémoire ELY générale.

---

## Sprint 5 — Personal Knowledge Graph ⏳ *Août-Septembre 2026*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 5 | **Personal Knowledge Graph** — graphe de connaissances per-user construit au fil des interactions (entités, préférences, patterns, relations). Extraction par LLM MAINTENANCE. Stockage SQLite + relations JSON. Retrieval ciblé en complément du RAG vectoriel actuel. Visualisable dans l'UI (« graphe de ton univers selon Éli »). | 🔴 Unique to ELY | L | LightRAG (Microsoft Research) + custom |

**Pourquoi unique** : combine l'esprit du World Model de LeCun (modèle interne du monde du user) avec une représentation **interprétable** que le user peut inspecter, corriger, exporter. Aucun agent commercial ne fait ça avec ce niveau de transparence.

**Stack envisagée** : LightRAG ou GraphRAG + BGE-M3 embeddings + SQLite (pas de Neo4j externe).

---

## Sprint 6 — Smart approval ⏳ *Septembre 2026*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 6 | **Smart approval auxiliaire** — un LLM rapide auxiliaire classifie une action critique comme « low-risk » ou « high-risk » et auto-approuve les low-risk sans déranger le user. Plus de hooks plugins `pre_approval_request`/`post_approval_response`. Allowlist persistante per-user. ContextVar thread-safe pour multi-session. | 🟡 Hermes-parity | M | `hermes-agent-main/tools/approval.py:30-90` |

**Pourquoi** : actuellement chaque action critique demande validation, ce qui devient pénible à l'usage. Le smart-approval réduit le bruit HITL de ~70% sans réduire la sécurité (le LLM auxiliaire ne valide que ce qui est trivialement bénin).

---

## Sprint 6.5 — Auto-réflexion en cours de mission ⏳ *Septembre-Octobre 2026*

> **Pré-requis stricts** : Sprint 3.7 livré (eval harness + A/B testing) + Sprint 6 livré (LLM auxiliaire classifier réutilisable comme critic). Sans ces deux fondations, ce sprint serait du **voodoo** — on ne saurait pas si la réflexion aide ou nuit, et on n'aurait pas le rail de mesure pour décider.

| # | Sous-item | Type | Effort | Détail |
|---|---|---|---|---|
| 6.5.1 | **Reflexion-style mid-mission critic** | 🔴 Unique to ELY | M | Pendant l'exécution d'une mission (pas seulement à la fin), un critic léger observe les 3 derniers tool_calls. Si pattern d'échec détecté (même tool appelé 3× avec même résultat, ou réponse user négative implicite, ou tool_call qui retourne `error`), il injecte une « réflexion » dans le state : *« cette stratégie ne marche pas, voici pourquoi, voici une alternative »*. L'agent reformule sa stratégie au tour suivant. Inspiré de Reflexion (Shinn et al., NeurIPS 2023), Self-Refine (Madaan et al.), LATS. |
| 6.5.2 | **Eval contre baseline + killswitch user** | 🔴 Unique to ELY | S-M | La boucle 6.5.1 est **toujours testée A/B** contre baseline sans réflexion (via la machinerie 3.7.4). Si l'eval harness 3.7.3 montre régression > 3% sur 2 semaines → rollback automatique avec alerte Telegram à Franck. Toggle user dans Settings → Auto-amélioration : « désactiver l'auto-critique en cours de mission ». **Garantie produit** : le user reste maître. |
| 6.5.3 | **Génération de dataset pour fine-tuning** | 🔴 Unique to ELY | S | Chaque trace mission (séquence d'actions + critique mid-mission + résultat final) est exportée en format JSONL standard (compatible Unsloth/MLX-LM). Le dataset devient le **carburant du Sprint 9 (LoRA personnel)** : on n'entraînera plus le LoRA sur du texte brut, mais sur des **traces qualifiées « action → critique → meilleure action »**. Multiplication de la valeur de v2.0. |

**Livrables mesurables** :
- Gain mesurable sur l'eval harness 3.7.3 (ou rollback honnête si pas de gain — c'est la règle du jeu)
- Dataset JSONL de 1000+ traces qualifiées générées en 1 mois d'usage Franck
- Démo 30 secondes capturable : « l'agent se trompe → se rend compte → corrige → réussit, sans intervention humaine »

**Risque assumé et nommé** : la littérature Reflexion 2024-2025 documente plusieurs cas de **régression** sur certains benchmarks (le critic hallucine la critique, l'agent sur-corrige). C'est pour ça que 6.5.2 est non-négociable : pas de mid-mission critic sans rail de mesure et killswitch. Si après 2 mois on n'a pas de gain net mesuré, on désactive par défaut et on garde l'opt-in pour les power-users.

**Pourquoi unique** : aucun agent personnel open-source ne ship Reflexion mid-mission en prod aujourd'hui. C'est de la recherche 2023-2024 qui n'a quasi pas migré en production. ELY le ferait en première — avec le garde-fou (3.7 + killswitch) qui rend la chose responsable plutôt qu'expérimentale-hype.

---

## Sprint 7 — Predictive tool gate ⏳ *Octobre 2026*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 7 | **Predictive tool gate** — avant d'appeler un tool coûteux/critique (LLM appel, Drive search lourd, web scrape), un LLM cheap prédit l'utilité du résultat probable. Si jugé inutile, on skip et on répond depuis la prédiction. Économies tokens massives + UX améliorée. | 🔴 Unique to ELY | M | LeCun WM appliqué à l'agentic |

**Pourquoi unique** : c'est la VRAIE essence du World Model de LeCun (« simuler avant d'agir ») appliquée à un agent texte. Aucun agent open-source ne le fait aujourd'hui. Combiné aux missions ELY, ça réduit les itérations inutiles.

---

## Sprint 8 — Skills marketplace standard ⏳ *Novembre 2026*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 8 | **Format SKILL.md standard + bridge agentskills.io** — adopte le format frontmatter YAML d'Hermes (`name`, `description`, `version`, `metadata.tags`, scripts/références). Permet d'importer les skills d'agentskills.io. ELY hérite d'un écosystème naissant sans tout produire elle-même. | 🟡 Hermes-parity | L | `hermes-agent-main/tools/skills_tool.py` + format `agentskills.io` |

---

## Sprint 9 — LoRA personnel par user ⏳ *Q1 2027*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 9 | **LoRA adapter personnel par user** — chaque user a son adapter LoRA (~200-500 MB) entraîné mensuellement sur Mac Studio en MLX/Unsloth. Base : Qwen2.5-3B ou Phi-3.5-mini. Le user peut **télécharger son `.safetensors`**, le sauvegarder, le restaurer, le partager. Inférence locale, A/B test contre baseline avant deploy. | 🔴 Unique to ELY | XL | Approche Personal AI / Adept, jamais shippée open-source |

**Pourquoi le moat ultime** : aucun agent commercial ne donne au user la *propriété physique* de son modèle d'IA. Le pitch devient : *"Va dans Paramètres → Mon Modèle → Télécharger. C'est à toi. Personne ne peut te l'éteindre."*

**Stack** : MLX-LM (Apple Silicon natif), Unsloth (cross-platform), Qwen2.5-3B-Instruct comme base, eval automatique avant chaque deploy.

---

## Recherche Q1-Q2 2027 — World Model expérimental 🔬

| # | Item | Type | Effort | Hypothèse à valider |
|---|---|---|---|---|
| 10 | **Predictive embedding model** (esprit JEPA texte) — petit modèle (~50-200M params) entraîné à prédire les états futurs probables : « si l'utilisateur vient d'envoyer ce message, quels sont les 3 tools les plus probablement appelés ensuite ? ». Pas génératif. Oracle complémentaire au LLM principal. | 🔬 Research | XXL | « Un modèle prédictif latent peut anticiper les besoins user et pre-fetcher les tools, réduisant la latence perçue de 40% » |

**Mode opératoire** : branch isolée `experimental/jepa-text`, A/B contre baseline (User State Vector), métriques objectives, rollback automatique si dégradation. **Ne sera shippé que si ça bat la baseline en éval.**

---

## Backlog non-prioritaire (à reconsidérer si demande user)

- **Sub-agents avec parallélisation** (`hermes-agent-main/tools/delegate_tool.py`) — utile pour missions très complexes, mais ELY a déjà les missions LangGraph qui couvrent 90% des cas
- **Plugins shell hooks** (`hermes-agent-main/agent/shell_hooks.py`) — ouvre l'extensibilité aux non-Pythonistes, mais peu de demande pour l'instant
- **Multi-canal massif** (au-delà de 5 canaux : Signal, Matrix, Mattermost, Email, etc.) — Hermes en a 18, ELY garde Telegram + Discord + Slack + WhatsApp + iOS + Android. Ajout uniquement sur demande user concrète.
- **6 backends terminal** (Modal, Daytona, Singularity) — pas le use-case ELY (agent personnel, pas dev infra)
- **TUI Ink (terminal client)** — régression vs UI Next.js, n'arrivera jamais

---

## Principes de priorisation appliqués

1. **Ce qui rend ELY unique en premier** (sprints 2.5, 3, 3.7, 5, 6.5, 7, 9 — tous 🔴)
2. **Ce qui réduit la dette technique de Franck** (sprint 2 — fini la triple-registration)
3. **Ce qui prépare le terrain de l'écosystème** (sprints 4, 8 — MCP + SKILL.md)
4. **Ce qui améliore la perception utilisateur immédiate** (sprint 1 — memory recall)
5. **Ce qui rend l'agent capable d'apprendre de lui-même** (sprints 3.7 → 6.5 → 9 — chaîne strictement ordonnée : eval + A/B d'abord, Reflexion ensuite, LoRA enfin)
6. **Recherche en parallèle, jamais bloquant** (sprint 10 — JEPA)

---

## Comment contribuer à un sprint

Chaque sprint sera tracké comme une **GitHub Milestone** avec ses issues. Les PRs externes sont les bienvenues, en particulier sur :
- Skills (`backend/app/skills/`) — easy win
- Traductions (`frontend/messages/`) — actuellement FR/EN, on attend ES, DE, IT
- Tests (`backend/tests/`) — il y en a 92 aujourd'hui, on vise 200+ d'ici fin 2026
- Docs (`README.md`, `docs/`) — les retours d'install sont précieux

Voir [CONTRIBUTING.md](./CONTRIBUTING.md) pour les détails.

---

## Versions cibles

| Version | Sprint(s) inclus | ETA |
|---|---|---|
| **v1.1.x** | Sprint 0 (launch) | ✅ Mai 2026 |
| **v1.1.2** | Sprint 0.5 (extension Chrome — tokens longue durée + actions interactives) | ✅ 14-15 mai 2026 |
| **v1.2** | Sprint 1 (memory recall) | Juin 2026 |
| **v1.3** | Sprint 2 (registry) + **Sprint 2.5 (mémoire cognitive multi-typée)** + Sprint 3 (user state) + Sprint 3.7 (self-improvement loop mesurée) | Juillet 2026 |
| **v1.4** | Sprint 4 (MCP — client + server + UI + OAuth) | Août 2026 |
| **v1.5** | Sprint 5 (Personal KG) | Septembre 2026 |
| **v1.6** | Sprint 6 (smart approval) + **Sprint 6.5 (self-reflection mid-mission)** + Sprint 7 (predictive gate) | Octobre-Novembre 2026 |
| **v1.7** | Sprint 8 (SKILL.md) | Novembre-Décembre 2026 |
| **v2.0** | Sprint 9 (LoRA personnel) — release majeure « Your Model, Your Control » | Q1 2027 |
| **v2.x** | Sprint 10 (JEPA recherche) — opt-in expérimental | Q2 2027+ |

Toutes les ETAs sont des **objectifs cibles**, pas des promesses. Un agent personnel one-developer-and-an-AI ne suit pas un Gantt d'ESN.

---

## Ce que la roadmap PROMET de ne pas faire

- ❌ Devenir un SaaS multi-tenant avec données chez nous
- ❌ Ajouter du tracking, des cookies tiers, ou de la télémétrie sans opt-in
- ❌ Verrouiller un user dans un provider LLM particulier
- ❌ Cacher les coûts (analytics tokens reste transparent dans le dashboard)
- ❌ Sacrifier l'UI au profit du terminal-first
- ❌ Promettre un World Model avant qu'on ait validé qu'il bat la baseline

---

*« On ne va pas confondre vitesse et précipitation. »* — Franck, 2 mai 2026

*« Il n'y a que ceux qui ne font rien qui ne se trompent jamais. »* — Franck, 15 mai 2026 (après un downtime de 4 min sur le site, le lendemain d'avoir livré 9 commits significatifs sur ELY 😅)
