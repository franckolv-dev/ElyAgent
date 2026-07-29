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
- **Web** — recherche, images, cartes
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
WebSocket, extension Chrome, application de bureau, Android et iOS.

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
