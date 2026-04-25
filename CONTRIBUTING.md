# Contributing to ELY

Thanks for your interest! ELY is a personal-AI-agent project under the [PolyForm Strict 1.0.0](LICENSE) license — usage is **free for personal, educational, and private testing**, but **commercial use and redistribution of modified versions require explicit prior agreement** with the author.

This contribution guide focuses on what's *welcome* in PRs and how to set up a dev environment.

---

## What kind of contributions are welcome

### ✅ Welcome

- **Bug fixes** with a clear repro (steps + expected vs actual)
- **Documentation improvements** (typos, clarifications, missing sections)
- **New skills** that follow the existing pattern in `backend/app/skills/`
- **Channel adapters** for chat platforms not yet supported (Mattermost, Rocket.Chat, etc.)
- **Translations** of the user guide / README
- **Performance improvements** on the agent loop or memory consolidation
- **Test coverage** improvements (pytest in `backend/tests/`)

### ⚠️ Discuss first (open an issue)

- Architectural changes (new sub-agent, new state field, new graph node)
- New LLM provider integration
- Major dependency upgrades (LangGraph, Next.js, FastAPI)
- New tier in the routing system
- Anything that adds a new top-level service to `docker-compose.yml`

### ❌ Not accepted

- Forks/derivatives intended for commercial use without prior agreement
- Removal of the license header from source files
- Code that disables HITL / security filters by default
- Telemetry / data exfiltration features

---

## Development setup

```bash
# 1. Clone
git clone https://github.com/franckolv-dev/PhysicalAgent.git
cd PhysicalAgent

# 2. Copy env templates
cp .env.example .env
# Edit .env: at minimum set JWT_SECRET_KEY (generate with: openssl rand -hex 32)
# Optional but recommended: set ANTHROPIC_API_KEY or use local Ollama (default)

# 3. Boot the stack
make up

# 4. Open http://localhost:3000 — first user created becomes admin automatically
```

### Backend (FastAPI + LangGraph)

```bash
cd backend
uv sync                              # install Python deps
uv run pytest tests/ -v              # run tests
uv run uvicorn app.main:app --reload # dev server with hot-reload
```

### Frontend (Next.js 16)

```bash
cd frontend
npm install
npm run dev                           # http://localhost:3000
npm run lint                          # ESLint
```

### Android (optional)

```bash
cd android
./gradlew assembleDebug              # build APK
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

---

## Pull request workflow

1. **Open an issue first** for non-trivial changes — saves you wasted work if the change isn't aligned
2. **Branch** off `master` with a clear name : `feat/<short-desc>`, `fix/<short-desc>`, `docs/<short-desc>`
3. **Commit messages** follow [Conventional Commits](https://www.conventionalcommits.org/) :
   - `feat(scope): description`
   - `fix(scope): description`
   - `docs(scope): description`
   - `refactor(scope): description`
   - `test(scope): description`
   - `chore(scope): description`
4. **Tests** : add or update tests for new behaviour
5. **License header** : keep the existing `# @author Franck OLLIVIER` block at the top of every source file
6. **PR description** : explain *why* (not just *what*), link the related issue
7. **CI** must pass (GitHub Actions runs pytest + frontend lint + build)

---

## Commit signing

Not required but appreciated. If you set up GPG signing, your commits will display a "Verified" badge on GitHub.

---

## Code of Conduct

By participating you agree to abide by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). The short version : be respectful, assume good faith, don't be a jerk.

---

## Reporting security vulnerabilities

**Don't open a public issue.** Email **franck.olv@gmail.com** with subject `[SECURITY] ...` — see [SECURITY.md](SECURITY.md) for the full process.

---

## Questions?

Open a [discussion](https://github.com/franckolv-dev/PhysicalAgent/discussions) (preferred) or an issue tagged `question`.

Happy hacking ! 🚀
