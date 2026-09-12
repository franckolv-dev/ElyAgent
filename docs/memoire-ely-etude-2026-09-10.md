# Mémoire d’Ely : étude et architecture recommandée

**Mise en œuvre :** voir [la réalisation et les comparaisons mesurées](memoire-ely-implementation-2026-09-10.md). Le texte ci-dessous conserve l’étude initiale et ses hypothèses.

10 septembre 2026. Étude réalisée **après l’implémentation des cinq fonctions d’autonomie**. Les propositions de ce document ne sont pas encore branchées dans le moteur mémoire. Les nouveaux déclencheurs, critères, accusés d’action, reprises et contrôles d’autonomie sont, eux, implémentés.

## Recommandation

Conserver les souvenirs utiles dans des magasins locaux durables, puis constituer un petit dossier de contexte adapté à chaque demande. Un modèle local peut aider à sélectionner les souvenirs ambigus et à consolider les épisodes en arrière-plan. Il ne doit décider ni des droits d’accès, ni de l’état réel des missions, ni de la validité d’une preuve.

Je recommande un **sélecteur déterministe en premier**, un **tri local facultatif ensuite**, et un **budget de contexte strict en dernier**. Le programme conserve l’état de travail nécessaire même si le petit modèle l’oublie. Cela répond mieux au besoin que d’ajouter systématiquement un second agent devant chaque réponse.

## Ce qui existe réellement

L’étude porte sur les fichiers suivants :

- `backend/app/agent/builders/memory_snapshot.py` : récupération parallèle de cinq sources, avec délai maximal de quatre secondes par source ; ajout des procédures et de l’état utilisateur.
- `backend/app/services/frozen_memory.py` : instantané figé par conversation, cache limité à 1 000 entrées et 24 heures.
- `backend/app/services/memory_service.py` : profil SQL compact, rappel lexical adapté à une question, extraction et consolidation.
- `backend/app/services/memory/_base.py` : recherche vectorielle avec renforcement lexical et FTS5, puis décroissance temporelle.
- `backend/app/services/memory/recall_service.py` : rappel par type et fusion des résultats ; les erreurs ne participent pas au rappel automatique général.
- `backend/app/services/memory/maintenance_rapid.py` : extraction de faits stables, en arrière-plan, à la fermeture d’une conversation ; maximum de 20 messages examinés et 250 caractères par fait.
- `backend/app/services/mission_workspace.py` : carnet borné à 64 Ko ; contexte du carnet limité à environ 4 000 caractères.
- `backend/app/services/mission_assurance.py` : nouveaux critères et accusés durables permettant de distinguer action constatée et déclaration.

Ely possède donc déjà une base de recherche hybride, des embeddings locaux et une consolidation par petit modèle. Il faut améliorer leur coordination plutôt que créer un second système concurrent.

### Mesures agrégées du compte examiné

Lecture seule, sans exporter les contenus personnels. Ces volumes décrivent ce compte à cet instant, pas tous les utilisateurs.

| Mesure | Valeur |
|---|---:|
| Faits du profil SQL encore valides | 417 |
| Entrées du journal mémoire SQL | 41 643 |
| Compétences apprises, tous statuts | 126 |
| Conversations | 1 689 |
| Taille cumulée des valeurs du profil | 19 145 caractères |
| Mesures récentes de contexte examinées | 100 |
| Contexte total médian estimé dans ces mesures | 43 129,5 tokens |
| Descriptions des outils natifs : part médiane, calculée mesure par mesure | 78,9 % |

Les compteurs de contexte sont les estimations internes d’Ely ; ce ne sont pas une mesure de facturation ni une mesure isolée du coût mémoire. Les médianes des catégories ne s’additionnent pas. Le profil entier n’est pas injecté : sa forme permanente est déjà fortement réduite.

