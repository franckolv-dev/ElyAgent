# Revue du correctif d’incidents, nettoyage et documentation Ely

Date : 10 septembre 2026.
Périmètre : correctifs d’incidents, liaison d’outils, vérification des exécutions,
cache de l’interface, restauration de l’avatar et lecture vocale associée.
Cette revue ciblée ne constitue pas une certification de tout le dépôt.

## Constats corrigés

### P2 — Vérification fondée sur une consigne mutable

Le suivi relisait la demande actuelle de la tâche pour décider si une exécution
ultérieure confirmait le correctif. Modifier la tâche pouvait ainsi fausser
l’attribution de la réussite. Le suivi consulte désormais le message réellement
persisté pour cette exécution, en contrôlant son utilisateur et sa date. Sans
trace correspondante, il conserve « en attente » et ne déclare pas une réussite.

Fichiers : `backend/app/services/learning/binding_repair.py`,
`backend/app/routers/learning_skills.py`.
Test : `test_verification_uses_executed_prompt_not_current_task`.

### P2 — Un correctif abîmé pouvait neutraliser les autres

La lecture des liaisons supposait que chaque valeur JSON stockée contenait une
demande et une liste de noms d’outils valides. Une valeur incorrecte faisait
échouer la récupération de l’ensemble. Le contenu est désormais validé ; une
liaison illisible est ignorée et journalisée par son identifiant, tandis que les
autres continuent à fonctionner. Son application est refusée avec une explication.

Test : `test_malformed_binding_does_not_disable_other_repairs`.

### P2 — Propositions périmées et modifications utilisateur

Une liaison pouvait être appliquée alors que sa demande avait changé depuis la
préparation. Les corrections de consigne pouvaient écraser une modification faite
entre-temps, y compris lors de l’annulation. Les services vérifient maintenant la
cible et sa valeur avant d’appliquer ou d’annuler. En cas de divergence, ils
préservent la modification et demandent une nouvelle proposition.

Tests : `test_stale_proposal_cannot_be_applied`,
`test_prompt_repair_preserves_later_user_edits` et
`test_prompt_undo_reopens_validated_incident_and_preserves_user_edits`.

### P2 — État du diagnostic après application et annulation

Une correction de consigne appliquée à un diagnostic déjà confirmé pouvait laisser
son ancien état. Son annulation ne réouvrait pas systématiquement l’incident.
L’application passe maintenant les diagnostics ouverts ou confirmés à l’état
traité ; l’annulation rouvre l’incident pour son suivi.

### Code devenu inutile

Le marqueur d’état `capability_lookup_forced` n’était plus lu depuis que la reprise
est bornée par l’appel du catalogue dans le tour courant. Il a été retiré. Un test
conserve une ancienne valeur de checkpoint pour vérifier qu’elle ne bloque pas
la reprise d’un nouveau tour.

Le portrait texturé abandonné n’avait plus d’import actif. Son composant, le modèle
GLB, la licence propre à cet asset et son script de préparation ont été retirés.
Le modèle filaire initial `frontend/public/models/avatar.glb` reste présent et son
intégrité est testée. Le module calculant l’amplitude audio du portrait n’avait plus
de lecteur : il a été retiré du parcours TTS avec ses tests devenus sans objet.
La lecture, l’arrêt, la libération des ressources audio et les réponses tardives
restent couverts par les tests de lecture vocale.

## Nettoyage des fichiers

**512 fichiers retirés ; 21 547 442 octets, soit environ 21,5 Mo.**
Le [manifeste CSV](nettoyage-2026-09-10.csv) donne chaque chemin et sa taille.

Les suppressions concernent les anciens résultats de benchmark et journaux de
tests non versionnés de plus de 30 jours, les métadonnées macOS inutiles et les
éléments d’avatar/audio abandonnés. Les sources, migrations, paramètres, exécutables
encore distribués, données utilisateur, sauvegardes de base et configurations ont
été conservés. Leur âge seul ne permet pas de conclure qu’ils sont inutiles.
Les dépendances installées et caches nécessaires aux vérifications n’ont pas été
supprimés arbitrairement.

## Guide d’utilisation et indexation

Le [Guide de l’interface Ely](guide-interface-ely.md) décrit les parcours réels :
missions, lancement et reprise, tâches planifiées et cadence, missions récurrentes,
connaissances, dossiers surveillés, Chrome, ELY Desktop, paramètres et incidents.
Il distingue les fonctions disponibles des actions absentes de l’interface, ainsi
que les droits d’un utilisateur et ceux d’un administrateur.

Le guide a été indexé dans la base de connaissances du compte concerné par
l’intervention, sous le titre « Guide de l’interface Ely — 10 septembre 2026 ».
L’indexation produit **12 fragments**. Les trois recherches suivantes retrouvent
le guide parmi les cinq premiers résultats au seuil normal de pertinence :

- « Comment créer une mission dans ton interface ? » — score 0,585.
- « Comment créer une tâche planifiée tous les jours à 9h ? » — score 0,667.
- « Comment connecter Chrome à Ely ? » — score 0,472.

Un second contrôle vérifie que les passages renvoyés contiennent effectivement
« Créer la mission » et « Démarrer », la cadence `0 9 * * *`, ainsi que
« Token longue durée » et « Options » pour Chrome.

Les bases étant isolées par compte, les autres utilisateurs peuvent importer ce
même fichier Markdown dans Connaissances. Le guide ne contient aucun secret et
n’est pas automatiquement copié dans les bases des autres comptes. La description
de l’outil de recherche rappelle à Ely d’utiliser les procédures indexées pour
les questions sur l’interface.

## Vérifications

- **111 tests backend ciblés réussis**, incluant les cas de régression ci-dessus,
  les incidents, permissions d’outils, reprises et connexions.
- **70 tests frontend réussis**, dont la lecture audio et la fraîcheur des incidents.
- Contrôle des références : aucun import actif vers le portrait ou le calcul audio retirés.
- Contrôle des modifications : aucune erreur d’espacement signalée.

## Limites du suivi

La réussite observée est un verdict d’exécution, pas une garantie que toute demande
future aboutira. Sans conversation conservant la demande exécutée, le suivi reste
en attente ; c’est notamment une limite pour certains historiques de missions.
Les requêtes reformulées ne sont pas assimilées automatiquement aux demandes
identiques par la règle de liaison. Les services externes et les autorisations
restent responsables de leur disponibilité effective.

## Mise en service

Version revue construite et mise en service le 10 septembre 2026. Backend et
frontend déclarés sains. Sur le site public, le modèle filaire original répond
HTTP 200, un canvas est actif et aucune erreur JavaScript n’est observée. Le
parcours d’incidents, testé avec des données simulées isolées, permet toujours de
préparer, appliquer et annuler un correctif, sur ordinateur et mobile. Le correctif
réel n° 54 reste appliqué ; aucun résumé quotidien n’a été relancé pour ces tests.
Les images de service précédentes sont conservées pour un retour arrière.
