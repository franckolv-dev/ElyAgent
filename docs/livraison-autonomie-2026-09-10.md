# Livraison autonomie — 10 septembre 2026

## Comportement livré

- Automatisme volontaire sur mail Gmail, modification d’agenda principal et document nouvellement indexé. Filtrage, simulation, activation/pause, curseurs persistants et pagination. File durable, événement unique par règle et plafond quotidien sérialisé en base. Aucun automatisme créé ou activé automatiquement pour l’utilisateur.
- Critères de réussite sur mission et automatisme : accusé d’outil, texte final et références citées. Un passage correctif supplémentaire, puis décision humaine. Les écritures incertaines bloquent la conclusion.
- Accusé durable réservé avant chaque appel d’outil de mission. Déduplication des écritures strictement identiques dans la même exécution. Un redémarrage ne transforme pas un accusé absent en succès. Reconnexion Chrome/Système pendant 24 h ; les reports de fournisseur existants sont conservés. La pause manuelle et la relance à zéro restent distinctes.
- Procédures : attribution prudente par procédure effectivement fournie et outils réellement appelés, résultats distincts de la simple utilisation, suspension après trois échecs consécutifs, exemption des procédures épinglées, réactivation manuelle et invalidation des caches.
- Page Autonomie : Automatismes, Suivi, Autorisations, Procédures. Règles par utilisateur ajoutant confirmation ou interdiction aux autorisations existantes ; notifications réglables et accès aux preuves.

## Vérification

107 tests backend ciblés réussis : nouveaux services, séparation des propriétaires, déduplication, pagination Gmail, indexation durable, quotas, critères, reprise, expiration, relance, suppression des missions, HITL et passerelle d’outils. Trois avertissements de dépendances, sans échec.

70 tests frontend réussis, vérification TypeScript et compilation de production réussies. Parcours Playwright vérifiés en 1440 px et 390 px avec services simulés : création, critères, simulation sans exécution, activation, autorisations, procédures, suivi et preuves. Les captures ont été relues visuellement, avec correction des fonds de formulaires. Aucune erreur JavaScript observée.

La revue a aussi fermé la réutilisation d’anciens accusés après une relance volontaire, empêché la relance avec une écriture incertaine, conservé le quota après suppression d’une mission et prévu la suppression en cascade des nouvelles données lors de la suppression du propriétaire.

## Exploitation

Migration additive `0038_autonomy`, six tables ; aucun effacement de mémoire existante. Images précédentes conservées sous `ely-backend:before-autonomy-20260910` et `ely-frontend:before-autonomy-20260910`. Sauvegarde SQLite cohérente créée avant mise à jour et contrôle d’intégrité réussi.

Les premiers automatismes sont vides et désactivés par défaut. Les tests n’envoient aucun mail, n’agissent sur aucun fichier personnel et ne rejouent aucune demande quotidienne.

## Limites explicites

Les événements sont interrogés périodiquement, pas reçus par webhook. Une reconnexion reprend un travail ; elle ne garantit pas la disponibilité de la ressource distante. La déduplication couvre un appel strictement identique dans une exécution de mission, pas deux formulations différentes produisant le même effet. Un accusé d’envoi n’est pas une preuve de livraison. Les compteurs de procédure mesurent les exécutions observées, pas une causalité démontrée ni une garantie de réussite globale.

La réflexion sur la mémoire est livrée séparément dans `memoire-ely-etude-2026-09-10.md`, avec inventaire agrégé et expérience locale sur données fictives. L’architecture proposée n’est pas activée dans le moteur mémoire.

## Contrôles sur l’instance publique

Les cinq API Autonomie répondent avec le compte utilisateur réel ; un appel sans authentification est rejeté. La migration active est `0038_autonomy`. Aucun automatisme ni événement n’est créé sur le compte par la livraison. Les parcours sur l’adresse publique ont également été rejoués avec services simulés, sans action externe.

Les deux guides sont indexés dans les connaissances de Franck (15 et 6 fragments), avec une fiche ciblée pour les actions incertaines. La recherche est vérifiée sur des questions naturelles. Les autres utilisateurs peuvent importer ces mêmes fichiers Markdown dans leurs connaissances.

Le contrôle des références de la base a retrouvé 599 messages orphelins déjà présents dans la sauvegarde avant livraison : même nombre et même table après migration, aucune anomalie ajoutée par les nouvelles tables. Ces données historiques n’ont pas été effacées. Leur traitement éventuel relève d’un nettoyage de données distinct.
