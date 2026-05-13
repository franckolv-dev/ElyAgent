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
curl -s http://localhost:8000/api/settings/llm | python3 -m json.tool
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

## 🌍 Browser extension doesn't connect

See [`extension/chrome/README.md`](../extension/chrome/README.md) — the 3 most common issues there are:
1. Extension reloaded but old service worker still cached → `chrome://extensions/` → 🔄 Reload
2. Backend URL has a trailing slash → strip it
3. Token expired → grab a fresh one from `localStorage.ely_access_token` in the ELY web UI (DevTools → Application → Local Storage)

---

## Still stuck?

- **Open an issue** with: OS, Docker version (`docker --version`), `make up` last 30 lines of output, content of `make logs s=backend | tail -30`.
- **Or email** contact@agent-ely.fr — we reply within 48h, always.

GitHub: https://github.com/franckolv-dev/ElyAgent/issues
