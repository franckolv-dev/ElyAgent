# Architecture d'Ely

> Ce document décrit ce que le code fait **aujourd'hui**, mesuré le 30 juillet 2026.
> Il ne décrit pas d'intentions. Quand un chiffre est cité, il a été compté.

Ely — *Exactly Like You* — est un agent personnel auto-hébergé. Un seul agent,
un catalogue d'outils, une boucle qui vérifie son propre travail avant de rendre
la main.

---

## La règle qui gouverne le reste

Toute la conception découle d'une seule distinction, posée après un recadrage de
juillet 2026 :

| | Qui décide | Qui exécute | Contrôle |
|---|---|---|---|
| **Mécanique** — une seule réponse correcte | personne | Ely | vérification interne |
| **Jugement** — plusieurs réponses défendables | **le modèle** | Ely | boucle de conformité |
| **Acte engageant** — irréversible ou visible par un tiers | le modèle propose | Ely **après accord** | HITL |

Le test : *« Deux personnes compétentes, avec la même information, pourraient-elles
répondre différemment ? »* Non → mécanique. Oui → jugement.

Un modèle de langage ne peut pas agir sur le monde : il n'émet que du texte.
**C'est donc toujours Ely qui exécute** — contrainte physique, pas choix
d'architecture. Ce qu'elle ne doit pas faire, c'est *trancher un jugement* à
votre place avec des seuils codés d'avance.

Exemples tranchés : « archive les mails de plus de six mois » est **mécanique**
(la règle est dans la phrase) ; « nettoie ma boîte » est un **jugement** et
demande un accord ; « rendez-vous jeudi 14 h » est mécanique ; « cale un
déjeuner avec Gert » est un jugement, parce que ça dépend de ses habitudes.

---

## Le graphe d'exécution

Un seul agent. Pas de superviseur, pas de spécialistes : cette architecture a
existé et a été retirée après un banc A/B qui a donné l'avantage au mono-agent
sur les quatre critères retenus, dont la latence et la justesse du choix d'outil.

```
                    ┌───────────┐
      entrée ──────▶│   agent   │◀────────────┐
                    └─────┬─────┘             │
                          │                   │
         ┌────────────────┼───────────────┐   │
         ▼                ▼               ▼   │
    ┌─────────┐    ┌────────────┐   ┌────────────────┐
    │  tools  │    │   verify   │   │ force_summary  │
    └────┬────┘    └──────┬─────┘   └───────┬────────┘
         │                │                 │
         └────────────────┘                 ▼
          retour à agent                   fin
                     │
              conforme ─▶ fin
              écart nommé ─▶ agent
```

- **`agent`** — assemble le prompt, choisit d'appeler un outil ou de répondre.
- **`tools`** — exécute l'outil, puis rend systématiquement la main à `agent`.
- **`verify`** — confronte le résultat à la demande. Conforme → fin. Sinon,
  retour à `agent` **avec l'écart nommé**, pas avec un « recommence ».
- **`force_summary`** — sortie de secours quand le budget d'itérations est
  épuisé. Elle ne passe pas par `verify` : un tour à bout de course n'a rien à
  relancer.

Deux principes dans cette boucle :

- **Elle échoue ouvert.** Sans signal clair de non-conformité, on considère
  conforme et on rend la réponse. L'inverse ferait boucler sur un doute.
- **C'est le progrès qui borne, pas un compteur.** La relance ne continue que si
  les écarts reculent. Un compteur fixe a été mesuré mauvais.

---

## Les outils

**201 outils** avec les drapeaux par défaut — le compte reproductible. Deux
choses s'y ajoutent selon la configuration :

- **+10** si le client MCP est activé (`mcp_client_v2_enabled`, éteint par
  défaut) : `mcp_connect`, `mcp_call_tool`, `mcp_discover_tools`… soit les
  outils qui *gèrent* MCP ;
- **+N** pour chaque serveur MCP connecté, qui expose les siens sous la forme
  `mcp__serveur__outil`.

Les familles les plus fournies :

| Famille | Outils | Famille | Outils |
|---|---:|---|---:|
| `browser_*` | 23 | `system_*` | 7 |
| `gmail_*` | 21 | `docs_*` | 7 |
| `drive_*` | 14 | `trainer_*` | 7 |
| `calendar_*` | 10 | `notes_*` | 6 |
| `sheets_*` | 9 | `os_*` | 6 |
| `desktop_*` | 9 | `scheduler_*` | 5 |
| `tasks_*` | 8 | `memory_*` | 5 |
| `contacts_*` | 8 | `pdf_*`, `maps_*` | 4 |

### Deux familles pour le navigateur, et c'est voulu

- **`browser_*`** — Chromium headless piloté par Playwright, côté serveur.
  **Aucun cookie, aucune session.** Pour le web public.
