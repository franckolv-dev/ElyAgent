<!-- English: README.md -->

# Ely

**Exactly Like You** — un agent personnel auto-hébergé qui agit, vérifie son
propre travail, et demande avant de vous engager.

Ely est un **projet personnel non commercial**, publié sous Elastic License 2.0.
Usage personnel et professionnel interne libres ; la revente comme service
hébergé n'est pas autorisée.

---

## L'idée

La plupart des assistants soit répondent à des questions, soit partent en roue
libre. Ely place la frontière ailleurs — non pas entre *parler* et *faire*, mais
entre trois natures de décision :

| | Qui décide | Qui exécute | Contrôle |
|---|---|---|---|
| **Mécanique** — une seule réponse correcte | personne | Ely | vérification interne |
| **Jugement** — plusieurs réponses défendables | **le modèle** | Ely | boucle de conformité |
| **Acte engageant** — irréversible ou visible par un tiers | le modèle propose | Ely **après accord** | validation humaine |

Le test : *deux personnes compétentes, avec la même information,
répondraient-elles différemment ?* Non → mécanique. Oui → jugement.

Un modèle de langage ne peut pas agir sur le monde : il n'émet que du texte.
C'est donc **toujours Ely qui exécute** — contrainte physique, pas choix
d'architecture. Ce qu'elle ne doit pas faire, c'est **trancher un jugement à
votre place** avec des seuils codés d'avance.

« Archive les mails de plus de six mois » est mécanique : la règle est dans la
phrase. « Nettoie ma boîte » est un jugement, et demande votre avis.

---

## Ce qui tourne

Un seul agent. Pas de superviseur, pas de spécialistes : cette architecture a
existé et a été retirée après un banc A/B qui a donné l'avantage au mono-agent
sur les quatre critères mesurés, latence et justesse du choix d'outil comprises.

```
entrée ──▶ agent ──▶ tools ──▶ retour à agent
              │
              ├──▶ verify ──▶ conforme ? fin : retour à agent avec l'écart nommé
              └──▶ force_summary ──▶ fin   (budget d'itérations épuisé)
```

La boucle **échoue ouvert** — sans signal clair de non-conformité elle rend la
réponse plutôt que de tourner en rond — et **c'est le progrès qui la borne, pas
un compteur** : une relance ne continue que tant que les écarts reculent.

Le modèle qui répond est choisi par une **fonction pure**, pas par un modèle :
une demande est soit une image, soit une demande ordinaire, et le tier suit. Ce
routage était un appel de modèle ; il a été retiré, mesures à l'appui — il
dégradait les demandes et débranchait les outils qu'il jugeait inutiles.

**Un petit modèle local porte le travail de fond.** Pas la réponse qui vous est
faite : le travail autour. Lire l'annuaire des outils (196 descriptions, environ
une seconde), extraire d'un tour les faits qui méritent d'être retenus, résumer,
éprouver une compétence candidate. Il tourne sur votre machine, ne coûte rien à
l'appel, et rien de ce trafic ne sort. Le choix du modèle n'y est pas cosmétique :
sur la même tâche d'annuaire, deux d'entre eux sortent 4/4 — l'un en 1,1 s,
l'autre en 8,9 s.

---

## Ce qu'elle sait faire

**196 outils intégrés** avec les drapeaux par défaut. Activer le client MCP
(`mcp_client_v2_enabled`, éteint par défaut) en ajoute **10** — les outils de
gestion MCP — et chaque serveur MCP connecté apporte les siens, sous la forme
`mcp__serveur__outil`.

Les grandes familles :

