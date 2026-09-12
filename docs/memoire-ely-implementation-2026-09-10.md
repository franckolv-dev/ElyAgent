# Mémoire d’Ely : réalisation et comparaison des méthodes

## Choix retenu

Le contexte varie avec la demande humaine. La sélection principale utilise une **union réelle des résultats vectoriels et lexicaux, fusionnés par rang (RRF)**. Aucun second appel à un modèle génératif n’est ajouté aux réponses interactives.

Le reclasseur et le modèle 3B ont été testés localement. Sur les exemples de cette évaluation, leur coût supplémentaire ne se justifie pas. Les modèles locaux restent utilisés pour extraire des faits stables en arrière-plan. L’état de mission et les preuves sont lus directement dans la base, indépendamment du modèle.

## Comparaison reproductible

Script : `scripts/bench_memory_methods.py`. Résultats détaillés : `docs/evaluations/memoire-comparatif-2026-09-10.json`.

120 demandes françaises fictives : **12 intentions, chacune formulée 10 fois**, avec 12 souvenirs candidats. Les réponses attendues sont définies dans le script. Il ne s’agit ni de 120 situations indépendantes, ni d’annotations humaines de conversations réelles. Aucun souvenir personnel n’a été envoyé aux modèles pendant ce benchmark.

| Pipeline | Bon premier résultat ou abstention correcte | Résultat utile parmi les 3 premiers |
|---|---:|---:|
| Recherche dense initiale | 105/120 | 110/120 |
| FTS5 + vecteurs + RRF, avec filtre des calculs | **119/120** | **120/120** |
| Fusion native Qdrant + filtre des calculs | 112/120 | 120/120 |
| Reclasseur MiniLM après récupération + filtre | 118/120 | 120/120 |
| Ministral 3B, identifiants sous schéma JSON + filtre | 109/120 | 109/120 |

Le modèle génératif a produit un JSON valide avec des identifiants autorisés dans 120/120 cas. La forme correcte ne garantit donc pas la pertinence. Le filtre des calculs est programmatique et appliqué aux nouveaux pipelines. La ligne dense représente le comportement antérieur sans ce filtre : son écart ne mesure pas uniquement la qualité du moteur de recherche.

Mesures sur cette machine, modèles chargés :

- Récupération locale FTS5 + Qdrant : médiane **4,4 ms**, p95 **5,7 ms** dans ce petit corpus en mémoire.
- Reclasseur `Xenova/ms-marco-MiniLM-L-6-v2` : **91,6 ms** supplémentaires en médiane ; p95 **107,6 ms**.
- `mistralai/ministral-3-3b` : **679,8 ms** supplémentaires en médiane ; p95 **728,4 ms** ; première requête environ **3,2 s**. Aucune requête sous 500 ms.
- Fusion native Qdrant : environ **0,94 ms** pour la requête de fusion seule, embeddings exclus.

La fusion native a réellement été exécutée avec `Prefetch` et `FusionQuery(RRF)`. Sa représentation lexicale est un vecteur sparse binaire simple ; celle du pipeline retenu est FTS5/BM25. Ce n’est donc pas une comparaison isolée de deux implémentations mathématiques de RRF. Le reclasseur testé est principalement anglophone ; ce test ne prouve pas qu’aucun reclasseur multilingue ne puisse apporter un gain. Les sorties 3B sont réutilisées au recalcul final des métriques, sans inventer de nouvelles mesures de latence.

Ces résultats justifient **le choix conservateur du pipeline déjà compatible avec les index d’Ely**, amélioré par une vraie union. Ils ne prouvent pas une qualité parfaite sur les demandes réelles ni une réduction donnée de la facture LLM.

## Observation sur une copie de la configuration réelle

Quatre demandes ont été préparées sans appeler de LLM et sans exécuter d’outils. Les contextes mesurés respectent le plafond : 0 token pour « Bonjour », environ 1 300 pour les demandes contextuelles. Les répétitions avec cache prennent environ 25–30 ms. Le chargement initial du modèle prend plusieurs secondes ; l’encodeur est maintenant préparé au démarrage du serveur pour éviter ce coût sur la première question.