**Conséquence :** traiter la mémoire améliore la pertinence et la continuité, mais réduire seulement les souvenirs ne peut pas éliminer le poids principal du contexte actuel. La sélection des outils et des procédures doit aussi être mesurée, tout en préservant `find_tool` pour découvrir les capacités non liées au premier tour.

### Limites concrètes à traiter

1. **La mauvaise requête peut piloter le rappel.** Dans `nodes.py`, `user_query` est le dernier message, parfois un résultat d’outil. La demande humaine `_a_router` est déjà disponible mais n’alimente pas tous les rappels mémoire. Une sortie d’outil longue peut donc détourner la sélection.
2. **Le premier sujet reste figé.** L’instantané conserve les souvenirs sélectionnés à l’ouverture. Un rappel lexical du profil existe dans la partie variable, mais il ne couvre pas tous les épisodes ni l’état de travail.
3. **Une limite intervient avant le classement du profil.** Le rappel SQL ne considère que 200 lignes. Sur les 417 faits valides examinés, 217 restent hors de cette fenêtre pour cette recherche, indépendamment de leur pertinence. Les faits ne sont pas supprimés, mais cette voie ne peut pas les retrouver.
4. **La recherche hybride est partielle.** Les identifiants FTS renforcent les candidats vectoriels déjà présents ; ils ne sont pas ajoutés au jeu de candidats. Un identifiant exact trouvé par FTS peut rester absent si le filtre vectoriel l’a écarté.
5. **Le temps peut pénaliser une information encore vraie.** Le rappel des épisodes applique une décroissance ; il faut distinguer ancienneté et obsolescence. Une décision ancienne explicitement demandée doit rester accessible.
6. **Profil personnel et travail en cours sont volontairement séparés.** L’extracteur rapide interdit de transformer l’avancement d’une mission en préférence utilisateur. Ce choix est juste, mais il exige une vraie mémoire de travail des missions, au-delà de la queue du carnet.
7. **Les budgets restent dispersés.** Profil, épisodes, procédures, carnet et sorties d’outils ont chacun leur limite. Il manque un arbitre final du budget total et une explication de ce qui a été retenu ou écarté.

## Essai du petit modèle local

Machine : 32 Go de RAM. LM Studio répond localement ; `mistralai/ministral-3-3b` était déjà chargé. Aucun téléchargement, aucun appel cloud et aucune donnée personnelle dans cet essai.

Le test présente jusqu’à 16 candidats courts après filtrage du propriétaire, du périmètre, de l’expiration et des versions. Le modèle doit retourner uniquement des identifiants, sous schéma JSON. Huit cas fictifs couvrent mission, adresse, voyage, aide à l’interface, compte Google, repas, livraison et calcul sans besoin de mémoire.

| Cas | Résultat |
|---|---|
| Reprendre une facture sans refaire le travail | Sélection partielle : le dossier est trouvé, mais l’accusé de l’étape déjà accomplie est oublié |
| Adresse actuelle | Bonne version sélectionnée |
| Voyage à Rennes | Bon souvenir |
| Créer une mission dans l’interface | Bonne procédure d’aide |
| Compte de l’agenda | Bon compte |
| Préférence de repas | Bonne préférence |
| Destinataire d’un document | Bon contact |
| Calcul 7 × 8 | Souvenir de communication sélectionné alors qu’aucun rappel variable n’était nécessaire |

Résultat exact attendu : **6/8**. JSON lisible et identifiants appartenant aux candidats : **8/8**. Latence médiane observée : **1 005 ms** ; première requête : **2 426 ms** ; plage : **870 à 2 426 ms**.

C’est une exploration en un passage sur huit exemples choisis, pas un benchmark de qualité en production. Le comparateur lexical du script est volontairement simple et ne reproduit pas le moteur hybride d’Ely. L’essai ne mesure ni la qualité de la réponse finale, ni le gain de facturation, ni le comportement sous charge.

Le schéma JSON contraint la forme, pas la pertinence. L’oubli de l’étape de mission empêche de confier au modèle seul la continuité du travail. La seconde ajoutée à chaque tour serait aussi sensible sur les réponses déjà rapides.

