# ELY Agent — Sécurité

> La sécurité est le pilier fondamental d'ELY. Beaucoup d'agents IA grand
> public privilégient l'expérience utilisateur au détriment de la
> sécurité — ELY est conçu avec une approche **security-first** dès le
> design : chaque tool a un coût, chaque coût est validé.

## Principes fondamentaux

1. **Aucune action irréversible sans validation humaine**
2. **Les données sensibles ne quittent jamais le périmètre local** (anonymisation avant envoi au LLM)
3. **L'agent apprend de ses erreurs** (contraintes de sécurité persistantes)
4. **Chaque canal a le même niveau de sécurité** (pas de raccourci pour Telegram vs Web)
5. **Least privilege** — l'agent ne peut faire QUE ce qui est explicitement autorisé

---

## Couches de sécurité

### 1. Authentification

- **JWT** avec `access_token` (60 min) + `refresh_token` (7 jours) en **cookie HttpOnly**
- Le refresh_token n'est JAMAIS accessible via JavaScript (protection XSS)
- Rotation automatique du refresh_token à chaque usage (protection replay)
- Déconnexion côté serveur (suppression du cookie)

### 2. Anonymisation des données (SecurityFilter)

Avant d'envoyer un message au LLM cloud, les données sensibles sont remplacées par des placeholders :

| Type | Pattern | Exemple |
|---|---|---|
| Carte bancaire | `\b(?:\d[ -]*?){13,16}\b` | `4111 2222 3333 4444` → `[CARD_0]` |
| Email | RFC 5322 | `nom@domaine.fr` → `[EMAIL_0]` |
| Token/API key | `token/secret/bearer:...` | `Bearer sk-abc123` → `[TOKEN_0]` |
| IBAN | `\b[A-Z]{2}\d{2}...` | `FR76 3000 6000...` → `[IBAN_0]` |
| Téléphone FR | `\b(?:\+33\|0)[1-9]...` | `06 12 34 56 78` → `[PHONE_0]` |

La réponse du LLM est **dé-anonymisée** avant d'être renvoyée à l'utilisateur.

#### Couche 2 (optionnelle) : noms, organisations, adresses en texte libre

En plus des regex ci-dessus (toujours actives), une **couche NER locale**
(GLiNER, modèle ONNX exécuté sur votre machine — rien ne sort) peut masquer
les PII en texte libre avant tout envoi à un LLM cloud :

| Type | Exemple | Placeholder |
|---|---|---|
| Personne | `Mme Élodie Rousseau` | `[PERSON_0]` |
| Organisation | `cabinet Durand & Associés` | `[ORG_0]` |
| Adresse postale (niveau rue) | `12 rue de la République, 33000 Bordeaux` | `[ADDRESS_0]` |

**Périmètre calibré par l'usage réel** (pour que l'agent reste utilisable) :

- La détection ne s'applique qu'au **texte que vous tapez** — pas aux
  résultats d'outils (web, GitHub, emails), qui sont majoritairement
  publics. Votre PII déjà connue reste masquée partout où elle réapparaît.
- Les **villes / régions / pays restent en clair** (« la météo à Toulouse »
  doit fonctionner) : seules les adresses de niveau rue sont masquées.
- Les **noms des services intégrés** (GitHub, Gmail, Telegram…) ne sont
  jamais masqués — extensible via `PII_NER_ALLOWLIST="nom1,nom2"`.

**Activation** (3 étapes, voir `.env.example`) : build avec
`PII_NER_INSTALL=1`, export du modèle ONNX sur l'hôte
(`backend/scripts/export_gliner_onnx.py`), puis `PII_NER_ENABLED=true`.

**Désactivation immédiate** (kill-switch) si la couche gêne votre usage :

```bash
# .env
PII_NER_ENABLED=false
```
```bash
docker compose up -d backend   # recreate — un simple restart ne relit pas l'env
```

Aucune perte : les regex de la couche 1 restent actives, et les
conversations en cours continuent normalement.

#### Limites assumées de l'anonymisation déterministe

L'anonymisation utilise un mapping **déterministe par session** : la même valeur (`Jean Dupont`) est toujours remplacée par le même placeholder (`[PERSON_0]`) à l'intérieur d'une conversation, pour que le LLM puisse raisonner sur les relations entre entités (« le PERSON_0 a envoyé un mail au PERSON_1 »). Ce choix a un coût en termes de garanties, qu'il faut documenter clairement :

| Limite | Description | Mitigation actuelle / planifiée |
|---|---|---|
| **Attaque de fréquence corpus-wide** | Si un attaquant dispose d'un grand corpus de prompts ELY anonymisés (par exemple via un dump compromis du provider LLM), il peut potentiellement reconstruire les entités les plus fréquentes via leur signature statistique. | Sel par session différent ; rotation périodique des sels en production ; chiffrement au repos des logs LLM côté serveur ELY. |
| **Données hors patterns regex** | Les patterns couvrent : carte bancaire, email, IBAN, téléphone FR, token API, et noms via NER. Tout PII en dehors de ces catégories (numéro de SS, immatriculation, identifiant interne entreprise…) **passe non-anonymisé** par défaut. | Configuration ajoutable côté serveur (`security_filter.custom_patterns`) ; passe ultérieure prévue avec une NER multilingue plus large. |
| **Inférence indirecte** | Même anonymisé, le LLM peut inférer des informations sensibles à partir du contexte (« le PERSON_0 travaille dans une banque parisienne et a 3 enfants »). L'anonymisation ne masque pas le contexte qualitatif. | Aucune mitigation technique simple ; en pratique : pour les secrets stricts, utiliser le **tier A 100% local** (Ministral 3B sur la machine de l'utilisateur, aucune donnée ne sort). |
| **Réversibilité de hashe court** | Les placeholders comme `[PERSON_0]` numérotent dans l'ordre d'apparition, ce qui peut leak l'ordre conversationnel. | Acceptable pour le cas d'usage ; pour les paranos : tier local. |

