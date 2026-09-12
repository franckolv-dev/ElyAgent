# Quels modèles locaux comparer pour Ely ?

État vérifié le **10 septembre 2026**. Cette sélection est une proposition d’essais, pas un classement de performances mesurées dans Ely. Elle accompagne les [40 scénarios de recette](plan-tests-ely-2026-09-10.md).

## Recommandation

Commencer avec **Qwen3.5 9B et Gemma 4 26B A4B déjà installés**. Ajouter en priorité **Ministral 3 14B Instruct 2512**, puis **Granite 4.1 8B**. Essayer ensuite **Qwen3.8 27B** comme candidat plus exigeant pour les missions complexes, si la mémoire disponible le permet.

Je ne remplacerais aucun modèle de production avant d’avoir comparé la qualité des actions, le français, les temps de réponse et la stabilité sur les mêmes scénarios. Un modèle prometteur sur une fiche éditeur peut rester moins utile dans Ely si ses appels d’outils sont mal interprétés ou si son chargement entraîne de l’attente.

## Machine et modèles effectivement présents

La machine consultée est un **Mac Studio M1 Max, 32 Go de mémoire unifiée**. L’inventaire ci-dessous vient de l’API locale de LM Studio ; il ne décrit pas d’éventuels modèles stockés ailleurs ou servis par une autre machine.

| Identifiant LM Studio relevé | Format / quantification | État lors de la lecture | Place dans la comparaison |
| --- | --- | --- | --- |
| `mistralai/ministral-3-3b` | GGUF Q4_K_M | Chargé, contexte 12 288 | Référence légère ; extraction de faits en arrière-plan |
| `gemma-4-e4b-it-mlx` | MLX 8 bits | Chargé, contexte 131 072 | Référence rapide de dialogue et d’actions simples |
| `mistralai/ministral-3-14b-reasoning` | GGUF Q4_K_M | Installé, non chargé | Planification et raisonnement ; mesurer le temps jusqu’au résultat |
| `qwen/qwen3.5-9b` | MLX 4 bits | Installé, non chargé | Premier candidat généraliste à tester sans téléchargement |
| `gemma-4-12b-it-mlx` | MLX 8 bits | Installé, non chargé | Français, documents et vision ; comparer aussi le coût mémoire |
| `google/gemma-4-26b-a4b` | MLX 4 bits | Installé, non chargé | Candidat pour l’exécution de missions à plusieurs étapes |
| `mistralai/devstral-small-2-2512` | MLX 4 bits | Installé, non chargé | Spécialiste pour les travaux de code et de fichiers |
| `text-embedding-nomic-embed-text-v1.5` | GGUF Q4_K_M | Installé, non chargé | Recherche vectorielle ; ce n’est pas un modèle conversationnel |

Tous les modèles conversationnels ci-dessus sont déclarés `tool_use` par LM Studio. Cette déclaration ne prouve pas qu’ils enchaînent correctement les outils d’Ely : le contrôle d’intégration ci-dessous reste nécessaire.

