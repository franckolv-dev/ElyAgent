# Ely — autonomie, mémoire et interface

Intervention du 9 septembre 2026, déployée sur ely.catalogmaker.fr le 10 septembre 2026. Les aperçus initiaux utilisent des données fictives et un service local de démonstration.

## Mise en ligne du 10 septembre 2026

Les images Docker du backend et du frontend ont été reconstruites, puis les deux services ont été remplacés. Le proxy nginx a été recréé pour desservir les services actualisés. Les volumes de données et les autres services ont été conservés.

Une sauvegarde SQLite cohérente a été réalisée avant le redémarrage dans `data/db/backups/pre-presence-2026-09-10.db` ; son contrôle d’intégrité est réussi.

Vérifications après déploiement :

- Backend sain et réponse publique `/health` : `{"status":"ok"}`.
- Page publique `/chat` : HTTP 200, réponse Cloudflare dynamique avec interdiction de conserver le HTML en cache.
- Feuille de style publique identique à celle servie par le proxy local, avec la nouvelle palette et les nouveaux composants.
- Identifiant du frontend : `Bbi2aA2UOabtJ_jS0fqA0`. Le service worker public porte le même identifiant, permettant le renouvellement du cache applicatif.
- Empreinte du module des nouveaux outils identique entre le dépôt local et le backend actif.
- Ouverture du domaine dans le navigateur : redirection normale vers la page de connexion. Aucune mission avec les comptes réels n’a été exécutée pendant cette vérification.

## Diagnostic et comparaison

Ely possède déjà une architecture riche : boucle LangGraph, fournisseurs cloud et locaux, missions persistantes, planification, mémoire SQLite/Qdrant, intégrations Google, contrôle du poste, voix et apprentissage de procédures. Le principal problème observé dans le code est la continuité entre exécution, vérification et apprentissage.

