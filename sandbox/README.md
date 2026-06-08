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

See [`docs/external-references/sprint-4b-v3-real-io-extension-j0-fr.md`](../docs/external-references/sprint-4b-v3-real-io-extension-j0-fr.md) (gitignored, local design note) for the full V3 plan.
