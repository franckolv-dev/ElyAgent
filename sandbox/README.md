# ELY sandbox image

Base image for the **python_tool sandbox** (Sprint 4b V3). Runs LLM-generated
Python code that does real network I/O, on an isolated network behind an
egress proxy. **Off by default** (gated by `LEARNED_PYTHON_TOOLS_IO_ENABLED`).

## Build locally

```bash
docker build -t ely-sandbox:latest -f sandbox/Dockerfile .
docker run --rm ely-sandbox:latest
# → ely-sandbox image OK
```

## What's inside

- `python:3.12-slim` base, non-root user (`sandbox:sandbox`, uid 1000).
- Curated, **pinned** third-party deps — see `requirements.txt`.
  V3.0 = HTTP GET read-only, so the list is intentionally tiny (`httpx`,
  `beautifulsoup4`, `lxml`). Bumping requires a PR (no auto-update).
- `pip` is **uninstalled** after deps are installed — the running container
  can never install new packages. Bumping the allow-list rebuilds the image.
- All setuid/setgid bits stripped from system binaries.
- No `gcc`/`make`/`bash` (slim base + we don't add any).

## Runtime contract (what J2.c will enforce)

This image is designed to be run by the `sandbox` service in
`docker-compose.yml` with:

- `read_only: true` (rootfs read-only, only `/tmp` writable via tmpfs)
- `cap_drop: [ALL]`
- `security_opt: [no-new-privileges]`
- Resource limits (cpus / memory / pids)
- Connected to a dedicated `sandbox-net` network with **no route** to the
  other ELY services — all egress must transit the `egress-proxy` service.

## Updating the curated deps

1. Edit `sandbox/requirements.txt` (pin a new exact version).
2. PR the change with a brief justification (why this library is needed).
3. CI rebuilds the image to validate it still builds.
4. Once merged + deployed, the new lib is available to generated tools.

---

## J2.b — Egress proxy & isolated network

`docker-compose.yml` adds:

- **`sandbox-net`** — Docker bridge with `internal: true`. Containers on
  this network have **no implicit route** to the Internet, and cannot reach
  the other ELY services (backend, qdrant, nginx, frontend) which live on
  `cyberentity-net`. The future sandbox service (J2.c) will live HERE.
- **`egress-proxy`** — Squid forward proxy (`ubuntu/squid:6.6-24.04_beta`),
  dual-homed on `sandbox-net` (accepts sandbox traffic) and `cyberentity-net`
  (forwards allowed traffic upstream). Config in `sandbox/squid.conf`.

Allow-list is per-domain (`dstdomain`), deny-by-default. V3.0 ships with
**only `httpbin.org` and `example.com`** for smoke testing — every real
integration adds its domain via PR.

### Egress policy enforced
- HTTP/HTTPS to **allow-listed** domains: pass through (HTTPS via CONNECT
  tunnel; the proxy sees the SNI hostname but NOT the encrypted payload —
  no MITM).
- HTTP/HTTPS to anything else: **403** (deny by default).
- All **RFC1918 / loopback / link-local** destinations (incl. AWS/GCP
  cloud metadata `169.254.169.254`): **403, fast** (the ACL fires before
  any DNS lookup, so denies return in ~0 s).
- Methods other than **GET / HEAD / CONNECT**: **403** (V3.0 = read-only;
  POST/PUT/DELETE land in V3.x).
- No caching (`cache deny all`) — every request actually hits the upstream,
  so the agent never sees stale responses.

### Adding a domain to the allow-list

1. Edit `acl allowed_domains` in `sandbox/squid.conf` (use the leading-dot
   form `.example.com` to allow all subdomains).
2. PR with a brief justification (which generated-tool integration needs it).
3. CI runs `sandbox/test-egress.sh` to confirm the proxy still boots and
   the 8 security invariants still hold.
4. After merge + `docker compose up -d --build egress-proxy`, the new
   domain is reachable.

### Smoke-testing locally

```bash
./sandbox/test-egress.sh
```

The script brings up only `egress-proxy`, spawns a curl-equipped client
on `sandbox-net`, runs the 8 invariants (allow-list pass-through, denies,
fast cloud-metadata deny, GET-only, isolation from other services), then
cleans up. Exits non-zero on any failed invariant — the CI uses the same
script.

### Watching live traffic

`docker logs ely-egress-proxy` shows only Squid's startup banner (cache_log).
Per-request access entries land in the file `/var/log/squid/access.log`
inside the container — Squid 6 refuses to run as root, and `/dev/stdout`
isn't writable from the `proxy` user, so we write to a file instead.

```bash
docker exec ely-egress-proxy tail -F /var/log/squid/access.log
```

---

## J2.c — Sandbox runner service

The actual execution surface. Receives a job spec (Python source + function
name + kwargs + timeout), runs it in a fresh `python -S` subprocess on the
**system** Python (the one with the curated allow-list), captures the JSON
outcome, returns it as the HTTP response.

### HTTP surface

```
POST /run
  { "source": "...", "func_name": "...", "kwargs": {...}, "timeout_s": 8 }
→ 200 application/json
  { "outcome": "returned" | "raised" | "nonserializable" | "timeout" | "crashed" | "error",
    "duration_s": 0.123,
    "result_json": "...",      # outcome=returned (the JSON-encoded result)
    "result_repr": "...",      # outcome=nonserializable
    "error": "...", "trace": "...", "stage": "import|call",  # outcome=raised
    "detail": "...",           # outcome=timeout / error / crashed
    "stdout": "...", "stderr": "..." }   # always, size-capped

GET /healthz   → { "status": "ok" }   (compose healthcheck)
GET /          → { "service": "ely-sandbox-runner", "ok": "true" }
```

Outcome vocab mirrors the in-process `SmokeReport` (`smoke_sandbox.py`) so
the backend can reuse the same handling code.

### Runtime hardening (docker-compose `sandbox` service)

- `read_only: true` — rootfs fully read-only.
- `tmpfs: /tmp:size=64m` — only writable path inside the container.
- `cap_drop: [ALL]` — every Linux capability dropped.
- `security_opt: [no-new-privileges:true]` — child process can't gain caps.
- `pids_limit: 64` — blocks fork bombs.
- `mem_limit: 512m` — OOM-killed before the host sweats.
- `cpus: 0.5` — half-core ceiling on the container.
- Network: **only sandbox-net**. The runner is invisible outside it, and
  outbound HTTP/HTTPS must transit `egress-proxy` (HTTP(S)_PROXY env).
- Inner limits (in the wrapper, via setrlimit before user code runs):
  - `RLIMIT_CPU` = 10 s (configurable via `ELY_SANDBOX_CPU_SECONDS`).
  - `RLIMIT_AS` = 256 MiB (configurable via `ELY_SANDBOX_MEM_BYTES`).
  - `RLIMIT_FSIZE` = 1 MiB.

### Why two Pythons in the image?

- `/opt/runner-venv/bin/python` — the **runner** venv: holds FastAPI +
  uvicorn + pydantic. Runs the HTTP server.
- `/usr/local/bin/python` — the **system** Python: holds the curated
  third-party libs (httpx, bs4, lxml). This is what the runner spawns for
  every user job. Pip is uninstalled here, so the running tool can never
  install new packages.

`-S` is kept on the subprocess (no implicit `site.py` init), and the system
site-packages path is passed via `PYTHONPATH` so the curated libs are
findable. Anything else stays invisible.

### Smoke-testing locally

```bash
./sandbox/test-sandbox-run.sh
```

10 invariants: pure compute, allowed egress (httpx → example.com → 200),
denied egress (httpx → google.com → ProxyError 403 surfaced to user code),
user-code raise captured, wall-clock timeout, read-only rootfs enforced,
/tmp tmpfs writable. Same script the CI runs.

---

See [`docs/external-references/sprint-4b-v3-real-io-extension-j0-fr.md`](../docs/external-references/sprint-4b-v3-real-io-extension-j0-fr.md) (gitignored, local design note) for the full V3 plan.
