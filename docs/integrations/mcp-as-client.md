# Ely en tant que client MCP

> Ely peut consommer des serveurs **Model Context Protocol** (MCP) : se
> connecter, découvrir leurs outils, les rendre appelables par le modèle, et
> appliquer ses garanties de sécurité (identité, HITL, Vault, isolation).
>
> Statut : derrière le flag global `MCP_CLIENT_V2_ENABLED` (OFF par défaut).

## Vue d'ensemble

Deux façons d'utiliser un serveur MCP :

1. **Configuration admin** (Réglages → MCP, ou import `mcpServers`). L'admin
   enregistre un serveur ; après approbation, ses outils sont exposés au
   modèle sous le nom `mcp__<slug>__<outil>`.
2. **Pilotage par le modèle** (flag ON). À ta demande, Ely se connecte
   elle-même à un serveur distant et utilise ses outils. Tu valides
   l'installation et les permissions ; Ely fait le reste.

## V2 — durcissement (2026)

Le client MCP a été durci au-delà de la V1 :

- **Identité par utilisateur** — les credentials d'un serveur distant (bearer / API key / OAuth) vivent dans le **Vault du propriétaire**, jamais en base ni dans les logs ; chaque appel agit avec l'identité de l'utilisateur.
- **Garde réseau** — HTTPS imposé, validation DNS/IP et **épinglage sur l'IP validée** (anti-SSRF / anti-DNS-rebinding), redirections re-validées. Exception réseau privé/LAN réglable par l'admin, par serveur (`allow_private_network`).
- **ACL / HITL par outil** — lecture sans friction, écriture confirmée une fois puis mémorisée ; classe de risque par outil ; workflow quarantaine → confiance.
- **Recherche du registre MCP officiel** — découverte only, zéro confiance implicite (même parcours de consentement qu'un import manuel).

Arrivant derrière leurs propres flags, **désactivés par défaut** :

- **OAuth 2.1 / PKCE** (`MCP_OAUTH_ENABLED`) — bouton « Se connecter » : découverte du serveur d'autorisation (RFC 9728/8414), PKCE, tokens rafraîchis/révocables rangés au Vault du propriétaire, identité par utilisateur. Débloque les serveurs MCP distants authentifiés (GitHub, Notion, Linear…).
- **Sandbox des serveurs stdio locaux** (`MCP_STDIO_SANDBOX_ENABLED`) — le processus est lancé sous limites de ressources (mémoire virtuelle / descripteurs / taille de fichier écrit) et **tout son arbre de processus est tué proprement à l'arrêt** (zéro orphelin). Limites par défaut overridables globalement (`MCP_STDIO_SANDBOX_*`) ou par serveur (`sandbox_profile_json`). *Validé en canary.* NB : l'isolation réseau/utilisateur/mounts du serveur local relève d'un conteneur sidecar (non couvert).
- **Resources / Prompts** (`MCP_RESOURCES_ENABLED`) — lecture seule : lister/lire les *resources* d'un serveur distant, lister/récupérer ses *prompts* (contenu tiers **marqué non fiable, jamais auto-injecté**). `roots` / `sampling` / `elicitation` restent hors périmètre.

## Transports pris en charge (V1)

| Transport | Usage |
|---|---|
| `stdio` | Serveur local lancé par Ely (admin-only, après approbation). |
| `streamable_http` | Serveur MCP distant moderne (HTTPS). |
| `legacy_sse` | Ancien transport HTTP+SSE — compatibilité uniquement. |

## Outils exposés au modèle (flag ON)

- `mcp_list_servers()` — serveurs accessibles (instance + tes serveurs perso).
- `mcp_discover_tools(server_id)` — catalogue d'un serveur (nom, risque).
- `mcp_call_tool(server_id, tool, args)` — appel sécurisé (ACL + garde réseau
  + politique de données sortantes + confirmation selon le risque).
- `mcp_connect(url)` — connexion **autonome** à un serveur distant **HTTPS**
  (cibles internes refusées ; confirmation humaine demandée). Crée un serveur
  **personnel**, visible de toi seul.
- `mcp_propose_server(name, command, args)` — pour un serveur **local** : Ely
  ne fait que **proposer** (quarantaine). Tu approuves l'installation dans
  Réglages → MCP. Ely ne s'auto-approuve jamais.

### Exemple

> « Connecte-toi au serveur MCP `https://mcp.exemple.com/mcp` et liste mes
> tickets. »

Ely valide la cible (HTTPS, pas d'IP interne), te demande confirmation,
découvre les outils, puis les appelle — chaque appel sensible repassant par
une confirmation.

## Import `mcpServers`

Réglages → MCP → **Importer (mcpServers)**. Colle un fichier standard :

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
    }
  }
}
```

Chaque serveur est créé **en quarantaine** — jamais lancé ni activé
automatiquement. Tu l'approuves ensuite serveur par serveur.

## Cycle de vie d'un serveur

```
draft → quarantined → (approbation humaine) → active
                                       ↘ blocked
active ↔ degraded   (santé runtime : healthy / degraded / offline / …)
```

- **Approuver** un serveur en quarantaine l'active et le charge (pour un
  serveur local, c'est *ici* — et nulle part dans le modèle — que s'autorise
  l'exécution du code tiers).
- **Quarantaine** le désactive et le décharge immédiatement.
- **Kill switch** : coupe-circuit par serveur, toujours honoré.

## Voir aussi

- [Modèle de sécurité et de confiance](mcp-security.md)
