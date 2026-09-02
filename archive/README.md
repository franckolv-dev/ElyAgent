# Archive

Code retiré de la surface active du dépôt mais conservé dans l'historique. Rien
ici n'est compilé, testé ni déployé : aucune CI ne le regarde, aucun Dockerfile
ne le copie. Ce fichier explique pourquoi, pour qu'un retour en arrière soit une
décision et non une fouille.

---

## `mobile/` — applications Android et iOS

Archivées le **2026-09-02**.

### Ce que contient le dossier

| Chemin | Contenu | Dernier commit |
|---|---|---|
| `mobile/android/` | Application Android complète (Kotlin, Compose, Hilt, Room), 6 180 lignes de Kotlin | 2026-04-26 (`21aeae1`) |
| `mobile/android-racine/` | Second arbre Android, qui vivait à la **racine** du dépôt (`app/`, `gradle/`, `gradlew`, `build.gradle.kts`, `settings.gradle.kts`, `gradle.properties`), 2 667 lignes de Kotlin | 2026-03-25 (`14d9ae9`) |
| `mobile/ios/` | Application iOS (SwiftUI), 3 295 lignes de Swift | 2026-04-26 (`21aeae1`) |

### Pourquoi

**1. Usage mesuré à zéro.** Sur les cinq mois d'historique de production, aucune
des deux applications n'a produit un seul appel. Ce n'est pas un usage faible :
c'est l'absence d'usage.

**2. Deux arbres Android en double.** `android/` et l'arbre de la racine
déclaraient tous deux `rootProject.name = "ElyAgent"`, et **aucun des deux n'est
un sur-ensemble de l'autre** :

- présent seulement dans `android/` : `core/fcm/FcmTokenManager.kt`, le module
  `core/files/` (4 fichiers), `ConversationsApi.kt`, `LinkifiedText.kt`, et
  l'écran `ui/files/` (2 fichiers) ;
- présent seulement à la racine : `BaseUrlInterceptor.kt` (là où l'autre a
  `DynamicUrlInterceptor.kt`), `SkillUpdateRequest.kt`, et le composant
  `ui/components/avatar/` (2 fichiers).

Un mois sépare leurs derniers commits. Personne ne savait lequel faisait foi, et
une fusion demande un arbitrage fichier par fichier, pas un `rm -rf`.

**3. iOS ne compilait pas.** Aucun `.xcodeproj`, `.pbxproj`, `.xcworkspace` ni
`Package.swift` n'a jamais été commité. Les 3 295 lignes de Swift ne sont donc
adossées à aucun projet buildable : le dossier était du texte, pas un logiciel.

**4. Dérive du protocole WebSocket.** Le backend a évolué, pas les clients :

- `{"type": "done"}` est envoyé par `backend/app/routers/chat.py` depuis le
  **2026-05-23** (`ac1127e`) pour déverrouiller la saisie en fin de tour.
  Aucun des trois clients ne le connaît — leur champ de saisie resterait
  bloqué après chaque réponse.
- Sur `{"type": "error", ...}`, le backend met le texte dans la clé
  **`content`**. Les deux adaptateurs Kotlin lisent `json.optString("message")`
  et `WSMessage.swift` lit `json["message"]`. Résultat : bandeau d'erreur vide
  côté Android, « Erreur inconnue » côté iOS — jamais la vraie cause.
- `{"type": "stopped"}` est traité par iOS mais ignoré par les deux clients
  Android.

Les applications étaient donc doublement mortes : personne ne les lançait, et
elles n'auraient plus fonctionné correctement si quelqu'un l'avait fait.

### Ce qu'il faudrait faire pour les réveiller

Dans cet ordre, avant toute nouvelle fonctionnalité :

1. **Choisir un seul arbre Android.** Comparer `mobile/android/` et
   `mobile/android-racine/`, fusionner ce qui doit l'être, supprimer l'autre.
   Le second doit remonter au niveau de `mobile/` s'il gagne, pas revenir à la
   racine du dépôt : deux `settings.gradle.kts` concurrents sont la cause
   première de la confusion.