- **Google** — Gmail, Agenda, Drive, Sheets, Docs, Contacts, Tasks
- **Documents** — lecture de PDF, analyse par vision, et conversion PDF → Word
  reconstruite depuis la géométrie de la page (le texte ne transite jamais par
  le modèle : l'intégrité est structurelle)
- **Web** — recherche, images, cartes (voir plus bas)
- **Navigateur** — deux familles, volontairement : un Chromium serveur **sans
  aucun cookie**, et **votre vrai Chrome** via l'extension, seul moyen
  d'atteindre ce qui est derrière une authentification
- **Machine** — fichiers, captures d'écran, contrôle du bureau, SSH
- **Mémoire** — rappel typé, recherche vectorielle, plein texte sur les
  conversations passées
- **Planification** — tâches récurrentes
- **Canaux** — Telegram, Slack, Discord, WhatsApp, sur le même moteur que le chat
  web
- **MCP** — Ely est à la fois cliente de serveurs MCP externes et serveur MCP
  elle-même

---

## La recherche, sans la louer

Une instance **SearXNG** est livrée dans le compose et prend la tête de la
chaîne. C'est un méta-moteur : il interroge plusieurs dizaines de moteurs en
parallèle et croise ce qu'ils rendent, au lieu de reprendre les dix premiers
liens d'une source unique. Pas de clé, pas de compte, pas de quota, et aucun
tiers qui relie vos requêtes à vous sous votre propre clé d'API.

Ely peut viser une famille de sources — `it`, `news`, `images`, `videos`,
`science`, `social_media`, `files`, `shopping`. La famille demandée **s'ajoute**
aux généralistes, elle ne les remplace jamais : « les actualités sur l'IA »
interroge Reuters *et* le web ouvert, sinon vous ne liriez qu'une seule source.

Derrière, les fournisseurs à clé restent en **filet**, essayés seulement quand
celui du dessus ne rend rien : Exa (sémantique), SearchCans, Google CSE, Tavily,
DuckDuckGo. Un fournisseur à court de quota est écarté trente minutes plutôt que
rappelé à chaque tour.

⚠️ SearXNG n'a pas d'index à lui — il interroge les moteurs amont depuis l'IP de
votre machine, donc le risque de blocage change de mains. C'est l'ampleur qui
l'absorbe : trois moteurs bloqués pendant les essais, vingt-six résultats sont
tout de même passés.

Au démarrage, en tâche de fond, Ely place un appel **réel** sur chaque tête de
chaîne — chaque tier de modèle et chaque fournisseur de recherche — et rapporte
ce qui a effectivement répondu. Le contrôle précédent vérifiait seulement qu'un
service était *constructible* ; deux pannes en une seule journée sont passées
par ce trou.

---

## Démarrage rapide

**Il faut :** Docker, Docker Compose, 16 Go de RAM (32 Go pour un modèle local),
20 Go de disque, `make`, `openssl`.

```bash
git clone https://github.com/franckolv-dev/ElyAgent.git
cd ElyAgent
cp .env.example .env

# 1. Secret de signature — l'app refuse de démarrer sans un vrai
openssl rand -hex 32          # à coller dans JWT_SECRET_KEY= du .env

# 2. Un fournisseur de modèle (obligatoire — sinon Ely ne peut rien répondre)
#    ex. ACTIVE_LLM_PROVIDER=gemini + GEMINI_API_KEY=…
#    Les chemins locaux marchent aussi : Ollama, LM Studio

# 3. Démarrer (le premier lancement télécharge plusieurs Go, 5-10 min)
make up
make logs                     # attendre que le backend soit healthy

# 4. Ouvrir http://localhost:3000 — le premier compte créé devient admin
```

⚠️ **Le `.env` est à la RACINE du dépôt.** Le conteneur lit celui-là, pas
`backend/.env`. C'est le piège de configuration le plus fréquent ici.

Marche à suivre complète : **[docs/installation.md](docs/installation.md)**.

---

## L'accord, et où il vit réellement

**46 outils** demandent votre accord par leur nom. En plus, le **contenu** d'une
demande peut déclencher une vérification : un virement, un achat, une
suppression, un passage en caisse.

Trois règles à connaître :

1. **On échoue fermé.** Un outil non classé est traité comme engageant. Un faux
   positif coûte une question ; un faux négatif, un message parti.
2. **Une dispense n'est pas un reclassement.** Certains actes engageants sont
   dispensés d'accord avec une raison écrite — un clic dans Chrome n'engage pas,
   remplir un champ n'est pas le soumettre. L'outil reste classé engageant : on
   sépare ce qu'il **est** de ce qui exige un accord.
3. **Une docstring n'est pas un garde-fou.** « Toujours demander confirmation »
   dans la documentation d'un outil est une consigne au modèle, pas un verrou.
   Ces phrases ont été retirées ; la garde seule décide.

---

## Vos données

Avant tout appel à un modèle **hébergé chez un tiers**, les données personnelles
sont remplacées par des marqueurs stables — la même adresse devient le même
marqueur d'un bout à l'autre de la conversation — et la réponse est reconstituée
au retour. Un appel à un modèle **local** ne passe pas par là : rien ne quitte la
machine.

Ely dit ce que la demande a coûté quand elle a utilisé un modèle facturé à
l'appel.

---

## Comment elle apprend

Une compétence naît d'un **succès obtenu après correction** : Ely a échoué, l'a
vu, a nommé l'écart, a corrigé, et le résultat a passé la vérification. La
procédure est alors rédigée et proposée en **candidate**. Rien ne devient actif
sans relecture.

Un outil n'est fabriqué que si la demande exige une **action** — toucher un
fichier, une API, un service. Sinon ce sera une compétence : une procédure
écrite, pas du code en plus.

---

## Pile technique

FastAPI · LangGraph · Next.js · SQLite (Alembic seul fait foi sur le schéma) ·
Qdrant · nginx · Squid pour le filtrage des sorties · Docker Compose.

Surfaces : web, API REST, Telegram, Slack, Discord, WhatsApp, voix par
WebSocket, extension Chrome et application de bureau. Les applications
Android et iOS sont archivées depuis le 02/09/2026 — voir
[archive/README.md](archive/README.md).

---

## Documentation

| | |
|---|---|
| [docs/architecture.md](docs/architecture.md) | comment ça marche à l'intérieur |
| [docs/installation.md](docs/installation.md) | installer et configurer |
| [docs/guide-utilisateur.md](docs/guide-utilisateur.md) | s'en servir au quotidien |
| `.env.example` | tous les réglages, annotés |

---

## Licence

**Elastic License 2.0** — voir [LICENSE](LICENSE), avec un résumé en langage
clair dans [licence-ELY.md](licence-ELY.md) et les conditions commerciales dans
[COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md).

- **Autorisé** — usage personnel, et usage professionnel interne, gratuitement.
- **Interdit** — revendre Ely comme service hébergé ou managé à des tiers, et
  retirer les notices de copyright ou de licence.

Marque : [TRADEMARK.md](TRADEMARK.md). Politique de sécurité :
[SECURITY.md](SECURITY.md).

---

## Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md) et
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

Ely est un projet personnel, le rythme est donc ce qu'il est. Les rapports de
bug précis et reproductibles sont ce qui aide le plus.
