# ROADMAP — ELY

> **Comment ce document est écrit.** Chaque ligne a été vérifiée dans le code
> le **24/08/2026**, pas reprise d'un plan. La version précédente de ce
> fichier — 392 lignes, douze sprints — a été archivée hors dépôt en [#308]
> parce qu'elle était périmée : cinq de ses chantiers marqués « à faire »
> tournaient déjà en production. Un markdown périmé est **pire qu'absent**, il
> oriente sur une fausse piste avec assurance.
>
> D'où la règle de ce fichier : **court, daté, et dérivé du code**. Le lien
> interne de chaque document est épinglé par `backend/tests/
> test_docs_match_the_code.py` — une référence qui pourrit fait rougir la CI.

[#308]: https://github.com/franckolv-dev/ElyAgent/pull/308

---

## Ce qui reste à faire

Par ordre de maturité, pas de date : les dates de l'ancienne roadmap étaient
toutes dépassées, ce qui ne renseignait plus personne.

### Deux mesures avant tout chantier

Elles ne demandent presque pas de code, et elles décident du reste.

| Chantier | Pourquoi maintenant |
|---|---|
| **Banc d'essai de la voie cloud** | C'est le plus gros levier de coût qui reste. La voie cloud lie le catalogue **entier** à chaque itération — un tour mesuré le 23/08 a coûté 223 693 tokens sur six itérations. Lui appliquer la discipline de la voie locale diviserait la facture. ⚠️ Mais la [#323] a **mesuré** que brancher tout le catalogue faisait passer les cas hors d'atteinte de 0 % à 86,7 %. Défaire ça sans banc serait prendre une hypothèse pour un constat. `bench/` existe pour ça |
| **Seconde mesure d'usage des outils** | La première (`usage_logs.skill_used`, huit mois) montre 115 outils jamais appelés sur 200. Elle est **inexploitable telle quelle** : elle a été collectée pendant que `find_tool` se trompait une fois sur deux et que la voie locale n'avait aucun outil. « 0 appel » y mesure autant nos défauts que l'utilité de l'outil. La même requête, relancée deux semaines après la 2.5.0, vaudra dix fois plus |

[#323]: https://github.com/franckolv-dev/ElyAgent/pull/323

### Les chantiers

| Chantier | Pourquoi il n'est pas fait | Ce qui manque, concrètement |
|---|---|---|
| **Auto-réflexion en cours de mission** | ⚠️ **À moitié fait — voir ci-dessous** | Le détecteur de stagnation existe et tourne. Il manque l'action corrective |
| **Photos & souvenirs** | Jamais commencé | Empreintes perceptuelles (pHash/dHash) pour les quasi-doublons, index CLIP local, scope Google Photos, page de tri par grappes. Tout doit rester **sur la machine** — c'est l'argument du chantier |
| **Graphe de connaissances personnel** | Jamais commencé | Extraction d'entités et de relations au fil des échanges, stockage SQLite, visualisation. Complète le RAG vectoriel actuel, ne le remplace pas |
| **Approbation intelligente** | **Bute sur un invariant** | Un classifieur qui auto-approuve le bénin. Mais le dépôt **échoue fermé** sur l'autorisation humaine (46 outils sous garde), et un classifieur qui se trompe fait exactement ce que cette règle interdit. À ne pas ouvrir sans rail de mesure |
| **Porte prédictive sur les outils** | Jamais commencé | Prédire l'utilité d'un appel coûteux avant de le faire |
| **LoRA personnel par utilisateur** | Horizon long | Un adaptateur entraîné sur les traces de l'utilisateur, téléchargeable. Suppose un jeu de traces qualifiées que seule l'auto-réflexion produirait |

⚠️ **L'auto-réflexion était mal décrite, et le chantier est plus petit qu'annoncé
(vérifié le 24/08).** L'entrée disait « un critique léger qui repère une
stratégie qui tourne en rond **et** injecte une correction » — deux choses, et
la première existe :

- `conformity.is_making_progress` décide de la relance depuis la [#289], qui a
  **mesuré** qu'un compteur fixe (« après 3 tentatives ») était mauvais et l'a
  remplacé par le progrès réel ;
- `conformity.py` branche `escalation.should_escalate` sur ce même signal.

Ce qui manque n'est donc pas le détecteur : c'est **quoi en faire**. Aujourd'hui
la stagnation déclenche un **panel de modèles en lecture seule** — il améliore
une réponse, jamais le résultat d'un outil. Injecter une correction dans le tour
en cours est un autre geste, et c'est celui-là qui reste.

⚠️ Et `mission_critic` ne compte pas : c'est un **post-mortem**, il lit la trace
*après* la fin de la mission. 1 628 appels au compteur, et zéro aide au tour en
cours.

---

## Livré depuis

### La voie locale devient empruntable — 24/08 (v2.5.0)

Sur une même question — « trouve des sites comme Babelio » :

```
avant   223 693 tokens   72,6 s   gpt-5.6-sol   catalogue entier
après     2 017 tokens    5,0 s   gemma-4-E4B   3 outils
```

Le tier A existait depuis des semaines et **n'avait jamais servi**. Six défauts
se tenaient, et le premier explique les autres :

- **Le routeur envoyait au local ce que le local ne pouvait pas faire.** Les
  motifs qui font *baisser* le score de complexité — météo, agenda, mails,
  recherche, itinéraire, traduction — sont **tous des besoins d'outils**, et la
  voie locale n'en avait aucun depuis le 21/08. Elle reçoit désormais un socle
  de trois outils plus ce que la demande réclame, choisis par expressions
  régulières, sans inférence supplémentaire.
- **Le routeur notait le retour d'outil, pas la demande.** Dès le second tour,
  `messages[-1]` est le résultat de l'outil — long et truffé d'URL, donc +35 au
  score. Le tour repartait au cloud **exactement au moment où le modèle local
  allait se servir de ce qu'il venait de trouver**.
- **Un appel d'outil écrit en texte n'est plus une réponse** : il est traité
  comme un échec de la voie locale, annoncé, et le tour repart au cloud.
- **Un tour sans voie locale laisse une trace**, avec sa raison. Sans elle, « le
  local a-t-il essayé ? » était une question sans réponse.
- **`Paramètres → Outils`** montre ce que chaque outil coûte et ce qu'il a
  servi, et permet de le couper — compétence par compétence *ou* outil par
  outil.
- **Une procédure apprise est une capacité** : `find_tool` cherche aussi dans
  les playbooks, et la branche « compétence » de l'aiguillage écrit enfin ce
  qu'elle décidait déjà.

⚠️ **La leçon de ce lot, qui vaut pour la suite : quatre fois ce mois-ci, une
écriture a atteint la base sans atteindre le runtime** ([#272], [#336], [#342],
[#346]). L'écran affichait la bonne valeur, l'API la rendait, et le
comportement suivait l'ancienne. C'est la classe de défaut la plus chère du
dépôt, parce qu'aucune des surfaces d'observation ne ment.

[#272]: https://github.com/franckolv-dev/ElyAgent/pull/272
[#289]: https://github.com/franckolv-dev/ElyAgent/pull/289
[#336]: https://github.com/franckolv-dev/ElyAgent/pull/336
[#342]: https://github.com/franckolv-dev/ElyAgent/pull/342
[#346]: https://github.com/franckolv-dev/ElyAgent/pull/346

### Automatisation web sans navigateur — 22/08 (v2.4.0)

`web_screenshot`, `web_to_pdf`, `web_extract`, `web_compare` : une URL entre,
un résultat sort, sans session de navigation.

⚠️ **Cette ligne de roadmap était inexacte, et le vérifier a évité d'écrire
deux outils en double.** Elle disait « l'extension Chrome couvre l'interactif,
pas le batch » ; en réalité `browser_skill` exposait déjà une capture et une
extraction côté serveur, via Playwright. Le manque réel était plus étroit :
ces outils travaillent sur la page **courante d'une session**, ce qu'une tâche
planifiée n'a pas. C'est l'isolement qui manquait, pas Playwright.

La leçon vaut pour les lignes qui restent : **une entrée de roadmap est une
hypothèse sur l'état du code, pas un constat.** Celle-ci avait été écrite le
02/08 en vérifiant l'absence des noms `web_*`, ce qui était vrai — et
insuffisant. L'entrée « auto-réflexion » ci-dessus vient d'être corrigée pour
la même raison.

---

## Écarts assumés

Ce qui a été **volontairement** écarté, pour que personne ne le reprenne en
croyant à un oubli.

- **Les outils intégrés ne migrent pas vers des playbooks.** Écarté le 24/08
  après lecture des sources d'Hermes, qui répond à la croissance du catalogue
  en faisant des capacités auto-créées des **documents** (`SKILL.md`), pas des
  outils. Le modèle est bon et il est déjà porté ici — mais il ne peut pas
  s'appliquer aux outils *existants* : la garde humaine d'Ely s'applique **par
  nom d'outil**, et un playbook qui dirait « exécute ce code pour envoyer le
  mail » n'a aucun nom à garder. La table de sécurité s'effondrerait. Un pin de
  contrat verrouille ce choix.

- **Mémoire spatiale** (lieux de l'utilisateur, géolocalisation). Prévue par
  l'ancienne roadmap comme cinquième type de mémoire, elle a été remplacée à
  la conception par la mémoire d'**erreur**. La réintroduire coûte une table,
  une révision Alembic, du chiffrement et un consentement RGPD explicite —
  pour un besoin que rien n'a encore réclamé. Écartée, pas oubliée.

- **Mémoire procédurale : pas de magasin, et c'est définitif.** Elle est
  *lisible* depuis le 02/08, mais sa source est le **registre d'outils**, relu
  à la volée par la voie de `find_tool`. Lui donner sa propre table aurait
  ouvert un second chemin de découverte d'outils, sans sélecteur local ni
  consignation des capacités manquantes. Voir l'avertissement dans
  `backend/app/services/memory/ROUTING.md`.

- **Superviseur et sous-agents.** Cette architecture a existé et a été
  **retirée** après un banc d'essai A/B perdu sur les quatre critères mesurés.
  Ne pas la réintroduire sans mesure.

- **Client terminal (TUI).** Régression face à l'interface web. N'arrivera pas.

---

## Ce que cette roadmap promet de ne pas faire

- **Pas de télémétrie sortante.** Ce qu'Ely apprend reste sur la machine de
  son propriétaire.
- **Pas d'action irréversible sans accord humain.** Un outil non classé est
  traité comme engageant — la règle échoue fermé, jamais ouvert.
- **Pas de repli silencieux.** Un mécanisme dégradé annonce qu'il en est un.
  Un fournisseur de secours qui se présente comme nominal fait conclure que
  le sujet n'existe pas.

---

## Voir aussi

- [CHANGELOG.md](./CHANGELOG.md) — l'historique daté, avec les SHA
- [docs/architecture.md](./docs/architecture.md) — le fonctionnement interne
- [CONTRIBUTING.md](./CONTRIBUTING.md) — comment proposer un changement
