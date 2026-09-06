<!-- English: README.md -->

# Ely

**Exactly Like You** — un agent personnel auto-hébergé. Vos données restent en
local, la puissance vient du cloud, et rien d'irréversible ne se fait sans
votre accord.

Ely est un **projet personnel non commercial**, publié sous licence **MIT**.
Faites-en ce que vous voulez ; gardez simplement la notice de copyright.

---

## Le local, le cloud, et la frontière entre les deux

Ely tourne sur votre machine et choisit un modèle par demande. Une demande
prend l'un de trois trajets.

**Sur votre machine.** Un petit modèle local (LM Studio ou Ollama) porte le
travail de fond : lire l'annuaire des outils, extraire d'un tour les faits qui
méritent d'être retenus, résumer, choisir les familles d'outils d'une mission,
éprouver une compétence candidate. Activez la voie locale (`SLM_ENABLED`,
éteinte par défaut) et il répond aussi aux demandes simples du chat, avec ses
outils : la météo, votre agenda, une traduction, une recherche. Rien de ce
trafic ne quitte la machine, et rien n'est facturé.

**Masqué, puis envoyé.** Ce qui demande un vrai raisonnement — du code, un
document de 400 pages, une mission de plusieurs heures — part vers le modèle
cloud que vous avez configuré. Ely parle à une douzaine de fournisseurs
(Gemini, Claude, Mistral, DeepSeek, OpenAI et l'abonnement ChatGPT, OpenRouter,
Moonshot, Qwen, Zhipu) ; la répartition se règle tier par tier, par
l'administrateur, jamais par utilisateur. Avant qu'un appel quitte la machine,
les données personnelles — adresses, IBAN, SIRET, numéros de téléphone, clés
d'API — sont remplacées par des marqueurs stables, la même adresse devenant le
même marqueur d'un bout à l'autre de la conversation, et la réponse est
reconstituée au retour. La frontière, c'est le **réseau**, pas le prompt : un
modèle local reçoit vos données en clair, parce que les masquer ne protégerait
rien et lui coûterait en qualité. Si le masquage échoue, le tour s'arrête au
lieu d'envoyer quoi que ce soit en clair.

**Mis en pause.** Envoyer un message, supprimer un fichier, lancer une
commande à distance : Ely s'arrête et attend votre accord, en montrant l'appel
exact avant qu'il parte. Sans réponse, l'action expire au lieu de se faire.

Deux limites à dire. La voie locale est un choix à activer, et elle demande
une machine capable de servir un modèle (32 Go de RAM en pratique). Les
missions et les tâches planifiées prennent toujours le tier cloud : un petit
modèle ne tient pas un travail à plusieurs outils sans personne devant l'écran.

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

Le choix du modèle local n'est pas cosmétique : sur la même tâche d'annuaire
des outils, deux d'entre eux sortent 4/4 — l'un en 1,1 s, l'autre en 8,9 s.

---

## Ce qu'elle sait faire

**199 outils** intégrés, avec les drapeaux par défaut. Activer le client MCP
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
- **Canaux** — Telegram, sur le même moteur que le chat web
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
#    Option : SLM_ENABLED=true confie les demandes simples à un modèle local

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

**44 outils** demandent votre accord par leur nom. En plus, le **contenu** d'une
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

Le masquage décrit plus haut est une couche d'expressions régulières, posée à
la frontière du réseau et seulement là : un modèle local est servi en clair.
Le trajet d'une demande est décidé avant l'appel, et la trace d'un tour dit
quel modèle a répondu.

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

Surfaces : web, API REST, Telegram, voix par WebSocket, extension Chrome et
application de bureau. Les applications Android et iOS, ainsi que les ponts
WhatsApp, Slack et Discord, sont archivés depuis le 02/09/2026 — voir
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

**MIT** — voir [LICENSE](LICENSE). Utilisez-la, modifiez-la, redistribuez-la,
vendez-la, hébergez-la comme service. La seule condition est que la notice de
copyright et le texte de licence voyagent avec le code.

Ely est passée de l'Elastic License 2.0 à MIT le 3 septembre 2026. C'est un
projet personnel, pas un produit ; une licence permissive retire toute raison
d'hésiter avant de la forker.

Marque : [TRADEMARK.md](TRADEMARK.md). Politique de sécurité :
[SECURITY.md](SECURITY.md).

---

## Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md) et
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

Ely est un projet personnel, le rythme est donc ce qu'il est. Les rapports de
bug précis et reproductibles sont ce qui aide le plus.