- **`browser_tab_*`** — votre vrai Chrome, via l'extension. Vos sessions
  réelles. **Seul moyen d'atteindre ce qui est derrière une authentification** :
  sans elle, LinkedIn, l'interface Gmail ou vos commandes Amazon renvoient la
  page de connexion.

Ce n'est pas un doublon. Fusionner les deux supprimerait une capacité.

### Ce qui est envoyé au modèle

Le catalogue d'outils part dans le prompt à chaque tour, et il domine le
contexte. Deux mécanismes coexistent aujourd'hui :

- un **profil** — une liste blanche nommée, portée par la conversation
  (colonne `conversations.toolset_profile`), figée au premier tour pour
  préserver le cache de préfixe ;
- un **filtre par mots-clés**, utilisé quand la conversation n'a pas de profil.

Le profil `default` vaut désormais **tout le catalogue**. Il a longtemps été
une liste tenue à la main : conçue pour 25-35 noms, rafistolée un outil à la
fois, elle en comptait 84 tout en oubliant seize familles entières — Sheets,
Docs, PDF, Maps… Une conversation ne pouvait ni ouvrir un tableur ni lire un
PDF, y compris avec la conversion construite en juillet.

La bascule s'appuie sur un banc A/B : à demande et modèle identiques, la
justesse du choix d'outil est inchangée sur les cas déjà couverts, et les cas
auparavant hors d'atteinte passent de **0 % à 86,7 %**. Le gain n'est pas
« Ely y arrive enfin » — elle consultait l'annuaire — mais qu'elle y arrive
**du premier coup**.

⚠️ **Sauf sur les petites fenêtres.** Le catalogue complet pèse ~61 000 tokens
de descriptions ; la tête du tier IMAGE tourne en local sur une fenêtre de
65 536. Hors tier COMPLEX, un profil restreint (`compact`, la liste de 84)
reste donc branché. Le mécanisme de profil a été conservé exactement pour ça.

### Retrouver un outil : `find_tool`

C'est l'annuaire. Un **petit modèle local** lit un catalogue compact — un outil
par ligne — et choisit. Le choix du modèle fait la latence : mesuré, un modèle
de 9 milliards de paramètres met 8,9 s là où un modèle de la classe 4B met
1,1 s pour la même qualité de réponse. Réglable par `TOOL_SELECTOR_MODEL`.

Il échoue **ouvert** : au moindre doute — pas de modèle, panne, réponse
illisible — il rend la liste complète plutôt que de mentir par omission.

---

## Autorisation humaine (HITL)

Un outil demande votre accord si son nom figure dans l'une des deux listes de
garde, ou si le **contenu de ses arguments** déclenche une alerte.

```
garde par NOM       hitl_preferences.LOCKED_HITL_TOOLS
                  ∪ security_filter.ALWAYS_CRITICAL_TOOLS      → 46 outils
garde par CONTENU   security_filter._CRITICAL_KEYWORDS
                    (« supprimer », « virement », « checkout », « panier »…)
```

Trois règles à connaître :

1. **On échoue fermé.** Un outil non classé est traité comme engageant. Un faux
   positif coûte une question ; un faux négatif, un message parti.
2. **Une dispense n'est pas un reclassement.** Certains actes engageants sont
   dispensés d'accord avec une raison écrite — un clic dans Chrome n'est pas un
   engagement, remplir un formulaire n'est pas le soumettre. L'outil reste
   classé « engageant » : on sépare ce qu'il **est** de ce qui exige un accord.
3. ⚠️ **Une docstring n'est pas un garde-fou.** Une phrase du type « demander
   toujours confirmation » dans la documentation d'un outil est une consigne au
   modèle, pas un verrou. Ces phrases ont été retirées ; la garde seule décide.

---

## Mémoire

- **Mémoire typée** en base, avec promotion du court terme vers le long terme.
- **Recherche vectorielle** dans Qdrant, plus un index plein texte SQLite
  (FTS5) sur les messages.
- **Traces d'outils** : ce qu'un outil a produit — un chemin de fichier, par
  exemple — est persisté sous forme compacte et rechargé au tour suivant comme
  message système. ⚠️ Jamais comme message de rôle `tool` : l'API le rejette
  hors d'une séquence d'appel valide.
- **Profil utilisateur** : environ 238 clés stockées, une quinzaine injectées
  par tour.

---

## Compétences apprises

Une compétence naît d'un **succès conforme après reprise** : Ely a échoué, a
nommé l'écart, a corrigé, et le résultat a passé la vérification. La procédure
est rédigée par le modèle principal, en état **candidate**, et attend une
validation avant de devenir active.

Les compétences actives sont listées dans le prompt et leur procédure est
**chargée** à la demande via `skill_view`.

Un outil n'est fabriqué que si la demande exige une **action** — toucher un
fichier, une API, un service. Sinon c'est une compétence. Ce tri est fait par un
modèle local.