2. **Committer un projet Xcode** pour iOS (`.xcodeproj` ou `Package.swift`).
   Tant qu'il n'existe pas, le code Swift n'est pas vérifiable.
3. **Traiter `done` et `stopped`** dans les trois clients WebSocket, sinon la
   saisie reste verrouillée après la première réponse.
4. **Corriger la clé d'erreur** : lire `content`, pas `message`.
5. **Rejouer l'inventaire du protocole** contre `backend/app/routers/chat.py` et
   `voice.py` — les trois écarts listés plus haut sont ceux repérés le
   2026-09-02, pas une garantie d'exhaustivité pour une reprise ultérieure.
6. **Brancher une CI** (au minimum `./gradlew assembleDebug`), sans quoi la
   dérive recommencera au premier commit backend suivant.

### Revenir en arrière

L'historique est intact : les fichiers ont été déplacés avec `git mv`, donc
`git log --follow` sur n'importe lequel d'entre eux remonte avant l'archivage.
Pour restaurer un arbre, un `git mv` en sens inverse suffit ; penser alors à
remettre les motifs `.gitignore` correspondants (artefacts Gradle,
`local.properties`, `google-services.json`) sur le chemin restauré.

---

## `canaux/` — ponts WhatsApp, Slack et Discord

Archivés le **2026-09-02**.

### Ce que contient le dossier

| Chemin (sous `canaux/`) | Contenu | Lignes | Dernier commit |
|---|---|---|---|
| `backend/app/channels/whatsapp.py` | Pont WhatsApp Meta Cloud API (webhook entrant + envoi) | 333 | 2026-09-02 (`af7cd82`) |
| `backend/app/channels/whatsapp_web.py` | Pont WhatsApp Web non officiel (neonize/whatsmeow, appairage par QR) | 484 | 2026-05-28 (`2b37455`) |
| `backend/app/routers/whatsapp_webhook.py` | Routes `/api/whatsapp/*` (webhook Meta + liaison de compte) | 157 | 2026-09-02 (`5a91340`) |
| `backend/app/routers/whatsapp_web.py` | Routes `/api/whatsapp-web/session/*` (QR, code d'appairage, logout) | 97 | 2026-05-28 (`2b37455`) |
| `backend/app/agent/tools/whatsapp_tool.py` | Outils sortants `whatsapp_send` / `whatsapp_send_template` | 151 | 2026-06-28 (`df754bd`) |
| `backend/app/skills/builtin/whatsapp_skill.py` | Compétence qui enregistrait ces deux outils | 40 | 2026-06-28 (`df754bd`) |
| `backend/app/channels/slack_bot.py` | Bot Slack (Socket Mode, Block Kit) | 515 | 2026-07-25 (`9cf718a`) |
| `backend/app/channels/discord_bot.py` | Bot Discord (DM + réactions) | 493 | 2026-07-25 (`9cf718a`) |
| `backend/tests/test_whatsapp_runs_on_the_unified_runtime.py` | Tests du pont WhatsApp | 283 | — |

### Pourquoi

**1. Usage mesuré à zéro.** Sur les cinq mois d'historique de production, les
appels de modèle se répartissent ainsi par canal :

```
fond      7 277        tier S    207
web       1 994        ntfy      154
missions  1 494        planifié  151
                       Telegram    3
WhatsApp 0 · Slack 0 · Discord 0
```

Telegram, qui reste, a servi trois fois. Les trois autres, jamais. Ce n'est pas
un usage faible : c'est l'absence d'usage, sur quatre surfaces (deux ponts
WhatsApp, un bot Slack, un bot Discord) qui coûtaient chacune un démarrage, un
arrêt, un formulaire de réglages et une entrée de configuration.

