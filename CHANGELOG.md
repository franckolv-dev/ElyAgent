# Changelog

All notable changes to ELY are documented here, in reverse chronological order.

This file follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) convention. Each entry references the commit short-SHA so you can dig into the exact diff with `git show <sha>`.

Categories used:
- **Added** — new user-visible capabilities.
- **Changed** — non-breaking changes to existing behaviour or wording.
- **Fixed** — bug fixes.
- **Security** — anything touching auth, anonymization, HITL, sandboxing, or vault.
- **Docs** — documentation-only changes that nonetheless affect what users see.

> Maintainer: [Franck OLLIVIER](mailto:contact@agent-ely.fr) — `franckolv-dev`

---

## [Unreleased]

> Lot des 17–23 juillet 2026 (PRs #199→#236) — fin du chantier Consolidation (C3c→C6). La boucle d'apprentissage devient **visible** (questions méta, gaps consignés), **automatique** (génération d'outil candidate sur capacité manquante, validation humaine systématique), **intelligente** (injection avec fenêtre de grâce et pertinence), **mesurée** (replay shadow A/B, métrique post-promotion), **nourrie** (👎 → signal d'apprentissage) — et l'**anticipation** naît en mode suggestion. Démontrée en prod le 19/07 : « crée-toi un outil distance de Levenshtein » → outil candidat généré en 12 s → promu par l'humain → utilisé par Ely.

### Added
- **Boucle d'auto-génération d'outils — le funnel a enfin son déclencheur** (`cd8b90b`/`cdf49fe`/`9f5c25f`, PR #217/#218/#219) : une question MÉTA (« peux-tu créer un outil qui… ») déclenche `find_tool` même sans tâche en cours et la réponse nomme le panneau « Capacités manquantes » ; un gap avéré lance AUTOMATIQUEMENT la génération d'un outil candidat (tier S, pipeline de validation 7 étages, 1 tentative par gap et par boot, kill-switch `AUTO_TOOL_GENERATION_ENABLED`) avec push ntfy quand une candidate attend validation — la sortie est TOUJOURS une candidate, la promotion reste un geste humain ; `report_missing_capability` donne au modèle le droit de consigner un gap malgré des faux-matchs lexicaux (division du travail : find_tool cherche, le modèle juge, report consigne, la fabrique produit, l'humain valide).
- **Injection intelligente des outils appris** (`026bd81`, PR #223) : un skill promu depuis < 7 jours est TOUJOURS injecté dans le prompt, en tête, tagué « (nouveau) » (colonne `promoted_at`, migration 0021 — fini le cold-start où l'outil fraîchement validé était le premier coupé du top-20 par usage) ; au-delà du cap, les places restantes sont re-rankées par pertinence contre la demande courante (lexical + cosine best-effort) ; le bloc `<learned_skills>` sépare playbooks (à lire via `skill_view`) et outils bindés (à appeler DIRECTEMENT) ; règle prompt « outil dédié d'abord » + contre-indication dans le docstring d'`orchestrate` ; une génération réussie referme ses gaps (processed_at + learned_skill_id).
- **Replay shadow A/B — la boucle devient mesurée** (`aa4a66d`/`377dc30`, PR #226/#227) : le tour d'un échec enregistré est rejoué SANS puis AVEC le skill appris — aucun outil réel n'est jamais ré-exécuté (les résultats capturés au signal sont re-servis par la passerelle en mode shadow, fail-closed), la seule différence entre les deux runs est le skill testé (snapshot mémoire pré-seedé), le détecteur d'origine tranche (improved/regressed/unchanged) et le verdict est écrit sur le skill ; `bench --case N` pour le déclenchement humain ; le curator hebdo mesure en plus la récurrence du pattern APRÈS chaque promotion (« le skill a-t-il éteint le problème ? »).
- **Les 👎 rejoignent le funnel d'apprentissage** (`b2c99f2`, PR #225) : chaque pouce-bas crée un cas d'échec (famille `user_feedback`, dédup par empreinte) que le cron de création de playbooks ramasse naturellement — les retours utilisateur étaient écrits en base et lus par les dashboards seulement, personne n'agissait dessus.
- **Anticipation V1 — Ely remarque tes routines et PROPOSE** (`da55ba3`/`d2d0f6e`, PR #228/#229) : un détecteur hebdo 100 % heuristique (zéro LLM) repère les demandes quasi identiques à cadence régulière (≥ 3 fois sur 28 jours, quotidien ou hebdomadaire) et propose d'en faire une tâche planifiée : push ntfy + bandeau sur la page Tâches planifiées avec modal de création PRÉ-REMPLIE (nom, prompt, cron) — c'est l'utilisateur qui crée, jamais Ely ; un refus est définitif (le pattern n'est plus jamais re-proposé) ; kill-switch `ANTICIPATION_DISABLED`. Au passage, la page gagne la première UI de création de tâche planifiée (il n'en existait aucune).
- **Formulaire de mandat d'autonomie dans la modal mission** (`ce0f08b`, PR #236) : le mandat (familles d'outils sans validation par action, comportement en cas imprévu, tier LLM, seuils de notification) se déclarait uniquement à la main dans le YAML `version: 2` + bloc `mandate:` — piège vécu deux fois. Le formulaire génère la spec v2 (validée croisée contre le parseur serveur) ; l'activation du mandat reste une validation humaine explicite et le noyau protégé (ssh, vault, admin…) reste non mandatable.
- **RoutingDecision traçable** (`9603c40`, PR #214) : chaque décision de routage (SLM-vs-cloud, tier du tour, domaine, modèle par cycle de sous-agent, fallback, rotation) émet un événement typé `kind=routing` + une ligne de log — le diagnostic ne repose plus sur des logs de timing qui mentent par omission.
- **Le tier S rejoint l'onglet Routage** (`9d9e0fd`, PR #232) : la voie de génération d'outils (tier S) devient visible et configurable dans Paramètres → Routage — ce qui est affiché est ce qui tourne.
- **MCP : permissions par utilisateur sur les serveurs d'instance** (`f8f02ec`, PR #201) : un admin peut ouvrir un serveur MCP d'instance à un autre utilisateur (serveur entier ou outil par outil) — table `mcp_tool_permissions` + UI dédiée.

### Changed
- **OutcomeVerifier — le garde anti-« c'est fait » couvre les 8 surfaces** (`984e032`/`7d22708`/`2c28e43`, PR #199/#203/#211) : la détection des fausses déclarations d'action (« j'ai supprimé les mails » sans outil appelé) était câblée sur le chat web seulement ; extraite en service commun puis appliquée aux canaux (Telegram, Slack, Discord, WhatsApp), au scheduler, à la voix et enfin à `ely_chat` (serveur MCP) — même point d'insertion partout, signal d'apprentissage uniforme tagué par surface.
- **Échéance murale sur chaque appel LLM** (`205daaa`, PR #212) : 14 sites d'appel enveloppés (`asyncio.wait_for` qui COUPE la connexion) — un SSE qui goutte ou une complétion pendue ne bloque plus jamais un tour 30 minutes ; le timeout est classé comme tel et déclenche la rotation de chaîne automatique ; défauts 30 s/120 s/240 s par tier, overridables (`LLM_DEADLINE_*_S`).
- **Rotation unifiée + fallback honnête** (`31e0284`, PR #213) : les trois systèmes de rotation divergents (chat, sous-agents, missions) passent par la même classification d'erreur ; en cas d'échec technique d'un spécialiste, le superviseur de secours HÉRITE des résultats d'outils déjà acquis et reçoit l'interdiction de déclarer « accès indisponible » quand l'échec précédent était technique (vécu : Gmail lu avec succès, puis « je n'ai pas accès à ta boîte » après un pépin serveur).
- **Arbitre local renforcé (routeur passe 2)** (`5727bc6`, PR #215) : parse tolérant du domaine, décision tracée, et la passe 2 APPREND — elle propose des mots-clés au routeur rapide pour s'auto-rendre inutile sur les requêtes récurrentes.

### Fixed
- **Anticipation : le détecteur voyait les tâches planifiées comme des routines à planifier** (`326dd92`, PR #230) : le scheduler persiste chaque exécution comme une conversation « [Planifié] … » — le premier cycle réel a proposé 8 « routines »… déjà planifiées. Conversations synthétiques exclues du scan.
- **Arrêt d'urgence : le mandat est révoqué** (`08293d8`, PR #233) : après un abort, `autonomy_state` restait « active » — badge « Autonomie active » sur une mission avortée.
- **Conversion PDF → Word en local + contrat `call_tool` testé** (`f74a4a9`, PR #231) : la conversion s'appuie sur la chaîne locale (plus de dépendance à un service tiers) et le contrat de composition `call_tool` des outils appris est enfin couvert par des tests.
- **Auto-génération : les tokens du tier S fuyaient dans le chat** (`23f62e1`, PR #222) : la tâche de fond héritait de l'arbre de callbacks LangChain par contextvars — le code généré s'entrelaçait CARACTÈRE PAR CARACTÈRE avec la réponse d'Ely. Contexte détaché (`spawn(detach_context=True)`).
- **Auto-génération : le pré-check lexical perd son droit de veto** (`b74127f`, PR #221) : un juge lexical simple re-contestait le jugement de pertinence du MODÈLE et bloquait la consignation de vrais gaps ; les méta-outils du funnel sont exclus des recherches (leur docstring s'auto-empoisonnait : l'exemple « pdf→docx » matchait à 1.0).
- **Notifications : en-têtes ntfy ASCII-sûrs** (`19f42ed`, PR #220) : un tiret cadratin dans le titre tuait le push HTTP — dont le push « question » des missions, qui n'était JAMAIS parti.
- **Sous-agents : la complexité se classe sur la question de l'utilisateur, pas le résultat d'outil** (`13125db`, PR #210) : au cycle post-outil, le classificateur lisait le blob du ToolMessage → COMPLEX → la synthèse de CHAQUE tour outillé partait sur le tier C quel que soit le routage choisi.
- **Auth : révocation de refresh idempotente** (`3383957`, PR #209) : deux refresh concurrents ne renvoient plus 500 — le perdant de la course reçoit 200.
- **Desktop : navigateur au démarrage opt-in** (`0ee87bb`, PR #208) : le daemon n'ouvre plus le navigateur à chaque boot (`open_browser`, défaut off).
- **Google auth : alias d'identité filtrés des scopes** (`ab49cf3`, PR #207) : le warning « missing scopes email » au refresh des credentials est éliminé à la source.
- **Chat : send stopped/done gardé quand la socket est déjà fermée** (`25a958e`, PR #206).
- **Canaux : content en blocs (codex) aplati avant désanonymisation** (`b381d90`, PR #205) : crash réel Telegram (`AttributeError: list.replace`) latent depuis GPT-5.6.
- **Upload : un sous-dossier par upload** (`0a1cd3d`, PR #204) : les pièces jointes du chat ne se mélangent plus entre elles ni avec les outils « dossier ».
- **Tests : flake TestVaultEmptyVerifier** (`135481b`, PR #216) : collision d'username due à un uuid tronqué — jamais tronquer l'identifiant UNIQUE d'un test.
- **CI : sandbox test-egress lisible** (`1511be2`, PR #224) : un reliquat de syntaxe Python dans le script bash masquait le diagnostic exactement quand un invariant d'egress échouait.
- **CI : ruff pinné sur la version du lock** (`542f1e5`, PR #234) : la sortie de ruff 0.16.0 (règles par défaut élargies) cassait le check requis de TOUTES les PRs d'un coup — monter de version redevient un geste volontaire.

### Docs
- **Design note « cran 3 — élargir la fabrique »** (interne) : cadrage des décisions pour que la boucle sache fabriquer des outils qui touchent des FICHIERS (libs PDF/DOCX sandbox-only, contrat fichier in/out, routage de profil io, alternative MCP différée) — matériau : les gaps réels PDF→DOCX et la composition spontanée observée.

> Lot des 16–17 juillet 2026 (chantier Consolidation C0→C3b + fixes). Le backfill fin juin → mi-juillet (client MCP v2, substrat de confiance, journal réversible…) suit ci-dessous, dans cette même section.

### Added
- **Missions : activation humaine du mandat + carnet dans le viewer** (`23bda47`, PR #194) : le mandat d'une mission autonome (budget de tokens, tier LLM, outils autorisés) doit être explicitement activé par un humain avant toute exécution ; le viewer affiche un carnet vivant (workspace + décisions) et un arrêt d'urgence. Toujours derrière le flag `autonomous_missions_enabled` (off par défaut).
- **Catalogue codex GPT-5.6 — terra, sol, luna** (`a04624d`, PR #189) : les modèles GPT-5.6 du forfait ChatGPT deviennent sélectionnables sur l'instance LLM (le défaut du provider reste 5.5).
- **Dédup des incidents d'auto-diagnostic récurrents** (`f559e3a`, PR #188) : garde anti-doublon AVANT l'appel LLM (clé user/source/source_id/catégorie) + compteur `occurrences`/`last_seen_at` (migration 0020) + marqueur `merged` anti-boucle — un échec répétitif fait UN incident, plus une inondation.
- **MCP : exception LAN configurable dans l'admin** (`6accb69`, PR #181) : `allow_private_network` exposé par serveur MCP pour autoriser explicitement un serveur du réseau local malgré la garde SSRF.

### Changed
- **ToolGateway — pipeline d'exécution d'outil unifié** (`374d83b`/`c1fdb5a`/`f48af01`, PR #195/#196/#197) : le chat, les sous-agents spécialistes et les missions autonomes exécutent chaque outil via la même passerelle (filtre sécurité → HITL → frontière PII → journal réversible → métriques). La décision de mandat reste souveraine côté missions. Une garantie ajoutée une fois vaut partout.

### Fixed
- **Missions : budget de tokens réel + tier LLM du mandat appliqué** (`e5b106d`, PR #191) : le budget comptabilisé correspond aux tokens réellement consommés et le tier LLM déclaré dans le mandat est celui utilisé.
- **Learning : calibration « jour vide » du signal no_write_effect** (`7fd6345`, PR #192) : une tâche à écriture conditionnelle (« supprime le spam », « traite les factures ») ne lève plus le signal les jours où il n'y a légitimement rien à muter — suppression sur preuve positive uniquement (outils réellement exécutés + résultat vide déclaré explicitement). 46,5 % des exécutions réussies étaient marquées douteuses à tort.
- **ELY Desktop : résilience aux resets du tunnel Cloudflare** (`7d26c2a`, PR #198) : le tunnel CF reset la WS périodiquement (rotation edge) et le blip de ~2 s avortait la tâche en cours. Désormais : grâce de reconnexion 15 s avant chaque outil `desktop_*`, `send_command` détecte le remplacement de connexion en cours de commande et re-tente une fois, garde d'identité sur `unregister` (un vieux handler ne peut plus éjecter la connexion fraîche), keepalive uvicorn pinné (`--ws-ping-*` 20 s). Daemon Go inchangé.

### Security
- **Frontière PII uniforme — sous-agents, canaux, scheduler** (`723c67d`, PR #190) : trois surfaces n'appliquaient pas le contrat PII du nœud d'outils central — chez les sous-agents spécialistes, les résultats d'outils (Gmail, Calendar, Drive…) repartaient EN CLAIR vers le LLM cloud. Registre de filtres partagé + dé/ré-anonymisation récursive : le contrat vaut désormais identiquement sur toutes les surfaces.

### Docs
- **README (EN+FR) + `.env.example` alignés sur la réalité du code** (`9db825f`, PR #193) et **docs à jour — MCP client v2, undo, GPT-5.5** (`867faca`, PR #187).

> **Backfill 16 juin → 13 juillet 2026** (post-v2.2.0, PRs #140→#186). Cinq chantiers structurants — le **serveur MCP** d'Ely, le **client MCP universel** (V1 puis v2 : OAuth, sandbox stdio, resources), le **substrat de confiance P1**, le **Reversible Action Journal** et les cinq premiers jalons des **missions autonomes** — plus l'assouplissement HITL demandé par l'usage réel et une salve de fixes.

### Added (backfill 16/06 → 13/07)
- **Missions autonomes — J1→J5** (`d5f3451`/`6b1810b`/`e83aaf6`/`75df9f4`/`96f7d2d`, PR #182→#186) : le socle des missions à mandat — contrat `mandate:` de la spec v2 (parser + validation, colonnes `mandate_json`/`autonomy_state`, migrations 0018/0019) ; enforcement du mandat dans `dispatch_tool` (mapping outil→famille, escape-hatches) ; disjoncteurs sur compteurs journaliers persistés + pause propre/reprise ; workspace de mission (journal + carnet de bord relu au plan/replan, promotion des leçons) ; autonomie stricte J5 (mode decide : refus + alternative ; anti-boucle sur appels identiques répétés en échec, cooldown + divergence, branchée dans `act_node`). Flag `autonomous_missions_enabled` OFF par défaut — l'activation humaine (J6) est dans le lot ci-dessus (PR #194).
- **Client MCP v2 — OAuth 2.1/PKCE, sandbox stdio, resources & prompts** (`fe03a33`→`e9bc01d`, PR #174→#179) : connexion OAuth de bout en bout aux serveurs MCP distants — découverte AS (RFC 9728/8414, replis OIDC) + DCR (RFC 7591), Authorization Code + PKCE S256, refresh proactif avec rotation du refresh token + révocation (RFC 7009), bundle de tokens dans le Vault du propriétaire (jamais en table/API/logs), UI « Se connecter »/« Déconnecter » par serveur dans settings/mcp ; durcissement des serveurs stdio via launcher (setsid + rlimits, kill de l'arbre de process par PGID — fini les orphelins npx→node→chromium) ; primitives resources/prompts exposées en 4 outils lecture seule (contenu serveur étiqueté non fiable, prompts jamais auto-injectés, binaires hors contexte). 3 flags dédiés OFF par défaut (`mcp_oauth_enabled`, `mcp_stdio_sandbox_enabled`, `mcp_resources_enabled`), migrations 0016/0017.
- **Reversible Action Journal — « Ely peut annuler ce qu'elle vient de faire »** (`7276a52`/`4e50ade`/`0673238`/`b8764d4`/`918f30c`, PR #165/#166/#169/#168/#170) : toute action mutante annulable est journalisée après succès et compensable — V1 par opération inverse (Drive delete → restauration depuis la corbeille, `restore_from_trash` implémenté pour l'occasion), mode snapshot pour rename/move (état capturé AVANT exécution), vérification post-annulation (verify), purge quotidienne + métriques admin. Trois surfaces : outils agent (« annule ce que tu viens de faire » — `undo_last_action`/`revert_action`), API `GET /api/me/reversible-actions` + undo (404 anti-fuite, 409 si non annulable), page « Annulations » dans l'UI. Fail-closed (owner/statut/expiration), `compensation_args` sans secret ni PII. Flag `reversible_journal_enabled` OFF, migration 0015.
- **Substrat de confiance — P1 complet, 4 contrats** (`a8c611b`, PR #160) : CapabilityManifest (chaque capacité décrite par un manifeste déclaratif, lu par le gate HITL en reproduisant à l'identique la règle actuelle) ; ActionPlan + empreinte sha256 (« tu valides exactement ce qui s'exécute » — re-vérifiée juste avant exécution, fail-closed, jamais de secret dans l'empreinte) ; clés d'idempotence (« jamais deux fois par accident », pilotées par le manifeste, TTL configurable, migration 0014) ; EventEnvelope + export OpenTelemetry optionnel (journal typé et corrélé sans aucun prompt privé, identité hachée). Flag `trust_substrate_enabled` OFF ; suite de tests verte flag OFF ET flag ON.
- **Client MCP universel — V1 (Lot 0 → J6)** (`8ef725d`/`545b07c`, PR #153/#159) : Ely cliente de n'importe quel serveur MCP, derrière `mcp_client_v2_enabled` (OFF). Namespace `mcp__<slug>__<tool>` avec garde anti-collision fail-closed (aucun outil MCP ne peut masquer un outil natif) ; transport Streamable HTTP + garde egress SSRF/DNS-rebinding fail-closed (HTTPS imposé, IP privées/link-local/métadonnées cloud refusées, connexion épinglée IP + SNI anti-TOCTOU) ; catalogue persisté avec quarantaine (outil nouveau ou définition changée = désactivé) ; validation des arguments contre le JSON Schema complet ; résultats normalisés et bornés (binaires hors contexte, `_meta` jamais transmis) ; ACL par (user, serveur, outil) + HITL selon le risque + credentials dans le Vault ; outils model-facing (`mcp_connect` HTTPS sous HITL, `mcp_propose_server` = quarantaine, jamais d'auto-approbation d'un stdio local) ; UI quarantaine/approbation + import `mcpServers` ; recherche dans le registre MCP officiel (découverte seule, zéro confiance implicite). `env_json` jamais renvoyé par l'API (noms de clés seulement). Migrations 0012/0013.
- **Serveur MCP d'Ely + clés API personnelles** (`1e29aa4`/`92a9244`, PR #145/#146) : Ely exposée COMME serveur MCP — endpoint Streamable-HTTP `/api/mcp` (FastMCP) authentifié par clés API personnelles (`ely_api_…`, hash-stockées, révocables, page Réglages → Clés API, migration 0011) ; tools v1 : `ely_chat` (un tour d'agent en mode autonome-sûr, outils irréversibles bloqués), `ely_list_scheduled_tasks`/`ely_create_scheduled_task`, `ely_memory_search`. Un client MCP externe (Claude Desktop…) pilote l'instance.
- **`delegate` — sous-tâches indépendantes en parallèle** (`262bd3c`, PR #140) : 2 à 6 sous-tâches lancées en parallèle, chacune dans un sous-agent autonome (outils irréversibles bloqués — l'enfant rapporte, le parent sous HITL agit), pas de délégation imbriquée, best-effort (un enfant qui casse ne coule pas le lot).
- **`model_metadata` — source de vérité des capacités modèles** (`85ca4ea`, PR #141) : snapshot bundlé offline-first + overlay models.dev (cache disque, TTL 7 j) remplacent l'heuristique fragile de `supports_vision` — corrige les faux positifs/négatifs de routage vision (ex. deepseek désormais correctement non-vision).
- **`drive_upload_local_file`** (`a58543b`, PR #143) : téléverser un fichier local binaire (PNG de capture…) sur Drive — ferme le trou documenté « capture prise mais impossible à sauvegarder » ; validation de chemin anti-traversal, liste blanche des dossiers de capture, MIME auto-déduit.

### Changed (backfill 16/06 → 13/07)
- **Licence** : le bloc « RÉSUMÉ DES CONDITIONS » des headers passe à 3 conditions — retrait de la ligne « Modification et redistribution avec attribution » dans 222 fichiers (`df754bd`, PR #173) ; la note de licence des README (EN + FR) ne restreint plus l'offre d'ELY en service hébergé (`4cb27c0`/`972e374`).

### Fixed (backfill 16/06 → 13/07)
- **PWA : auto-récupération après déploiement** (`9f7c669` puis `31bc082`, PR #151/#171) : un onglet ouvert pendant un déploiement restait bloqué sur « This page couldn't load » (ChunkLoadError). D'abord reload-une-fois automatique + écran d'erreur FR (#151) ; puis récupération dure (`lib/recover.ts` : désenregistrement du service worker + purge des caches + rechargement) parce qu'un simple reload pouvait re-servir un shell périmé et re-boucler (#171).
- **HITL MCP : lecture sans friction + « Toujours autoriser » qui tient** (`86a5097`, PR #162) : un outil MCP de consultation (readOnlyHint ou risque low, jamais high/critical) ne demande plus de confirmation à chaque appel ; « Toujours autoriser » écrit désormais dans `mcp_tool_permissions` — le gate MCP ne lisait pas `hitl_preferences`, la préférence était ignorée à chaque appel. Anti tool-poisoning : un nom dangereux (delete/exec/pay…) reste high/critical et confirme toujours.
- **Chat : n'afficher que la réponse finale, pas les préambules d'outils** (`5dffc0f`, PR #148) : depuis GPT-5.5, le modèle recopiait son préambule (y compris le script orchestrate complet) dans le contenu du tour qui appelle un outil — streamé et persisté tel quel. On ne garde que le contenu du dernier tour (filet : contenu complet si le dernier tour est vide).
- **LLM-juge : content en liste de blocs → crashs silencieux** (`23ad569`/`a6e9fa7`, PR #149/#180) : certains providers renvoient `response.content` en LISTE de blocs — le cron des critiques de mission plantait toutes les 5 min (`'list' object has no attribute 'strip'`, tout le signal d'auto-amélioration mort) et « Proposer un correctif » de l'auto-diagnostic renvoyait HTTP 500. Aplati via le helper partagé `content_to_text()` à la frontière, tests de régression.
- **Upload chat > 1 Mo bloqué** (`b9fd86e`, PR #147) : nginx sans `client_max_body_size` → défaut 1 Mo, tout upload plus gros rejeté avant même le backend (qui autorise 50 Mo), spinner infini côté frontend. `client_max_body_size 50M` + garde côté client avec message clair.
- **orchestrate : « Google non connecté » à tort** (`c0da6c7`, PR #142) : le dispatcher du sandbox n'injectait jamais les credentials Google — tout appel Drive/Gmail/Calendar depuis un script orchestrate échouait alors que l'utilisateur EST connecté. Credentials du compte par défaut résolus et injectés comme dans les autres chemins (limite documentée : compte par défaut seul).
- **Gmail : pièce jointe depuis `/tmp/ely-screenshots`** (`781f19a`, PR #144) : les captures de l'extension Chrome ne pouvaient pas partir par mail — seul `/tmp/ely-attachments` était dans la liste blanche.
- **Déploiement : 502 nginx après `git pull`** (`566c8ec`, PR #163) : un bind-mount de FICHIER unique épingle l'inode au démarrage — après un pull (rename atomique → nouvel inode), le conteneur servait une conf périmée ; même piège latent côté squid. Confs nginx et squid montées en DOSSIER dédié + `--force-recreate` dans le Makefile.
- **Tâches planifiées : la page crashait sur le statut `silent`** (`4b082c1`, PR #172) : la map d'états de l'indicateur ne couvrait pas `silent` → TypeError plein écran dès qu'une veille `[SILENT]` avait tourné. Entrée ajoutée + lookup défensif pour tout statut inconnu futur.
- **Bench nocturne : scénarios HITL I & K réalignés** (`191aaae`, PR #164) : ils encodaient encore le comportement HITL d'avant #150 et échouaient toutes les nuits depuis le 20/06 (le bench n'est pas dans la CI requise des PR).

### Security (backfill 16/06 → 13/07)
- **HITL : confirmations dangereuses désactivables + délai 30 min + timeout ≠ refus** (`03091d8`, PR #150) : la préférence « autoriser définitivement » est désormais honorée même pour les outils verrouillés (défaut inchangé : confirmation ON ; désactivation explicite « à ses risques » dans les Réglages, y compris pour les tâches planifiées) ; délai de validation 5 → 30 min (`HITL_TIMEOUT_SECONDS`) ; un timeout n'est plus compté comme un refus délibéré — le signal d'apprentissage n'est plus pollué et le LLM reçoit « ni autorisée, ni refusée ».

### Docs (backfill 16/06 → 13/07)
- **Docs install/usage remises à l'état réel d'Ely** (`172d47d`, PR #152) : audit des 16 docs puis correction fidèle — URI de redirection OAuth Google corrigée (bug bloquant `redirect_uri_mismatch`), création du compte admin actualisée (`make create-admin`), `JWT_SECRET_KEY` signalée seule variable obligatoire, ports corrigés, canaux livrés marqués livrés, ajout des features non documentées (serveur MCP, upload 50 Mo, multi-compte Google, delegate).
- **`.env.example` : flags des nouveaux chantiers documentés** (`7b25e89`/`0722375`, PR #161/#167) : `MCP_CLIENT_V2_ENABLED` et `TRUST_SUBSTRATE_ENABLED` (+ variables liées optionnelles), puis `REVERSIBLE_JOURNAL_ENABLED` + TTL.

---

## [2.2.0] — 2026-06-16 — L'apprentissage qui démarre vraiment, le planifié plus malin, le chat plus souple

> Quatre jours d'usage réel. La **boucle de skills** passe enfin d'« architecture prête » à « vivante » : Ely crée et active ses playbooks toute seule, et on peut en importer. Le **planificateur** (déjà une force) gagne le `[SILENT]` anti-spam et un vrai one-shot. Le **chat** gagne les gestes qui manquaient (régénérer, éditer, titre LLM). Et la **boucle d'auto-diagnostic** mesure le succès réel, pas déclaré.

### Added
- **Réveil autonome du funnel skills** (`1198eb0`, PR #132) : un job de fond crée + active automatiquement des playbooks à partir des `failure_cases` réels (le déclencheur manquant — `run_full_loop` n'était appelé que par un bouton admin), auto-promotion sur eval-pass, 5 playbooks seed FR, gel acté de la génération de code (markdown-only).
- **Import de playbooks `SKILL.md` depuis une URL** (`e589a8b`, PR #137) : format standard frontmatter + Markdown, fetché → file de revue admin (`candidate`, jamais auto-activé), réutilise la machinerie skills. Endpoint `POST /admin/learning/skills/import` + bouton sur `/me/learning/candidates`.
- **Boucle d'auto-diagnostic** (`6d91622`→`1da1338`, PR #125→#130) : signal `execution_outcome`, heuristiques « succès de façade », diagnostiqueur de cause (LLM-juge + repli règles), page admin « Incidents & propositions », correctifs validables/réversibles.
- **Scheduler `[SILENT]` + vrai one-shot + lifecycle** (`ff09bca`, PR #133) : une veille sans rien de nouveau ne notifie plus ; `@once <ISO8601>` exécuté une fois puis auto-supprimé (fini le cron jour+mois qui re-déclenchait chaque année) ; outils agent `scheduler_update_task` / `scheduler_run_task`.
- **Chat : titre généré par LLM** (`7ef72c1`, PR #134) — remplace le `user_content[:50]` ; **régénérer une réponse + éditer/renvoyer le dernier message** (`c2e71e0`, PR #135).
- **Indicateur d'état d'exécution des tâches planifiées** (en cours / réussi / échec) (`ad5fb12`, PR #124).
- **Bouton admin « Créer un outil »** (amorçage du funnel) (`474e654`, PR #131).

### Changed
- **README (EN + FR) recentré** : positionnement perso non-commercial assumé (retrait du pitch de vente PME) ; partie « auto-développement » recadrée honnêtement autour de la boucle de playbooks vivante (la génération de code Python est marquée expérimentale/désactivée) ; roadmap remise à jour ; compteur d'outils 181 → 190+.
- **Missions : le planificateur exécute le travail** au lieu de le déléguer (`fe80d49`, PR #123) ; `recursion_limit` configurable 25→60 (`8128760`, PR #122).

### Fixed
- **openai-codex (forfait ChatGPT)** : paramètres backend, entrée legacy de routage, rejeu du reasoning chiffré en multi-tours (`25c1c5a`/`8769cf6`/`5e3fe31`/`4a4f201`/`4f85178`, PR #112→#116).
- **Tâches planifiées** : outils nommés perdus au tour 2, filtre d'outils reparti du prompt initial, binding `desktop_*` quand le prompt référence un fichier local (`8f77747`/`6e445fb`/`4a2e8a5`, PR #117/#119/#121) ; page de gestion avec suppression réelle (`90b1a4e`, PR #118).
- **Desktop** : binaires servis en octet-stream + attachment, fini le suffixe `.txt` (`5e3fe31`, PR #113).
- **Makefile** : `create-admin` et reload nginx via les services compose (noms de conteneurs périmés) (`5d437e4`/`bf65a7e`).

### Security
- **Audit sécurité 13/06 — pile A** (`9a32fa7`, PR #120) : IDOR sur `ban_action`, vault vide vérifiable, chunking PII sans perte, bump dépendances (pypdf/multipart), doc README/security honnête.

---

## [2.1.0] — 2026-06-12 — Cycle PII des missions, mémoire qui dit vrai, choix de modèles sur mesures

> Trois chantiers nés de l'usage réel. Le **cycle PII des missions** ferme le dernier trou documenté de la frontière souveraineté. Le **routage d'écriture mémoire** répare le cas le plus naturel (« retiens mes URLs ») qui produisait des confirmations hallucinées. Et deux **outils de mesure** font que plus aucun changement de modèle ne se décide au ressenti.

### Security
- **Cycle anonymise/dé-anonymise complet sur les missions** (`021aec7`, PR #108) : les missions autonomes envoyaient goal, sorties d'outils et audit trail **en clair** aux LLM cloud. Invariant appliqué (le même que le chat) : *la base et l'utilisateur vivent dans le monde réel ; seul le LLM voit des placeholders*. Prompts anonymisés avant chaque appel (plan/act/eval/replan + LLM-juge), args d'outils restaurés avant exécution, notifications protégées. Design sans vault persistant : aucun placeholder ne touche jamais le disque. 15 tests pins.
- **Positionnement couche 2 NER documenté** (`b7d8324`) : protection de la *confidence passive*, structurellement en tension avec l'usage agentique — flag éteint = réglage recommandé, la couche 1 regex (emails/téléphones/IBAN/CB) reste toujours active.

### Fixed
- **« Retiens mes URLs » fonctionne enfin** (`82eb3f3`, PR #106) : `memory_archive` n'avait pas de phrases déclencheurs — le LLM ne le choisissait jamais et confirmait des enregistrements **hallucinés** (attrapés par le completion_guard). Docstring réécrit intention-d'abord + règle « ne jamais confirmer sans appel réel » + nouvel outil `memory_view_profile` (« qu'est-ce que tu sais de moi ? ») pour vérifier ce qui est réellement stocké.
- **Sandbox « unhealthy » en permanence** (`3212eb5`) : le healthcheck passait par le proxy egress qui refuse localhost — `NO_PROXY` ajouté.

### Added
- **Gate d'extraction maintenance** (`287e708`, PR #107, tag bench `deep`) : tout changement de modèle sur le tiers MAINTENANCE passe un examen d'extraction (rappel de faits plantés, rejet du bruit, piège anti-fabrication) avant d'écrire dans la mémoire long-terme. A attrapé en conditions réelles une config encore sur un modèle défaillant.
- **Probes tier A** (`backend/scripts/probe_tier_a_models.py`) : latence au premier token *utile* + correction sur 5 questions représentatives — l'outil qui a départagé Gemma 4bit/8bit/LFM2.5 sur données.

---

## [2.0.0] — 2026-06-11 — Ely contribue à son propre code source 🎓

> Le saut majeur que la roadmap promettait depuis le Sprint 4b. La [PR #105](https://github.com/franckolv-dev/ElyAgent/pull/105) est la **première pull request générée, commitée et ouverte de manière autonome par Ely** sur son propre dépôt — et mergée par un humain après revue, avec sa CI verte. Le cycle complet de l'auto-developing agent est fermé :
>
> *Ely s'écrit un outil → le valide en 7 étages → le fait promouvoir par l'admin → l'éprouve à l'usage réel (gates : invocations, zéro erreur, ancienneté) → le convertit en code core avec test pytest et manifest de preuves → **ouvre la PR** → la CI exécute son test → un humain review et merge → au boot suivant, la garde de chargement retire la version dynamique et le code core prend le relais.*
>
> Le garde-fou est structurel : Ely ne peut pas merger — la revue et le merge restent humains, et chaque artefact (provenance dans l'en-tête du fichier, manifest dans le corps de la PR) est conçu pour cette revue.

### Added
- **Premier outil gradué** : `app/agent/tools/graduated/fibonacci_tool.py` + `tests/test_graduated_fibonacci.py` (`6666d7c`, PR #105 — par Ely). Outil volontairement trivial : c'est le **pipeline** qu'on éprouvait, pas l'outil. La row `learned_skills` d'origine est conservée en `graduated` (trace d'audit complète : génération → usage → graduation).

### Notes de version
- La mécanique complète (gates, codegen, garde d'unicité, canal PR GitHub, UI) a été livrée en v1.19.0 (PRs #95-#98) — la v2.0.0 est sa première exécution réelle de bout en bout.
- Prochaines étapes du chantier : amorçage du funnel en régime de croisière (≥ 3 outils réels avec usage), graduation des outils io (V4.1, sandbox conservée), et calibrage des seuils sur données réelles.

---

## [1.19.0] — 2026-06-11 — Mécanique de graduation (V4) + couche PII calibrée terrain + avatar réparé

> Deux histoires dans cette release. **La graduation** : toute la mécanique qui permettra à Ely de convertir un outil qu'elle a elle-même généré et éprouvé en code core livré **par une pull request qu'elle ouvre** — gates, codegen, garde d'unicité, canal GitHub, UI de revue (la v2.0.0 sera la première graduation réelle de bout en bout). **Le calibrage PII** : la couche 2 activée en conditions réelles a montré en quelques heures qu'un filtre trop zélé rend l'agent inutilisable — trois corrections terrain le jour même, et un principe gravé : *masquer ce qui identifie quelqu'un, jamais ce qui décrit le monde*.

### Added (graduation — Sprint 4d J1+J3+J4+J5, PRs #95-#98)
- **Instrumentation par outil** (`537ba8e`) : colonne `tool_origin` (learned|builtin) posée à la capture sur `error_log` + `hitl_refusals` (migration 0005), service de gates env-tunables (`GRADUATION_MIN_INVOCATIONS=10`, `GRADUATION_ERROR_FREE_DAYS=14`, `GRADUATION_MIN_AGE_DAYS=7`), endpoint `GET /admin/learning/skills/{id}/graduation`, scénario bench qui **exécute** un python_tool.
- **Codegen + garde d'unicité** (`319abb7`) : statut `graduated`, dry-run complet (gates + revalidation 7 étages + dépendances de composition), génération du fichier core (provenance embarquée) + test pytest livré dans la même PR + manifest des preuves ; au boot, un tool core homonyme bascule automatiquement la row en `graduated` — jamais deux outils du même nom bindés.
- **Livraison PR GitHub** (`cbc3722`) : branche + commits + pull request ouverts par Ely via l'API (token fine-grained chiffré en base, clé `github_graduation_token`), corps de PR = manifest ; fallback export local sans token ; livraison refusée (409) si le dry-run n'est pas vert.
- **UI de graduation** (`c1a2c75`) : panneau dans la revue des candidates — gates en chips, dry-run avec aperçu des fichiers, « Ouvrir la PR de graduation » confirmé.

### Fixed
- **`use_count` bumpé à chaque invocation d'un python_tool pur** (`82b986d`) : le compteur n'était câblé que pour les playbooks — la gate « invocations » ne pouvait jamais passer (constaté en réel sur le premier outil amorcé).
- **Avatar 3D : fuite de contextes WebGL** (`f946648`) : la sonde de disponibilité créait un contexte par render sans le libérer — Chrome (~16 contextes max) finissait par tuer celui du vrai avatar, fallback « WebGL indisponible » définitif au bout de quelques minutes. Sonde mémoïsée + contexte de test libéré + remontage automatique (3 tentatives). sw.js v17.

### Security (couche 2 PII — calibrage terrain, PRs #101-#103)
- **Pas de détection NER fraîche sur le contenu machine** (`f3d74ed`) : résultats d'outils, erreurs, stdout sandbox et historique assistant passent en vault-first-only — la PII que l'utilisateur a tapée reste masquée partout, mais le contenu public (web, GitHub, en-têtes d'emails) n'est plus mutilé. Corrige le briefing illisible (`[ORG_n]` partout) et le routage d'outils cassé.
- **Allow-list des services intégrés** (`f3d74ed`, défense en profondeur `01423d1`) : GitHub, Gmail, Telegram… jamais masqués (extensible via `PII_NER_ALLOWLIST`), appliquée au moteur ET dans SecurityFilter ET aux entrées vault pré-existantes (guérison automatique des conversations polluées).
- **Le label ADDRESS ne masque que le niveau rue** (`d10c403`) : ville/région/pays restent en clair (« la météo à Toulouse » fonctionne) ; l'adresse postale complète du bench reste couverte, pinnée.
- **Kill-switch documenté** : `PII_NER_ENABLED=false` + `docker compose up -d backend` — voir `docs/security.md`, `docs/TROUBLESHOOTING.md` et `.env.example`.

### Changed
- `mem_limit` backend 4g → 5g (`4f1db60`) : la couche 2 charge le GLiNER ONNX **fp32** (~1,2 Go) — toutes les quantizations (int8 ×2, fp16, int8 communautaire) ont échoué la validation qualité de l'export.

### Docs
- `docs/security.md` : section couche 2 (périmètre calibré, activation, kill-switch) ; `docs/TROUBLESHOOTING.md` : entrée « Ely répond avec des [PERSON_0] » ; `.env.example` : kill-switch + allow-list.

---

## [1.18.0] — 2026-06-10 — Couche 2 PII (NER), re-rank outils missions, voix affinée

> Trois chantiers du jour : la frontière PII gagne une **couche NER** pour les noms / organisations / adresses en texte libre (ce que les regex ne peuvent pas voir), les missions choisissent leurs outils par **re-rank hybride lexical+sémantique**, et la voix d'Ely devient plus naturelle (Vivienne, débit calmé). Plus un tri de printemps : les docs internes quittent le dépôt public.

### Security
- **Couche 2 PII NER** (`1d0d770`) : GLiNER `urchade/gliner_multi_pii-v1` en **ONNX int8** détecte personnes / organisations / adresses avant tout envoi à un LLM cloud — emails, téléphones, IBAN, CB restent à la couche 1 regex (déterministe). Flag `PII_NER_ENABLED` **défaut OFF** : sans lui, comportement strictement identique (pinné par test). Design issu du bench du jour : remplacement **vault-first** (une valeur connue est masquée à chaque occurrence, quel que soit le score NER), **cache** hash→entités (l'historique ré-anonymisé à chaque tour ne paie l'inférence qu'une fois), placeholders `[PERSON_n]`/`[ORG_n]`/`[ADDRESS_n]` réversibles, fail-open vers la couche 1 si le modèle manque. Le faux positif « Pierre qui roule » (0.99) est documenté et **accepté** : le placeholder est réversible, ne pas « corriger » en montant le seuil. Activation en 3 étapes (build `PII_NER_INSTALL=1` → export ONNX **sur l'hôte** via `backend/scripts/export_gliner_onnx.py` → `PII_NER_ENABLED=true`), détail dans `.env.example`. 31 tests pins.

### Added
- **Re-rank hybride des outils missions** (`f594f28`) : `_filter_tools_for_step` combine recouvrement de tokens (mène) et cosine fastembed ×0.5 (affine) — le matching mots-clés seul ratait les accents (incident briefing du 31 mai, corrigé par `_norm`) et le pur sémantique échoue en cross-lingual FR. Embeddings du catalogue cachés par `tools_version`, fail-open lexical-only, kill-switch `MISSION_SEMANTIC_TOOLS_DISABLED`. 10 tests.
- **Débit TTS réglable** (`e70d109`) : `settings.tts_rate`, override env `TTS_RATE` sans rebuild — source unique partagée par le routeur `/tts` et le service voix WebSocket (le débit était codé en dur dans 2 constantes séparées, même piège que la voix avant son câblage).

### Changed
- **Débit TTS +20 % → +10 %** (`e70d109`) : +20 % était perçu trop rapide / pas naturel avec la voix Vivienne.
- **Dockerfile backend : layer caching** (`1d0d770`) : `COPY app/` & co déplacés **après** les grosses couches (Chromium ~150 Mo, fastembed ~90 Mo) avec `--chown=appuser`, `.dockerignore` passé en patterns récursifs `**/` — un changement de code seul ne rebuilde plus que les couches COPY. Le pin v1.17.1 tolère désormais les flags `COPY --chown`.

### Docs
- **Tri des docs publiques** (`1d0d770`) : seules les docs d'install / configuration / utilisation restent sur GitHub. Retirés du dépôt (conservés localement) : `ADDING_A_TOOL`, checklists release/testing, READMEs bench & screenshots, note Sprint 2.5, doublon `docs/roadmap.md`. Le `.gitignore` couvre les familles récurrentes (`docs/audit-*`, `docs/code-review-*`, …). `ROUTING.md` reste public à dessein : il est lu par les tests. Liens morts nettoyés (`CONTRIBUTING`, `ROADMAP`, `docs/architecture.md`).

---

## [1.17.1] — 2026-06-10 — Hotfix : les migrations Alembic n'étaient pas dans l'image Docker

> Bug de déploiement découvert en prod le jour même de la v1.17.0 : la page Missions entière répondait **HTTP 500** (`no such column: missions.spec_yaml`) et le heartbeat missions échouait toutes les 10 s. Cause : le Dockerfile backend copie sélectivement (`app/`, `scripts/`) et n'embarquait ni `alembic.ini` ni `migrations/` — `ensure_migrations()` échouait au boot **en best-effort comme conçu** (CRITICAL loggé, boot continue), donc la base prod n'a jamais reçu les révisions 0002→0004 du Sprint 4c. Le rebuild post-fix applique les migrations automatiquement au boot : aucune intervention manuelle sur la base.

### Fixed
- **`backend/Dockerfile` embarque Alembic** : `COPY alembic.ini` + `COPY migrations/` — sans eux, toute révision post-baseline est silencieusement perdue en prod Docker alors qu'elle fonctionne en dev (où `backend/` complet est présent). Pin source-level dans les tests pour que la régression soit impossible. *(2026-06-10)*

### Added
- **`/health/deep` expose le drift de migrations** : nouveau check `migrations` (la base est-elle au `head` des révisions ?) à côté de `db` et `qdrant` — 503 `degraded` si la base est en retard. C'est le signal qui manquait : l'échec best-effort du boot n'était visible que dans un CRITICAL de log que personne ne regarde ; désormais le monitoring le voit avant le premier 500 utilisateur. Helper `migrations_current_sync()` dans `alembic_runner`. 6 tests pin (Dockerfile, drift détecté/à jour/en retard, sonde degraded/ok). *(2026-06-10)*

---

## [1.17.0] — 2026-06-10 — Sprint 4c : missions structurées (spec YAML + ask_user + viewer)

> Sprint complet en 5 jalons (PRs #86-#90) : J1 format+parser · J2 exécuteur · J3 hook ask_user · J4 viewer liste · J5 docs. Fin du prompt-monolithe des missions : ajouter un cas oublié = ajouter UNE ligne, et quand Ely hésite, elle pose la question puis reprend sur la réponse — le « mode chat fait à la main », automatisé.

### Added (J4 — viewer liste, la fonctionnalité devient visible)
- **Le viewer LISTE** (pas de canvas — choix de design explicite du backlog) : sur la page de détail d'une mission structurée, panneau « Exécution structurée » — chaque step de la spec avec son icône d'état, la progression `done/total` des `foreach`, les items dessous (✓ done avec extrait de résultat · ⏳ en cours · ⏸ **attend ta réponse** avec champ inline « Répondre » (Entrée pour envoyer) · ⊝ sauté avec sa note · ✗ échec), les cas prévus du step, et la réponse passée affichée sur l'item traité (« ↳ Celle de Bordeaux »). Badge « N questions en attente » en tête. Auto-refresh 3 s pendant l'exécution (poll existant). Endpoint `GET /missions/{id}/structure` (outline de la spec — TOUS les steps, même futurs — + runs, un seul round-trip ; remplace `step-runs`). **Création depuis l'UI** : zone repliable « Mission structurée (YAML) » dans le modal Nouvelle mission, avec exemple canonique en placeholder — 422 listant toutes les erreurs si la spec est invalide. i18n FR/EN, `sw.js` v14→v15. *(2026-06-10)*

### Added (J3 — hook ask_user, le cœur du sprint)
- **La mission qui hésite pose sa question, et reprend sur la réponse.** Quand un handler `ask_user` parque un item : **notification multicanal** (event `mission_question` en fan-out sur toutes les sockets du user + push ntfy + DM Telegram si la mission vient de Telegram — chaque canal isolé, calqué sur `_notify_terminal`). Nouvel endpoint `POST /missions/{id}/step-runs/{step}/{item}/answer` (owner-scoped 404, 409 si l'item n'attend rien) : la réponse est stockée (`answer`, révision Alembic `0004`), l'item repasse `pending` avec tentatives remises à zéro, la mission redevient due **immédiatement**. Au tick suivant, le prompt acteur reçoit « RÉPONSE DE L'UTILISATEUR (à la question « … ») : … » avec `{{ item }}` substitué — le « mode chat fait à la main » de la prospection LinkedIn, automatisé. *(2026-06-10)*

### Added (J2 — exécuteur)
- **Les missions structurées s'exécutent.** Quand `spec_yaml` est présent : le plan **est** la spec (déterministe, zéro appel au planner LLM) ; un step `foreach` est étendu paresseusement en items (extraction LLM unique depuis l'output du step source, cap 200) avec une ligne `mission_step_runs` par item — un tick traite UN item ; l'acteur reçoit les edge-cases déclarés du step et le **protocole `EDGE_CASE:`** (« si tu rencontres un cas prévu, ne bricole pas : signale-le ») ; l'évaluateur applique le handler — `skip_with_note`/`resume_next` journalisent et avancent, `ask_user` parque l'item en `waiting_user` (ping + reprise = J3), `fail` termine franchement. **Jamais de replan** sur une mission spec (la spec est le contrat) ; échec répété d'un item sans `on_error` → skip automatique après 2 tentatives (vivacité garantie) ; terminaison **déterministe** (tous les steps done/skipped), plus de `all_done` LLM. Table `mission_step_runs` (révision Alembic `0003`, défensive) + `GET /missions/{id}/step-runs` (matière du viewer J4). Tout est gardé derrière `plan_json.from_spec` — zéro changement pour les missions legacy. *(2026-06-10)*

### Added
- **Sprint 4c J1 — format de mission structurée V2.** Fin du prompt-monolithe : une mission peut désormais être décrite en YAML (`steps` ordonnés avec instruction `do` en langage naturel, `foreach` itérant sur le résultat d'un step précédent via `{{ step.output }}` ou en texte libre, et **handlers d'edge-case par step** — `on_ambiguous`, `on_not_found`, `on_<cas_métier_libre>` — dont les actions forment un vocabulaire fermé : `ask_user("…")`, `skip_with_note("…")`, `resume_next`, `fail`). Ajouter un cas oublié = ajouter UNE ligne. Le parser (`services/mission_spec.py`) collecte **toutes** les erreurs en une passe, en français. Colonne `missions.spec_yaml` (NULL = mission legacy, rétrocompatibilité totale) via la **première vraie révision Alembic** (`0002_mission_spec_yaml`, défensive). API : `POST /missions` accepte `spec_yaml`, 422 avec la liste complète des erreurs ; validation aussi côté service (défense en profondeur pour Telegram/scheduler). *(2026-06-10)*

### Fixed
- **Adoption Alembic : stamp baseline puis upgrade (au lieu de stamp head).** Stamper `head` sur une base jamais vue aurait sauté les révisions post-baseline sur les bases **existantes** (colonne manquante à jamais) — corrigé avant la première vraie révision ; les migrations sont écrites défensives pour les installs fraîches. Également : `fileConfig(disable_existing_loggers=False)` dans `migrations/env.py` — le défaut aurait **éteint tous les loggers de l'application** à chaque boot. *(2026-06-10)*

---

## [1.16.0] — 2026-06-10 — Sprint 4b V3 J7+J8 : le générateur produit des outils io + revue admin du périmètre

### Added
- **J7 — le `tool_creator` génère le profil `io`.** Dernier verrou du pipeline V3 : le générateur ne produisait que du `pure`. Nouveau prompt système io qui enseigne le contrat sandbox (httpx vers les **domaines egress déclarés uniquement**, `get_secret()` injecté par le wrapper — jamais importé, jamais loggé —, deps bornées à httpx/bs4/lxml, fonction sync auto-contenue, pas de `call_tool`). Le prompt utilisateur embarque la **vraie ACL Squid** (`squid_allowed_domains()` parse `sandbox/squid.conf` — même source de vérité que le proxy au runtime) et les **labels Vault réellement provisionnés** du user. Validation via la chaîne 7 étages de J5 (`profile="io"`) + gate async `check_secrets_exist` : un label manquant déclenche une reformulation (labels disponibles re-listés), et s'il persiste le candidat est quand même persisté — la revue J8 l'affiche et le bind-time gate (J6.c.1) tient l'outil hors du LLM tant que le Vault n'est pas prêt. Persistance avec `tool_profile=io`. API : `POST /admin/learning/tool-creator/run` accepte `profile: "pure"|"io"` (défaut `pure`, rétrocompatible). *(2026-06-10)*
- **J8 — la revue admin expose le périmètre déclaré.** Promouvoir un outil io, c'est valider **aussi** son périmètre, pas seulement son code. `CandidateOut` porte `tool_profile` + les déclarations parsées (`v3_network_allow`, `v3_requires`, `v3_requires_secrets`) ; la page candidates affiche un badge `io` et un panneau « Périmètre déclaré » (chips domaines egress / dépendances / secrets Vault + rappel du canary HITL 10 appels). i18n FR/EN, `sw.js` bumpé v13→v14 (gotcha PWA). *(2026-06-10)*

### Notes
- Le pipeline V3 est désormais complet de bout en bout : génération io (J7) → validation 7 étages (J5) → revue admin du périmètre (J8) → promotion → bind agent (v1.15.0) → canary HITL → exécution sandbox avec audit per-call (J6). Activation : `LEARNED_PYTHON_TOOLS_IO_ENABLED=true`. Pour ouvrir un nouveau domaine egress : `sandbox/squid.conf` (ACL `allowed_domains`) + rebuild sandbox.

---

## [1.15.0] — 2026-06-10 — Sprint 4b V3 : intégration agent du pipeline io + canary HITL

### Added
- **L'agent peut enfin utiliser ses outils io auto-générés (Sprint 4b V3, intégration agent).** Le pipeline V3 (PRs #67-#71 : code_guard profil io, déclarations egress/secrets/deps, validation sandboxée, dispatch sandbox, secrets bag, audit per-call) était fonctionnellement complet mais **dormant** — l'agent n'appelait jamais `load_active_io_tools`. Les outils io rejoignent désormais les **deux coutures partagées** (`append_learned_tools` au bind, `merge_into_tool_map` au dispatch) : chat **et** missions en héritent sans câblage supplémentaire. Ordre déterministe : builtins > pure > io (un outil appris ne shadow jamais un builtin ; en collision pure/io, le pure in-process gagne). Toujours derrière `LEARNED_PYTHON_TOOLS_IO_ENABLED` (off par défaut) — zéro changement de comportement tant que le flag n'est pas posé. *(2026-06-10)*
- **Période canary HITL (design V3 §5.6).** Les outils io sont intrinsèquement plus risqués (egress réel, code auto-généré) : leurs **N premières invocations passent par HITL** (`LEARNED_IO_TOOLS_CANARY_CALLS`, défaut 10, 0 = off) avant que l'outil ne soit de confiance. Le compteur s'appuie sur la table d'audit `io_tool_dispatches` (une ligne par appel, déjà écrite par le dispatcher) — aucun nouvel état. **Fail-closed** : historique illisible → HITL conservé. Les consentements explicites (« autoriser pour cette tâche », « toujours autoriser ») restent honorés. *(2026-06-10)*

### Notes
- Reste pour la v1.16.0 : **J7** (le tool_creator génère du profil `io`) et **J8** (panneaux admin de revue egress/secrets/deps). Limitation connue : le canary HITL couvre le chemin chat (`tool_node`) ; les missions autonomes utilisent leur propre plancher HITL.

---

## [1.14.11] — 2026-06-10 — Phase 3 (lot 3) : Alembic + chemin Postgres documenté — **revue multi-utilisateurs SOLDÉE**

### Added
- **Alembic branché (B-4).** La dépendance existait depuis toujours sans échafaudage : toute évolution de schéma passait par `create_all` + des `ALTER TABLE` ad hoc aux exceptions avalées — drift silencieux modèle/DB (le bug `critic_run_at` : 676 erreurs en prod). Échafaudage complet (`alembic.ini`, `migrations/env.py` async branché sur `Base.metadata` + `settings.database_url`, baseline `0001_baseline` vide) + **intégration au boot** : les bases jamais vues sont stampées sur la baseline, les révisions postérieures appliquées par `upgrade head` (exécuté en thread, best-effort — un échec ne tue pas le boot). Règle d'équipe : les nouvelles colonnes passent par `alembic revision --autogenerate`, plus par `_safe_columns`. *(2026-06-10)*
- **Chemin PostgreSQL documenté (décision du 10 juin : opt-in, pas de migration par défaut).** Nouvelle section dans `docs/DEPLOYMENT.md` : pourquoi SQLite reste le bon défaut (5-10 actifs simultanés), ce que Postgres apporte/coûte, activation par `DATABASE_URL`, limites connues (checkpointer missions, mono-process). *(2026-06-10)*

### Fixed
- **Les `ALTER TABLE` ad hoc n'avalent plus toutes les exceptions (B-4 court terme).** Seul « duplicate column » est l'état nominal ; disque plein, lock ou faute de frappe SQL sont désormais **loggés** au lieu de produire du drift silencieux. *(2026-06-10)*

---

## [1.14.10] — 2026-06-10 — Phase 3 (lot 2) revue multi-utilisateurs : secrets chiffrés & ACL outils d'instance

### Security
- **Secrets d'instance chiffrés au repos (B-11).** Le flag `is_secret` de `system_config` ne faisait que masquer l'UI : le Google client_secret, les clés provider `api_key_*` et les `llm_instances.api_key` étaient **en clair dans SQLite** — une fuite du fichier (backup égaré, volume copié) exposait toutes les clés. Nouveau `services/secrets_at_rest.py` : AES-256-GCM, valeurs préfixées `enc:gcm:` (déchiffrement auto-descriptif, legacy en clair toléré), **migration de boot idempotente** qui chiffre l'existant en une passe. Clé maître : `ELY_SECRETS_KEY` (recommandé), sinon dérivée de `JWT_SECRET_KEY` via HKDF avec tag d'usage distinct. ⚠️ **Changer `JWT_SECRET_KEY` sans avoir posé `ELY_SECRETS_KEY` rendra les secrets chiffrés illisibles** (re-saisie des clés API nécessaire) — pose `ELY_SECRETS_KEY` dès maintenant. *(2026-06-10)*
- **Outils d'instance réservés au rôle admin (B-12).** Les hôtes SSH (`hosts.yaml`, clés montées) et les serveurs MCP (lancés avec les secrets `env_json` de l'admin) étaient invocables par **tout utilisateur** routé sur le bon domaine — avec l'identité et les credentials de l'admin. Nouveau `services/tool_acl.py` branché dans `tool_node` : `ssh_*` + outils MCP chargés → rôle `admin` requis (cache rôle TTL 60 s, fail-closed), refus propre restitué par l'agent. Une ACL per-user (façon `tool_policy_service` de la branche salvage) reste la cible si le besoin émerge. *(2026-06-10)*

---

## [1.14.9] — 2026-06-10 — Phase 3 (lot 1) revue multi-utilisateurs : invariants & observabilité

### Added
- **Verrou mono-process au boot (A-7).** L'architecture est mono-process par construction (HITL, ws_registry, schedulers, bots en RAM) — `--workers 2` ou deux conteneurs sur le même volume cassaient silencieusement au moins 8 composants (HITL split-brain, crons en double, Telegram 409, double tick de missions). L'hypothèse devient un **invariant vérifié** : `flock` exclusif sur `<db_dir>/.ely-singleton.lock` au démarrage, échec de boot explicite si déjà tenu. Échappatoire documentée : `ELY_ALLOW_MULTIPROCESS=true` (réservée à l'état externalisé). *(2026-06-10)*
- **`GET /health/deep`** — `/health` répondait « ok » avec une DB corrompue ou un Qdrant mort. La sonde profonde teste réellement les deux (timeout 5 s) et renvoie 503 + booléens en cas de dégradation. Exemptée du rate limit. *(2026-06-10)*
- **`GET /admin/metrics`** — photo instantanée de la charge du process (sockets WS par user, tâches de fond en vol, ticks missions, filtres PII actifs, caches, sessions navigateur) : de quoi répondre à « pourquoi c'est lent depuis 14 h » sans grep de logs Docker. Admin-only. *(2026-06-10)*

### Fixed
- **Sessions navigateur : TTL d'inactivité + relance auto de Chromium (B-17).** Chaque user qui touchait un tool `browser_*` gardait un BrowserContext Chromium résident **à vie** ; et si Chromium crashait, `is_available()` restait vrai et le browsing était cassé pour tous jusqu'au restart backend. Cron d'éviction (15 min d'inactivité, passage toutes les 10 min) + relance automatique du browser quand `new_context` échoue. *(2026-06-10)*
- **Pool de connexions dimensionné pour le chemin Postgres (B-5).** Le défaut SQLAlchemy (5+10) serait le premier goulot invisible après une migration : `pool_size=20`, `max_overflow=30`, `pool_pre_ping` (connexions mortes écartées après un restart du serveur PG). Sans effet sur SQLite. *(2026-06-10)*
- **Index payload Qdrant sur `user_id` (§4).** Toutes les recherches filtrent par `user_id`, mais sans index keyword Qdrant scanne le payload des candidats HNSW — chaque recherche ralentit pour tout le monde quand les collections grossissent (×N users). Index créé idempotent sur les 6 collections (appliqué aussi aux collections existantes au premier boot). *(2026-06-10)*

---

## [1.14.8] — 2026-06-10 — Phase 2 (lot 3b) revue multi-utilisateurs : caches LRU+TTL & rétention — **Phase 2 complète**

### Security
- **Vault PII unifié entre les canaux chat et voix.** `voice.py` maintenait son **propre** dict de `SecurityFilter` alors que `tool_node` dé-anonymise les arguments d'outils via le registre partagé `conversation_filters` : sur le canal vocal, les deux vaults divergeaient → un tool_call vocal contenant un placeholder partait avec le **littéral `[EMAIL_0]`** (la résurgence côté voix du bug Gmail du 2026-05-07). Une seule source de vérité désormais, épinglée par test (`voice._get_filter is conversation_filters.get_filter`). *(2026-06-10)*

### Fixed
- **Caches par-conversation : LRU + TTL d'inactivité au lieu du FIFO (B-7).** Quatre modules (`conversation_filters`, `frozen_memory`, `system_prompt_cache`, `fallback_manager`) dupliquaient le même `_BoundedDict` plafonné à 1000 entrées avec éviction **FIFO à l'insertion** : sous charge (~1000 conversations actives cumulées), l'entrée évincée était la plus *anciennement créée* — potentiellement une conversation **encore en cours** (vault PII détruit en pleine conversation = placeholders du contexte LLM irrésolubles ; état fallback perdu = retour silencieux au primary en panne). Nouveau `services/bounded_cache.BoundedLRUDict` partagé : chaque lecture rafraîchit l'entrée (l'éviction ne cible que la plus longtemps inactive) + TTL d'inactivité 24 h (expiration paresseuse). *(2026-06-10)*

### Added
- **Rétention des tables de signaux (§4).** Aucune politique n'existait : audit, usage et signaux learning croissent à chaque tour — N fois plus vite en multi-utilisateurs, et sur SQLite un gros fichier = checkpoints WAL plus longs = fenêtres de lock plus larges. Job quotidien 04:30 : `audit_logs`/`hitl_refusals`/`hallucination_blocks`/`provider_switches`/`error_logs` → `ELY_SIGNALS_RETENTION_DAYS` (90 j, 0 = off) ; `usage_logs` → `ELY_USAGE_RETENTION_DAYS` (365 j). Volontairement épargnés : messages/conversations, `mission_critiques` (bench mining), `failure_cases` (UI tool-gaps). *(2026-06-10)*

---

## [1.14.7] — 2026-06-10 — Phase 2 (lot 3a) revue multi-utilisateurs : budget LLM par utilisateur

### Added
- **Budget LLM quotidien par utilisateur, opt-in (A-6b).** Rien ne bornait la dépense cloud d'un user (ou d'un script avec un token volé) — c'est l'opérateur de l'instance qui paie. Nouveau `services/budget_guard.py` (inspiré du `budget_guard.py` Phase 5A de la branche salvage, dont le volet tracking est déjà couvert par `UsageLog.cost_usd`) : somme des coûts du jour (minuit UTC), refus au-delà de `ELY_USER_DAILY_BUDGET_USD`. **Désactivé par défaut (0)** — une install solo ne doit jamais s'auto-bloquer sur une table de prix heuristique ; les instances multi-utilisateurs l'activent via env. Application : chat et voice (refus doux avec message explicite), tâches planifiées (exécution du jour sautée, tâche préservée), missions (tick **reporté d'une heure** — un user temporairement à sec ne perd pas sa mission). Best-effort : une erreur DB ne bloque jamais un run. *(2026-06-10)*

### Fixed
- **Les coûts LLM background sont enfin comptés dans `UsageLog`.** Les résumés de fin de conversation (3 appels LLM à chaque déconnexion), l'extraction + consolidation mémoire et le critic de missions (cron 5 min sur tier cloud) n'appelaient pas `log_usage` : la facture réelle par user était sous-estimée précisément sur les chemins qui scalent avec le nombre d'utilisateurs — et le budget A-6b aurait été contournable par ces chemins. Nouveau helper `analytics_service.log_response_usage()` (extraction `usage_metadata` best-effort, no-op silencieux si le provider ne l'expose pas), branché sur les 4 sites. *(2026-06-10)*

---

## [1.14.6] — 2026-06-10 — Phase 2 (lot 2) revue multi-utilisateurs : équité entre utilisateurs

### Fixed
- **Le rate limit global est enfin branché (A-6a).** `RATE_LIMIT=60/minute` existait dans le compose et `settings.rate_limit` dans la config **depuis le début, sans jamais être relié au limiter** : seuls 3 endpoints d'auth étaient limités, tout le reste était illimité. `default_limits` + `SlowAPIMiddleware` appliquent désormais la limite à toutes les routes HTTP (multi-bornes acceptées : `120/minute,2000/hour`). `/health` est exempté (sondé par le healthcheck Docker — un 429 ferait flapper le conteneur). Les WebSockets ne sont pas concernés : leur débit est borné par B-15. *(2026-06-10)*
- **Cap de runs agent concurrents par utilisateur (B-15).** 1 user × 10 onglets = 10 runs LLM simultanés (coût cloud, RAM, contention) payés en latence par les autres. Nouveau `services/run_gate.py` : sémaphore par user (défaut 2, `ELY_MAX_AGENT_RUNS_PER_USER`), acquis par chat et voice — les runs excédentaires du même user font la queue sans impacter les autres. *(2026-06-10)*
- **Heartbeat missions : équitable et non bloquant (B-3).** Les missions étaient tickées séquentiellement sous un lock global : la mission lente d'un user (tick de 3 min) bloquait les missions de **tous** les autres, et le beat suivant était sauté tant que le précédent tournait (débit max théorique ~5 ticks/30 s, bien moins en pratique). Désormais : dispatch **round-robin par user** (un user avec 5 missions dues n'affame plus les autres), ticks en tâches de fond bornées par `MISSION_TICK_CONCURRENCY` (défaut 3), garde-fou `_in_flight` par mission (jamais deux ticks simultanés de la même mission), et le beat rend la main immédiatement. *(2026-06-10)*

---

## [1.14.5] — 2026-06-10 — Phase 2 (lot 1) revue multi-utilisateurs : hygiène disque & données

### Fixed
- **Connexions FTS hors-engine alignées sur les pragmas de l'engine (B-2).** Les deux stores FTS5 ouvraient des `aiosqlite.connect()` nus sur le même fichier que l'engine SQLAlchemy : 5 s de lock timeout (vs 30 s engine) et `synchronous=FULL`. Sous écrivains concurrents, une écriture d'index qui attendait > 5 s recevait `database is locked` — avalé par le « best-effort » — et **la ligne d'index FTS était perdue définitivement** : rappel mémoire et recherche de messages dégradés silencieusement, par user, de façon non reproductible. Nouveau helper `services/sqlite_aio.connect()` (timeout 30 s + `busy_timeout` + `NORMAL`), 11 sites migrés, test source-level anti-régression. *(2026-06-10)*
- **Voix Vivienne réellement active en Docker.** Le compose forçait `TTS_VOICE=${TTS_VOICE:-fr-FR-DeniseNeural}` — le défaut applicatif de la v1.14.2 était **écrasé silencieusement** quand `TTS_VOICE` n'était pas dans le `.env` hôte. Défaut compose aligné. *(2026-06-10)*

### Added
- **Backup SQLite nocturne (§4).** Qdrant était sauvegardé chaque nuit ; `cyberentity.db` — users, conversations, missions, signaux learning, la **vraie** source de vérité — jamais. Nouveau job 02:30 via `VACUUM INTO` (snapshot cohérent à chaud, les writers continuent) couvrant aussi `missions_checkpoints.sqlite`, rotation 7 j (`ELY_SQLITE_BACKUP_RETENTION_DAYS`), à destination du volume hôte déjà monté. *(2026-06-10)*
- **Uploads : volume persistant, quota par user, purge (B-9).** `/app/uploads` n'était pas monté — chaque rebuild perdait les fichiers et captures référencés dans l'historique des conversations (liens morts). Volume `./data/uploads` ajouté ; quota disque par user (500 Mo, `ELY_UPLOAD_QUOTA_MB`, 0 = off) vérifié à l'upload (413 au-delà, scan en thread) ; purge quotidienne 03:30 des fichiers > 90 j (`ELY_UPLOADS_RETENTION_DAYS`, 0 = off). *(2026-06-10)*
- **`mem_limit: 4g` sur le backend (B-16).** Seul service sans cap mémoire alors que c'est lui qui grossit avec N users (Whisper, fastembed, Chromium, clients WhatsApp par user) — risque de swap hôte qui dégrade LM Studio. *(2026-06-10)*

---

## [1.14.4] — 2026-06-10 — Phase 1 (lot 2) revue multi-utilisateurs : event loop & LLM local

### Fixed
- **`get_llm_for_tier` ne bloque plus l'event loop au cold start (B-1).** La branche de chargement paresseux des settings LLM faisait `fut.result(timeout=10)` depuis du code sync exécuté **sur** la loop : cache froid + premier appel = toute l'application gelée (tous les WebSockets, tous les users) jusqu'à 10 s — précisément au moment du rush post-redémarrage. Désormais : si une loop tourne, le chargement part en tâche de fond (référence forte via `spawn`) et le tour courant utilise les défauts ; hors loop (script `docker compose exec`, cron isolé), chargement synchrone comme avant. *(2026-06-10)*
- **Porte de concurrence devant le LLM local (A-5).** LM Studio/MLX ne sert qu'**une** requête à la fois : N requêtes simultanées (N users, ou chat + cron MAINTENANCE) s'empilaient côté serveur sans signal, chacune payant le prompt processing complet des précédentes jusqu'au timeout 900 s. Borne au niveau **transport** : `httpx.AsyncClient` partagé par base_url avec `max_connections=1` (env `LOCAL_LLM_MAX_CONCURRENCY`) — la file d'attente vit côté client, couvre `ainvoke`/`astream`/`bind_tools` sans wrapper. Même borne (`async_client_kwargs`) sur les chemins Ollama legacy. *(2026-06-10)*

---

## [1.14.3] — 2026-06-10 — Phase 1 (lot 1) revue multi-utilisateurs : fiabilité temps réel

### Fixed
- **`ws_registry` multi-sockets + bug des deux onglets (B-6).** Un user avec deux connexions (deux onglets, PWA + desktop, chat + voix) perdait des pushes : la 2ᵉ connexion *remplaçait* la 1ʳᵉ, et — pire — fermer l'ancien onglet désinscrivait la socket du nouveau (`pop(user_id)` aveugle), laissant l'utilisateur connecté mais injoignable (cartes HITL, résultats de tâches planifiées, alertes watchdog, frames navigateur). Registre `dict[str, set[WebSocket]]`, `unregister(user_id, ws)` ciblé, et fan-out `send_text_all()` avec purge des sockets mortes — adopté par hitl_manager, scheduler, watchdog et browser_skill. *(2026-06-10)*
- **Webhook Telegram : réponse immédiate + dédup par `update_id` (B-8).** Le traitement tournait inline — la réponse HTTP ne partait qu'après le run agent complet (souvent > 60 s) ; Telegram considérait le webhook en échec et **rejouait le même update** → agent exécuté 2-3× pour un message (actions et coûts dupliqués). Désormais : dédup bornée (1000 ids) puis traitement en tâche de fond, la route répond 200 instantanément. *(2026-06-10)*
- **Sandbox : concurrence bornée (B-10).** Aucune limite sur `/run` alors que chaque subprocess a droit à 256 Mio dans un conteneur plafonné à 512 Mio : deux runs gourmands simultanés (deux users) suffisaient à OOM-kill **le conteneur entier**, faisant échouer tous les runs de tous les users d'un coup. Sémaphore (défaut 2, env `ELY_SANDBOX_MAX_CONCURRENCY`) + file d'attente bornée 10 s puis 503 propre. *(2026-06-10)*
- **Backpressure sur le stream de tokens (B-14).** Un client lent ou zombie bloquait `websocket.send_text` par token, ce qui gelait la consommation du stream LLM (connexion provider maintenue ouverte, tokens facturés pour rien). Timeout d'envoi 10 s → socket traitée comme morte, sur les deux canaux chat et voix. *(2026-06-10)*
- **Fire-and-forget fiabilisé : `background_tasks.spawn()` (§4 mineurs).** 9 sites `asyncio.create_task(...)` sans référence forte (signaux learning, extraction mémoire, log usage, résumés de fin de conversation) pouvaient être garbage-collectés en vol sous pression mémoire — perte silencieuse. Module central avec registre de références fortes + log des exceptions (pattern repris de `sub_agents/factory.py`). *(2026-06-10)*

---

## [1.14.2] — 2026-06-10 — Phase 0 revue multi-utilisateurs : durcissement + voix Vivienne

### Security
- **PII : l'historique assistant du canal vocal est ré-anonymisé avant le LLM (B-13, revue 2026-06-10).** Le fix #55 (`4af483b`) couvrait le chat mais pas `/ws/voice` : les réponses passées de l'agent (stockées dé-anonymisées pour l'affichage) repartaient **en clair** vers les LLM cloud à chaque tour vocal — emails, téléphones inclus. Le canal vocal applique désormais le même `sf.anonymize(...)` que le chat (helper `_anonymized_history`, testé). *(2026-06-10)*
- **Headers de sécurité HTTP sur toutes les réponses backend (B-18/D1).** Nouveau middleware `app/middleware/security_headers.py` : `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, et `Strict-Transport-Security` quand le déploiement est HTTPS (`cookie_secure`). Pas de CSP (casserait Swagger UI pour zéro gain — les pages utilisateur sont servies par Next.js). *(2026-06-10)*
- **TTL des access tokens : 60 → 15 minutes par défaut (B-18/D2).** Les access tokens n'ont pas de `jti` et ne sont pas révocables — seule l'expiration borne un token volé (le logout ne blackliste que le refresh). Le refresh étant transparent côté frontend, on aligne sur la durée que `docs/architecture.md` documentait déjà. Override possible : `ACCESS_TOKEN_EXPIRE_MINUTES`. *(2026-06-10)*
- **Warning de démarrage si HTTPS sans `CORS_ORIGINS` explicite (B-18/M3).** Le runtime retombe sur `[frontend_url]` (pas un wildcard, donc pas bloquant — et les déploiements nginx même-origine ne déclenchent jamais le CORS), mais une allowlist explicite est la posture attendue en multi-utilisateurs. *(2026-06-10)*

### Fixed
- **Chemin SQLite par défaut ancré sur `backend/` (revue §4, mineur).** Le défaut relatif `./cyberentity.db` dépendait du cwd : lancé depuis la racine vs depuis `backend/`, le backend lisait/écrivait **deux bases divergentes** (constaté en réel le 9 juin : 798 Ko à la racine, 978 Ko dans backend/). Le défaut est désormais absolu ; toute `DATABASE_URL` explicite (Docker) passe inchangée. *(2026-06-10)*
- **`recursion_limit` du canal vocal aligné sur `CHAT_RECURSION_LIMIT`** au lieu d'un `100` codé en dur (divergence chat/voice, revue B-13). *(2026-06-10)*

### Changed
- **Voix TTS par défaut : `fr-FR-DeniseNeural` → `fr-FR-VivienneMultilingualNeural`.** Le réglage `settings.tts_voice` existait mais n'était **lu nulle part** — la voix restait épinglée sur Denise dans deux constantes séparées (`routers/tts.py`, `services/voice_service.py`). Les deux sont désormais câblées sur le setting (override : `TTS_VOICE`), et le défaut passe sur la voix multilingue HD, nettement plus naturelle. Retour utilisateur : « voix trop artificielle » → à re-tester. *(2026-06-10)*

---

## [1.14.1] — 2026-06-10 — Sécurité multi-utilisateurs Phase 0 : IDOR + Whisper

### Security
- **Conversation ownership enforced on the chat WebSocket (IDOR A-1, revue 2026-06-10).** The `/ws/chat` handler accepted any client-supplied `conversation_id` without checking it belongs to the authenticated user — any logged-in user could write into (and have the agent read from) another user's conversation by replaying its UUID, including the per-conversation PII vault and frozen-memory snapshot keyed by that id. A foreign or unknown id now closes the socket with code 4003, indistinguishable from "not found" (no existence oracle), mirroring `conversations._get_owned_conversation`. Regression-pinned by `tests/test_idor_conversation_ownership.py` (real WS round-trip). *(2026-06-10)*
- **Ownership check on `POST /api/me/state/recompute` (IDOR A-2, revue 2026-06-10).** The `conversation_id` query param was passed straight to `compute_user_state`, whose `_load_recent_messages` has no user filter — the MAINTENANCE LLM could read a foreign conversation. Foreign/unknown ids now 404 before any read. *(2026-06-10)*

### Fixed
- **faster-whisper moved off the event loop (A-4, revue 2026-06-10).** `model.transcribe(...)` was called synchronously inside async handlers (`/ws/voice` + `POST /api/transcribe`), freezing the whole backend (all websockets, mission heartbeats, webhooks) for the duration of each decode. Transcription now runs in `asyncio.to_thread` with the lazy segments generator consumed inside the worker thread, bounded by a shared `Semaphore(2)`. *(2026-06-10)*
- **`POST /api/transcribe` always returned 500.** The endpoint read `info.detected_language`, which does not exist on faster-whisper's `TranscriptionInfo` (real field: `language`) — every successful transcription crashed at response-build time. Latent since the endpoint was written; surfaced by the A-4 test pins. *(2026-06-10)*

### Changed
- `.gitignore` now excludes SQLite WAL/SHM sidecars (`*.db-wal`, `*.db-shm`) that appear when the backend runs outside Docker with the relative DB path. *(2026-06-10)*

---

## [1.1.2] — 2026-05-17 — Sprint 1: cross-conversation memory recall + agent hallucination hardening

Tagged release closing **Sprint 1 (Memory recall)** on the `feature/memory-recall` branch, plus everything else merged after `v1.1.0`. Two themes dominate this version:

1. **Memory recall**: ELY can now retrieve and summarise past conversations across the user's entire history, in pure prose, via a local Ministral 3B summariser (cost-marginal-zero). The agent calls it autonomously when the user says *« tu te souviens de… »*, *« on en était où… »*, *« mon médecin traitant… »*, etc.
2. **Anti-hallucination hardening**: a stricter RULE 0 covers all data-bearing tools (not just browser), plus six rules around calendar/timestamps/list-size/refusal-on-suspicion. Triggered by a live audit where DeepSeek fabricated four fictional corporate calendar events instead of calling `calendar_list_events`.

### Added (Sprint 1 — Memory recall, full pipeline)
- **`2fbef2b` — Phase 1: FTS5 messages index + auto-indexer + backfill.** New `MessagesFTSStore` sister to the existing `FTSStore` (which indexes extracted facts). Indexes the literal messages of every conversation behind a SQLAlchemy `after_insert` hook (fire-and-forget). Idempotent backfill script (`scripts/backfill_messages_fts.py`) ran on Franck's history: 1862/2468 messages indexed. 16 unit tests cover tokenizer, stop-words, prefix-match, accents, user isolation. *(2026-05-15)*
- **`2fbef2b` — Phase 2: `session_search.py` + Ministral 3B summariser.** FTS hits grouped by conversation, BM25-ranked, top-K loaded with their full transcript (truncated to 80k chars), summarised in parallel via `ComplexityTier.SIMPLE` (Ministral 3B local in the default routing). Cost: zero euros per call. Latency: ~5-10s for 3 conversations in parallel. 11 unit tests cover JSON extraction, prompt formatting, group-ranking, content normaliser. *(2026-05-15)*
- **`7577c3d` — Phase 3: `search_past_conversations_tool` registered as agent tool.** Exposed via `tool_sets.USER_ID_TOOLS` + `toolset_profiles._DEFAULT_TOOLS` + `memory_skill` registration. Default profile is now 65 tools (was 64). Tool docstring primes the LLM on WHEN to call (memory references) and WHEN NOT TO (current-turn-only queries → use `knowledge_search` or `memory_search` instead). *(2026-05-15)*
- **`eb08dd9` — Skill registry registration fix.** Tools in ELY are discovered through the global SkillRegistry at startup, not by import. The new tool was listed in `tool_sets.py` and `toolset_profiles.py` but never plugged into a skill — so the registry silently dropped it from the bind layer (64 tools instead of 65). Added a `memory_recall` skill registration next to `memgpt_memory` in `memory_skill.py`. Lesson written into the commit message for future contributors: define → register in a skill → list in toolset_profiles. *(2026-05-15)*

### Added (related infrastructure)
- **`5fe0410` indirectly** — Docker backend image now copies `backend/scripts/` so operational scripts (backfill, admin, migrations) can be invoked via `docker compose exec backend uv run --no-sync python scripts/<name>.py`. *(2026-05-15)*

### Fixed
- **`818c6ce` — Memory bridge: `search_past_conversations_tool` triggered by implicit personal-data references too.** Previously the prompt mentioned the tool only for explicit memory patterns (« tu te souviens », « on a parlé »). It didn't cover implicit references to personal data the user had previously shared (« mon médecin », « ma banque », « le projet sur lequel je travaille »). The agent broke the implicit contract « I told you once, you remember » and asked the user to repeat. Now the prompt explicitly lists these patterns and adds: *AVANT de dire « je n'ai pas cette information » ou de demander à l'utilisateur de te répéter quelque chose qu'il a déjà mentionné, FAIS UN search_past_conversations_tool.* *(2026-05-16)*
- **`45b01b5` — RULE 0: universal anti-hallucination data rule.** Live audit on 16 May: DeepSeek-v4-pro fabricated four corporate calendar events ("Point hebdo équipe", "Déjeuner avec Sarah", "Revue de code", "Session brainstorming") instead of calling `calendar_list_events`. The actual events were "Tennis de table", "Pictavino", "Festival Food Truck". The previous "Intégrité des actions" block only covered email/document CONTENT; structured LISTS like calendar events, contacts, scheduled tasks fell through. New RULE 0 added at the top of both `_SYSTEM_PROMPT_BASE` and `_SYSTEM_PROMPT_SLM`, applies to ALL tool families. Includes concrete forbidden examples copied from the audit. *(2026-05-16)*
- **`44ee987` — Tool output reshaped from Markdown structure to conversational prose.** Root cause of a multi-model JSON-leak bug: all tested cloud LLMs (DeepSeek, Haiku, Qwen, Mistral large, Kimi K2.6) re-encode structured tool outputs as JSON cards in their reply to the user. Only the local Ministral 3B respected the original Markdown. Instead of adding per-model regex filters in the response pipeline (technical debt + risk of side effects), the tool's output was redesigned: a single conversational paragraph with connectors ("D'abord", "Ensuite", "Et enfin"), no `### [N]` headings, no metadata italics, no fences. The structure that SCREAMED data is gone, so the calling LLM has no structural signal to re-encode. *(2026-05-16)*
- **`8fd5327` — Flatten nested structured summaries from Ministral 3B.** Ministral occasionally ignored the "summary must be a plain string" instruction and returned a JSON object like `{"rendez-vous_principaux": [...], "actions_pendantes": [...]}`. Excellent content, wrong shape. New `_flatten_to_summary(value)` helper recursively renders any value (str / number / list / dict / nested combinations) as a Markdown-bullet-list string instead of dropping the LLM's work. *(2026-05-15)*
- **`a8a4f5f` — Guard against non-string title/summary in parsed JSON.** Ministral 3B sometimes returns the title/summary fields as nested objects rather than plain strings. Coerce both through `_content_to_text` before calling `.strip()` instead of crashing. *(2026-05-15)*
- **`166d97d` — Tool-pair-aware context trimming.** The context manager used to drop messages from the head of the conversation when the token budget was exceeded, without checking that it didn't break a `tool_call ↔ tool_response` pair. DeepSeek (and every OpenAI-protocol provider) rejects orphan tool messages with `400 Bad Request`, which triggered the fallback chain down to weaker models. After the fix, trimming respects pairs: orphan `ToolMessage` in the head is skipped, dangling `AIMessage` with unanswered `tool_calls` in the tail is trimmed. *(2026-05-15)*
- **`a7bf15d` — Anti-hallucination prompt rules 5 & 6.** Mandatory temporal sanity-check before proposing any date (refuses to propose `Wednesday 13 May` when today is the 14th); explicit refusal threshold on lists with > 15-20 values at a regular interval (classic hallucination signature). *(2026-05-14)*
- **`596c329` — Pattern C: collapsed-UI handling.** Doctolib and similar SPAs render days as collapsible cards with the slots out of the DOM until you click the chevron. The agent now has a concrete recipe (read_html → identify chevron selector → click → wait_for_selector → read scoped) and a hard refusal rule when the same precise values appear for two distinct items (e.g. identical slots for two different days). *(2026-05-14)*
- **`e797e1a` — Anti-hallucination rules 1-4 + Pattern C bootstrap.** First version of the rules forbidding fabrication of precise values, vision-for-numerics misuse, and context-coherence violations. *(2026-05-14)*
- **`403c48d` — Revert needless LOCKED_HITL on `scheduler_delete_task`.** User-initiated deletion of their own scheduled tasks shouldn't require HITL confirmation — pure friction. The previous commit had added it "for safety" but `scheduler_delete_task` wasn't in `ALWAYS_CRITICAL_TOOLS` anyway, so the lock was a no-op with a misleading docstring. *(2026-05-14)*
- **`6423c29` — Expose scheduler list + delete to the default agent profile.** The tools existed but only `scheduler_create_task` was bound to the agent. Symptom: ELY would create scheduled tasks but answer "I have no tool to delete them" and resort to scheduling a cleanup task for tomorrow at 9am. Regression-guard test included. *(2026-05-14)*
- **`5a6b52a` — Chat bubble overflow + soft handling of structured tool outputs.** `MessageBubble.tsx` `<pre>` renderer used `overflow-x-auto` only, so a 500-char-line JSON dump forced a horizontal scrollbar across the chat. Added `whitespace-pre-wrap break-all` so long single-line dumps wrap inside the bubble. Inline tokens (URLs, hashes) also wrap. *(2026-05-15)*
- **`e5b1a2e` — Contrast fix on `/settings/extension`.** The amber "new token created" banner used `bg-amber-50` with default text colour, which rendered as light-grey-on-cream in dark mode — barely legible. Switched to theme-agnostic semi-transparent overlays. *(2026-05-14)*

### Changed
- Default `_DEFAULT_TOOLS` profile size: 64 → 65 tools (added `search_past_conversations_tool`).
- `LOCKED_HITL_TOOLS` no longer contains `scheduler_delete_task` (cf. `403c48d`).

### Docs
- **`cfc57d6` — CHANGELOG.md created** and bug-report template extended with HUD-model + tier dropdowns to make user reports actionable. *(2026-05-15)*
- **`e9e3553` — LinuxFr feedback addressed across docs.** ROADMAP.md reformulated to drop ambiguous "open-source" claims (we are source-available); `docs/security.md` gains a "Limites assumées de l'anonymisation déterministe" section (corpus-wide frequency attack, out-of-pattern PII, indirect inference, hash reversibility); `docs/installation.md` gains a chapter "8. Exposer ELY à l'extérieur" with three options (Tailscale → Caddy+Let's Encrypt → Cloudflare Tunnel) ranked by sovereignty; FAQ FR + EN clarified for non-profits (strict non-commercial = free, no paperwork). *(2026-05-15)*
- **`094f257` — Roadmap aligned with reality + MCP expanded.** Sprint 0.5 (Chrome extension) inserted between launch and memory-recall; Sprint 3.5 (Web Automation) reframed as complementary to the extension (batch use cases); Sprint 4 (MCP) expanded from a single line into four sub-items: 4.1 consume external MCP servers, 4.2 expose ELY as MCP server, 4.3 Settings UI, 4.4 OAuth manager. New `v1.1.2` row in the target versions table. *(2026-05-15)*

### Known limitations carried over
- **Cosmetic JSON leak after memory recall**: cloud LLMs re-encode the prose tool output as JSON cards in the user-facing reply. The content is correct, the form is noisy. Three rounds of fixes attempted (prompt rule, tool docstring, server-side regex filter), none held reliably. Accepted as cosmetic in this release; will be addressed properly in a future version via either a UI-side renderer for tool results, or a runtime bypass that delivers `search_past_conversations_tool` output directly without LLM reformat.
- **Gemini returns "internal error"** when used as the agent's primary tier. Untested but likely a message-format compatibility issue (Gemini is stricter than OpenAI-protocol providers about sequence ordering). Backlogged for a "Gemini compat" sprint.
- **GitHub Traffic stats not accessible to the agent**: when asked "how many clones on the ELY repo?", ELY answers with whatever it can find via web search (typically incorrect or zero). A dedicated `github_traffic_stats` tool is backlogged.
- **599 messages from the FTS backfill are orphan** (pre-existing conversations that were deleted but whose messages remained without a CASCADE). Acceptable for the current backfill since the missing data isn't catastrophic; `audit messages orphelins` is in the backlog.

---

## Pre-1.1.2 (entries previously listed under [Unreleased])

The bug fixes below predate Sprint 1 work and were rolled into this same v1.1.2 release for simplicity.

### Fixed
- **`166d97d` — Tool-pair-aware context trimming.** The context manager used to drop messages from the head of the conversation when the token budget was exceeded, without checking that it didn't break a `tool_call ↔ tool_response` pair. DeepSeek (and every OpenAI-protocol provider) rejects orphan tool messages with `400 Bad Request`, which triggered the fallback chain down to weaker models. After the fix, trimming respects pairs: orphan `ToolMessage` in the head is skipped, dangling `AIMessage` with unanswered `tool_calls` in the tail is trimmed. *(2026-05-15)*
- **`a7bf15d` — Anti-hallucination prompt rules 5 & 6.** Mandatory temporal sanity-check before proposing any date (refuses to propose `Wednesday 13 May` when today is the 14th); explicit refusal threshold on lists with > 15-20 values at a regular interval (classic hallucination signature). *(2026-05-14)*
- **`596c329` — Pattern C: collapsed-UI handling.** Doctolib and similar SPAs render days as collapsible cards with the slots out of the DOM until you click the chevron. The agent now has a concrete recipe (read_html → identify chevron selector → click → wait_for_selector → read scoped) and a hard refusal rule when the same precise values appear for two distinct items (e.g. identical slots for two different days). *(2026-05-14)*
- **`e797e1a` — Anti-hallucination rules 1-4 + Pattern C bootstrap.** First version of the rules forbidding fabrication of precise values, vision-for-numerics misuse, and context-coherence violations. *(2026-05-14)*
- **`403c48d` — Revert needless LOCKED_HITL on `scheduler_delete_task`.** User-initiated deletion of their own scheduled tasks shouldn't require HITL confirmation — pure friction. The previous commit had added it "for safety" but `scheduler_delete_task` wasn't in `ALWAYS_CRITICAL_TOOLS` anyway, so the lock was a no-op with a misleading docstring. *(2026-05-14)*
- **`6423c29` — Expose scheduler list + delete to the default agent profile.** The tools existed but only `scheduler_create_task` was bound to the agent. Symptom: ELY would create scheduled tasks but answer "I have no tool to delete them" and resort to scheduling a cleanup task for tomorrow at 9am. Regression-guard test included. *(2026-05-14)*
- **`e5b1a2e` — Contrast fix on `/settings/extension`.** The amber "new token created" banner used `bg-amber-50` with default text colour, which rendered as light-grey-on-cream in dark mode — barely legible. Switched to theme-agnostic semi-transparent overlays. *(2026-05-14)*

### Added
- **`6726b27` — Sprint 1: browser interactivity tools.** `browser_tab_click(selector)`, `browser_tab_fill(selector, value)`, `browser_tab_navigate(url)`. React-aware implementations (native value setter + dispatchEvent for controlled inputs; MouseEvent + native click for buttons). Trust model: agent only emits these on explicit user request, user sees the tab live in their own Chrome. Unlocks multi-step SPA workflows (Doctolib, SNCF, Booking, .gouv.fr forms). *(2026-05-14)*
- **`56acb6e` — Sprint 0.5: long-lived extension tokens.** New `ExtensionToken` model + REST CRUD `/api/extension/tokens` + dedicated Settings page. Format `ely_ext_<48 hex>` (192 bits of entropy). SHA-256 + last_4 stored; plaintext shown exactly once at creation, then never. Replaces the previous DevTools → Application → Local Storage → copy-JWT bidouille, and ends the every-60-min disconnection. Backwards compatible: the WS handshake still accepts legacy access JWTs. *(2026-05-14)*

### Docs
- **`166d97d` indirectly** — `docs/security.md` will be updated to call out the trim-boundary class of bugs in the next sweep.
- **`e9e3553` — LinuxFr feedback addressed across docs.** ROADMAP.md reformulated to drop ambiguous "open-source" claims (we are source-available); `docs/security.md` gains a "Limites assumées de l'anonymisation déterministe" section (corpus-wide frequency attack, out-of-pattern PII, indirect inference, hash reversibility); `docs/installation.md` gains a chapter "8. Exposer ELY à l'extérieur" with three options (Tailscale → Caddy+Let's Encrypt → Cloudflare Tunnel) ranked by sovereignty; FAQ FR + EN clarified for non-profits (strict non-commercial = free, no paperwork). *(2026-05-15)*
- **`094f257` — Roadmap aligned with reality + MCP expanded.** Sprint 0.5 (Chrome extension) inserted between launch and memory-recall; Sprint 3.5 (Web Automation) reframed as complementary to the extension (batch use cases); Sprint 4 (MCP) expanded from a single line into four sub-items: 4.1 consume external MCP servers, 4.2 expose ELY as MCP server, 4.3 Settings UI, 4.4 OAuth manager. New `v1.1.2` row in the target versions table. *(2026-05-15)*

---

## [1.1.0] — 2026-05-11 — Public launch

Initial public release on GitHub. The repository was opened from private to public on Wednesday 12 May 2026; the actual development had been ongoing since early March 2026 (200+ commits, see `git log` for the pre-launch history).

### Added (launch capabilities)
- **Multi-LLM routing** with tier A/B/C/IMG and per-conversation fallback chain. Default routing: Tier A = Ministral 3B local; Tier B = DeepSeek v4-flash → v4-pro → Qwen 3.6 Flash → Ministral; Tier C = DeepSeek v4-pro primary; Tier IMG = DeepSeek v4-flash. Configurable per-user in Settings → Routing.
- **Native PII anonymization** before any cloud LLM call — credit cards, emails, tokens, IBANs, French phone numbers, named entities via NER. Deterministic mapping within a session so the LLM can reason on relationships.
- **HITL gating** on every irreversible action (gmail_send_email, calendar_delete_event, drive_delete_file, ssh_execute, vault_unlock, plus 20+ others in `LOCKED_HITL_TOOLS`). Per-user preferences, force-locked for the most destructive operations.
- **Multi-channel access**: Web UI (Next.js, FR + EN), Telegram bot, Slack app, Discord bot, WhatsApp (via webhook), iOS PWA, Android FCM push.
- **374/374 pytest** tests passing at launch.
- **Sovereignty modes documented**: 100 % local (Ministral on user's Mac), 100 % EU (Mistral only), or mixed performant (DeepSeek + Mistral + anonymization).
- **`feat(extension): browser companion`** *(`71bcbc6`)* — Chrome extension Sprint 0: WebSocket handshake, tab listing, DOM read, screenshot. Foundation for Sprint 0.5 and Sprint 1 that landed three days later.
- **`feat(install): bullet-proof first-time install`** *(`5fe0410`)* — install audit on a fresh `/tmp/ely-fresh-test/` sandbox surfaced 10 bugs (Python 3 detection on Mac Sequoia, hardcoded ports, password policy not documented…); all fixed in this release.
- **`feat(ui): mobile hamburger drawer`** *(`a67aedd`)* — sidebar properly collapses on screens under 768 px instead of being truncated at 64 px wide.
- **`feat(dashboard): per-user stats opened to all users`** *(`236c1af`)* — every user can see their own LLM cost/usage breakdown, no longer admin-only.
- **`feat(prompt): RÈGLE INVIOLABLE anti-confabulation`** *(`ef9c047`)* — early version of the anti-hallucination guard for factual queries.
- **`feat(desktop): 9 filesystem tools`** *(`725ce7b`)* — ELY Desktop daemon exposes read + write filesystem tools, with HITL forced on destructive operations.

### Security
- **`chore(security): harden .gitignore before public launch`** *(`da3908d`)* — extra patterns to prevent accidental commit of `.env`, `credentials.json`, `*.p8`, `*.safetensors`, vault DB.

### Fixed (right before launch)
- **`fix(auth): clear stale tokens on login + fix SameSite mismatch`** *(`470700e`)* — fresh-install testing surfaced session-expired errors on new devices; root cause in cookie SameSite policy.
- **`fix(deepseek): auto-swap to deepseek-chat for multi-turn`** *(`dbdcd90`)* — `v4-flash` and `v4-pro` reject multi-turn tool_calls with HTTP 400 unless `thinking={"type": "disabled"}` is passed.
- **`fix(name): Ely canonical spelling`** *(`cc1f103`, `966a72a`)* — agreed in May 2026 to standardise on "Ely" (no accent), pronounced "Éli". All onboarding messages and HITL notifications now use the canonical form.

---

## Pre-1.1.0 — Private development (March-May 2026)

The 200+ commits from `2026-03-09` (repo created) to `2026-05-11` (public launch) are not individually listed here. Highlights:

- **Phase 1** *(March)* — Bot Telegram integration, HITL via inline buttons, session linking via `/link` command.
- **Phase 2** *(March)* — Scheduled tasks with APScheduler, natural-language cron creation ("rappelle-moi tous les lundis à 9h").
- **Phase 3** *(March)* — Hybrid memory: SQLite FTS5 for keyword + Qdrant for semantic, time-decay weighting, automatic fact extraction.
- **Phase 4** *(March)* — Skill registry (`@register` decorator), 11 builtin skills (system, gmail, calendar, drive, docs, sheets, tasks, scheduler, météo, actualités, traduction).
- **Phase 5** *(March-April)* — Server-side Playwright browser control with per-user isolation, 7 tools, HITL on click/fill.
- **Phase 1bis** *(April)* — Slack, Discord, WhatsApp channels; agentic RAG; CI/CD.
- **Phase 2bis** *(April)* — Security marketplace, audit logging, skills marketplace foundations.
- **Phase 3bis** *(April)* — Voice wake "Éli", WebSocket `/ws/voice`, iOS SwiftUI app.
- **Phase 4bis** *(April)* — Mode Arena (ELO), agentic RAG v2, PWA.
- **Hermes Chantier 1** *(2026-05-07)* — sticky toolset profile per conversation + 13 fixes — 198 tests.
- **Hermes Chantiers 2, 4, 9, 10 partial** *(2026-05-08)* — prompt cache + frozen memory, transparent fallback chain, iteration budget + force_summary, toast UI on provider.switched — 340 tests.
- **Sovereignty stack 100 % Mistral pivot** *(2026-05-09)* — abandoned xLAM-2 8B (tool-call confabulation), validated Ministral 3B local + Mistral Small 4 + Mistral Large 3.

For the full pre-launch history, see `git log --pretty=format:"%h %ai %s" --until="2026-05-11"`.

---

## Reporting a bug

ELY ships without telemetry — this is deliberate. We will not silently collect usage data, error reports, or any signal from your installation. The flip side: we can't see your bugs from here.

If you spot a regression or hallucination, please open an [issue](https://github.com/franckolv-dev/ElyAgent/issues/new?template=bug_report.yml) with the new bug-report template (it asks for the model shown in the HUD at the time of the bug — critical for fallback-chain diagnostics).

For security-sensitive issues, do **not** open a public issue. See [`SECURITY.md`](./SECURITY.md) and e-mail `contact@agent-ely.fr`.

---

## Versioning policy

ELY follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html), adapted to a self-hosted personal AI agent:

- **Major (`x`.0.0)** — breaking change to the user's data, configuration, or API surface. Example: v2.0 will ship the LoRA-personnel-par-user feature, which changes how the LLM is stored on disk.
- **Minor (1.`x`.0)** — new capabilities or sprints from the [roadmap](./ROADMAP.md), backwards-compatible.
- **Patch (1.1.`x`)** — bug fixes, documentation, security hardening; no behaviour change beyond fixing what was broken.

The roadmap target-versions table tracks which sprint lands in which version.
