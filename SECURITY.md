# Security Policy

ELY is a self-hosted AI agent that handles personal data, OAuth credentials, channel tokens, and can execute tools (mail send, file delete, SSH commands…). Security is not a feature — it's a prerequisite.

If you find a vulnerability, please **disclose responsibly**.

---

## Supported versions

Only the `master` branch is supported. Tagged releases receive critical security patches for 90 days after release; older versions get nothing.

| Branch / Version | Security updates |
|------------------|-------------------|
| `master`         | ✅ Active         |
| Latest tag       | ✅ 90-day window  |
| Older tags       | ❌ No support     |

---

## Reporting a vulnerability

**Do NOT open a public GitHub issue for security bugs.**

Email **franck.olv@gmail.com** with subject prefix `[SECURITY]`. Include :

1. Affected component (backend / frontend / Android / iOS / desktop / channel)
2. Exact version or commit SHA
3. Step-by-step reproduction (or PoC)
4. Impact assessment (data exposure, RCE, DoS, auth bypass…)
5. Suggested fix if you have one

You can request a PGP-encrypted reply if you provide your public key.

### Response timeline

| Step | Target |
|------|--------|
| Acknowledgement | Within 48 hours |
| Initial triage | Within 7 days |
| Fix or mitigation merged | Within 30 days for high/critical, 90 days for medium/low |
| Public disclosure | Coordinated; usually 7 days after the fix lands on `master` |

Critical issues (active exploitation, RCE without auth, mass credential leak) get expedited handling.

---

## Hall of fame

Researchers who responsibly disclosed valid vulnerabilities will be credited here (with permission) :

*(empty — be the first !)*

---

## Out of scope

The following are not considered vulnerabilities for this project :

- **Self-DoS** : you can hammer your own backend, don't expect rate-limit to protect you from yourself
- **HITL bypass via your own admin account** : the admin role is intentionally powerful — don't share it
- **API key validation calls during bootstrap** : the `/setup/validate-key` endpoint is open BEFORE the first user is created (no admin yet to gate it). Once any user exists, it requires admin auth. This is by design for first-launch UX.
- **Cookies in localStorage** : the access token (60-min lifetime) is stored in localStorage so the SPA can attach it to fetch headers. The refresh token (7 days) is in HttpOnly cookie. This trade-off is documented and accepted.
- **Channel webhook spam** : if your Telegram bot token leaks, attackers can spam your webhook. ELY's HITL + per-user `_linked_users` mapping means they still can't impersonate you, but they can DoS the agent loop. Rotate the token.

---

## Security best practices for operators

If you self-host ELY, **at minimum** :

1. **Generate a strong `JWT_SECRET_KEY`** : `openssl rand -hex 32` (the default is `CHANGE-ME-...` and the app refuses to start with it in production)
2. **Run behind HTTPS** : Cloudflare Tunnel, Caddy, nginx with Let's Encrypt — never expose port 8000 directly
3. **Lock down `CORS_ORIGINS`** : never use `*` in production
4. **Rotate your channel tokens periodically** (Telegram, Discord, Slack, WhatsApp Business)
5. **Don't commit `.env`** : it's in `.gitignore` for a reason
6. **Run as non-root** : the Docker image already does (`USER appuser`), don't override with `--user root`
7. **Backup regularly** : Qdrant snapshot is automated nightly at 02:00 (`qdrant_backup` job), but verify the file lands in `data/backups/`
8. **Patch fast** : subscribe to GitHub watch on this repo for security advisories

---

## Cryptography

- **Passwords** : Argon2id via `pwdlib`, with sane parameters
- **JWT** : HS256, 32-byte minimum secret enforced
- **Vault secrets** : AES-256-GCM with per-user key derived from password (zero-knowledge — server can't read after lock)
- **At rest** : SQLite + Qdrant files inherit OS file permissions; encrypt the host filesystem if you handle sensitive data

---

## Threat model (summary)

ELY is designed for **single-user or family/small-team deployments behind a trusted edge**. It is NOT designed for :

- ❌ Multi-tenant SaaS without further hardening
- ❌ Public-facing chat exposed to anonymous internet traffic
- ❌ Untrusted prompt sources (the agent will execute what tools you bind to it)

If you operate ELY at scale, you'll need to add : per-user resource quotas, prompt injection detection, tool allowlists per user, audit log monitoring, and probably a Web Application Firewall.

---

Thanks for helping keep ELY safe ❤️
