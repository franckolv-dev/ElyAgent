# ELY — Rapport de test-runner

- Total exécutés : **5**
- ✓ Pass : **5**
- ✗ Fail : **0**
- ⧖ HITL timeout : **0**
- ⊘ Skip : **0**

| # | Section | Prompt | Statut | Tool attendu | Tools réels | Temps | Notes |
|---|---|---|:---:|---|---|---:|---|
| 82 | Maps | Quelle est l'adresse de la Tour Eiffel ? | ✓ | `maps_geocode` | `maps_geocode,browser_navigate` | 7.9s |  |
| 83 | Maps | Comment aller de Paris à Lyon en voiture ? | ✓ | `maps_directions` | `maps_directions` | 5.8s |  |
| 84 | Maps | Trouve les restaurants italiens près de la Place de la Répub | ✓ | `maps_nearby` | `maps_nearby,web_search` | 16.3s |  |
| 98 | QR | Crée un QR code vCard pour Franck Ollivier, email franck@tes | ✓ | `qrcode_generate_vcard` | `qrcode_generate_vcard,generate_image` | 12.4s |  |
| 144 | MCP | Liste les serveurs MCP disponibles dans ta bibliothèque | ✓ | `mcp_list_library` | `mcp_list_library` | 39.5s |  |

## Détails des échecs
