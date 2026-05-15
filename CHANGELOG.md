# Changelog

All notable changes to ELY are documented here, in reverse chronological order.

This file follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) convention. Each entry references the commit short-SHA so you can dig into the exact diff with `git show <sha>`.

Categories used:
- **Added** — new user-visible capabilities.
- **Changed** — non-breaking changes to existing behaviour or wording.
- **Fixed** — bug fixes.
- **Security** — anything touching auth, anonymization, HITL, sandboxing, or vault.
- **Docs** — documentation-only changes that nonetheless affect what users see.

> Maintainer: [Franck OLLIVIER](mailto:contact@agent-ely.fr) — `franckolv-dev`

---

## [Unreleased]

This section captures everything merged after `v1.1.0` (public launch, 11 May 2026). It will be tagged as `v1.1.2` once the LinuxFr-feedback dust settles.

### Fixed
- **`166d97d` — Tool-pair-aware context trimming.** The context manager used to drop messages from the head of the conversation when the token budget was exceeded, without checking that it didn't break a `tool_call ↔ tool_response` pair. DeepSeek (and every OpenAI-protocol provider) rejects orphan tool messages with `400 Bad Request`, which triggered the fallback chain down to weaker models. After the fix, trimming respects pairs: orphan `ToolMessage` in the head is skipped, dangling `AIMessage` with unanswered `tool_calls` in the tail is trimmed. *(2026-05-15)*
- **`a7bf15d` — Anti-hallucination prompt rules 5 & 6.** Mandatory temporal sanity-check before proposing any date (refuses to propose `Wednesday 13 May` when today is the 14th); explicit refusal threshold on lists with > 15-20 values at a regular interval (classic hallucination signature). *(2026-05-14)*
- **`596c329` — Pattern C: collapsed-UI handling.** Doctolib and similar SPAs render days as collapsible cards with the slots out of the DOM until you click the chevron. The agent now has a concrete recipe (read_html → identify chevron selector → click → wait_for_selector → read scoped) and a hard refusal rule when the same precise values appear for two distinct items (e.g. identical slots for two different days). *(2026-05-14)*
- **`e797e1a` — Anti-hallucination rules 1-4 + Pattern C bootstrap.** First version of the rules forbidding fabrication of precise values, vision-for-numerics misuse, and context-coherence violations. *(2026-05-14)*
- **`403c48d` — Revert needless LOCKED_HITL on `scheduler_delete_task`.** User-initiated deletion of their own scheduled tasks shouldn't require HITL confirmation — pure friction. The previous commit had added it "for safety" but `scheduler_delete_task` wasn't in `ALWAYS_CRITICAL_TOOLS` anyway, so the lock was a no-op with a misleading docstring. *(2026-05-14)*
- **`6423c29` — Expose scheduler list + delete to the default agent profile.** The tools existed but only `scheduler_create_task` was bound to the agent. Symptom: ELY would create scheduled tasks but answer "I have no tool to delete them" and resort to scheduling a cleanup task for tomorrow at 9am. Regression-guard test included. *(2026-05-14)*
- **`e5b1a2e` — Contrast fix on `/settings/extension`.** The amber "new token created" banner used `bg-amber-50` with default text colour, which rendered as light-grey-on-cream in dark mode — barely legible. Switched to theme-agnostic semi-transparent overlays. *(2026-05-14)*

### Added
- **`6726b27` — Sprint 1: browser interactivity tools.** `browser_tab_click(selector)`, `browser_tab_fill(selector, value)`, `browser_tab_navigate(url)`. React-aware implementations (native value setter + dispatchEvent for controlled inputs; MouseEvent + native click for buttons). Trust model: agent only emits these on explicit user request, user sees the tab live in their own Chrome. Unlocks multi-step SPA workflows (Doctolib, SNCF, Booking, .gouv.fr forms). *(2026-05-14)*
- **`56acb6e` — Sprint 0.5: long-lived extension tokens.** New `ExtensionToken` model + REST CRUD `/api/extension/tokens` + dedicated Settings page. Format `ely_ext_<48 hex>` (192 bits of entropy). SHA-256 + last_4 stored; plaintext shown exactly once at creation, then never. Replaces the previous DevTools → Application → Local Storage → copy-JWT bidouille, and ends the every-60-min disconnection. Backwards compatible: the WS handshake still accepts legacy access JWTs. *(2026-05-14)*

