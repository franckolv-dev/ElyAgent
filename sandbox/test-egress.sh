#!/usr/bin/env bash
# =============================================================================
# Sprint 4b V3 J2.b — egress-proxy invariants smoke test.
#
# Brings up the `egress-proxy` service alone, spawns a curl-equipped client
# on the isolated `sandbox-net`, and checks every property we depend on:
#
#   1. Internet is unreachable WITHOUT the proxy (network is internal).
#   2. Allow-listed domains (HTTP + HTTPS) succeed through the proxy.
#   3. Non-allow-listed domains are refused (HTTP 403).
#   4. Cloud metadata IPs are refused FAST (no 8 s timeout).
#   5. Non-safe HTTP methods (POST, PUT, DELETE, …) are refused.
#   6. Other compose services (backend, qdrant) are NOT reachable from
#      sandbox-net (the proxy is isolation, not the only check).
#
# Exits 0 on success, non-zero on first failed invariant.
# Designed to be runnable locally AND from the CI workflow.
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Resolve the sandbox-net name as docker-compose creates it (prefixed by
# the project name = basename of $PROJECT_DIR by default).
PROJECT_NAME="$(basename "$PROJECT_DIR" | tr '[:upper:]' '[:lower:]' | tr -dc 'a-z0-9_-')"
NET="${PROJECT_NAME}_sandbox-net"

CURL_IMAGE="curlimages/curl:latest"

PASS=0
FAIL=0

assert_eq() {
  local name="$1" got="$2" want="$3"
  if [[ "$got" == "$want" ]]; then
    echo "  ✓ $name"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $name (got=${got!r:-<empty>} want=${want})"
    FAIL=$((FAIL + 1))
  fi
}

assert_unreachable() {
  local name="$1" url="$2"
  # curl returns non-zero (6=DNS, 7=connect, 28=timeout) when the host is
  # unreachable; we accept any of those as proof of isolation.
  if docker run --rm --network "$NET" "$CURL_IMAGE" \
       -fsS --max-time 3 -o /dev/null "$url" >/dev/null 2>&1; then
    echo "  ✗ $name (unexpectedly REACHED $url)"
    FAIL=$((FAIL + 1))
  else
    echo "  ✓ $name"
    PASS=$((PASS + 1))
  fi
}

http_code_via_proxy() {
  # $1: method ; $2: URL ; stdout: 3-digit HTTP code (or 000 on transport error)
  local method="$1" url="$2"
  docker run --rm --network "$NET" "$CURL_IMAGE" \
    -sS --max-time 8 -o /dev/null -w "%{http_code}" \
    -x http://egress-proxy:3128 -X "$method" "$url" 2>/dev/null || echo "000"
}

# ── Bring up just the proxy ──────────────────────────────────────────────────
echo "▶ Starting egress-proxy…"
docker compose up -d egress-proxy >/dev/null
trap 'echo "▶ Cleaning up…"; docker compose stop egress-proxy >/dev/null 2>&1 || true' EXIT

# Pull the curl image once up-front so per-test latency stays predictable
docker pull "$CURL_IMAGE" >/dev/null 2>&1 || true

# Wait for Squid to actually accept connections (it logs "listening port: 3128")
for _ in {1..20}; do
  if docker logs ely-egress-proxy 2>&1 | grep -q "listening port: 3128"; then break; fi
  sleep 0.5
done

echo ""
echo "▶ Egress invariants:"

# 1. Network isolation (NO proxy → no Internet)
assert_unreachable "network is internal (no implicit Internet route)" "http://example.com"

# 2. HTTP allow-listed → 200
assert_eq "HTTP allow-listed (example.com) → 200" \
  "$(http_code_via_proxy GET http://example.com)" "200"

# 3. HTTP denied → 403
assert_eq "HTTP not-allow-listed (google.com) → 403" \
  "$(http_code_via_proxy GET http://google.com)" "403"

# 4. Cloud metadata IP → 403, FAST (the ACL must fire before DNS timeouts)
start=$(date +%s)
code=$(http_code_via_proxy GET http://169.254.169.254/)
elapsed=$(( $(date +%s) - start ))
if [[ "$code" == "403" && "$elapsed" -lt 4 ]]; then
  echo "  ✓ cloud metadata 169.254.169.254 → 403 in ${elapsed}s"
  PASS=$((PASS + 1))
else
  echo "  ✗ cloud metadata → ${code} in ${elapsed}s (want 403 in <4s)"
  FAIL=$((FAIL + 1))
fi

# 5. Non-safe methods refused (V3.0 = GET-only)
assert_eq "POST refused (V3.0 GET-only)" \
  "$(http_code_via_proxy POST http://httpbin.org/post)" "403"

# 6. HTTPS through CONNECT for allow-listed
assert_eq "HTTPS allow-listed (example.com) → 200" \
  "$(http_code_via_proxy GET https://example.com)" "200"

# 7. Internal services from cyberentity-net are unreachable from sandbox-net
assert_unreachable "backend:8000 unreachable from sandbox-net" "http://backend:8000/health"
assert_unreachable "qdrant:6333 unreachable from sandbox-net"  "http://qdrant:6333"

echo ""
echo "────────────────────────"
echo "Result: ${PASS} pass / ${FAIL} fail"
echo "────────────────────────"
exit "$FAIL"