**2. WhatsApp n'a jamais pu émettre non plus.** Le `.env` de production ne porte
aucune des quatre variables `WHATSAPP_*`. L'outil sortant `whatsapp_send`, lui,
lit `get_settings()` et rien d'autre : à chaque appel il répondait « WhatsApp non
configuré ». Il était donc annoncé au modèle dans le catalogue d'outils sans
pouvoir aboutir — un outil injoignable annoncé est pire qu'un outil absent, il
fait promettre une action qui n'arrivera pas. C'est pourquoi l'outil et sa
compétence partent avec les ponts, alors que la mesure ne portait que sur le
canal entrant.

**3. Discord et Slack ne notifiaient rien.** `hitl_manager` calculait
`send_discord` et `send_slack` dans son éventail de notification et les comptait
dans son journal (`fan-out=N`), mais **aucune fonction d'envoi n'existait** :
les commentaires du code disaient déjà « currently no-op until `_send_discord` ».
Une préférence HITL posée sur l'un des deux rendait donc l'utilisateur
silencieusement injoignable.

⚠️ **Ce retrait a d'abord été mal décrit ici** (relecture du 02/09/2026). Il
était écrit qu'une préférence orpheline « retombait sur `all` ». Elle ne
retombait sur rien : `request_validation` lisait la colonne brute sans jamais
la confronter à la liste blanche, et seul le `GET /api/hitl/channel`
normalisait — de l'affichage. Un compte resté sur « discord » sortait donc avec
un éventail VIDE, prévenu par le seul WebSocket ; sur un chemin sans navigateur
(mission, tâche planifiée) il n'était prévenu par rien et la demande expirait
en auto-refus. La normalisation vit maintenant dans
`app/services/hitl_channels.py` et s'applique À LA LECTURE des deux côtés :
une valeur orpheline vaut « all », donc Telegram + ntfy + Android.

**4. neonize emportait un contournement du lockfile.** La bibliothèque du pont
WhatsApp Web exigeait `protobuf >= 6.32`, en conflit avec
`google-generativeai` (épinglé `protobuf < 5`, toujours utilisé pour
Imagen/Vision). Le `Dockerfile` réglait ça par un
`uv pip install --force-reinstall` **après** `uv sync --frozen` : l'image
tournait donc sur un environnement que `uv.lock` ne décrivait pas, et le
`--no-sync` du `CMD` existait pour empêcher uvicorn de « réparer » cet écart.
Le `uv pip install --force-reinstall` part avec la dépendance ; le `--no-sync`
du `CMD`, lui, **reste** — il sert aussi à l'install opt-in de `gliner`
(PII NER), posée hors lockfile (voir `backend/Dockerfile` lignes 94-97).
`libmagic1` quitte l'image du même
coup : `python-magic` n'y entrait que comme dépendance transitive de neonize,
et `app/` ne fait aucun `import magic`.

### Ce qu'il faudrait faire pour les réveiller

1. **Trancher le doublon WhatsApp avant tout.** Deux ponts pour un seul service,
   avec deux modèles d'authentification (jeton Meta d'un côté, appairage QR par
   utilisateur de l'autre), deux jeux de routes et deux endroits où l'état de
   liaison vivait. Aucun des deux n'était un sur-ensemble de l'autre. En
   ressusciter un signifie choisir lequel, pas restaurer le dossier.
2. **Écrire `_send_discord` / `_send_slack`** avant de remettre ces valeurs dans
   `ALLOWED_CHANNELS` (`app/services/hitl_channels.py`). Une préférence proposée
   sans chemin d'envoi est un piège, pas une fonctionnalité — c'est exactement
   le défaut décrit plus haut (« Discord et Slack ne notifiaient rien »). Le pin
   `test_chaque_canal_de_la_liste_blanche_a_un_envoyeur`
   (`backend/tests/test_canaux_sans_usage_retires.py`) échoue tant que
   l'envoyeur manque.
3. **Rétablir la livraison du planificateur** dans `_deliver_result`
   (`app/services/scheduler.py`) : les branches `whatsapp` / `discord` / `slack`
   sont parties. Une tâche encore enregistrée sur l'un de ces canaux n'est pas
   perdue pour autant — un canal inconnu retombe sur le repli web, qui persiste
   toujours le résultat dans la conversation `[Tâches planifiées]`.
