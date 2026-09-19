# Guide de l’interface Ely — aide aux utilisateurs

Version vérifiée le **10 septembre 2026**. Langue de référence : français.
Ce manuel décrit les écrans réellement présents dans cette version d’Ely.
Il est destiné à la lecture humaine et à l’indexation dans **Connaissances**.
Les chemins indiqués sont relatifs à l’adresse de votre instance Ely.

## Se repérer dans l’interface Ely

Le menu de gauche donne accès à **Chat**, **Missions**, **Autonomie**, **Tâches planifiées**,
**Connaissances**, **Compétences**, **Analyse** et **Paramètres**. Sur un petit
écran, ouvrez le menu avec le bouton à trois traits en haut à gauche.
**Nouvelle conversation** ouvre un échange distinct ; les échanges précédents
restent accessibles dans **Récentes**. Les groupes Compétences et Analyse se déplient.
Certains écrans sont réservés aux administrateurs et ne figurent pas dans le menu
d’un compte ordinaire. L’absence d’un menu ne signifie donc pas qu’il faut réinstaller Ely.

## Choisir entre Chat, mission et tâche planifiée

| Besoin | Écran conseillé | Résultat attendu |
| --- | --- | --- |
| Poser une question ou demander une action ponctuelle | Chat `/chat` | Réponse dans la conversation |
| Poursuivre un objectif qui peut nécessiter plusieurs étapes | Missions `/missions` | Travail avec état, suivi et budgets |
| Exécuter une demande à des horaires réguliers | Tâches planifiées `/scheduled` | Demande exécutée selon une cadence |
| Démarrer régulièrement un travail long | Tâches planifiées, option Exécuter comme mission | Une mission démarre à l’heure prévue |
| Réagir à un nouveau mail, une modification d’agenda ou un document indexé | Autonomie `/autonomy` | Mission déclenchée par l’événement |
| Fournir des documents de référence à Ely | Connaissances `/knowledge` | Documents consultables dans les conversations |

Une mission ne définit pas à elle seule une récurrence. Une tâche planifiée définit
la récurrence ; son option **Exécuter comme mission** permet de combiner les deux.

## Comment créer une mission dans l’interface Ely ?

Chemin : **Missions → Nouvelle mission** (`/missions`).

1. Cliquez sur **Missions** dans le menu de gauche, puis **Nouvelle mission**.
2. Renseignez **Titre court**, par exemple « Comparer trois solutions de sauvegarde ».
3. Dans **Goal — décris ce qu’Éli doit accomplir**, précisez le résultat, les critères
   et les limites. Exemple : « Compare trois solutions de sauvegarde pour un Mac.
   Produis un tableau avec prix, capacité et liens vers les sources. Ne souscris à aucune offre. »
4. Réglez au besoin **Budget itérations** et **Budget tokens**. Vous pouvez conserver
   les valeurs préremplies pour un premier essai. Ce sont des plafonds de travail,
   pas un pourcentage de réalisation de l’objectif.
5. Laissez **Mission autonome** décochée si vous souhaitez un fonctionnement supervisé.
   Cette option ne donne pas des droits illimités : les permissions et restrictions
   des actions sensibles restent applicables.
6. Cliquez sur **Créer la mission**. Elle apparaît dans la liste à l’état **brouillon**.
7. Ouvrez sa carte, puis cliquez sur **Démarrer** pour lancer le travail.

Le titre est obligatoire et le champ Goal doit comporter au moins cinq caractères.
Créer le brouillon et démarrer la mission sont deux étapes distinctes. Aucun fichier
YAML ni définition technique d’outil n’est nécessaire dans ce formulaire.

## Comment suivre, suspendre ou reprendre une mission Ely ?

Chemin : **Missions → ouvrir la carte de la mission** (`/missions/<identifiant>`).

La page de détail présente l’état, les consommations, les informations de travail
et le résultat ou la raison d’échec lorsqu’ils sont disponibles. Dans la liste,
les onglets **Toutes**, **Actives** et **Terminées** facilitent la recherche.

- **Pause** suspend une mission en cours ; **Reprendre** reprend une mission en pause.
- **Abandonner**, ou **Arrêt d’urgence** lorsqu’il est affiché, arrête la poursuite de l’objectif.
- Si Ely pose une question, utilisez le champ de réponse associé puis **Répondre**.
  Une mission en attente de votre réponse n’est pas une mission terminée.
