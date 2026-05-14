# ELY · Browser Companion (Chrome)

> Extension navigateur qui permet à ELY d'agir dans ton vrai Chrome,
> avec tes sessions, sous ton contrôle (HITL avant chaque action irréversible).
>
> **Statut au 14 mai 2026 — Sprints 0, 0.5 et 2 livrés en production.**
> Connexion WebSocket stable, tokens longue durée (plus de coupure toutes
> les 60 minutes), 9 outils d'autonomie agent (ouverture d'onglets, attente
> de chargement, screenshots avec fallback vision pour Amazon / LinkedIn).
> Sprint 1 (overlay HITL dans la page) en cours ; Sprint 3 (Chrome Web Store)
> à venir. Voir la [roadmap complète](#roadmap) en bas du fichier.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Chrome                                                              │
│  ┌─────────┐  ┌─────────────────┐  ┌──────────────────────────┐      │
│  │ Popup   │  │ Service Worker  │  │ Content Script (par page)│      │
│  │ (status)│←→│  (WebSocket)    │←→│  (lecture DOM, overlays) │      │
│  └─────────┘  └────────┬────────┘  └──────────────────────────┘      │
│                        │                                              │
└────────────────────────┼──────────────────────────────────────────────┘
                         │ wss://
                         ▼
                 ┌─────────────────────┐
                 │ ELY backend         │
                 │ /ws/browser-extension│
                 │ (FastAPI)           │
                 └─────────────────────┘
```

- **Service worker** (`src/background/service-worker.js`)
  Owner du WebSocket. Se reconnecte avec backoff exponentiel. Forwarde
  les commandes du backend vers le content script de l'onglet actif.
- **Content script** (`src/content/content-script.js`)
  Injecté sur toutes les pages. Lit le DOM, exécute (Sprint 1+) les
  clics / fills sous validation HITL via overlay.
- **Popup** (`src/popup/*`)
  Status connexion + bouton reconnect + lien réglages.
- **Options** (`src/options/*`)
  Saisie de l'URL backend + JWT.
- **Shared** (`src/shared/*`)
  Protocole de messages typés + helpers storage.

## Permissions (manifest.json)

| Permission | Pourquoi |
|---|---|
| `activeTab` | Lire la page de l'onglet courant quand l'utilisateur agit |
| `scripting` | Injecter le content script |
| `storage` | Sauvegarder l'URL backend + JWT (storage local, chiffré par Chrome) |
| `tabs` | Suivre tab/URL change pour informer le backend |
| `host_permissions: ["<all_urls>"]` | Le content script doit pouvoir tourner partout |

## Installation locale (dev)

1. Ouvrir `chrome://extensions/`
2. Activer le **mode développeur** (toggle en haut à droite)
3. Cliquer **"Charger l'extension non empaquetée"**
4. Sélectionner le dossier `extension/chrome/`
5. L'icône ELY (⚡ cyan) apparaît dans la toolbar

## Configuration

1. Clic-droit sur l'icône ELY → **Options**
   (ou clic gauche sur l'icône → bouton **Réglages**)
2. Renseigner l'**URL backend** : `https://ely.catalogmaker.fr`
   (ou ton instance ELY auto-hébergée — sans slash final).
3. Cliquer **« 🔑 Générer un token dans ELY »** — ça ouvre la page
   *Réglages → Extension navigateur* dans un nouvel onglet.
4. Donner un nom au token (ex : *Chrome Mac Studio*) → **Générer** →
   copier le token (`ely_ext_…`) **immédiatement** (il ne sera plus
   jamais affiché en clair).
5. Revenir sur la page Options, coller le token, **Enregistrer & reconnecter**.
6. Le popup ELY doit basculer en vert « Connecté » — et y rester, même
   après un redémarrage de Chrome.

> **Pourquoi un token longue durée ?** Le JWT classique de l'app web
> expire au bout de 60 minutes. Pour une extension qui tourne en tâche
> de fond, ça veut dire reconnexion forcée toutes les heures. Les
> tokens `ely_ext_…` n'expirent pas ; tu les révoques toi-même depuis
> *Réglages → Extension navigateur* quand tu n'en as plus besoin.
> Seul le hash SHA-256 est stocké côté serveur — le plaintext ne
> quitte jamais ta machine après la copie initiale.

## Test end-to-end (Sprint 0)

Backend log attendu lors du connect :
```
[browser-ext] connection accepted, waiting for hello…
[browser-ext] registered user=<uuid> version=0.1.0 ua='Mozilla/...'
```

Pour tester la lecture DOM, depuis un python REPL connecté au backend :
```python
from app.services import browser_extension_registry
import json, asyncio

async def demo():
    conn = browser_extension_registry.get(user_id="<your-user-id>")
    if not conn: return print("Not connected")

    msg = {"v":"0.1.0","id":"test-1","type":"read_text","payload":{"selector":"h1"},"ts":0}
    fut = asyncio.get_event_loop().create_future()
    conn.pending["test-1"] = fut
    await conn.websocket.send_text(json.dumps(msg))
    result = await asyncio.wait_for(fut, timeout=5)
    print(result)

asyncio.run(demo())
```

Tu devrais voir le `textContent` du `<h1>` de la page active.

## Sécurité

- ❌ **L'extension ne stocke aucun mot de passe.** Seul un JWT, scopé à
  ton utilisateur ELY, et révocable côté backend.
- ❌ **L'extension n'envoie rien à un tiers.** Le WebSocket pointe
  exclusivement vers ton instance ELY que tu as configurée toi-même.
- ✅ **Toute action destructive** (Sprint 1+) **passe par un overlay HITL**
  rendu dans la page courante, attendant un clic Autoriser / Refuser /
  Bannir.
- ✅ **URLs protégées** (chrome://, file://, extensions) sont automatiquement
  refusées avec `protected_url`.

## Roadmap

- ✅ **Sprint 0** *(mai 2026)* — Plomberie : connexion WebSocket, handshake
  `hello`, lecture DOM, heartbeat 20 s pour survivre au killer MV3 de Chrome,
  reconnect avec backoff exponentiel + suspension sur close codes fatals
  (4001/4029/1008).
- ✅ **Sprint 0.5** *(mai 2026)* — Tokens longue durée au format
  `ely_ext_<48 hex>` (192 bits d'entropie). REST endpoints
  `POST/GET /api/extension/tokens` + `DELETE /api/extension/tokens/{id}`.
  UI dédiée *Réglages → Extension navigateur* pour générer / lister /
  révoquer. Plaintext affiché **une seule fois** ; hash SHA-256 + last_4
  en base. Fini le copier-coller depuis DevTools.
- ✅ **Sprint 2** *(mai 2026)* — Autonomie agent : 9 outils backend
  (`browser_list_tabs`, `browser_open_tab`, `browser_tab_wait_loaded`,
  `browser_tab_wait_for_selector`, `browser_tab_get_url`,
  `browser_tab_read_text`, `browser_tab_read_html`,
  `browser_tab_screenshot`, `browser_close_tab`). Screenshot avec
  fallback vision pour les sites anti-bot (Amazon, LinkedIn…).
  Intégration complète dans `tool_sets.py` + `toolset_profiles.py` +
  registration de skill `browser_extension_skill`.
- 🟨 **Sprint 1** *(en cours)* — Actions destructives `click` / `fill` /
  `navigate` avec overlay de validation HITL **dans la page elle-même**.
  Le gating HITL existe déjà côté backend (validation/HITL channels) ;
  reste à câbler l'overlay côté content-script pour que la confirmation
  soit visible là où l'action se produit, pas dans Telegram/web.
- ⏭ **Sprint 3** — Publication Chrome Web Store + adaptation Firefox/Edge
  (signature MV3, screenshots store, asset pack, build CI automatisé).

## Licence

PolyForm Strict 1.0 — voir [LICENSE](../../LICENSE) à la racine du repo.
