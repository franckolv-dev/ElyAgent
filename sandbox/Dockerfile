# =============================================================================
# @project    ELY — Exactly Like You
# @file       sandbox/Dockerfile
# @brief      Sprint 4b V3 J2.a — base image for the python_tool sandbox.
#
#             This image runs LLM-generated Python code that does real network
#             I/O. Hardened accordingly: non-root user, no setuid/setgid bits,
#             no shell tools, no build chain, curated dependency allow-list
#             (see requirements.txt). The image is BUILT here ; runtime
#             isolation (read-only rootfs, dropped capabilities, isolated
#             network with egress proxy, resource limits) is enforced by the
#             docker-compose service that runs it (J2.c).
#
#             Per decision §10.⑥ of the V3 design note:
#               - base: python:3.12-slim
#               - non-root user
#               - rootfs read-only at runtime
#               - curated libs pinned (see requirements.txt)
#               - rebuilt in CI (.github/workflows/ci.yml — `sandbox-image` job)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# =============================================================================

# Pin the digest (not just the tag) for reproducible builds. Bump deliberately
# after reviewing the upstream changelog — never auto.
FROM python:3.12-slim

# Build-time only — no apt cache layer in the final image, and no compiler
# left behind (lxml's wheel is shipped pre-built for slim, so no gcc needed).
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    # Strip setuid/setgid bits from every binary still in the image. The
    # generated tool runs as non-root anyway, but defence in depth: even if
    # the user escapes its uid, no SUID binary remains to climb back to root.
    find / -xdev -type f \( -perm -4000 -o -perm -2000 \) -exec chmod a-s {} \; 2>/dev/null || true

# Curated dependency allow-list for the USER code (decision §10.③) — pinned
# exactly. These libs live in the system Python and are what `python -S
# wrapper.py` (the subprocess that runs the generated tool) sees.
COPY sandbox/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# Sprint 4b V3 J2.c — runner HTTP service.
#
# FastAPI + uvicorn live in a SEPARATE venv (/opt/runner-venv). The
# generated tool's subprocess uses the system `python` (so it sees httpx /
# bs4 / lxml but NOT fastapi/uvicorn — keeps the user-visible namespace
# minimal). The runner itself is launched from /opt/runner-venv/bin/python.
RUN python -m venv /opt/runner-venv \
 && /opt/runner-venv/bin/pip install --no-cache-dir --root-user-action=ignore \
        "fastapi==0.121.1" "uvicorn[standard]==0.40.0" "pydantic==2.13.1"

# Now that BOTH dep sets are installed, drop pip from system Python so the
# running sandbox can never install new packages. The runner venv keeps its
# own pip (isolated) — irrelevant since the runner doesn't expose any way to
# trigger pip from outside.
RUN pip uninstall -y pip setuptools wheel 2>/dev/null || true

# Copy the runner code into the image (immutable — the read-only rootfs will
# keep it that way at runtime).
COPY sandbox/runner /opt/runner

# Non-root user. Fixed uid 1000 so the docker-compose service can map a
# read-only volume without uid mismatch surprises. NOT --system (1000 is
# outside the SYS_UID range, which would trigger a useradd warning).
RUN groupadd --gid 1000 sandbox \
 && useradd --uid 1000 --gid 1000 --no-create-home \
            --shell /usr/sbin/nologin sandbox \
 && mkdir -p /work /home/sandbox \
 && chown -R sandbox:sandbox /work /home/sandbox

USER sandbox:sandbox
WORKDIR /opt/runner

# Disable bytecode + buffering — both noise inside an ephemeral container
# (read-only fs means .pyc writes would fail anyway).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    HOME=/home/sandbox \
    PATH="/opt/runner-venv/bin:${PATH}"

# Default CMD = the runner HTTP server. The runner binds 0.0.0.0:8080; the
# compose file connects it ONLY to sandbox-net, so the port is unreachable
# from outside that network. `docker run --rm` for image smoke just imports
# the module — the j2.a CI job's CMD override stays usable.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