- **Relancer**, quand il est disponible, ouvre les options de reprise. Vérifiez l’objectif
  et le budget avant de confirmer. La reprise conserve le contexte prévu par ce parcours.
- **Tick manuel** demande un passage de travail ; ce n’est pas une preuve que toute la mission a abouti.

Pour une mission terminée, les actions de la carte permettent aussi de modifier
ses paramètres, la relancer ou la supprimer. La suppression demande confirmation
et retire la mission, son plan et ses étapes ; elle n’annule pas les actions déjà
réalisées dans des services externes. Pour juger la réussite, lisez le résultat et
vérifiez le livrable, plutôt que de vous fier au budget consommé.

## Comment créer une tâche planifiée dans Ely ?

Chemin : **Tâches planifiées → Nouvelle tâche** (`/scheduled`).

1. Ouvrez **Tâches planifiées**, puis cliquez sur **Nouvelle tâche**.
2. Dans **Nom**, saisissez un titre reconnaissable, par exemple « Météo du matin ».
3. Dans **Demande à exécuter**, décrivez une demande autonome et précise.
   Exemple : « Donne la météo du jour à Poitiers, avec la température et le risque de pluie. »
4. Renseignez **Cadence (cron 5 champs)**. Les exemples sous le champ sont cliquables
   et remplissent directement la cadence.
5. Pour une demande courte, conservez **Exécuter comme mission** décoché. Pour un
   objectif long, cochez cette option afin d’obtenir un suivi dans **Missions**.
6. Cliquez sur **Créer** et vérifiez que la tâche apparaît dans la liste avec l’état **Active**.

Le formulaire exige le nom, la demande et la cadence. Il ne propose actuellement
ni sélecteur de canal de livraison ni sélecteur de fuseau horaire. Pour une livraison
particulière, par exemple sur Telegram, demandez explicitement à Ely dans le Chat de
créer la tâche avec ce canal, puis vérifiez la configuration du canal et la tâche créée.

## Comment écrire la cadence d’une tâche planifiée ?

Dans **Tâches planifiées → Nouvelle tâche → Cadence (cron 5 champs)**, les champs
sont dans cet ordre : **minute, heure, jour du mois, mois, jour de la semaine**.
L’astérisque signifie « toutes les valeurs ». Dans cette version, l’ordonnanceur
utilise le fuseau **Europe/Paris**, avec ses changements d’heure saisonniers.

| Fréquence souhaitée | Valeur à saisir |
| --- | --- |
| Tous les jours à 9 h | `0 9 * * *` |
| Tous les jours à 12 h 30 | `30 12 * * *` |
| Du lundi au vendredi à 8 h | `0 8 * * 1-5` |
| Chaque lundi à 9 h | `0 9 * * 1` |
| Toutes les deux heures, à l’heure pile | `0 */2 * * *` |

Les exemples correspondent au format accepté par Ely. Pour une exécution unique,
une date précise ou une cadence difficile à exprimer, décrivez la demande dans le
Chat et demandez à Ely de confirmer la programmation obtenue.

## Comment tester, désactiver ou supprimer une tâche planifiée ?

Chemin : **Tâches planifiées** (`/scheduled`), sur la carte de la tâche.

- **Exécuter maintenant** déclenche réellement la demande. Ce n’est pas un aperçu :
  si elle prévoit un envoi ou une modification autorisée, cet effet peut avoir lieu.
- **Désactiver** suspend les prochaines exécutions ; **Activer** les rétablit.
- **Supprimer** retire la tâche après confirmation. Préférez Désactiver si vous
  souhaitez pouvoir la reprendre plus tard.
- Consultez **Dernière exécution**, son état et le résultat affiché. Utilisez
  **Rafraîchir** si vous avez besoin de recharger la liste.

Les états peuvent indiquer **En cours**, **Réussie**, **Échec**, **Silencieuse**,
**Occurrence manquée** ou **Jamais exécutée**. Une tâche déclenchée n’est pas encore
une tâche réussie. Un résultat « silencieux » concerne les demandes configurées
pour rester silencieuses quand il n’y a rien à signaler.

