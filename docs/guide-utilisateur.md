# Guide d'utilisation

> Vérifié le 30 juillet 2026 contre les outils réellement enregistrés.

Ely fait des choses. Ce guide dit lesquelles, comment le lui demander, et où
sont les limites — y compris celles qui sont volontaires.

---

## Le principe, en une phrase

Vous formulez une demande en français. Ely choisit ses outils, agit, **confronte
le résultat à ce que vous avez demandé**, et recommence en nommant l'écart si ça
ne colle pas. Elle vous demande votre accord avant tout acte engageant.

---

## Bien formuler une demande

La différence qui compte n'est pas la politesse, c'est **où se trouve la règle**.

**Quand la règle est dans votre phrase**, Ely exécute directement :

> « Archive les mails de plus de six mois. »
> « Mets un rendez-vous jeudi à 14 h avec le titre "Revue mensuelle". »
> « Convertis ce PDF en Word. »

**Quand la règle dépend de votre jugement**, elle propose et attend :

> « Nettoie ma boîte mail. »
> « Cale un déjeuner avec Gert la semaine prochaine. »

Dans le second cas, deux personnes compétentes ne feraient pas la même chose —
donc Ely ne décide pas seule. Si vous voulez qu'elle tranche, **mettez le critère
dans la demande** : « supprime les newsletters non lues de plus de trois mois »
est mécanique, « fais le tri » ne l'est pas.

### Dites ce que vous attendez du résultat

La boucle de vérification confronte ce qui a été produit à ce que vous avez
demandé. Plus votre demande est précise sur la **forme attendue**, plus cette
vérification a prise :

> ❌ « Convertis ce PDF. »
> ✅ « Convertis ce PDF en Word, sans les numéros de page, en gardant les titres
> comme titres. »

C'est ce qui a permis, sur une conversion de 395 pages, de retirer 347 folios sur
347 sans perdre un caractère.

---

## Ce qu'Ely sait faire

**201 outils** avec les réglages par défaut. Activer le client MCP en ajoute 10,
et chaque serveur MCP connecté apporte les siens. Les grandes familles :

### Google

Gmail (lire, chercher, envoyer, répondre, étiqueter, corbeille par catégorie),
Agenda (lister, créer, modifier, supprimer, disponibilités, réunions Meet),
Drive (chercher, lire, envoyer, partager), Sheets, Docs, Contacts, Tasks.

Nécessite d'avoir autorisé votre compte Google.

### Documents

Lecture de PDF, extraction, analyse d'un PDF par vision, et **conversion
PDF → Word** reconstruite depuis la géométrie de la page.

Sur la conversion : le texte ne transite **jamais** par le modèle. Ely extrait la
géométrie, demande au modèle un balisage d'identifiants, puis matérialise
elle-même le document. L'intégrité du texte est garantie par construction, pas
par confiance.

### Web et navigateur

Recherche web, recherche d'images, cartes et lieux.

Pour naviguer, **trois familles, et le choix compte** :

| | Ce que ça pilote | Sessions | Pour quoi |
|---|---|---|---|
| `web_*` | un Chromium jetable | **aucune, et rien à ouvrir** | une URL précise, en un seul appel |
| `browser_*` | un Chromium côté serveur | une session par utilisateur | explorer un site pas à pas |
| `browser_tab_*` | **votre vrai Chrome** | les vôtres | tout ce qui est derrière une connexion |

**`web_screenshot`, `web_to_pdf`, `web_extract`, `web_compare`** prennent
l'adresse en argument, ouvrent la page, font leur travail et referment. C'est
ce qu'il faut dans une **tâche planifiée** : elle tourne sans personne devant,
parfois pendant que vous naviguez vous-même, et elle ne doit ni dépendre de la
page que vous regardez ni vous la déplacer.

`web_compare` sert la **veille** : donnez-lui le texte relevé la fois
précédente, il vous dit ce qui a changé — un prix, une offre d'emploi, une page
de statut.

Les `browser_*` restent pour l'exploration à deux : Ely et vous regardez la
même page, elle clique, vous voyez.

Si vous voulez qu'Ely lise votre LinkedIn, vos commandes Amazon ou l'interface
Gmail, il faut l'extension : sans elle, le serveur ne voit que la page de
connexion — et les outils `web_*` non plus, ils ne s'authentifient pas.

### Machine et bureau