Sur le catalogue complet chargé pour cette observation, la sélection conserve 48 outils sur 214, dont `find_tool`, et réduit leurs schémas de 37 895 à 7 969 tokens de référence. Ce n’est pas une réduction mesurée sur tous les tours réels : les profils, les réparations et les découvertes font varier la sélection. Résultats agrégés sans contenu personnel : `docs/evaluations/memoire-observation-2026-09-10.json`.

## Fonctionnement livré

### Contexte par demande

- Dernière demande humaine utilisée, y compris après un résultat d’outil et lors d’un repli de modèle.
- Même dossier pour les modèles locaux compacts et les autres modèles ; les preuves ne sont plus tronquées par l’ancien format compact.
- Calcul ou salutation isolée : aucun rappel variable. Une question personnelle reste couverte sur la voie rapide.
- Profil SQL sans élimination arbitraire des lignes au-delà de la 200e ; reconnaissance des clés séparées par des underscores et des références comme `FAC-42`.
- Faits, épisodes, documents et procédures sélectionnés avec références. Les procédures sont décrites brièvement ; `skill_view` permet de charger le détail.
- Budgets maximum de **1 400 tokens de référence** en conversation et **2 400** en mission, enveloppe comprise. Tokenizer `cl100k_base`, préparé à la construction de l’image. C’est un compteur de référence, pas le tokenizer ni la facturation de chaque fournisseur.
- Déduplication des textes et limitation des fragments d’une même source. Les permissions restent vérifiées dans les passerelles d’actions.

### Continuité de travail

Le dossier obligatoire contient l’objectif, l’état courant, la dernière étape confirmée avec son accusé, le nombre et les références des écritures incertaines, la question en attente ou la conduite à tenir, et les critères de réussite.

Le sélecteur ne peut retirer ce dossier. Une écriture incertaine reste distincte d’un succès. Si les informations obligatoires dépassent le budget, la mission est suspendue pour vérification. Le carnet et les accusés complets restent disponibles ; le dossier ne prétend pas remplacer les archives.

### Versions et périmètres

Le profil existant demeure la source canonique. Une migration additive crée le journal de sélection, les versions historiques et les checkpoints. Un déclencheur SQLite conserve les valeurs remplacées par tous les chemins d’écriture du profil.

Les faits du profil disposent d’une provenance, d’une confirmation, d’un périmètre et d’un épinglage. Plusieurs valeurs d’une même clé peuvent appartenir à des périmètres distincts. Les anciennes valeurs ne participent au rappel SQL que sur une demande explicitement historique.

Le périmètre personnel peut être restreint à une mission ou à un compte Google possédé par l’utilisateur. Le contexte de compte est activé lorsqu’un compte est explicitement nommé dans la demande ; il ne constitue jamais une permission d’agir sur ce compte. Les projets sans mission ni compte associé ne disposent pas d’une nouvelle entité « projet mémoire » dans cette livraison.

Les index dérivés peuvent être en retard : leurs résultats de profil sont relus dans SQL avant injection. Une correction ou suppression ne peut ainsi être annulée par un ancien vecteur. Les faits SQL sont indexés progressivement, 64 modifications par passage. Les documents déjà présents reçoivent progressivement leur index lexical, 128 fragments par passage.

### Cache et consolidation

Le préfixe stable du prompt et les embeddings restent réutilisés. Le cache de recherche, limité à 256 entrées et 30 secondes, inclut utilisateur, périmètre, requête, source et version locale des index. Les écritures, corrections et suppressions invalident les entrées concernées. Les profils canoniques, leur validité et les accusés sont relus ; aucun dossier de mission n’est figé pour toute la conversation.

La consolidation parcourt les états durables toutes les minutes : missions et accusés, tâches terminées, index dérivés et conversations mises en attente d’extraction. Un identifiant déterministe et un checkpoint évitent de dupliquer un épisode après un redémarrage. Une conversation en attente peut être reprise après une panne ; trois échecs enregistrés mettent son extraction en échec plutôt que de boucler indéfiniment. Le modèle local n’est pas autorisé à transformer une déclaration de réussite en preuve.

