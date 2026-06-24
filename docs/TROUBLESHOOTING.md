# Troubleshooting · `make up` failed or first chat errors out

> If something doesn't work on first install, **search this page first**. 95% of issues are covered. Open an issue only after checking.

## 🆘 The 6 things to check, in order

### 1. `JWT_SECRET_KEY` is set to a real value (not the placeholder)
```bash
grep -E "^JWT_SECRET_KEY=" .env
```
You should see one line, a 64-character hex string, NOT `CHANGE-ME-…`.

If it's wrong, regenerate cleanly:
```bash
sed -i.bak "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$(openssl rand -hex 32)|" .env && rm .env.bak
make restart s=backend
```

> ⚠️ **The README used to recommend `python -c "import secrets; …"`** which fails silently on Mac (no `python` in PATH). Use `openssl` instead — it's preinstalled everywhere.

---

### 2. At least one LLM provider is configured
ELY boots fine with no LLM key, but **every chat message will fail** with a connection error if the active provider isn't reachable.

Check current active provider:
```bash
grep -E "^ACTIVE_LLM_PROVIDER|^GEMINI_API_KEY|^ANTHROPIC_API_KEY|^MISTRAL_API_KEY" .env
```

If `ACTIVE_LLM_PROVIDER=ollama` and you don't have Ollama running on the host:
- **Either** install Ollama from https://ollama.ai and `ollama pull qwen2.5:7b-instruct`
- **Or** switch to a cloud provider:
  ```bash
  # Example with Gemini (free key at https://aistudio.google.com/apikey)
  sed -i.bak 's|^ACTIVE_LLM_PROVIDER=.*|ACTIVE_LLM_PROVIDER=gemini|' .env
  sed -i.bak 's|^GEMINI_API_KEY=.*|GEMINI_API_KEY=YOUR_KEY_HERE|' .env
  rm .env.bak
  make restart s=backend
  ```

---

### 3. No port conflict on 3000 / 8000 / 6333 / 80
If `make up` shows `Bind for 0.0.0.0:3000 failed: port is already allocated`:
```bash
# Find who's using port 3000 (or 8000, 6333, 80)
lsof -i :3000

# Either stop the conflicting process, OR override the ELY port:
echo "ELY_FRONTEND_PORT=13000" >> .env
echo "ELY_BACKEND_PORT=18000" >> .env
echo "ELY_QDRANT_PORT=16333" >> .env
echo "ELY_HTTP_PORT=18080" >> .env
make down && make up
# Now open http://localhost:13000 instead of 3000
```

---

### 4. Container conflict with another ELY install
If `make up` shows `Conflict. The container name "/cyberentity-backend" is already in use`:
```bash
# Either reuse the existing install (cd to that folder and `make up` there)
# Or fully reset this install:
docker compose down -v       # ⚠️ deletes the SQLite DB + Qdrant volumes
make up
```

---

### 5. The first signup says "password too weak"
ELY's password policy: **min 12 chars, at least one uppercase, at least one special character** (`!@#$%^&*…`).

Pick something like `MyElyPass2026!`. If the form rejects, the API response (in browser DevTools → Network) will tell you exactly which rule failed.

---

### 6. The frontend loads but chat says "no LLM available"
This means the LLM key isn't reaching the backend, even though it's in `.env`. Two reasons:
- You added the key AFTER `make up` → restart backend: `make restart s=backend`
- The key has spaces around `=` (broke parsing) → re-edit `.env`, no whitespace.

Confirm the backend sees it:
```bash
docker compose exec backend env | grep -E "GEMINI|ANTHROPIC|MISTRAL"
```

---

## 🩺 First-line diagnostic commands

```bash
# Are containers running?
make ps

# Backend logs (look for "Application startup complete" or red errors)
make logs s=backend

# Health endpoint
curl -s http://localhost:8000/health   # should return 200

# What providers does the backend see?
curl -s http://localhost:8000/api/settings/llm | python3 -m json.tool || cat
```

---

## 🐌 `make up` takes forever?

**First run** downloads ~2 GB of base images (Python, Node, Qdrant, Playwright Chromium). Expect 5-15 min on a decent connection. Subsequent `make up` should be under 30 seconds.

If it's hung longer than 20 min:
```bash
# Check what's actually downloading
docker compose logs --no-color | grep -E "pull|download|fetch" | tail -20
```

---

## 📎 Un upload reste bloqué (spinner) au-delà de ~1 Mo