Les références consultées sont [Hermes Agent](https://github.com/nousresearch/hermes-agent), sa [documentation d’architecture](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture/) et [OpenClaw](https://github.com/openclaw/openclaw). Hermes met notamment en avant ses outils, sa mémoire, ses skills et ses tâches récurrentes ; OpenClaw organise les interactions autour d’une passerelle et de nombreux canaux. Ces références servent à comparer les mécanismes, pas à établir un classement de performances.

| Sujet | Situation constatée dans Ely | Intervention |
|---|---|---|
| Persévérance | Une limite annoncée pouvait être assimilée à une demande satisfaite | Le juge demande une tentative, une alternative ou une preuve d’accès manquant |
| Reprise | Le nombre d’exigences ouvertes était le principal critère de progrès | Les nouveaux appels réussis et distincts permettent une reprise supplémentaire, dans le plafond existant |
| Recours aux LLM | Une réponse d’un panel sans outils pouvait remplacer le travail exécuté | Le panel fournit une stratégie à l’agent, qui reprend ses outils et vérifie le résultat |
| Mémoire entre conversations | Le premier tour omettait les interactions antérieures, puis le contexte était figé | Recherche dès l’ouverture ; panne d’un magasin isolée des autres |
| Erreurs | Historique surtout destiné à la collecte | Recherche par utilisateur avec `memory_recall(memory_type="error")`, consultation et suppression depuis la mémoire |
| Outils nouveaux | Fabrique existante avec validation avant activation | Ajout d’outils de calcul testés, versionnés et utilisables immédiatement en sous-processus |
| Apprentissage | Une réussite après correction dans la boucle d’outils pouvait ne pas déclencher de proposition | Les erreurs corrigées lors d’un tour vérifié alimentent aussi la rédaction d’une skill candidate |
| Interface | Hiérarchie visuelle dense, visage peu lisible | Palette sombre/menthe et claire/verte, accueil guidé, panneau simplifié, visage éclairé et bouche animée par l’audio |

La parité avec Hermes ou OpenClaw n’est pas démontrée. Un benchmark identique, avec les mêmes modèles, accès, budgets et missions, reste nécessaire pour cette affirmation.

## Changements de comportement

### Un résultat doit être établi

Les contrôles portent sur la demande courante et ses tentatives, sans réutiliser les preuves d’une conversation précédente. Un abandon sans outil peut déclencher une vérification. Le dernier essai reste vérifié lorsque le budget de reprises est épuisé.

Un juge indisponible ou un verdict inexploitable ne valide plus implicitement une réussite : l’écart reste ouvert, ce qui empêche les passages de mission concernés de se déclarer accomplis ou de produire une compétence prétendument validée.

La passerelle reconnaît davantage d’erreurs, y compris les réponses JSON négatives. Elle propose une reprise adaptée, enregistre les erreurs retournées en texte et suggère les outils voisins lorsqu’un nom est inconnu. Elle ne répète pas automatiquement une écriture incertaine. Les autorisations, les refus et les budgets existants restent applicables.

### Une capacité de calcul peut être créée pendant la mission

1. Ely découvre `sandbox_save_tool` avec `find_tool`.
2. Elle fournit `run(arguments)`, une description et de un à cinq exemples avec résultats attendus.
3. Le programme est contrôlé et exécuté en sous-processus. Un test en échec interdit l’enregistrement.
4. La version immuable enregistrée devient utilisable avec `sandbox_run_tool`, automatiquement découvert pour la conversation.
5. Les autres utilisateurs ne peuvent pas exécuter cette version. Le code est de nouveau contrôlé à chaque exécution.

Ces programmes sont limités aux calculs et transformations en mémoire avec une sélection de bibliothèques standard. Ils ne constituent pas une nouvelle voie d’accès aux comptes Google, au réseau ou aux fichiers. Les intégrations qui réalisent ces actions continuent de passer par les outils et contrôles dédiés. L’isolation réutilise le sous-processus et les limites de ressources existants ; ce n’est pas une nouvelle machine virtuelle ni une garantie générale contre tout code hostile.

L’arrêt d’une exécution interrompt désormais son processus Python au lieu de le laisser continuer en arrière-plan.

### Une mémoire exploitable et propre à chaque utilisateur

Les recherches d’erreurs filtrent le propriétaire en SQL avant de sélectionner les résultats. Les arguments et traces ne sont pas remontés par ce rappel. Les incidents restent des observations historiques : ils ne deviennent pas des instructions et ne prouvent pas qu’une panne persiste.

Les nouvelles procédures issues de réussites corrigées restent candidates dans le circuit de validation existant. Les programmes de calcul ont leur propre format et deviennent actifs seulement après leurs tests. Aucun changement des poids des LLM n’est effectué : l’amélioration repose sur la mémoire, les procédures et les outils.

## Interface et voix

- Thèmes clair et sombre persistants, sans chargement de polices depuis Google Fonts.
- Trois entrées de conversation : faire le point, passer à l’action, préparer une mission.
- Panneau de présence avec états lisibles, modèle/latence/tokens réels lorsqu’ils sont disponibles ; retrait des scores synthétiques du panneau principal.
- Modèle 3D conservé, surface éclairée, grille plus fine, contours moins noyés par le halo.
- Ouverture de la bouche calculée sur l’audio effectivement lu, fermeture dans les silences et lors d’une pause. Il s’agit d’une synchronisation d’amplitude, pas de visèmes phonétiques.
- Lecteur vocal : nettoyage des ressources, interruption des requêtes anticipées, protection contre les anciennes réponses et signalement d’une phrase audio en échec.
- Menu mobile masqué lorsqu’il est fermé, fermeture au clic d’un lien, commandes nommées pour les technologies d’assistance.
- Le défilement ne ramène plus systématiquement en bas une personne qui relit les messages précédents.

Le modèle vocal XTTS et les données de la voix clonée sont conservés. Le test visuel/audio utilise un signal synthétique de démonstration ; il ne valide pas la qualité du clone en production.

## Vérification

Les tests ont utilisé une base SQLite en mémoire et une identité de test. Aucune migration de données n’est nécessaire : le nouveau format de compétence utilise la colonne existante.

- Suite backend complète, hors fichier nécessitant le DNS : **4 624 tests réussis, 9 ignorés**. Avec les 21 tests web séparés, cela donne **4 645 tests backend réussis**.
- Fichier de tests web exécuté séparément avec DNS public autorisé : **21 tests réussis**.
- Frontend : **68 tests réussis**, dont six nouveaux tests couvrant l’enveloppe audio, les silences, l’arrêt, les réponses périmées et l’échec d’une phrase.
- Vérification statique Python : réussie.
- Compilation Next.js de production et vérification TypeScript : réussies, 26 pages générées.
- Analyse statique frontend : zéro erreur ; 86 avertissements restent dans le projet.
- Navigateur : thèmes, persistance après rechargement, absence de débordement horizontal à 1536 px, mise en page et navigation mobile à 390 px, saisie depuis les suggestions, échange simulé et lecture audio effective.

Les tests backend ajoutés couvrent aussi l’isolement des utilisateurs, les erreurs JSON, les outils répétés qui ne constituent pas un progrès, un verdict illisible, la reprise après panel, la création et l’utilisation effective d’un programme, les tests négatifs et l’arrêt du sous-processus.

## Mesure à effectuer avec les comptes réels

Pour comparer objectivement les trois agents, utiliser par exemple vingt missions reproductibles : recherche sourcée, création de fichier, calcul, traitement d’un dossier, lecture Google, agenda, reprise après timeout, découverte d’outil, création d’un calcul réutilisable, rappel entre conversations, séparation de deux utilisateurs et tâche planifiée. Même modèle et même budget pour chaque agent ; vérification du livrable et de l’état final des services.

Mesurer le taux de réussite vérifié, les reprises utiles, le coût, la durée, les doubles écritures et les interventions humaines nécessaires. Les tests locaux prouvent les mécanismes corrigés ; ils ne mesurent pas encore ce taux de réussite réel.


## Correctifs après essais réels — 10 septembre 2026

Les essais de Franck ont révélé une régression fonctionnelle et un écart entre le concept visuel et le rendu livré. Le diagnostic de production a identifié un modèle local lié à `gmail_list_emails` seulement pour une demande de suppression, une consigne qui décourageait la découverte d’autres actions du même service, et une vérification arrêtée par un jeton cloud expiré.

Corrections :

- La sélection locale ajoute les actions demandées aux outils de lecture du domaine. Les outils découverts restent liés dans les relances, même si les mots-clés du domaine ne sont plus présents. Les préférences et contrôles d’exécution restent appliqués.
- Une affirmation d’absence d’outil sans recherche provoque une consultation du catalogue dans le même tour, via le circuit normal d’outils. Cette reprise est bornée et ne dépend pas du juge cloud. Elle n’exécute pas une suppression à la place de l’utilisateur.
- Le juge essaie les autres fournisseurs de sa chaîne configurée en cas d’échec, y compris une erreur d’authentification. Le repli reste désactivable par la configuration existante. Aucun secret expiré n’a été remplacé arbitrairement.
- Les événements WebSocket de transport ne remplacent plus la réponse destinée au lecteur vocal. Une réponse attend le chargement des préférences vocales ; le mode conversation et le lecteur automatique ne parlent plus en double.
- Nouveau portrait féminin 3D texturé avec déformations coordonnées de la bouche, des dents, de la langue et des paupières. Le mouvement suit l’audio XTTS réellement lu, se referme à l’arrêt et dans les silences. Il reste piloté par l’amplitude, sans reconnaissance phonétique.
- Fond du canvas transparent, couleurs adaptées au thème clair, éclairage et trame holographique. Les écouteurs et délais de récupération du contexte graphique sont nettoyés au démontage.

Le nouveau modèle provient de l’avatar MPFB de [TalkingHead](https://github.com/met4citizen/TalkingHead#credits), déclaré CC0 par son auteur. Il est recadré aux épaules et préparé avec les seules déformations utiles ; sa taille passe de 36,8 Mo à 18,1 Mo. Les textures sont intégrées au fichier, sans appel à un service d’avatar externe. Ce modèle et sa chaîne de préparation ont été retirés lors du nettoyage du 10 septembre, après restauration de l’avatar filaire initial à la demande de Franck. Le rendu est un modèle 3D animé et ne prétend pas reproduire à l’identique le portrait photoréaliste de la maquette.

Validation :

- **4 658 tests backend réussis, 9 ignorés**, dont un nouveau contrôle du modèle 3D. Base en mémoire ; les 21 tests nécessitant le DNS ont été exécutés séparément. Une première exécution sur l’ancienne base locale de tests a été écartée après des erreurs de schéma ; aucune de ces erreurs ne se reproduit avec la base de test isolée.
- **70 tests frontend réussis** ; TypeScript et compilation de production réussis ; zéro erreur de lint (86 avertissements existants).
- Essai du modèle local réellement configuré, Qwen3.5-9B, sur la demande de Franck : recherche Gmail, puis `gmail_trash_emails` avec les identifiants exacts fournis par une boîte fictive. Aucun mail réel n’a été supprimé.
- Essai réel de la chaîne du juge sur un calcul sans données personnelles : Mistral Large prend le relais du fournisseur expiré.
- Comparaison des 159 fonctions d’outils natifs au HEAD initial : aucune suppression. Ce contrôle et les tests réduisent le risque de régression ; ils ne prouvent pas que toutes les missions possibles réussiront.
- Navigateur Chrome avec WebGL, données de conversation simulées et véritable échantillon de la voix XTTS existante : lecture, arrêt, articulation et thèmes clair/sombre.

Une sauvegarde cohérente avant la mise en ligne des correctifs est conservée dans `data/db/backups/pre-regressions-20260909-231058.db` (horodatage UTC), avec contrôle d’intégrité réussi.

Mise en ligne terminée le 10 septembre 2026 : backend et frontend reconstruits et redémarrés, puis accès Nginx actualisé. La version frontend active est `l6sjVRcIFAELIVsA2LNeb`. Depuis `https://ely.catalogmaker.fr`, la page répond HTTP 200, la santé retourne `{"status":"ok"}`, le service worker annonce la version courante et le modèle public correspond au fichier local (SHA-256 `acf959ab8371b4d52d4242530e14ef4e401faf51e3795af69dc3f8791c60876a`). Cloudflare sert le HTML sans cache persistant. Un dernier essai Chrome sur la page de connexion publique confirme le chargement du modèle, un canvas actif, aucune erreur JavaScript et aucun avertissement du chargeur GLTF. Les bornes des déformations du modèle sont incluses et contrôlées par le test d’asset.

Captures de validation conservées : `ely-light-corrected.png`, `ely-dark-corrected.png`, `ely-mobile-corrected.png` et animation `ely-lips-corrected.gif`, dans le répertoire de visualisation Codex de cette tâche. Les captures du chat utilisent une identité fictive ; le test public n’ouvre aucun compte utilisateur. Les serveurs temporaires de démonstration ont été arrêtés.


## État actuel — restauration et revue du 10 septembre 2026

Les paragraphes précédents relatent les essais historiques. Le portrait texturé a été remplacé par le modèle filaire original `frontend/public/models/avatar.glb`, avec ses couleurs et sa lueur de bouche. Le composant de portrait abandonné, son modèle de 18 Mo, sa licence associée et son script de préparation ne sont plus distribués. Le guide d’interface actuel est [guide-interface-ely.md](guide-interface-ely.md).