Le formulaire de la liste ne propose actuellement pas de bouton de modification
d’une tâche existante. Pour changer une demande ou un horaire, demandez-le à Ely
en précisant la tâche, ou désactivez l’ancienne tâche puis créez sa remplaçante.
Évitez de laisser les deux tâches actives si elles exécutent la même demande.

## Comment programmer une mission récurrente ?

Chemin : **Tâches planifiées → Nouvelle tâche → Exécuter comme mission**.

Remplissez Nom, Demande à exécuter et Cadence, puis cochez **Exécuter comme mission**
avant de cliquer sur **Créer**. À l’heure prévue, Ely crée et démarre une mission
pour cette demande. Le suivi du travail se fait dans **Missions** ; la cadence
reste gérée dans **Tâches planifiées**. Désactiver la récurrence ne remplace pas
l’arrêt d’une mission déjà démarrée.

## Comment fournir un document à Ely et l’indexer ?

Chemin : **Connaissances** (`/knowledge`), zone **Importer un document**.

1. Ouvrez **Connaissances**.
2. Renseignez éventuellement **Titre (optionnel)** avant de choisir le fichier.
3. Glissez le document dans la zone d’importation ou cliquez dans cette zone
   pour sélectionner le fichier. L’importation démarre à la sélection.
4. Attendez le message **Document indexé en … fragments** et l’apparition du document
   dans la liste **Documents**.
5. Dans **Rechercher dans la base**, saisissez une question, puis cliquez sur
   **Tester la recherche**. Vérifiez que des passages du document sont retrouvés.
6. Dans le Chat, demandez par exemple : « D’après mon guide de l’interface Ely,
   explique-moi comment créer une mission, étape par étape. »

Les formats acceptés comprennent PDF, TXT, **MD (Markdown)**, CSV, JSON, DOC, DOCX,
XLS et XLSX, avec une limite de 50 Mo par fichier. Les documents sont associés au
compte qui les importe : un document indexé par une personne n’est pas automatiquement
partagé avec tous les utilisateurs de l’instance.

Pour rendre ce manuel consultable par Ely, importez **guide-interface-ely.md**
avec le titre « Guide de l’interface Ely — 10 septembre 2026 ». Après une mise à
jour du manuel, importez la nouvelle version, testez la recherche, puis retirez
l’ancienne version identifiée dans la liste pour éviter les consignes contradictoires.

## Comment surveiller un dossier de documents ?

Chemin : **Connaissances → Dossiers surveillés → Ajouter un dossier**.

Saisissez le **Chemin du dossier**, sous forme de chemin absolu sur votre machine.
Choisissez si les sous-dossiers doivent être inclus, puis cliquez sur **Ajouter**.
Utilisez **Scanner maintenant** pour un premier contrôle ; les scans automatiques
sont ensuite périodiques. L’accès doit être autorisé et ELY Desktop doit être connecté,
sauf si l’administrateur a rendu ce dossier directement lisible par le serveur.

Si le dossier est « offline », vérifiez ELY Desktop et les répertoires autorisés.
Un scan peut être partiel ; consultez son compte rendu. Les fichiers déjà indexés
sont ignorés : modifier un fichier ne garantit pas sa réindexation automatique.
Pour une mise à jour, retirez l’ancienne entrée du document de **Connaissances**,
puis relancez le scan ou importez le fichier actualisé.

Retirer un dossier de la surveillance ne supprime pas les documents déjà indexés
et ne supprime pas les fichiers originaux sur votre machine.

## Comment connecter Chrome à Ely ?

Chemin : **Paramètres → Intégrations → Gérer les tokens d’extension**,
ou directement `/settings/extension`.

L’extension Chrome permet à Ely d’interagir avec des pages dans votre navigateur.
Elle utilise un token de connexion distinct des intégrations Google.

1. Installez l’extension Chrome Ely fournie pour votre instance, si nécessaire.
2. Ouvrez **Gérer les tokens d’extension** dans Ely.
3. Donnez un nom au token, puis cliquez sur **Générer**.
4. Copiez le token affiché et conservez-le dans les paramètres de l’extension.
   Il n’est affiché en clair qu’à sa création : ne le publiez pas dans le Chat.
5. Dans Chrome, ouvrez l’extension Ely, puis **Options**. Renseignez l’adresse
   de votre instance et le champ **Token longue durée**.