Résultats reproductibles : `docs/evaluations/memoire-locale-2026-09-10.json`. Script autonome, utilisant uniquement des données fictives et le serveur local : `scripts/bench_memory_selection.py`. L’inventaire agrégé est conservé dans `docs/evaluations/memoire-inventaire-2026-09-10.json`.

## Architecture proposée

### 1. Une mémoire de travail durable par mission ou demande

Enregistrer les objectifs, décisions validées, étapes terminées, résultats structurés, identifiants des fichiers/messages/événements, prochaines actions et blocages. Chaque fait d’exécution pointe vers son accusé ou sa source.

Pour une mission en reprise, inclure obligatoirement : objectif actuel, dernière étape confirmée, actions encore incertaines et prochaine étape. Le petit modèle ne peut retirer ces éléments. Les accusés d’action ajoutés dans cette livraison fournissent une partie de cette base.

Après la fin de la mission, conserver un épisode synthétique qui dit ce qui a réellement été produit et où le retrouver. L’état « en cours » ne devient pas un trait permanent de l’utilisateur. Une tâche récurrente possède une mémoire commune de ses règles et une mémoire distincte pour chaque exécution.

### 2. Un profil stable, versionné et contextualisé

Chaque fait doit porter son propriétaire, son périmètre éventuel de projet/compte, sa provenance, sa date d’observation, sa validité et son niveau de confirmation. Une nouvelle adresse remplace l’ancienne dans le contexte courant ; l’ancienne reste disponible pour une question historique.

Une information extraite d’un document externe reste un fait issu de ce document. Elle ne devient pas automatiquement une consigne de l’utilisateur. Les permissions restent vérifiées dans les passerelles d’action, indépendamment des souvenirs et du modèle.

Conserver les traces originales dans les archives adaptées et indexer leurs résumés avec une référence. Une ancienne trace utile ne doit pas être supprimée uniquement parce qu’elle a plus de trente jours. Le vieillissement réduit sa priorité par défaut ; il n’efface pas sa valeur historique.

### 3. Un dossier variable adapté à la demande et à son origine

Entrée du sélecteur : identifiant utilisateur fiable, dernière demande humaine, mission/tâche/conversation concernée, compte Google ou intégration sollicitée, projet et état courant. Le canal est un indice de contexte, jamais une autorisation d’élargir l’accès.

Ordre proposé :

1. Appliquer les filtres d’accès, de périmètre et de validité avant toute recherche ou appel au petit modèle.
2. Charger directement les faits de travail obligatoires par identifiant.
3. Rechercher dans les faits, épisodes et documents avec embeddings et correspondances exactes. Réunir réellement les candidats lexicaux et vectoriels.
4. Dédupliquer les versions et regrouper les fragments d’une même source ; favoriser la diversité utile plutôt que cinq paraphrases du même souvenir.
5. Si les meilleurs candidats sont ambigus, autoriser un tri local sur 10 à 20 résumés courts. Retourner seulement leurs identifiants. Valider ces identifiants côté serveur.
6. Ajouter les faits obligatoires, puis remplir le budget avec les candidats retenus.
7. Fournir les références permettant à Ely de demander le détail à la demande, sans relire tout l’historique.

Le socle stable du prompt reste au début pour le cache. Le dossier lié à la question est ajouté ensuite et invalidé à la modification des faits concernés. Le cache doit être indexé par utilisateur, périmètre, requête normalisée et version mémoire ; un changement de mission ne doit jamais réutiliser le dossier d’une autre mission.

### 4. Des budgets explicites

Budgets initiaux proposés, à valider par mesure avec le tokenizer du modèle destinataire :

| Usage | Rappel variable cible |
|---|---:|
| Calcul, salutation, action évidente sans contexte passé | 0 token |
| Conversation ordinaire nécessitant des souvenirs | 800 à 1 500 tokens |
| Reprise de mission, avec état vérifié et preuves courtes | 1 200 à 2 500 tokens |
| Recherche approfondie demandée explicitement | Budget supplémentaire borné, avec lecture progressive des sources |