**Cause** : nginx limite la taille du corps de requête. Vérifiez que
`config/nginx/default.conf` contient bien `client_max_body_size 50M;` (corrigé
par défaut depuis #147), puis **recréez** le conteneur nginx :
```bash
docker compose up -d --no-deps --force-recreate nginx
```
> ⚠️ N'utilisez **pas** `docker compose exec nginx nginx -s reload` : après un
> `git pull` qui renomme la conf, le reload relit l'inode épinglé (périmé) et
> peut servir une conf tronquée → 502 (`unexpected end of file …:84`). Il faut
> **recréer** le conteneur. `make restart` / `make build` recréent déjà nginx
> ainsi ; pour un simple changement de conf, la commande ci-dessus suffit.

La limite serveur est de **50 Mo** (`MAX_FILE_SIZE` côté backend +
`client_max_body_size` côté nginx).

> ⚠️ Un `.zip` s'uploade (limite 50 Mo) mais l'agent **ne peut pas lire son
> contenu** : il n'existe aucun outil de décompression. Envoyez les fichiers
> **non zippés** pour qu'Ely puisse les ouvrir.

---

## 🕶️ Ely répond avec des `[PERSON_0]` / `[ORG_0]`, ou « ne comprend plus » des demandes simples

Ce cas ne survient que si vous avez **délibérément installé ET activé** la
couche 2 NER (rebuild avec `PII_NER_INSTALL=1` PUIS `PII_NER_ENABLED=true`).
Sur une installation par défaut la couche 2 est **absente du conteneur**
(`PII_NER_INSTALL=0`) et `PII_NER_ENABLED=true` reste un **no-op** — vous ne
verrez donc jamais de `[PERSON_0]` / `[ORG_0]` sans ce rebuild explicite.

Si vous l'avez activée et qu'elle masque quelque chose dont l'agent a besoin
(un nom de service, un lieu…), deux options :

1. **Affiner** : ajoutez les termes à ne jamais masquer dans le `.env` —
   `PII_NER_ALLOWLIST="MonEntreprise,MonOutil"` — puis
   `docker compose up -d backend`.
2. **Désactiver** (kill-switch, aucune perte — les regex email/téléphone/
   IBAN/CB restent actives) :
   ```bash
   # .env
   PII_NER_ENABLED=false
   ```
   ```bash
   docker compose up -d backend
   ```
   ⚠️ `up -d` (recreate), pas `restart` — un simple restart ne relit pas
   les variables d'environnement.

Le périmètre de la couche et ses réglages sont détaillés dans
[`security.md`](security.md#couche-2-optionnelle--noms-organisations-adresses-en-texte-libre).

---

## 🌍 Browser extension doesn't connect

See [`extension/chrome/README.md`](../extension/chrome/README.md). The most common issues:

1. **Extension reloaded but old service worker still cached**
   → `chrome://extensions/` → 🔄 Reload on the ELY card.
2. **Backend URL has a trailing slash** → strip it
   (use `https://ely.example.com`, not `https://ely.example.com/`).
3. **Disconnects every ~60 min** → you're using the short-lived JWT
   from `localStorage.ely_access_token`. Switch to a long-lived token:
   ELY web app → **Réglages → Extension navigateur** → **Générer**.
   Tokens are formatted `ely_ext_<48 hex chars>` and never expire
   (you revoke them yourself from the same page).
4. **Token revoked or invalid** → the WS closes with code `4001` and
   the service worker suspends to avoid reconnect loops. Open
   `chrome://extensions/` → ELY → *service worker* (Inspect) to confirm
   the close code, then paste a fresh token in the Options page.
5. **Rate limited (close code 4029)** → wait 60 s. The backend allows
   30 connection attempts per minute per IP.

### Generating a token from the CLI (for self-hosters)

If the web UI isn't reachable yet, hit the API directly:

```bash
TOKEN_API="https://ely.example.com/api/extension/tokens"
ACCESS_JWT="$(curl -s -X POST https://ely.example.com/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"…"}' | jq -r .access_token)"

curl -s -X POST "$TOKEN_API" \
  -H "Authorization: Bearer $ACCESS_JWT" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Chrome Mac Studio"}' | jq .
# → { "id": "...", "name": "...", "token": "ely_ext_xxxx...", "last_4": "xxxx", ... }
```

The plaintext `token` is returned **once**; store it in your password
manager before closing the terminal. The server only keeps the SHA-256
hash.

---

## 🔑 Le serveur MCP / une clé API renvoie `401`

Ely est exposée **comme serveur MCP** sur `/api/mcp` (pour connecter Claude
Desktop, Cursor…). L'authentification se fait par **clé API personnelle** :

- Vérifiez l'en-tête `Authorization: Bearer ely_api_…` (préfixe `ely_api_`).
- La clé se crée dans **Réglages → Clés API** (`/settings/api-keys`). Son
  secret en clair n'est affiché **qu'une seule fois** à la création.
- Une clé **révoquée ou inexistante** → `401`.
- Maximum **20 clés actives** par utilisateur.

---

## Still stuck?

- **Open an issue** with: OS, Docker version (`docker --version`), `make up` last 30 lines of output, content of `make logs s=backend | tail -30`.
- **Or email** contact@agent-ely.fr — we reply within 48h, always.

GitHub: https://github.com/franckolv-dev/ElyAgent/issues