6. Vérifiez ensuite l’indicateur **Chrome** dans **Connexions**, à droite du Chat.

Un token créé ne prouve pas que l’extension est connectée. Chrome et l’extension
doivent être ouverts et reliés au serveur. **Révoquer** un token coupe l’accès
de l’extension qui l’utilise.

## Comment autoriser Ely à agir sur les fichiers de mon ordinateur ?

Chemin : **Paramètres → Intégrations → ELY Desktop** (`/settings`).

ELY Desktop donne accès à votre ordinateur et aux dossiers autorisés. Dans cette
section, configurez les **Répertoires autorisés**, enregistrez, puis utilisez les
téléchargements et les instructions d’installation proposés pour votre système.
Lancez ELY Desktop et vérifiez l’indicateur **Système** dans **Connexions** du Chat.

Précisez ensuite dans votre demande le dossier et l’action attendue. Un répertoire
non autorisé n’est pas rendu accessible simplement parce qu’il est cité dans un
message. Ajouter un dossier autorisé ne l’indexe pas automatiquement : l’indexation
se configure séparément dans **Connaissances → Dossiers surveillés**.

## Comment connecter Google, Telegram ou régler les modèles ?

Chemin général : **Paramètres** (`/settings`).

- **Intégrations** : connectez votre compte Google dans la section correspondante
  et suivez l’autorisation proposée. Vérifiez les services autorisés avant de
  demander des actions dans Gmail, Agenda ou Drive.
- **Channels** (canaux) : configurez notamment Telegram et suivez les instructions de liaison
  du compte affichées à l’écran. Un service configuré et un compte effectivement
  lié ne sont pas toujours le même état.
- **Modèles IA** et **Routage** (administrateur) : paramètres du fournisseur et du modèle utilisé.
  Les réglages disponibles dépendent des droits et de la configuration de l’instance.
  En cas de fournisseur indisponible, faites vérifier sa connexion et sa configuration.
- **Mon compte** : langue et paramètres du compte selon les options affichées.

Les indicateurs **Chrome** et **Système** signalent la connexion de l’extension et
d’ELY Desktop. Ils ne garantissent pas qu’un site tiers est authentifié ou qu’un
répertoire particulier est autorisé.

## Comment améliorer la consigne d’une tâche planifiée qui n’aboutit pas ?

Ouvrez **Tâches planifiées**. Quand la dernière exécution d’une tâche est en
erreur, ou qu’elle s’est déclarée réussie sans avoir vraiment abouti, sa fiche
propose **Améliorer la consigne**.

1. Cliquez sur **Améliorer la consigne**. Ely relit la consigne, le dernier
   résultat et les signaux de la dernière exécution, puis propose une réécriture.
   Rien n’est modifié à ce stade.
2. Comparez **Avant** et **Après**, et lisez l’explication.
3. Cliquez sur **Appliquer** pour remplacer la consigne, ou **Rejeter** pour
   écarter la proposition.
4. Après application, **Revenir en arrière** restaure l’ancienne consigne tant
   que vous ne l’avez pas modifiée entre-temps.

Si vous modifiez la consigne à la main après une proposition, celle-ci ne peut
plus être appliquée : demandez-en une nouvelle. Une cause de configuration, par
exemple un fournisseur qui rejette la requête ou un compte déconnecté, ne se
répare pas par une réécriture : le dernier résultat de la tâche l’indique.

L’ancienne page **Incidents & propositions** a été retirée le 19 septembre 2026,
avec le diagnostic automatique de chaque exécution douteuse.

## Comment utiliser les autres écrans Compétences et Analyse ?

**Compétences → Apprentissage** présente le suivi de l’apprentissage.
**Compétences apprises** permet de consulter les compétences enregistrées.
**Compétences à valider** et **Capacités manquantes** sont réservés aux
administrateurs dans cette version.

Dans **Analyse**, les écrans de tableau de bord, état, mémoires et actions réversibles
servent à examiner ce qu’Ely a retenu ou effectué. Une mémoire personnelle, une
compétence apprise et un document dans Connaissances remplissent des rôles différents.
Supprimer un document de la base ne supprime pas automatiquement une mémoire
personnelle déjà enregistrée dans un autre écran.

