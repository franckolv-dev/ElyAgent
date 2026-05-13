# ELY · Browser Companion (Chrome) — Sprint 0

> Extension navigateur qui permet à ELY d'agir dans ton vrai Chrome,
> avec tes sessions, sous ton contrôle (HITL avant chaque action irréversible).
> Sprint 0 actuel : lecture DOM, status, plomberie WebSocket. Aucune action
> destructive encore — les handlers `click` / `fill` / `navigate` renvoient
> `not_implemented_yet_sprint1`.

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
2. Renseigner :
   - **URL backend** : `https://ely.catalogmaker.fr` (ton instance ELY)
   - **JWT** : token obtenu via *ELY → Réglages → Extension navigateur*
     (endpoint à ajouter — voir todo Sprint 0.5)
3. Clic **Enregistrer & reconnecter**
4. Le popup ELY doit basculer en vert "Connecté"

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

- ✅ **Sprint 0** — Plomberie : connexion WS, HELLO, lecture DOM, screenshot.
- ⏭ **Sprint 0.5** — REST endpoint `/api/browser-extension/issue-token`
  côté backend + UI dans Réglages ELY pour générer un JWT scoped extension.
- ⏭ **Sprint 1** — Actions HITL-gated : `click`, `fill`, `navigate` avec
  overlay de validation dans la page.
- ⏭ **Sprint 2** — Outils agent : `browser.read_active_page`,
  `browser.fill_form`, `browser.click_element`. Intégration dans le
  registry des tools backend.
- ⏭ **Sprint 3** — Publication Chrome Web Store + adaptation Firefox/Edge.

## Licence

PolyForm Strict 1.0 — voir [LICENSE](../../LICENSE) à la racine du repo.
