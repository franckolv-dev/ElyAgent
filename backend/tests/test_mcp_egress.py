# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_egress.py
# @brief      J2 — garde SSRF / DNS-rebinding des serveurs MCP distants.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Matrice SSRF + rebinding + pinning du transport HTTP durci.

C'est la barrière *load-bearing* du chemin « connexion autonome remote
HTTPS » : si elle cède, un résultat empoisonné peut faire viser le réseau
interne ou les métadonnées cloud. Tests fail-closed et exhaustifs.
"""
from __future__ import annotations

import pytest

from app.services.mcp_egress import (
    MCPEgressBlocked,
    build_guarded_http_factory,
    is_blocked_ip,
    validate_egress_url,
)


# ─────────────────────────────────────────────────────────────────────────
# Classification IP
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "127.5.5.5",              # loopback
    "::1",                                  # loopback v6
    "10.0.0.1", "192.168.1.1", "172.16.0.1",  # privé RFC1918
    "169.254.169.254",                      # MÉTADONNÉES cloud (link-local)
    "169.254.0.1",                          # link-local
    "fd00::1", "fc00::1",                   # ULA v6
    "fe80::1",                              # link-local v6
    "100.64.0.1",                           # CGNAT
    "0.0.0.0",                              # unspecified
    "224.0.0.1",                            # multicast
    "::ffff:10.0.0.1",                      # IPv4 privée mappée en IPv6
])
def test_blocked_ips(ip):
    assert is_blocked_ip(ip) is True, f"{ip} doit être bloqué"


@pytest.mark.parametrize("ip", [
    "1.1.1.1", "8.8.8.8", "93.184.216.34",  # public v4
    "2606:4700:4700::1111",                  # public v6 (Cloudflare)
])
def test_allowed_public_ips(ip):
    assert is_blocked_ip(ip) is False, f"{ip} doit passer"


def test_unparsable_ip_is_blocked_failclosed():
    assert is_blocked_ip("not-an-ip") is True


# ─────────────────────────────────────────────────────────────────────────
# Validation d'URL
# ─────────────────────────────────────────────────────────────────────────


def _resolver(ips):
    return lambda host: list(ips)


def test_https_public_passes():
    t = validate_egress_url("https://mcp.example.com/mcp", resolver=_resolver(["93.184.216.34"]))
    assert t.host == "mcp.example.com"
    assert t.validated_ips == ["93.184.216.34"]
    assert t.port == 443


def test_http_rejected_when_https_required():
    with pytest.raises(MCPEgressBlocked) as e:
        validate_egress_url("http://mcp.example.com/mcp", resolver=_resolver(["93.184.216.34"]))
    assert e.value.code == "MCP_EGRESS_SCHEME"


def test_credentials_in_url_rejected():
    with pytest.raises(MCPEgressBlocked) as e:
        validate_egress_url("https://user:pass@mcp.example.com/mcp",
                            resolver=_resolver(["93.184.216.34"]))
    assert e.value.code == "MCP_EGRESS_URL_CREDENTIALS"


@pytest.mark.parametrize("url", [
    "https://localhost/mcp",
    "https://foo.local/mcp",
    "https://svc.internal/mcp",
    "https://metadata.google.internal/mcp",
])
def test_internal_hostnames_rejected_before_dns(url):
    # resolver renverrait du public, mais le nom est bloqué en amont.
    with pytest.raises(MCPEgressBlocked):
        validate_egress_url(url, resolver=_resolver(["93.184.216.34"]))


def test_dns_resolving_to_private_is_blocked():
    with pytest.raises(MCPEgressBlocked) as e:
        validate_egress_url("https://sneaky.example.com/mcp", resolver=_resolver(["10.0.0.5"]))
    assert e.value.code == "MCP_EGRESS_PRIVATE"


def test_dns_rebinding_mixed_answer_is_blocked():
    """Une seule IP interne dans la réponse DNS suffit à refuser (fail-closed)."""
    with pytest.raises(MCPEgressBlocked):
        validate_egress_url(
            "https://rebind.example.com/mcp",
            resolver=_resolver(["93.184.216.34", "169.254.169.254"]),
        )


def test_literal_private_ip_blocked():
    with pytest.raises(MCPEgressBlocked):
        validate_egress_url("https://10.0.0.1/mcp", resolver=_resolver([]))


@pytest.mark.parametrize("host", [
    "2130706433",      # décimal = 127.0.0.1
    "0x7f000001",      # hexadécimal = 127.0.0.1
    "017700000001",    # octal = 127.0.0.1
])
def test_encoded_loopback_blocked(host):
    with pytest.raises(MCPEgressBlocked):
        validate_egress_url(f"https://{host}/mcp", resolver=_resolver([]))


def test_metadata_ip_literal_blocked():
    with pytest.raises(MCPEgressBlocked):
        validate_egress_url("https://169.254.169.254/latest/meta-data/", resolver=_resolver([]))


def test_allow_private_bypasses_for_lan_exception():
    # Exception LAN explicite (admin, hors V1) : la cible privée passe.
    t = validate_egress_url("https://192.168.1.50/mcp", allow_private=True, resolver=_resolver([]))
    assert t.host == "192.168.1.50"


# ─────────────────────────────────────────────────────────────────────────
# Transport durci — pinning anti-rebinding
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transport_pins_to_validated_ip(monkeypatch):
    """Le transport se connecte à l'IP validée mais conserve Host + SNI."""
    import httpx

    captured: dict = {}

    async def fake_super(self, request):
        captured["url"] = str(request.url)
        captured["host"] = request.headers.get("Host")
        captured["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_super)

    factory = build_guarded_http_factory(resolver=_resolver(["93.184.216.34"]))
    client = factory()
    try:
        req = httpx.Request("GET", "https://mcp.example.com/mcp")
        resp = await client._transport.handle_async_request(req)
        assert resp.status_code == 200
        assert "93.184.216.34" in captured["url"]   # épinglé sur l'IP validée
        assert captured["host"] == "mcp.example.com"  # Host d'origine préservé
        assert captured["sni"] == "mcp.example.com"   # SNI/cert sur le hostname
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_transport_blocks_private_target(monkeypatch):
    """Une redirection / connexion vers une IP privée lève au niveau transport."""
    import httpx

    async def fake_super(self, request):  # ne doit jamais être atteint
        raise AssertionError("la connexion vers une cible privée ne doit pas partir")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_super)

    factory = build_guarded_http_factory(resolver=_resolver(["10.0.0.9"]))
    client = factory()
    try:
        req = httpx.Request("GET", "https://evil.example.com/redirected")
        with pytest.raises(MCPEgressBlocked):
            await client._transport.handle_async_request(req)
    finally:
        await client.aclose()
