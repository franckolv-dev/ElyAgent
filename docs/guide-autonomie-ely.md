# Utiliser l’autonomie d’Ely

Version du 10 septembre 2026. Fonctionnalités accessibles dans **Autonomie**, dans le menu de gauche. Sur téléphone, ouvrir d’abord le menu avec le bouton en haut à gauche.

## Déclencher une mission à l’arrivée d’un événement

1. Ouvrir **Autonomie → Automatismes**.
2. Donner un nom au nouvel automatisme.
3. Dans **Quand**, choisir **Nouveau mail Gmail**, **Modification de l’agenda principal** ou **Nouveau document indexé**.
4. Pour Google, préciser l’alias du compte connecté dans Paramètres. `default` utilise le compte par défaut. Pour les documents, indiquer éventuellement un dossier.
5. Ajouter les conditions souhaitées : expéditeur du mail, mots dans le titre, dossier du document. Tous les filtres renseignés doivent correspondre. Les mots sont recherchés sans distinction de majuscules.
6. Décrire ce qu’Ely doit faire dans **Alors, Ely doit…**. Nommer le dossier, le destinataire ou le résultat attendu lorsque c’est nécessaire.
7. Choisir le maximum de missions par jour. Le compteur se renouvelle à minuit UTC. Les événements dépassant ce plafond attendent dans la file.
8. Ajouter éventuellement des **Critères de réussite**.
9. Cliquer sur **Enregistrer en pause**.
10. Cliquer sur **Simuler**, renseigner un expéditeur, un titre ou un chemin fictif, puis sur **Tester les conditions**. Cette simulation teste les filtres ; elle ne contacte aucun compte et n’exécute aucune mission.
11. Cliquer sur **Activer** lorsque la règle convient.

Ely vérifie les événements toutes les minutes lorsque le serveur fonctionne. Cette vérification ne fait pas appel à un modèle de langage. Une mission est créée lorsqu’un événement correspond. Elle utilise ensuite les outils et les modèles ordinaires d’Ely, avec un budget de 500 000 tokens et 100 actions/itérations.

À l’activation, les anciens mails et documents ne sont pas repris. Un même événement n’est traité qu’une fois par automatisme, y compris après un redémarrage. Deux automatismes distincts peuvent chacun traiter le même événement.

**Mettre en pause** arrête les nouveaux déclenchements de cette règle. Cela n’arrête pas les missions déjà créées : les mettre en pause depuis **Missions**. Lors d’une réactivation, les événements encore en attente de l’ancienne activation sont annulés ; seuls les nouveaux sont pris en compte.

### Prérequis et limites des sources

- **Gmail** : compte Google connecté avec l’accès aux mails. Le filtre de titre porte sur l’objet, pas sur le corps du mail. Le journal de l’événement conserve son identifiant, son objet et son expéditeur, pas tout le message.
- **Agenda** : compte Google connecté avec l’accès au calendrier. La source surveille l’agenda principal du compte, y compris les modifications et suppressions d’événements. Ce n’est pas un rappel à l’heure d’un rendez-vous.
- **Documents** : le document doit être nouvellement indexé dans **Connaissances**, par import ou par un dossier surveillé. Un fichier seulement présent sur le disque n’est pas encore un événement. Le scan des dossiers et la disponibilité d’Ely Desktop peuvent ajouter un délai. Les modifications d’un fichier déjà indexé ne sont pas surveillées par cette source.

Si le compte Google est déconnecté, la carte de l’automatisme indique le problème. Reconnecter le compte dans **Paramètres → Intégrations**. La lecture reprend depuis son dernier repère réussi.

## Donner des critères de réussite à une mission

Dans **Missions → Nouvelle mission**, utiliser **Ajouter un critère**, avant de créer la mission. Pour un automatisme, les critères se définissent dans son formulaire et sont repris par chaque mission créée.

Trois vérifications sont disponibles :

| Critère | Ce qu’Ely vérifie | Limite |
|---|---|---|
| Action confirmée | Un outil a réellement renvoyé un résultat sans erreur : mail accepté par Gmail, événement créé, fichier écrit ou recherche effectuée | Un accusé d’envoi ne prouve pas la réception ni la lecture d’un mail ; une écriture ne garantit pas à elle seule la qualité du document |
| Texte présent dans le résultat | Le texte demandé figure dans le bilan final, sans distinction de majuscules | La présence d’un texte ne prouve pas une action externe |
| Sources citées et retrouvées | Le nombre demandé d’URL distinctes figure dans le bilan et dans les résultats d’outils de lecture réussis | Cela vérifie les références, pas la justesse de toutes les affirmations |

