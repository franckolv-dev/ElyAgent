# Client MCP — modèle de sécurité et de confiance

> Principe directeur : un serveur MCP est une **frontière de confiance**. Ses
> descriptions, annotations et résultats sont des **entrées non fiables**. Ely
> automatise la mécanique (connexion, découverte, adaptateurs) ; l'humain garde
> le contrôle de l'installation, des credentials, des droits et des actions
> sensibles. En cas de doute : **fail-closed** (on refuse).

## Invariants

1. **Identité utilisateur** — chaque appel est attribué à un utilisateur. Un
   serveur `scope=user` n'est utilisable que par son propriétaire (isolation
   multi-utilisateur). Les serveurs d'instance sont réservés à l'admin par
   défaut.
2. **Le modèle ne décide pas des permissions** — il propose un appel ; Ely
   l'autorise ou le bloque côté serveur (ACL `mcp_acl`).
3. **HITL par outil** — un outil `high`/`critical` exige une confirmation
   humaine avant tout envoi. La connexion autonome à un serveur distant et
   l'approbation d'un serveur local exigent aussi un consentement explicite.
4. **Credentials dans le Vault** — bearer / API key vivent dans le Vault du
   propriétaire (`credential_ref` = référence opaque). Jamais stockés dans les
   tables MCP, jamais renvoyés par l'API, jamais transmis au modèle ni
   journalisés.
5. **Namespace** `mcp__<slug>__<outil>` — aucun outil MCP ne peut masquer un
   outil natif d'Ely ; deux homonymes coexistent sans collision.
6. **Schémas sans perte** — les arguments sont validés contre le JSON Schema
   complet *avant* l'appel ; un argument non conforme est refusé sans
   contacter le serveur.
7. **Résultats bornés** — tous les blocs sont normalisés ; les binaires sont
   stockés hors contexte ; `_meta` n'est jamais transmis au modèle ; la taille
   est plafonnée.

## Garde réseau (serveurs distants)

`mcp_egress` protège contre le SSRF et le DNS rebinding, en trois couches :

- **URL** : HTTPS obligatoire, pas de credentials dans l'URL, hostnames
  internes (`localhost`, `*.local`, `metadata.google.internal`…) bloqués.
- **DNS** : refus si une seule IP résolue est loopback / link-local / privée /
  ULA / CGNAT / multicast / réservée / **métadonnées cloud** (IPv4 + IPv6,
  formes encodées comprises).
- **Transport** : la connexion est **épinglée sur l'IP validée** (Host + SNI/
  certificat conservés via l'extension `sni_hostname`), et **chaque
  redirection est re-validée** — pas de fenêtre TOCTOU.

Une exception LAN (`allow_private_network`) existe pour un serveur approuvé,
réservée à l'admin (hors V1 par défaut).

## Données sortantes

Un appel MCP est une **sortie de données vers un tiers** (`mcp_outbound`) :

- **Secrets** (clés API, tokens, clés privées, références `vault://`) →
  **bloqués** par défaut (fail-closed). Filet contre l'exfiltration d'un
  secret du Vault via un argument.
- **PII** (email, téléphone, IBAN, carte) → **tracées** (l'anonymisation
  aveugle casserait l'outil ; la décision dépend du serveur et du champ).

## Serveurs locaux (`stdio`)

Un serveur local = **code tiers exécuté** avec accès potentiel aux données et
au système d'Ely. V1 :

- **installation admin-only**, jamais automatique : le modèle ne fait que
  *proposer* (quarantaine) ; un humain approuve dans l'UI.
- environnement **filtré** (aucune clé d'Ely héritée), commande **sans shell**
  (exécutable + arguments séparés).
- **confinement durci** (conteneur/sandbox par serveur) = V2.

## Injection par contenu MCP

Les descriptions d'outils et les résultats peuvent contenir des instructions
visant le modèle (*prompt injection* / *tool poisoning*). Mitigations :
provenance explicite, contenu marqué non fiable, annotations **jamais** prises
pour argent comptant (le `risk_level` est déduit du nom/schéma, pas des
annotations), et HITL sur les actions sensibles.

## Ce qui reste en V2

OAuth 2.1 (PKCE/refresh/révocation), sandbox stdio durci, `resources`/
`prompts`/`sampling`/`roots`/`elicitation`, exceptions LAN généralisées,
serveurs **locaux** par-utilisateur.

## Voir aussi

- [Ely en tant que client MCP](mcp-as-client.md)
