# 📸 ELY screenshots — automation pour agent-ely.fr

Génère **28 captures d'écran** haute résolution de l'UI ELY pour le site marketing :

> **7 pages × 2 thèmes × 2 langues = 28 PNG Retina (3840×2160)**

| Page slug | URL | Ce qu'on capture |
|---|---|---|
| `chat` | `/chat` | Chat empty state + avatar 3D + suggestions |
| `missions` | `/missions` | Liste des missions + bouton "Nouvelle" |
| `ai-models` | `/settings` | Onglet Modèles IA — instances configurées |
| `hitl` | `/settings` (onglet HITL) | Tuiles HITL Confirmations + canal de notification |
| `dashboard` | `/dashboard` | Stats + chart tokens/jour + breakdown providers |
| `arena` | `/arena` | Mode Arena — prompt + comparaison ELO |
| `security` | `/security` | 11 tuiles sécurité + live status |

Chaque page est capturée en 4 variantes : `dark-fr`, `dark-en`, `light-fr`, `light-en`.

## ⚡ Setup (5 min)

Dans **un terminal**, depuis la racine ELY :

```bash
cd scripts/screenshots
npm install                       # télécharge playwright (~50 Mo)
npm run install:browser           # télécharge Chromium (~150 Mo)
```

C'est tout pour le setup. Tu peux maintenant tirer les captures.

## 🎬 Générer les captures

### Sur ton instance locale (par défaut http://localhost:3000)

```bash
npm run shoot
```

Tu peux personnaliser via env vars :

```bash
ELY_LOGIN=admin ELY_PASSWORD=mon-mdp npm run shoot
```

### Sur ton instance remote (via Cloudflare / Tailscale)

```bash
npm run shoot:remote
# équivalent à :
ELY_BASE_URL=https://ely.catalogmaker.fr ELY_API_URL=https://ely.catalogmaker.fr npm run shoot
```

### Mode debug (voir le navigateur en action)

```bash
npm run shoot:headed
```

## 📂 Sortie

Les PNG arrivent dans `./out/` :

```
out/
├── chat-dark-fr.png
├── chat-dark-en.png
├── chat-light-fr.png
├── chat-light-en.png
├── missions-dark-fr.png
├── ...
└── security-light-en.png
```

Chaque PNG fait **3840×<height> @ 2x DPR** (Retina-ready). Tailles typiques : 800 Ko à 4 Mo selon la longueur de la page.

## ⚙️ Personnalisation

Toutes les options par variables d'env :

| Variable | Défaut | Effet |
|---|---|---|
| `ELY_BASE_URL` | `http://localhost:3000` | URL frontend |
| `ELY_API_URL` | `http://localhost:8000` | URL backend (pour le login) |
| `ELY_LOGIN` | `admin` | Username admin |
| `ELY_PASSWORD` | `changeme` | Password admin |
| `ELY_OUT_DIR` | `./out` | Dossier de sortie |
| `ELY_HEADED` | `0` | `1` = navigateur visible |
| `ELY_SCALE` | `2` | Device pixel ratio (2 = Retina) |
| `ELY_VIEWPORT` | `1920x1080` | Format viewport `WxH` |

## 🎨 Optimiser pour le web

Convertir les PNG en WebP pour ton site (gain ~70% de poids) :

```bash
# Mac : brew install imagemagick
for f in out/*.png; do
  magick "$f" -quality 85 -define webp:method=6 "out/$(basename "$f" .png).webp"
done
```

Ou avec [`@squoosh/cli`](https://github.com/GoogleChromeLabs/squoosh) si tu as Node :

```bash
npx @squoosh/cli --webp '{"quality":85}' out/*.png
```

## 🆘 Troubleshooting

**`Login failed (401)`**
→ Mauvais `ELY_LOGIN` / `ELY_PASSWORD`. Reconfigure ou crée un compte admin :
```bash
docker exec cyberentity-backend uv run python -c "
import asyncio
from app.database import async_session
from app.models.user import User
from app.auth.passwords import hash_password
async def go():
    async with async_session() as db:
        u = User(email='admin', username='admin',
                 hashed_password=await hash_password('changeme'),
                 role='admin', is_active=True)
        db.add(u); await db.commit()
asyncio.run(go())
"
```

**`page.goto: net::ERR_CONNECTION_REFUSED`**
→ ELY n'est pas démarré. Lance `make up` depuis la racine.

**Captures trop sombres / claires (mauvais thème)**
→ Le thème est appliqué via `localStorage` + `colorScheme`. Si une page met le focus visuel sur un mauvais thème, augmente le `waitForTimeout` final dans `take-screenshots.mjs` (ligne avec `// Buffer pour les animations`).

**Avatar 3D pas chargé sur la capture chat**
→ Le composant 3D peut prendre 2-3s à initialiser sur une machine lente. Augmente le `afterReady` du slug `chat` à `await page.waitForTimeout(2500)`.

**Le chart Dashboard est vide**
→ Logique : ton compte admin n'a pas généré de tokens récents. Soit tu prends la capture sur une instance avec data, soit tu accèpes une heatmap vide.

**La tuile "ELY Desktop" affiche "déconnecté"**
→ Normal si tu n'as pas le daemon lancé. Pour la capture marketing, tu peux le lancer rapidement (`./desktop/dist/ely-desktop-macos-arm64`) avant de shooter.

## 🚀 Workflow recommandé pour le launch site

1. **Prépare tes données** : assure-toi que ton chat a des messages (pour la capture `chat-*`), que tu as 2-3 missions, que ton dashboard a de la data sur 30 jours.
2. **Démarre les services** : `make up` + lance `ely-desktop` si tu veux la tuile connectée.
3. **Tire les captures** : `npm run shoot` (compte ~3 min pour les 28).
4. **Vérifie visuellement** : ouvre `out/` et regarde les 28 PNG.
5. **Optimise** : convertis en WebP, puis en thumbnails (1280x_) pour le hero du site.
6. **Push** : intègre dans le repo de ton site agent-ely.fr.

Bon shoot ! 🎬