### Docs
- **`166d97d` indirectly** — `docs/security.md` will be updated to call out the trim-boundary class of bugs in the next sweep.
- **`e9e3553` — LinuxFr feedback addressed across docs.** ROADMAP.md reformulated to drop ambiguous "open-source" claims (we are source-available); `docs/security.md` gains a "Limites assumées de l'anonymisation déterministe" section (corpus-wide frequency attack, out-of-pattern PII, indirect inference, hash reversibility); `docs/installation.md` gains a chapter "8. Exposer ELY à l'extérieur" with three options (Tailscale → Caddy+Let's Encrypt → Cloudflare Tunnel) ranked by sovereignty; FAQ FR + EN clarified for non-profits (strict non-commercial = free, no paperwork). *(2026-05-15)*
- **`094f257` — Roadmap aligned with reality + MCP expanded.** Sprint 0.5 (Chrome extension) inserted between launch and memory-recall; Sprint 3.5 (Web Automation) reframed as complementary to the extension (batch use cases); Sprint 4 (MCP) expanded from a single line into four sub-items: 4.1 consume external MCP servers, 4.2 expose ELY as MCP server, 4.3 Settings UI, 4.4 OAuth manager. New `v1.1.2` row in the target versions table. *(2026-05-15)*

---

## [1.1.0] — 2026-05-11 — Public launch

Initial public release on GitHub. The repository was opened from private to public on Wednesday 12 May 2026; the actual development had been ongoing since early March 2026 (200+ commits, see `git log` for the pre-launch history).

### Added (launch capabilities)
- **Multi-LLM routing** with tier A/B/C/IMG and per-conversation fallback chain. Default routing: Tier A = Ministral 3B local; Tier B = DeepSeek v4-flash → v4-pro → Qwen 3.6 Flash → Ministral; Tier C = DeepSeek v4-pro primary; Tier IMG = DeepSeek v4-flash. Configurable per-user in Settings → Routing.
- **Native PII anonymization** before any cloud LLM call — credit cards, emails, tokens, IBANs, French phone numbers, named entities via NER. Deterministic mapping within a session so the LLM can reason on relationships.
- **HITL gating** on every irreversible action (gmail_send_email, calendar_delete_event, drive_delete_file, ssh_execute, vault_unlock, plus 20+ others in `LOCKED_HITL_TOOLS`). Per-user preferences, force-locked for the most destructive operations.
- **Multi-channel access**: Web UI (Next.js, FR + EN), Telegram bot, Slack app, Discord bot, WhatsApp (via webhook), iOS PWA, Android FCM push.
- **374/374 pytest** tests passing at launch.
- **Sovereignty modes documented**: 100 % local (Ministral on user's Mac), 100 % EU (Mistral only), or mixed performant (DeepSeek + Mistral + anonymization).
- **`feat(extension): browser companion`** *(`71bcbc6`)* — Chrome extension Sprint 0: WebSocket handshake, tab listing, DOM read, screenshot. Foundation for Sprint 0.5 and Sprint 1 that landed three days later.
- **`feat(install): bullet-proof first-time install`** *(`5fe0410`)* — install audit on a fresh `/tmp/ely-fresh-test/` sandbox surfaced 10 bugs (Python 3 detection on Mac Sequoia, hardcoded ports, password policy not documented…); all fixed in this release.
- **`feat(ui): mobile hamburger drawer`** *(`a67aedd`)* — sidebar properly collapses on screens under 768 px instead of being truncated at 64 px wide.
- **`feat(dashboard): per-user stats opened to all users`** *(`236c1af`)* — every user can see their own LLM cost/usage breakdown, no longer admin-only.
- **`feat(prompt): RÈGLE INVIOLABLE anti-confabulation`** *(`ef9c047`)* — early version of the anti-hallucination guard for factual queries.
- **`feat(desktop): 9 filesystem tools`** *(`725ce7b`)* — ELY Desktop daemon exposes read + write filesystem tools, with HITL forced on destructive operations.

### Security
- **`chore(security): harden .gitignore before public launch`** *(`da3908d`)* — extra patterns to prevent accidental commit of `.env`, `credentials.json`, `*.p8`, `*.safetensors`, vault DB.

### Fixed (right before launch)
- **`fix(auth): clear stale tokens on login + fix SameSite mismatch`** *(`470700e`)* — fresh-install testing surfaced session-expired errors on new devices; root cause in cookie SameSite policy.
- **`fix(deepseek): auto-swap to deepseek-chat for multi-turn`** *(`dbdcd90`)* — `v4-flash` and `v4-pro` reject multi-turn tool_calls with HTTP 400 unless `thinking={"type": "disabled"}` is passed.
- **`fix(name): Ely canonical spelling`** *(`cc1f103`, `966a72a`)* — agreed in May 2026 to standardise on "Ely" (no accent), pronounced "Éli". All onboarding messages and HITL notifications now use the canonical form.

---

## Pre-1.1.0 — Private development (March-May 2026)

The 200+ commits from `2026-03-09` (repo created) to `2026-05-11` (public launch) are not individually listed here. Highlights:

- **Phase 1** *(March)* — Bot Telegram integration, HITL via inline buttons, session linking via `/link` command.
- **Phase 2** *(March)* — Scheduled tasks with APScheduler, natural-language cron creation ("rappelle-moi tous les lundis à 9h").
- **Phase 3** *(March)* — Hybrid memory: SQLite FTS5 for keyword + Qdrant for semantic, time-decay weighting, automatic fact extraction.
- **Phase 4** *(March)* — Skill registry (`@register` decorator), 11 builtin skills (system, gmail, calendar, drive, docs, sheets, tasks, scheduler, météo, actualités, traduction).
- **Phase 5** *(March-April)* — Server-side Playwright browser control with per-user isolation, 7 tools, HITL on click/fill.
- **Phase 1bis** *(April)* — Slack, Discord, WhatsApp channels; agentic RAG; CI/CD.
- **Phase 2bis** *(April)* — Security marketplace, audit logging, skills marketplace foundations.
- **Phase 3bis** *(April)* — Voice wake "Éli", WebSocket `/ws/voice`, iOS SwiftUI app.
- **Phase 4bis** *(April)* — Mode Arena (ELO), agentic RAG v2, PWA.
- **Hermes Chantier 1** *(2026-05-07)* — sticky toolset profile per conversation + 13 fixes — 198 tests.
- **Hermes Chantiers 2, 4, 9, 10 partial** *(2026-05-08)* — prompt cache + frozen memory, transparent fallback chain, iteration budget + force_summary, toast UI on provider.switched — 340 tests.
- **Sovereignty stack 100 % Mistral pivot** *(2026-05-09)* — abandoned xLAM-2 8B (tool-call confabulation), validated Ministral 3B local + Mistral Small 4 + Mistral Large 3.

For the full pre-launch history, see `git log --pretty=format:"%h %ai %s" --until="2026-05-11"`.

---

## Reporting a bug

ELY ships without telemetry — this is deliberate. We will not silently collect usage data, error reports, or any signal from your installation. The flip side: we can't see your bugs from here.

If you spot a regression or hallucination, please open an [issue](https://github.com/franckolv-dev/ElyAgent/issues/new?template=bug_report.yml) with the new bug-report template (it asks for the model shown in the HUD at the time of the bug — critical for fallback-chain diagnostics).

For security-sensitive issues, do **not** open a public issue. See [`SECURITY.md`](./SECURITY.md) and e-mail `contact@agent-ely.fr`.

---

## Versioning policy

ELY follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html), adapted to a self-hosted personal AI agent:

- **Major (`x`.0.0)** — breaking change to the user's data, configuration, or API surface. Example: v2.0 will ship the LoRA-personnel-par-user feature, which changes how the LLM is stored on disk.
- **Minor (1.`x`.0)** — new capabilities or sprints from the [roadmap](./ROADMAP.md), backwards-compatible.
- **Patch (1.1.`x`)** — bug fixes, documentation, security hardening; no behaviour change beyond fixing what was broken.

The roadmap target-versions table tracks which sprint lands in which version.