Fichiers, captures d'écran, contrôle du bureau, exécution SSH.

### Mémoire

Ely retient. Vous pouvez lui demander de rappeler quelque chose, ou chercher dans
vos conversations passées.

### Planification

Tâches récurrentes : « chaque matin à 9 h, fais-moi un briefing ». Une tâche
planifiée tourne sans personne pour lever une ambiguïté — formulez-la de façon
mécanique.

### Canaux

Telegram, Slack, Discord, WhatsApp. Ces surfaces utilisent le **même** moteur que
le chat web : mêmes outils, même mémoire, mêmes préférences.

---

## Quand Ely demande votre accord

Un bandeau apparaît avant l'action, avec ce qu'elle s'apprête à faire.

**46 outils** sont sous accord par leur nom. En plus, le **contenu** de la
demande peut déclencher une vérification : un virement, un achat, une
suppression, un passage en caisse.

Vous pouvez désactiver la demande d'accord outil par outil dans les réglages.
Certains outils restent verrouillés et ne peuvent pas être dispensés.

**Un délai d'attente n'est pas un refus.** Si vous ne répondez pas, l'action
n'est pas exécutée, mais elle n'est pas non plus rejetée définitivement.

À l'inverse, certains gestes **ne** demandent rien, volontairement : un clic dans
Chrome n'est pas un engagement, remplir un champ de formulaire n'est pas le
soumettre, et un message Telegram vers vous-même n'engage personne.

---

## Quand Ely dit qu'elle n'a pas l'outil

Ça arrive, et c'est presque toujours l'un de ces trois cas.

**1. L'outil existe mais n'était pas sous la main.** Demandez-lui de le
chercher : « cherche dans tes outils si tu peux faire ça ». `find_tool` est son
annuaire — un petit modèle local y lit les descriptions et choisit. C'est le seul
moyen de retrouver un outil non branché au tour courant.

**2. L'intégration n'est pas autorisée.** Les outils Google n'existent pas tant
que votre compte n'est pas connecté.

**3. L'outil n'existe vraiment pas.** Ely consigne alors le manque. Si la demande
exige une **action** — toucher un fichier, une API, un service —, un outil peut
être fabriqué, validé, puis proposé. Sinon, ce sera une **compétence** : une
procédure écrite plutôt qu'un nouvel outil.

---

## Comment Ely apprend

Une compétence naît d'un **succès obtenu après correction** : Ely a échoué, l'a
vu, a nommé l'écart, a corrigé, et le résultat a passé la vérification. La
procédure est alors rédigée et proposée en **candidate**.

Rien ne devient actif sans validation. Vous retrouvez les candidates dans les
réglages d'administration.

C'est pour ça qu'il vaut la peine de **corriger Ely plutôt que de refaire à la
main** : une correction qui aboutit devient une compétence, un travail refait à
votre place ne laisse rien.

---

## Vos données

Avant tout appel à un modèle **hébergé chez un tiers**, vos données personnelles
sont remplacées par des marqueurs stables : la même adresse mail devient le même
marqueur d'un bout à l'autre de la conversation, et la réponse est reconstituée
au retour.

Un appel à un modèle **local** ne passe pas par là : rien ne quitte la machine.

Ely affiche ce que la demande a coûté quand elle utilise un modèle facturé à
l'appel.

---

## Ce qu'il faut savoir des limites

**Une page web entière ne rentre pas dans le contexte.** Le contenu lu est borné.
Si vous avez besoin d'une page longue en entier, demandez-la par morceaux ou
faites-la résumer.

**Ely voit tout son catalogue d'outils** sur les demandes courantes. Sur une
demande qui part au modèle local — l'analyse d'image — elle n'en voit qu'une
partie : la fenêtre de ce modèle ne peut pas porter les descriptions des deux
cents outils. Si elle semble alors ignorer une capacité qu'elle a, `find_tool`
va la chercher.

**La latence est le vrai coût d'usage, pas l'argent.** Un tour enchaîne plusieurs
appels au modèle. Sur un abonnement forfaitaire, ce n'est pas la facture qui
gêne, c'est l'attente.

**Une tâche planifiée ne peut rien vous demander.** Elle tourne sur un graphe
plat, sans boucle de vérification ni interlocuteur.

---

## Voir aussi

- [installation.md](installation.md) — installer et configurer
- [architecture.md](architecture.md) — comment ça marche à l'intérieur