Une mission ne peut pas se déclarer terminée avec un critère manquant. Ely dispose d’un passage supplémentaire pour corriger le résultat. Si la vérification échoue encore, elle demande une décision.

Dans **Autonomie → Suivi**, ouvrir **Critères et preuves** pour consulter les vérifications et les accusés des outils. Pour modifier les critères d’une mission, elle doit être en brouillon, en pause ou en attente d’une réponse. Après modification, cliquer sur **Enregistrer les critères**. Répondre ensuite à la question ou reprendre la mission depuis sa page.

Les critères explicites sont facultatifs. Ils s’ajoutent à la vérification de conformité existante d’Ely.

## Reprendre un travail interrompu

Si une mission a besoin de **Chrome** ou de **Système** et que la connexion est absente, elle attend sans exécuter l’action. Ely vérifie la connexion aux battements suivants et reprend au retour du service. Après 24 heures, la reprise nécessite une décision de l’utilisateur.

Les pannes temporaires du fournisseur de modèle conservent la reprise progressive existante : jusqu’à cinq reports, espacés de 2, 5, 15, 30 puis 60 minutes. Les budgets et les échéances de la mission restent applicables. Une pause demandée manuellement reste manuelle.

Les actions d’écriture sont enregistrées avant leur exécution. Pendant la même exécution d’une mission, un appel strictement identique déjà confirmé retourne son résultat conservé. Ely ne répète pas automatiquement une écriture dont le résultat reste incertain après une interruption.

### « Exécution incertaine »

1. Ouvrir **Autonomie → Suivi → Critères et preuves** sur la mission concernée.
2. Consulter le résultat et vérifier dans le service concerné : mail envoyé, fichier présent, événement créé, etc.
3. Décrire ce qui a été vérifié dans le champ prévu.
4. Choisir **L’action a bien eu lieu**, ou **Elle n’a pas eu lieu : autoriser un essai**.
5. Ouvrir la mission et répondre à sa question pour poursuivre.

Une confirmation humaine est affichée comme telle ; elle ne devient pas artificiellement un accusé d’outil. Une mission ne peut pas être relancée à zéro tant qu’une écriture reste incertaine. Après résolution, une relance volontaire démarre une nouvelle exécution et ne réutilise pas les anciens accusés comme preuves de cette nouvelle exécution.

La protection contre la répétition porte sur le même outil et les mêmes arguments. Deux demandes formulées différemment peuvent encore correspondre au même effet externe. Pour les envois importants, conserver les confirmations appropriées.

## Choisir ce qu’Ely peut faire

Ouvrir **Autonomie → Autorisations**. Pour chaque catégorie, choisir :

- **Selon mes autorisations existantes** : conserver les droits et les confirmations déjà configurés.
- **Toujours me demander** : demander une validation avant l’action.
- **Interdire** : empêcher l’exécution.

Les catégories couvrent la consultation, les modifications privées, les actions engageantes, Ely Desktop et les outils dont l’effet n’est pas encore classé. Si plusieurs règles s’appliquent, l’interdiction l’emporte, puis la confirmation. Ces réglages s’appliquent au chat, aux missions et aux tâches planifiées ; ils ne donnent pas accès à des comptes ou dossiers supplémentaires.

Cliquer sur **Enregistrer mes limites**. Le réglage des notifications permet de recevoir les échecs, également les fins de mission, ou de consulter uniquement le suivi. Les décisions bloquantes sont consignées dans la conversation **[Missions] Notifications** lorsque les notifications sont activées. Les attentes courtes de reconnexion restent visibles dans le suivi sans créer une notification à chaque vérification.

## Voir si les procédures apprises fonctionnent

Dans **Autonomie → Procédures**, Ely affiche les procédures actives et suspendues, leur description et leurs résultats observés depuis cette mise à jour.

Le compteur repose sur les appels d’outils d’un tour où une procédure fournie à Ely correspond effectivement au travail effectué. Charger une procédure ou afficher son nom ne suffit pas. Si l’attribution est ambiguë ou si aucune trace n’est disponible, aucun succès n’est inventé.

Les résultats distinguent **exécutions sans erreur observée**, **échecs** et **non vérifiées**. Ce bilan ne démontre pas à lui seul la réussite complète de la demande ni que la procédure a causé une erreur.

Après trois exécutions observées en échec consécutives, une procédure non épinglée est suspendue. Les procédures épinglées restent sous contrôle manuel. **Suspendre** permet de retirer une procédure active ; **Réactiver** permet de la remettre à disposition après examen. Cette page ne remplace pas la validation des nouvelles compétences candidates.