4. **Remettre les colonnes de liaison** `users.whatsapp_phone`, `users.slack_id`
   et `users.discord_id` dans `app/models/user.py`. Elles existent encore dans
   les bases DÉJÀ déployées (aucune migration ne les supprime) mais ne sont plus
   mappées : une base fraîche ne les créera pas.
5. **Rejouer le conflit protobuf** si neonize revient — ou migrer d'abord
   `image_tool.py` / `vision_skill.py` / `image_skill.py` vers le SDK
   `google-genai`, qui accepte protobuf 6. Le contournement du Dockerfile ne
   doit pas être recopié tel quel.

---

## `arena/` — comparateur de modèles en aveugle (ELO)

Archivée le **2026-09-02**.

### Ce que contient le dossier

| Chemin (sous `arena/`) | Contenu | Lignes | Dernier commit |
|---|---|---|---|
| `backend/app/routers/arena.py` | Cinq routes `/api/arena/*` (match, vote, classement, historique, modèles) | 135 | 2026-06-28 (`df754bd`) |
| `backend/app/services/arena_service.py` | Duel de deux modèles + mise à jour ELO (K=32) | 386 | 2026-06-28 (`df754bd`) |
| `backend/app/models/arena.py` | Tables `arena_match` et `arena_elo` | 77 | 2026-06-28 (`df754bd`) |
| `backend/tests/test_arena_service.py` | Tests du service | 203 | — |
| `frontend/src/app/arena/page.tsx` | Page `/arena` (duel + classement) | 276 | 2026-06-28 (`df754bd`) |

### Pourquoi

**Six matchs en cinq mois**, et trois lignes de classement. Le classement ELO
n'était lu **nulle part ailleurs** dans le backend : il ne pilotait aucun
routage, aucun choix de modèle, aucune décision. C'était un jouet de mesure dont
personne ne lisait la mesure.

⚠️ **Deux décisions du même jour se suivent, elles ne se contredisent pas.**
Quelques heures avant cet archivage, l'Arena a été *rebranchée* dans la barre
latérale : sa page était livrée, ses routes répondaient, mais aucun lien n'y
menait — un défaut réel, et la bonne correction pour ce défaut-là. La question
posée ensuite est différente : non plus « la page est-elle atteignable ? » mais
« sert-elle ? ». Six matchs répondent non.

⚠️ **Les tables restent en base.** `arena_match` et `arena_elo` ne sont plus
dans `Base.metadata` — une base fraîche ne les créera pas — mais **aucune
migration ne les supprime des bases déjà déployées**. Effacer des données
utilisateur est une décision à prendre séparément, pas un effet de bord d'un
ménage de code.

### Ce qu'il faudrait faire pour la réveiller

1. `git mv` en sens inverse, puis remettre `from app.models import arena` dans
   `app/models/__init__.py` (sinon `create_all` ignore les tables) et
   `app.include_router(arena_router.router)` dans `app/main.py`.
2. Remettre l'entrée `{ href: "/arena", labelKey: "navArena", icon: Swords }`
   dans `frontend/src/components/layout/nav.ts`, ses clés `sidebar.navArena` et
   le bloc `arena` dans **les deux** catalogues `frontend/messages/*.json` — le
   test de parité fr/en échoue si un seul des deux bouge — et les cinq appels
   `arena*` dans `frontend/src/lib/api.ts`. Remettre aussi le raccourci
   `{ "name": "Arena", "url": "/arena" }` dans `frontend/public/manifest.json` :
   il en est parti le 02/09/2026 parce qu'un appui long sur l'icône installée
   menait à un 404. Sans lui, un réveil mécanique laisse le raccourci absent
   dans l'autre sens.
3. Se demander d'abord **qui lira le classement**. Tant que la réponse est
   « personne », le réveil ne fera que rouvrir le même dossier.