Gemma 4 inclut l’appel de fonctions ; le 26B A4B active une partie de ses paramètres à chaque génération, mais doit garder les poids de l’ensemble en mémoire. Son nom ne signifie donc pas qu’il occupe la mémoire d’un modèle 4B. [Documentation Google](https://ai.google.dev/gemma/docs/core).

Devstral Small 2 est spécialisé dans les travaux de développement. Je le testerais pour analyser ou modifier un petit projet, sans en faire par défaut le modèle du dialogue général. [Fiche Mistral](https://docs.mistral.ai/models/devstral-small-2-25-12).

## Trois téléchargements utiles

### 1. Ministral 3 14B Instruct 2512 — mon premier ajout

**À chercher :** `Ministral-3-14B-Instruct-2512-GGUF`, publié par `mistralai`. Choisir **Q4_K_M** pour commencer ; Q5_K_M pourra être comparé si la mémoire reste confortable. Ce n’est pas la variante Reasoning déjà installée.

Le modèle annonce le français, les appels de fonctions et les sorties JSON. Le dépôt officiel propose un Q4_K_M de **8,24 Go** et un Q5_K_M de **9,62 Go** ; ces tailles de fichiers ne sont pas l’empreinte totale à l’exécution. [Modèle et téléchargements officiels](https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512-GGUF).

**Mon hypothèse à tester :** un meilleur équilibre entre qualité, temps de réponse et exécution que le 3B, et moins de raisonnement superflu que le 14B Reasoning pour les demandes ordinaires. Comparer surtout S04, S05, S13, S21 à S25, puis S35 à S40. Aucune supériorité dans Ely n’est encore mesurée.

### 2. Granite 4.1 8B — un concurrent léger pour les outils

**À chercher :** `ibm-granite/granite-4.1-8b-GGUF`. Commencer par une variante 4 bits proposée dans le dépôt ; garder la même variante pendant la première campagne. Ne pas prendre le modèle `base`.

IBM présente ce modèle comme un assistant avec appel d’outils, extraction et recherche documentaire, avec le français parmi les langues prises en charge. C’est une autre famille à comparer aux modèles déjà présents. [Fiche officielle](https://huggingface.co/ibm-granite/granite-4.1-8b), [GGUF officiel](https://huggingface.co/ibm-granite/granite-4.1-8b-GGUF).

**Mon hypothèse à tester :** un bon candidat aux tâches structurées, avec une charge plus modérée qu’un 27B. Vérifier particulièrement les noms d’outils, les arguments exacts, les demandes de précision et la qualité du français. Cela peut aussi devenir un candidat à l’extraction de souvenirs, mais uniquement si le gain justifie son coût face au 3B.

### 3. Qwen3.8 27B — pour tester le plafond de qualité local

**À chercher :** `Qwen3.8-27B` dans le catalogue LM Studio, en **MLX 4 bits** ou **GGUF Q4_K_M** selon les variantes disponibles dans le moteur installé. Le dépôt Qwen d’origine contient les poids Transformers ; il faut sélectionner une conversion compatible pour LM Studio, pas télécharger les poids pleine précision par défaut. [Entrée LM Studio](https://lmstudio.ai/qwen/qwen3.8-27b), [modèle original](https://huggingface.co/Qwen/Qwen3.8-27B).

Qwen annonce des améliorations pour les tâches longues avec outils et un raisonnement réglable. **Mon hypothèse à tester :** un gain sur les missions complexes, à confronter au Gemma 4 26B A4B déjà présent. Ce n’est pas une promesse de meilleur fonctionnement sur le M1 Max.

Sur 32 Go, ce candidat est plus contraignant : le charger seul pour le premier essai, avec une fenêtre de contexte modérée. Surveiller la mémoire totale, y compris les services Ely. Si le système commence à échanger fortement avec le disque ou si les délais deviennent gênants, le conserver comme essai ponctuel plutôt que modèle permanent.

## Formats et réglages de départ

Ces réglages sont un **protocole de départ proposé**, pas une mesure de performance ni une garantie que chaque option est exposée par tous les moteurs.

| Paramètre | Proposition |
| --- | --- |
| Modèles chargés | Un candidat à la fois pour la comparaison isolée ; tester ensuite la cohabitation réelle avec les autres services |
| Contexte | Commencer à 16 384 tokens si la requête complète tient, puis 32 768 pour les finalistes et les longues missions |
| Vérification du contexte | Inclure système, historique, mémoire, schémas d’outils et marge de sortie ; augmenter ou marquer B si cela ne tient pas, sans supprimer les preuves obligatoires |
| Format | Partir du format déjà installé ; comparer MLX/GGUF seulement sur les finalistes, à quantification comparable |
| Quantification | 4 bits en première intention ; comparer 5/8 bits sur un modèle finaliste si le gain de qualité justifie la mémoire |
| Raisonnement | Variante Instruct pour les tâches courantes ; comparer raisonnement activé/désactivé quand le modèle et le moteur le permettent |
| Génération | Suivre les réglages publiés pour le modèle et enregistrer les valeurs réellement appliquées ; ne pas imposer une température unique à toutes les familles |
| Répétitions | Trois essais par scénario et configuration, mêmes données et mêmes budgets ; une première mesure à froid séparée des mesures après chargement |

Mistral recommande une température inférieure à 0,1 pour l’usage quotidien de Ministral 3 Instruct. À l’inverse, Qwen3.8 publie des réglages différents selon le mode de raisonnement. Utiliser le profil adapté, puis changer un seul facteur à la fois. Vérifier que LM Studio et l’adaptateur Ely transmettent effectivement l’option : le nom d’un paramètre dans la fiche du modèle ne prouve pas sa prise en charge locale. [Réglages Ministral](https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512-GGUF#recommended-settings), [réglages Qwen](https://huggingface.co/Qwen/Qwen3.8-27B#api-usage).

Le Gemma E4B actuellement chargé annonce une fenêtre de 131 072 tokens. Cela ne prouve pas que toute cette mémoire est préallouée, ni que cette fenêtre est utile à Ely. Mesurer l’usage réel avec un contexte plus court fait partie de la comparaison. Ne pas modifier les réglages de production au milieu d’une mission.

Sur cette machine, je ne commencerais pas par des modèles denses 70B ou par un gros mélange d’experts : les paramètres actifs indiquent surtout une partie du travail de calcul, pas la taille de tous les poids à stocker. Je n’installerais pas non plus toute la gamme Qwen intermédiaire avant d’avoir comparé le 9B présent et le 27B proposé.

## Contrôler d’abord l’intégration des outils

Avant les scénarios utilisateur, faire ces essais **avec des outils factices, sans effet externe**, sur la même API et le même moteur que ceux employés par Ely. Ils demandent une petite recette technique ; ce document ne fournit pas encore un programme qui les exécute automatiquement.

| Contrôle | Mise en situation | Réussite attendue |
| --- | --- | --- |
| T01 — Un appel valide | Proposer `meteo_test(ville)` et demander la météo de Poitiers | Véritable appel structuré avec le bon argument ; pas seulement du JSON affiché dans une phrase |
| T02 — Exploiter le retour | Renvoyer à T01 une température fictive de 12 °C | Réponse fondée sur 12 °C, sans rappeler le même outil indéfiniment |
| T03 — Enchaîner | Premier outil renvoyant un identifiant, deuxième outil exigeant cet identifiant | Identifiant réel transmis au deuxième appel, puis résultat final |
| T04 — Respecter une erreur | Outil renvoyant un échec d’écriture | Aucune annonce de création réussie ; reprise justifiée ou explication |
| T05 — Découvrir un outil | Fournir un outil de découverte qui révèle une fonction d’abord absente, puis l’ajouter au tour suivant | Découverte, appel de la fonction ajoutée, exploitation du résultat |
| T06 — Arguments incomplets | Action factice exigeant une date, absente de la demande | Question utile ou abstention ; aucune date inventée |

Répéter aussi T01–T03 avec la diffusion progressive utilisée par Ely si le premier essai était sans diffusion. Vérifier la correspondance des identifiants d’appels et des réponses d’outils. La fiche LM Studio explique la distinction entre appels structurés et sortie textuelle et le rôle du traitement des réponses. [Documentation des outils LM Studio](https://lmstudio.ai/docs/developer/openai-compat/tools).

Si un modèle affiche un appel d’outil en texte brut, conserver la sortie et vérifier le moteur, le format et le modèle de conversation avant de conclure qu’il ne sait pas utiliser les outils. Cette défaillance d’intégration reste néanmoins éliminatoire pour son utilisation immédiate dans Ely.

## Distinguer le modèle seul de l’application complète

**Campagne A — Modèle local :** sur une instance de recette, imposer le candidat au traitement des demandes et désactiver les bascules automatiques vers d’autres modèles pour cette campagne. Conserver les mêmes outils, droits, critères de réussite et données. La préparation peut nécessiter une configuration technique ; il n’est pas affirmé qu’un bouton unique existe dans l’interface.

**Campagne B — Ely en fonctionnement normal :** rétablir les modèles de secours et le routage habituel. Mesurer le résultat utilisateur, les coûts éventuels et les délais cumulés. Un succès après reprise par un modèle distant est un succès d’Ely, mais pas une réussite autonome du modèle local testé.

Dans les deux cas, contrôler les modèles **réellement appelés à chaque étape**, y compris l’extraction de mémoire et les éventuels vérificateurs. Pour isoler le candidat conversationnel, garder ces composants annexes fixes et les déclarer dans le compte rendu. Restaurer également les procédures apprises et les caches entre campagnes comparatives.

## Et pour la mémoire ?

Conserver comme référence la sélection hybride actuelle, sans ajout d’un LLM à chaque demande. Le précédent comparatif portait sur **120 formulations fictives issues de 12 intentions**, pas sur 120 situations utilisateur indépendantes ; le Ministral 3B n’améliorait pas la sélection et ajoutait du délai. [Rapport de mise en œuvre](memoire-ely-implementation-2026-09-10.md).

Évaluer séparément deux travaux :

- **Retenir les bons faits en arrière-plan :** comparer le 3B actuel, Gemma E4B, Qwen3.5 9B et éventuellement Granite 8B sur des échanges fictifs annotés. Compter faits inventés, faits manqués, mauvais périmètres, corrections mal reconnues et délai avant disponibilité. Les scénarios S16–S20 et S34/S39 contrôlent ensuite leur effet dans Ely.
- **Choisir le contexte d’une demande :** comparer d’abord la sélection existante aux jugements humains. Un modèle supplémentaire ne sera intéressant que s’il améliore les réponses finales, sans retirer une preuve obligatoire ni dépasser un budget de délai fixé avant l’essai.

Ne pas changer de modèle d’embeddings pendant la comparaison des modèles conversationnels : cela changerait simultanément la recherche. Le Nomic installé n’est pas automatiquement meilleur que le moteur d’indexation actuel ; son adoption demanderait une évaluation distincte et une réindexation compatible, sans mélanger des espaces vectoriels différents.

## Décision à prendre après les tests

Retenir idéalement un modèle pour les demandes courantes et un candidat pour les missions exigeantes, seulement si les mesures montrent que cette distinction apporte un gain. Évaluer aussi le coût du chargement lors du passage de l’un à l’autre.

Mon ordre pratique est : **Qwen3.5 9B déjà présent → Ministral 3 14B Instruct à installer → Gemma 4 26B A4B déjà présent → Granite 4.1 8B à installer → Qwen3.8 27B à installer si la marge mémoire le permet**. Gemma E4B et Ministral 3B servent de références légères ; les autres modèles présents complètent les essais spécialisés.

Le meilleur choix sera celui qui termine les demandes utiles de façon fiable, dans un délai acceptable, avec le moins de corrections et de faux succès. Ce document n’attribue encore ce titre à aucun candidat.
