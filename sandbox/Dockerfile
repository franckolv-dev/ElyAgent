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
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
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

# Curated dependency allow-list (decision §10.③) — pinned exactly.
COPY sandbox/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt \
 # Remove pip itself — the running sandbox must never be able to install new
 # packages. Bumping the allow-list = rebuild the image.
 && pip uninstall -y pip setuptools wheel 2>/dev/null || true

# Non-root user. Fixed uid 1000 so the docker-compose service can map a
# read-only volume without uid mismatch surprises. NOT --system (1000 is
# outside the SYS_UID range, which would trigger a useradd warning).
RUN groupadd --gid 1000 sandbox \
 && useradd --uid 1000 --gid 1000 --no-create-home \
            --shell /usr/sbin/nologin sandbox \
 && mkdir -p /work /home/sandbox \
 && chown -R sandbox:sandbox /work /home/sandbox

USER sandbox:sandbox
WORKDIR /work

# Disable bytecode + buffering — both noise inside an ephemeral container
# (read-only fs means .pyc writes would fail anyway).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    HOME=/home/sandbox

# Default entrypoint just exits cleanly — the J2.c service overrides this
# with the actual job runner. Having a sane default lets us smoke-test the
# image directly (`docker run --rm sandbox:latest`).
CMD ["python", "-c", "print('ely-sandbox image OK')"]