**Conclusion produit** : l'anonymisation déterministe est utile pour les cas d'usage standards (réduction de surface d'attaque, conformité raisonnable, raisonnement préservé). Pour les cas à très haut risque (secrets industriels, données HDS, professions réglementées), **la bonne réponse est le tier A 100% local**, pas l'anonymisation seule. La page Sovereignty détaille les 3 modes (local / 100% EU / mixte performant).

### 3. HITL (Human-In-The-Loop)

Certaines actions **requièrent toujours** une validation humaine :

- `ssh_execute` — exécution de commande sur un serveur
- `gmail_send_email` — envoi d'email
- `calendar_create_event` — création d'événement

De plus, toute action contenant des **mots-clés critiques** déclenche HITL :
`delete`, `remove`, `drop`, `purge`, `send`, `mail`, `pay`, `virement`, `rm -rf`, `format`, `chmod 777`...

La validation peut aboutir à :
- **Allow** — action exécutée
- **Deny** — action refusée pour cette occurrence
- **Ban** — action refusée ET règle permanente stockée dans Qdrant

### 4. Contraintes de sécurité persistantes

Quand un utilisateur **ban** une action, la règle est stockée dans Qdrant (collection `security_constraints`)
et injectée dans le system prompt à chaque message futur par recherche sémantique.

Exemple : "INTERDICTION PERMANENTE: Outil: ssh_execute | ne jamais exécuter rm -rf sur le serveur prod"

### 5. SSH sécurisé

- Whitelist de commandes par hôte (`config/hosts.yaml`)
- L'agent ne peut PAS exécuter de commandes arbitraires
- Exécution non-bloquante via `asyncio.to_thread` (Paramiko)
- Le fichier `config/hosts.yaml` est dans `.gitignore`

### 6. Google OAuth2

- Credentials OAuth app stockées en DB (`system_config`), pas dans `.env`
- Secrets masqués dans l'API admin (`••••••••`)
- Chaque utilisateur a ses propres tokens (colonne `google_credentials`)
- `user_google_credentials_json` marqué `InjectedToolArg` — **invisible au LLM**
- Credentials **jamais affichées** dans les logs, le chat, ni les requêtes HITL (filtrage `display_args`)
- PKCE supporté pour l'échange de code

### 7. Configuration sécurisée

- `.env` et `config/` dans `.gitignore`
- `system_config` en DB avec flag `is_secret` pour le masquage
- Priorité DB > env (pas besoin de redémarrer pour changer une config sensible)

---

## Sécurité des canaux (Telegram, WhatsApp...)

L'ajout d'un canal de messagerie ne compromet **pas** la sécurité car :

1. **Même pipeline** — les messages Telegram passent par les mêmes filtres (anonymisation, HITL, contraintes)
2. **Whitelist** — seuls les Telegram user IDs liés à un compte ELY peuvent interagir
3. **Pas de mode groupe** — le bot ne répond qu'en DM (sauf configuration explicite)
4. **Bot token** — stocké en `system_config` (chiffré), pas dans le code
5. **Validation HITL** — les actions critiques sont validées via boutons inline dans le même canal

**Surface d'attaque supplémentaire** :
- Compromission du bot token → régénérer via BotFather
- DM d'un inconnu → rejeté si pas dans la whitelist
- Interception réseau → Telegram utilise le chiffrement serveur-client (MTProto)

**Ce qu'on ne fait PAS, par design** :
- Pas d'exécution de code arbitraire depuis un message channel
- Pas d'accès fichier non contrôlé (chemins SSH whitelistés, vault pour les secrets)
- Pas de bash non-whitelisté
- Pas d'auto-promotion d'actions « sensibles » sans HITL
- Pas de logging des credentials (jamais — masqués via SecurityFilter)

---

## Garanties de sécurité résumées

| Aspect | Implémentation |
|---|---|
| Anonymisation PII avant LLM | Oui (regex + vault) |
| HITL pour actions critiques | Oui (3 niveaux : Allow / Deny / Ban) |
| Apprentissage des refus | Oui (Qdrant `security_constraints` persistant) |
| SSH whitelist | Oui (par hôte) |
| Credentials dans les logs | Jamais (filtrés au niveau du logger) |
| Refresh token | Cookie HttpOnly (pas accessible en JS) |
| Access token | localStorage 60 min, refresh transparent |
| Mots de passe | Argon2id via pwdlib |
| JWT | HS256, secret 32-byte minimum imposé |
| Vault user secrets | AES-256-GCM zero-knowledge (clé dérivée du mdp) |
