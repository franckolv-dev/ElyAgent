#!/usr/bin/env bash
# =============================================================================
# Sprint 4b V3 J2.c — sandbox runner end-to-end smoke.
#
# Brings up `sandbox` + its `egress-proxy` dependency, then POSTs a handful
# of `/run` jobs from inside sandbox-net (the only network that can reach
# the runner). Pins every invariant we depend on:
#
#   1. Pure computation: source → returned (correct value).
#   2. Allowed network egress: httpx → example.com → 200.
#   3. Denied egress: httpx → google.com → ProxyError 403 (NOT exception
#      from the runner — the user code observes the proxy refusal).
#   4. User-code exception: outcome=raised + traceback captured.
#   5. Wall-clock timeout: outcome=timeout in ~timeout_s.
#   6. Hardening: rootfs is read-only; opening a file for write fails.
#
# Exits 0 on success, non-zero on first failed invariant.
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

PROJECT_NAME="$(basename "$PROJECT_DIR" | tr '[:upper:]' '[:lower:]' | tr -dc 'a-z0-9_-')"
NET="${PROJECT_NAME}_sandbox-net"
CURL_IMAGE="curlimages/curl:latest"

PASS=0
FAIL=0

# Tiny in-net curl helper that POSTs JSON and prints the response body.
post() {
  local body="$1"
  docker run --rm --network "$NET" "$CURL_IMAGE" \
    -sS --max-time 30 -H "Content-Type: application/json" \
    -X POST -d "$body" http://sandbox:8080/run
}

# Walks the JSON response looking for a `"foo":` field. Simplistic but enough
# for our tests (no real JSON parser needed inside the bash script).
field() {
  local json="$1" key="$2"
  echo "$json" | sed -E "s/.*\"$key\":\"?([^,\"}]*)\"?.*/\1/"
}

assert_contains() {
  local name="$1" actual="$2" needle="$3"
  if echo "$actual" | grep -qF "$needle"; then
    echo "  ✓ $name"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $name (looking for '$needle' in: ${actual:0:200}…)"
    FAIL=$((FAIL + 1))
  fi
}

# ── Bring up just sandbox + its egress-proxy dep ─────────────────────────────
echo "▶ Starting sandbox + egress-proxy…"
docker compose up -d --build sandbox >/dev/null
trap 'echo "▶ Cleaning up…"; docker compose stop sandbox egress-proxy >/dev/null 2>&1 || true' EXIT

docker pull "$CURL_IMAGE" >/dev/null 2>&1 || true

# Wait for /healthz to come back OK (compose healthcheck does the same but
# we poll directly so the wait is bounded).
for _ in {1..30}; do
  if docker run --rm --network "$NET" "$CURL_IMAGE" \
       -fsS --max-time 2 http://sandbox:8080/healthz >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo ""
echo "▶ Runner invariants:"

# 1. Pure computation
out=$(post '{"source":"def double_it(x: int) -> int:\n    return x * 2\n","func_name":"double_it","kwargs":{"x":21}}')
assert_contains "[1] pure computation returns 42" "$out" '"result_json":"42"'

# 2. Allowed egress (httpx via proxy → example.com)
out=$(post '{"source":"import httpx\ndef fetch():\n    r = httpx.get(\"https://example.com\", timeout=5)\n    return r.status_code\n","func_name":"fetch","timeout_s":10}')
assert_contains "[2] httpx via proxy to example.com → 200" "$out" '"result_json":"200"'

# 3. Denied egress — must surface as a ProxyError caught by user code
out=$(post '{"source":"import httpx\ndef try_blocked():\n    try:\n        httpx.get(\"https://google.com\", timeout=5)\n        return \"unexpected_pass\"\n    except Exception as e:\n        return f\"{type(e).__name__}:{str(e)[:80]}\"\n","func_name":"try_blocked","timeout_s":10}')
assert_contains "[3] httpx to google.com is denied by proxy" "$out" 'ProxyError'
assert_contains "[3] proxy returns 403 to the user code"     "$out" '403'

# 4. User-code raise
out=$(post '{"source":"def boom():\n    raise ValueError(\"intentional\")\n","func_name":"boom"}')
assert_contains "[4] user-code raise → outcome=raised" "$out" '"outcome":"raised"'
assert_contains "[4] error message preserved"          "$out" 'ValueError: intentional'

# 5. Wall-clock timeout
out=$(post '{"source":"def hang():\n    while True:\n        pass\n","func_name":"hang","timeout_s":2}')
assert_contains "[5] infinite loop → outcome=timeout" "$out" '"outcome":"timeout"'

# 6. Read-only rootfs — writing OUTSIDE /tmp must fail (tmpfs /tmp is fine)
out=$(post '{"source":"def write_outside():\n    open(\"/opt/runner/probe\", \"w\").write(\"nope\")\n    return \"unexpected\"\n","func_name":"write_outside"}')
assert_contains "[6] write to /opt → outcome=raised (read-only rootfs)" "$out" '"outcome":"raised"'
assert_contains "[6] error mentions read-only or permission"           "$out" 'OSError'

# 7. /tmp is writable (tmpfs), so the same write inside /tmp succeeds.
out=$(post '{"source":"def write_tmp():\n    open(\"/tmp/probe\", \"w\").write(\"hello\")\n    return open(\"/tmp/probe\").read()\n","func_name":"write_tmp"}')
assert_contains "[7] /tmp tmpfs is writable" "$out" '"result_json":"\"hello\""'

echo ""
echo "────────────────────────"
echo "Result: ${PASS} pass / ${FAIL} fail"
echo "────────────────────────"
exit "$FAIL"