La validation d'une compétence passe par un bac à sable de sous-processus, avec
environnement réduit et suppression du groupe de processus complet en fin de
course (`services/env_filter.py`).

---

## Souveraineté et données personnelles

Avant tout appel à un modèle **hébergé chez un tiers**, les données
personnelles sont remplacées par des marqueurs stables : la même adresse mail
devient le même `<EMAIL_3>` d'un bout à l'autre de la conversation, et la
réponse est dé-anonymisée au retour. La détection repose sur des expressions
régulières ; la couche de reconnaissance d'entités par modèle est désactivée.

Un appel à un modèle **local** ne passe pas par là : rien ne sort de la machine.

---

## Modèles

Le routage et les clés sont une **configuration d'administration**, héritée par
tous les comptes — jamais un réglage par utilisateur.

Quatre chaînes, chacune avec ses replis :

| Chaîne | Usage |
|---|---|
| `simple` | tours courts, modèle local d'abord |
| `medium` | usage courant |
| `complex` | raisonnement, outils |
| `maintenance` | tâches de fond (extraction de faits, résumés) |

⚠️ **Mesuré** : `medium` et `complex` démarrent sur le même modèle. Router entre
les deux ne change rien.

**Escalade par panel** : quand le progrès s'arrête — pas après N tentatives —
la demande part à deux ou trois modèles, et la meilleure réponse est retenue,
avec sa provenance et son coût annoncés. Le panel améliore une **réponse**, pas
le résultat d'un outil : il n'a pas d'outils.

### La voie locale, et son unique porte

Quand `SLM_ENABLED` est vrai, un routeur note la demande de 0 à 100 et envoie
au modèle **local** tout ce qui passe sous `SLM_COMPLEXITY_THRESHOLD`.

⚠️ **Cette voie ne reçoit pas le catalogue** — seulement `find_tool` et
`report_missing_capability` (`_SLM_TOOL_NAMES`). Ce n'est pas un oubli : livrer
le catalogue entier à un modèle de 4 milliards de paramètres faisait dépasser
60 s sur « bonjour », donc repli cloud systématique. La voie rapide s'annulait
elle-même.

👉 Conséquence à connaître avant de toucher au prompt local : **`find_tool` est
la seule porte** entre le modèle local et tout le reste — la météo, l'agenda,
les mails, la recherche web. Un prompt qui ne l'annonce pas laisse le modèle
conclure de bonne foi qu'il ne sait rien faire, puisque de son point de vue
c'est vrai. Les outils qu'il découvre ainsi sont liés au tour suivant, comme
sur la voie cloud.

Et si le local dépasse son délai, le repli vers le cloud **s'affiche** — c'est
l'invariant « un repli doit se voir ».

---

## Surfaces

| Surface | Détail |
|---|---|
| Web | Next.js, port 3000 |
| API | FastAPI, port 8000 |
| Canaux | Telegram, Slack, Discord, WhatsApp |
| Voix | WebSocket |
| Extension Chrome | pilotage de votre vrai navigateur |
| Bureau | application dédiée |
| Mobile | archivé le 02/09/2026 — voir [archive/README.md](../archive/README.md) |
| MCP | Ely est **client** (`mcp__serveur__outil`) **et serveur** (`/api/mcp`) |

Les cinq surfaces conversationnelles passent par le **même** runtime que le chat
web : mêmes outils appris, même mémoire, mêmes préférences.

---

## Services

```
backend        FastAPI + LangGraph
frontend       Next.js
nginx          entrée HTTP, port 80
qdrant         mémoire vectorielle, port 6333
sandbox        exécution isolée
egress-proxy   Squid — filtre les sorties réseau du bac à sable
```

**Base de données** : SQLite, `data/db/cyberentity.db`, monté dans le conteneur
sur `/app/data`.

⚠️ **Le schéma a une seule autorité : Alembic.** Les tables manquantes sont
créées au démarrage, mais **aucune évolution de table existante** ne se fait
ailleurs que dans une révision. Un second chemin de migration laisse le schéma
diverger en silence — ça s'est produit, et ça a coûté des centaines d'erreurs
en production.

---

## Journal réversible

Les actions qui modifient quelque chose sont journalisées avec de quoi les
défaire. Les outils d'annulation ne sont branchés au catalogue que si le drapeau
correspondant est actif — sinon ils ne coûtent rien en contexte.

---

## Missions autonomes

Une mission tourne sans vous. Son **mandat** — ce qu'elle peut faire seule, ce
qui reste sous accord — se déclare dans son fichier YAML. Le noyau interdit
reste verrouillé même sous mandat autonome.

Les tâches planifiées utilisent un graphe plat, sans boucle de vérification :
un travail programmé n'a personne à qui demander une précision.

---

## Voir aussi

- [installation.md](installation.md) — installer et configurer
- [guide-utilisateur.md](guide-utilisateur.md) — s'en servir au quotidien
- `.env.example` — la référence de configuration, annotée
