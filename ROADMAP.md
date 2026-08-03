# ROADMAP — ELY

> **Comment ce document est écrit.** Chaque ligne a été vérifiée dans le code
> le **02/08/2026**, pas reprise d'un plan. La version précédente de ce
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

| Chantier | Pourquoi il n'est pas fait | Ce qui manque, concrètement |
|---|---|---|
| **Photos & souvenirs** | Jamais commencé | Empreintes perceptuelles (pHash/dHash) pour les quasi-doublons, index CLIP local, scope Google Photos, page de tri par grappes. Tout doit rester **sur la machine** — c'est l'argument du chantier |
| **Automatisation web sans navigateur** | L'extension Chrome couvre l'interactif, pas le batch | `web_screenshot`, `web_to_pdf`, `web_extract`, `web_compare`. Playwright est déjà là ; il manque la surface d'exposition. Sert les tâches planifiées, qui ne peuvent pas dépendre d'un navigateur ouvert |
| **Graphe de connaissances personnel** | Jamais commencé | Extraction d'entités et de relations au fil des échanges, stockage SQLite, visualisation. Complète le RAG vectoriel actuel, ne le remplace pas |
| **Approbation intelligente** | **Bute sur un invariant** | Un classifieur qui auto-approuve le bénin. Mais le dépôt **échoue fermé** sur l'autorisation humaine (46 outils sous garde), et un classifieur qui se trompe fait exactement ce que cette règle interdit. À ne pas ouvrir sans rail de mesure |
| **Auto-réflexion en cours de mission** | Dépend de l'approbation intelligente | Un critique léger qui repère une stratégie qui tourne en rond et injecte une correction. La littérature documente des **régressions** ; sans mesure A/B et interrupteur, c'est du bricolage |
| **Porte prédictive sur les outils** | Jamais commencé | Prédire l'utilité d'un appel coûteux avant de le faire |
| **LoRA personnel par utilisateur** | Horizon long | Un adaptateur entraîné sur les traces de l'utilisateur, téléchargeable. Suppose un jeu de traces qualifiées que seule l'auto-réflexion produirait |

---

## Écarts assumés

Ce qui a été **volontairement** écarté, pour que personne ne le reprenne en
croyant à un oubli.

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