## Comment régler l’apparence et la voix du Chat ?

Le bouton de thème en haut de l’interface permet de changer d’apparence.
Le thème sombre utilise un fond ardoise avec un accent bleu. À droite du Chat,
l’avatar numérique filaire change d’état ; la lueur au niveau de sa bouche anime
la parole. Le bouton de voix permet d’activer ou de couper sa lecture vocale.

Une voix coupée ne déconnecte pas Ely. Les connexions aux services se vérifient
séparément dans **Connexions** et dans les paramètres de chaque intégration.

## Aide rapide : je ne trouve pas le bouton ou la demande ne fonctionne pas

| Situation | Vérification utile |
| --- | --- |
| Ma mission reste en brouillon | Ouvrir la mission puis cliquer sur Démarrer |
| Ely attend ma réponse | Répondre à la question dans la page de la mission |
| Ma tâche planifiée ne se lance pas | Vérifier Active, la cadence Europe/Paris et le dernier état |
| Chrome ou Système est inactif | Vérifier l’extension ou ELY Desktop, puis sa connexion |
| Ely ne retrouve pas mon guide | Importer le MD dans Connaissances avec le même compte, puis Tester la recherche |
| Un dossier est offline | Vérifier ELY Desktop ou demander à l’administrateur de contrôler son accès serveur |
| Ma tâche planifiée se déclare réussie sans rien faire | Ouvrir sa fiche et cliquer sur Améliorer la consigne |
| L’écran semble afficher une ancienne version | Recharger la page après la mise à jour |

## Référence éditoriale du manuel

Les procédures ont été vérifiées dans les écrans Chat, Missions, Tâches planifiées,
Connaissances et Paramètres, dans la navigation et les libellés français
ainsi que dans les services de planification et d’indexation de la version du
10 septembre 2026. Les noms et disponibilités peuvent évoluer après une mise à jour.
Ce manuel ne contient ni identifiants, ni tokens, ni données personnelles réelles.

## Autonomie : événements, critères, reprises et limites

Dans le menu de gauche, **Autonomie** regroupe quatre onglets : **Automatismes**, **Suivi**, **Autorisations** et **Procédures**.

Pour agir à l’arrivée d’un mail, à une modification de l’agenda principal ou à l’indexation d’un document : ouvrir **Automatismes**, remplir **Nom**, **Quand**, le compte ou les filtres, puis **Alors, Ely doit…**. Choisir le plafond quotidien et cliquer sur **Enregistrer en pause**. **Simuler → Tester les conditions** teste les filtres sans exécuter d’action. **Activer** commence la surveillance des nouveaux événements, toutes les minutes. Les documents doivent d’abord être indexés dans **Connaissances**. Les tâches à une heure fixe restent dans **Tâches planifiées**.

Dans **Missions → Nouvelle mission**, **Ajouter un critère** permet d’exiger une action confirmée par son outil, un texte dans le résultat ou des sources citées et retrouvées. **Autonomie → Suivi → Critères et preuves** montre les vérifications et les accusés. Une mission ne se termine pas si un critère reste manquant : Ely tente une correction puis attend une décision.

Si Chrome ou Système est absent, une mission qui en a besoin attend et reprend à la reconnexion, dans une limite de 24 heures. Une pause manuelle reste manuelle. Une écriture incertaine après interruption n’est pas répétée automatiquement. La vérifier dans **Suivi**, décrire le constat, choisir **L’action a bien eu lieu** ou **Elle n’a pas eu lieu : autoriser un essai**, puis reprendre la mission depuis sa page.

**Autorisations** permet de conserver les autorisations existantes, demander toujours une confirmation ou interdire une catégorie d’actions. Cliquer sur **Enregistrer mes limites**. Ces choix s’appliquent au chat, aux missions et aux tâches planifiées, sans élargir l’accès aux comptes ou aux dossiers.

**Procédures** affiche les exécutions observées des procédures actives ou suspendues. Après trois échecs consécutifs, une procédure non épinglée est suspendue ; **Réactiver** permet de la remettre à disposition après examen. Un simple chargement de procédure ne vaut pas succès.

Pour les détails, prérequis, plafonds et limites de preuve : [Guide de l’autonomie d’Ely](guide-autonomie-ely.md).