Ces cibles s’ajoutent au socle stable réduit et restent subordonnées à la capacité du modèle. Les permissions et les blocages obligatoires ne peuvent pas disparaître au profit d’un souvenir facultatif. Si leur taille dépasse la place disponible, réduire les autres blocs ou expliquer le blocage.

Pour le tri local, viser un délai cible inférieur à 300–500 ms sur les cas interactifs ; cette cible **n’est pas atteinte par l’essai 3B actuel**. En cas de lenteur ou de réponse invalide, utiliser immédiatement le classement déterministe. Ne pas réessayer le petit modèle en boucle et ne pas basculer discrètement cette sélection sur un service cloud.

### 5. Consolidation en arrière-plan et contrôle utilisateur

Déclencher la consolidation sur un changement utile : étape de mission confirmée, tâche terminée, fait corrigé, document indexé, fin d’échange substantiel. Dédupliquer ces événements comme les automatismes et enregistrer le dernier événement consolidé pour reprendre après une panne.

Le modèle local convient mieux ici : extraire des faits candidats, résumer un épisode et proposer des contradictions sans retarder la réponse. Les formats doivent distinguer fait confirmé, hypothèse, événement passé et prochaine action. Une répétition du même fait ne doit pas créer des milliers d’entrées nouvelles.

Dans **Mémoires**, ajouter une vue « Utilisé pour cette réponse » : souvenirs choisis, source, date, périmètre, raison du choix et coût en tokens. Prévoir correction, oubli, épinglage et changement de périmètre. La suppression doit invalider les index et caches correspondants, pas seulement masquer une ligne.

## Ordre de réalisation conseillé pour la mémoire

1. Corriger la requête de rappel et la recherche limitée aux 200 premières lignes ; ajouter des tests pour les identifiants exacts et changements de sujet.
2. Introduire un dossier de contexte par demande, avec budget commun, références, journal de sélection et état de mission obligatoire.
3. Ajouter versions, provenance et périmètres aux faits ; migrer progressivement les magasins existants avec possibilité de retour arrière.
4. Faire fonctionner le nouveau sélecteur en observation, sans modifier les réponses. Comparer les souvenirs sélectionnés à des annotations humaines sur au moins 100 cas variés, y compris une mémoire vide et les reprises après plusieurs jours.
5. Comparer le classement existant amélioré, un modèle de reclassement local et le 3B facultatif. Retenir ce qui augmente le rappel utile sans pénaliser la latence.
6. Activer progressivement, puis optimiser la liaison des outils et des procédures, qui pèse actuellement davantage que le seul profil mémoire.

Critères de validation : aucune fuite entre utilisateurs ou projets, aucun état confirmé omis lors d’une reprise, aucune action incertaine présentée comme faite, respect du budget, rappel des corrections récentes, absence de souvenirs sur les demandes qui n’en ont pas besoin. Mesurer séparément latence du rappel, tokens ajoutés, cache effectivement réutilisé, qualité des réponses et taux de répétition d’actions.

## Appuis techniques

La documentation [Qdrant sur les requêtes hybrides](https://qdrant.tech/documentation/search/hybrid-queries/) décrit la fusion de résultats et les recherches en plusieurs étapes. Elle fournit une option pour remplacer le simple renforcement lexical actuel, sans imposer une nouvelle base.

Le principe « retrouver des candidats, puis les reclasser » est documenté par [Sentence Transformers](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html). Un reclasseur local est une alternative à comparer au modèle génératif, pas une amélioration déjà mesurée dans Ely.

[LM Studio permet les sorties contraintes par schéma JSON](https://lmstudio.ai/docs/developer/openai-compat/structured-output), utilisées dans l’expérience. La validation des identifiants, des droits et du budget doit rester dans le programme.