L’ingestion des documents met à jour leur index lexical et invalide le cache. Les extractions de faits stables restent distinctes des états de mission. Le rappel ne supprime pas les faits uniquement parce qu’ils sont anciens.

### Contrôle utilisateur et descriptions d’outils

Dans **Analyse → Mes mémoires** : profil consolidé, correction, choix du périmètre, épinglage, oubli et panneau « Utilisé pour cette réponse ». Ce panneau présente les contextes préparés, sources, raisons, dates et tokens. Il garde les 200 dernières sélections distinctes par utilisateur ; 20 sont présentées à l’ouverture. Corriger ou oublier efface les extraits de journal concernés par l’invalidation et les anciennes versions de l’entrée oubliée.

Les schémas d’outils facultatifs sont limités à un budget de référence de 8 000 tokens. `find_tool`, `skill_view`, `memory_recall`, les outils explicitement requis, les réparations d’incidents et les outils découverts sont préservés. Ces éléments obligatoires peuvent dépasser ce budget : l’optimisation ne doit pas réintroduire les capacités invisibles. Les préférences de désactivation sont appliquées après la sélection.

## Validation et limites

**160 tests backend ciblés et 70 tests frontend passent**, ainsi que TypeScript et les contrôles de confidentialité. Les tests couvrent les changements de sujet, la correction immédiate, l’expiration, les références lexicales seules, les faits situés après la 200e ligne, le propriétaire et le périmètre, l’oubli des versions, le cache, les preuves obligatoires, les écritures incertaines et la préservation des outils découverts/réparés.

La migration a été répétée sur une copie de la base réelle. Les 599 références de messages orphelines déjà présentes avant cette intervention restent identiques après migration ; aucune donnée utilisateur n’a été supprimée pour les masquer.

Les essais navigateur utilisent des données fictives et couvrent ordinateur/mobile, journal, correction, périmètre, épinglage et oubli. Le plugin Browser n’étant pas disponible, ces contrôles utilisent Playwright.

Le modèle local de consolidation préexistant reste un extracteur imparfait. Les anciennes données ne possèdent pas toutes une provenance détaillée ou un historique antérieur à la migration : ils ne sont pas inventés. Les scores du benchmark ne remplacent pas un suivi des réponses réelles et des reprises de missions. Aucun email ni message Telegram réel n’a été envoyé pour les tests.

Retour arrière : images `ely-backend:before-memory-20260910` et `ely-frontend:before-memory-20260910`, sauvegarde `data/db/backups/before-memory-20260910-final.db`. Une restauration de données demande de tenir compte des écritures postérieures. Le downgrade refuse de fusionner destructivement des valeurs de même clé appartenant à plusieurs périmètres.

## Sources techniques vérifiées

- [Qdrant — Hybrid and Multi-Stage Queries](https://qdrant.tech/documentation/search/hybrid-queries/) : fusion des résultats et API multi-étapes.
- [Sentence Transformers — Retrieve & Re-Rank](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html) : récupération puis reclassement des candidats.
- [LM Studio — Structured Output](https://lmstudio.ai/docs/developer/openai-compat/structured-output) : sorties contraintes par schéma JSON.


## Mise en service

La migration `0039_memory_context` est appliquée. Les API Mémoires authentifiées répondent 200 ; une requête sans authentification est refusée avec 401. L’intégrité SQLite est correcte. Les versions du modèle de confidentialité sont conservées : GLiNER 0.2.28, Transformers 5.13.1, Torch 2.14.0.

L’indexation initiale a traité les **619 profils de l’ensemble de cette instance**, sans mélanger leurs propriétaires. Le rattrapage lexical des documents est terminé. Les extractions en arrière-plan conservent un état d’échec et peuvent être reprises ; une indisponibilité du stockage n’est plus comptée comme une conservation réussie.

Le guide `docs/guide-memoire-ely.md` est indexé pour le compte de Franck (3 fragments). Les trois recherches naturelles sur la correction, le périmètre et le journal retrouvent le guide. Le parcours navigateur a été rejoué sur l’interface publiée, avec les opérations simulées : aucune modification d’un souvenir personnel réel pour la recette.
