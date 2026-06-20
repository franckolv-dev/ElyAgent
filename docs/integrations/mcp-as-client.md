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
