# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_egress.py
# @brief      Garde SSRF / DNS-rebinding pour les connexions MCP distantes.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Défense egress des serveurs MCP distants (Streamable HTTP / legacy SSE).

Le modèle peut, depuis le 19/06, demander à Ely de se connecter de façon
AUTONOME à un serveur MCP distant HTTPS (cf. décision produit). Cette garde
est donc *load-bearing* : c'est la seule barrière entre un « connecte-toi à
http://169.254.169.254/… » (potentiellement glissé via un résultat
empoisonné) et le réseau interne / les métadonnées cloud.

Trois couches, toutes fail-closed :

1. **URL** : schéma `https` obligatoire (sauf localhost explicitement marqué
   dev), interdiction des credentials dans l'URL (`user:pass@`), host non
   vide.
2. **Résolution DNS** : on résout le host et on REFUSE si une seule des IP
   retournées est loopback / link-local / privée / ULA / multicast /
   réservée / métadonnées cloud (IPv4 et IPv6, formes encodées comprises).
3. **Pinning (anti-rebinding)** : le transport HTTP se connecte à l'IP
   *validée* (et re-valide chaque redirection), tout en conservant le Host
   et le SNI/cert d'origine via l'extension httpcore ``sni_hostname``. Pas
   de fenêtre TOCTOU entre la validation et le connect.

Toutes les fonctions de validation acceptent un ``resolver`` injectable pour
les tests (simulation de rebinding, d'IPv6, d'encodages alternatifs).
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Callable, NamedTuple
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

Resolver = Callable[[str], list[str]]


class MCPEgressBlocked(Exception):
    """Cible egress refusée. Le ``code`` est stable et sans secret."""

    def __init__(self, message: str, *, code: str = "MCP_EGRESS_BLOCKED") -> None:
        super().__init__(message)
        self.code = code


# Hostnames toujours bloqués (avant même la résolution).
_BLOCKED_HOSTNAMES = frozenset({
    "localhost",
    "metadata.google.internal",
    "metadata",
})
# Suffixes de domaines internes courants.
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")


def _default_resolver(host: str) -> list[str]:
    """Résout *host* en toutes ses adresses (A + AAAA) via getaddrinfo.

    getaddrinfo normalise au passage les encodages alternatifs (décimal,
    hexadécimal, octal) — ``2130706433`` ou ``0x7f000001`` ressortent en
    ``127.0.0.1`` et sont donc attrapés par la validation IP."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    out: list[str] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0]
        if ip not in out:
            out.append(ip)
    return out


def _normalize_ip(ip_str: str) -> ipaddress._BaseAddress:
    """Parse une IP, en dépliant les IPv4-mapped IPv6 (``::ffff:10.0.0.1``)."""
    addr = ipaddress.ip_address(ip_str)
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return addr.ipv4_mapped
        # 6to4 (2002::/16) embarque une IPv4 — on la déplie si possible.
        if addr.sixtofour is not None:
            return addr.sixtofour
    return addr


def is_blocked_ip(ip_str: str) -> bool:
    """True si l'IP vise une ressource interne / dangereuse.

    Couvre : loopback, link-local (dont 169.254.169.254 métadonnées),
    privé (RFC1918 + ULA fc00::/7), CGNAT, multicast, réservé, non spécifié,
    et les IPv4 embarquées dans une IPv6."""
    try:
        addr = _normalize_ip(ip_str)
    except ValueError:
        # Pas une IP parsable → on ne sait pas → on bloque (fail-closed).
        return True
    if (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_private
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    ):
        return True
    # CGNAT 100.64.0.0/10 (selon version Python is_private peut ne pas couvrir).
    if isinstance(addr, ipaddress.IPv4Address):
        if addr in ipaddress.ip_network("100.64.0.0/10"):
            return True
    return False


def _try_parse_host_as_ip(host: str) -> str | None:
    """Renvoie une IP canonique si *host* est un littéral IP (formes
    encodées comprises), sinon None.

    Bloque les ruses ``http://2130706433``, ``http://0x7f000001``,
    ``http://0177.0.0.1`` avant même la résolution."""
    h = host.strip("[]")  # IPv6 entre crochets
    # Forme standard.
    try:
        return str(ipaddress.ip_address(h))
    except ValueError:
        pass
    # Entier décimal (ex. 2130706433 = 127.0.0.1).
    try:
        return str(ipaddress.ip_address(int(h)))
    except (ValueError, OverflowError):
        pass
    # Hexadécimal / octal (ex. 0x7f000001, 017700000001).
    for base in (16, 8):
        try:
            return str(ipaddress.ip_address(int(h, base)))
        except (ValueError, OverflowError):
            pass
    return None


class EgressTarget(NamedTuple):
    scheme: str
    host: str            # hostname ou IP d'origine (pour Host + SNI)
    port: int
    validated_ips: list[str]   # IP(s) sûres vers lesquelles se connecter


def validate_egress_url(
    url: str,
    *,
    allow_private: bool = False,
    require_https: bool = True,
    resolver: Resolver | None = None,
) -> EgressTarget:
    """Valide une URL MCP distante. Lève ``MCPEgressBlocked`` si refusée.

    `allow_private` : exception LAN explicite (admin, hors V1). `require_https`
    : peut être relâché pour un localhost de DEV explicitement marqué — mais
    localhost reste bloqué par la validation IP sauf `allow_private`."""
    resolver = resolver or _default_resolver
    parts = urlsplit(url)

    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise MCPEgressBlocked(
            f"schéma non supporté : {scheme!r} (https requis)",
            code="MCP_EGRESS_SCHEME",
        )
    if require_https and scheme != "https":
        raise MCPEgressBlocked("HTTPS obligatoire pour un serveur MCP distant",
                               code="MCP_EGRESS_SCHEME")
    # Credentials dans l'URL → refus catégorique (fuite de secret + ambiguïté).
    if parts.username or parts.password:
        raise MCPEgressBlocked("credentials interdits dans l'URL",
                               code="MCP_EGRESS_URL_CREDENTIALS")

    host = parts.hostname
    if not host:
        raise MCPEgressBlocked("URL sans host", code="MCP_EGRESS_NO_HOST")

    host_lc = host.lower()
    if not allow_private:
        if host_lc in _BLOCKED_HOSTNAMES or host_lc.endswith(_BLOCKED_SUFFIXES):
            raise MCPEgressBlocked(f"host interne bloqué : {host}",
                                   code="MCP_EGRESS_PRIVATE")

    port = parts.port or (443 if scheme == "https" else 80)

    # Host est-il un littéral IP (forme encodée comprise) ?
    literal_ip = _try_parse_host_as_ip(host)
    if literal_ip is not None:
        candidates = [literal_ip]
    else:
        try:
            candidates = resolver(host)
        except OSError as exc:
            raise MCPEgressBlocked(f"résolution DNS échouée pour {host}",
                                   code="MCP_EGRESS_DNS") from exc
        if not candidates:
            raise MCPEgressBlocked(f"aucune IP pour {host}",
                                   code="MCP_EGRESS_DNS")

    if not allow_private:
        for ip in candidates:
            if is_blocked_ip(ip):
                raise MCPEgressBlocked(
                    f"cible interne bloquée : {host} → {ip}",
                    code="MCP_EGRESS_PRIVATE",
                )

    return EgressTarget(scheme=scheme, host=host, port=port, validated_ips=candidates)


def assert_egress_allowed(
    url: str,
    *,
    allow_private: bool = False,
    require_https: bool = True,
    resolver: Resolver | None = None,
) -> None:
    """Variante sans valeur de retour — lève si la cible est interdite."""
    validate_egress_url(
        url, allow_private=allow_private,
        require_https=require_https, resolver=resolver,
    )


# ── Transport HTTP durci (pinning anti-rebinding) ───────────────────────────


def _host_header(host: str, port: int, scheme: str) -> str:
    default = 443 if scheme == "https" else 80
    bracket = f"[{host}]" if ":" in host else host
    return bracket if port == default else f"{bracket}:{port}"


def build_guarded_http_factory(
    *,
    allow_private: bool = False,
    require_https: bool = True,
    resolver: Resolver | None = None,
):
    """Renvoie un ``McpHttpClientFactory`` (compatible SDK MCP) dont chaque
    requête — connexion initiale ET redirections — passe par la garde SSRF
    et se connecte à l'IP *validée et épinglée*.

    Importe ``httpx`` paresseusement pour ne pas alourdir les imports des
    modules qui n'ouvrent jamais de connexion distante."""
    import httpx

    class _SsrfGuardTransport(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request: "httpx.Request") -> "httpx.Response":
            url = str(request.url)
            target = validate_egress_url(
                url,
                allow_private=allow_private,
                require_https=require_https,
                resolver=resolver,
            )
            pinned = target.validated_ips[0]
            # Connexion vers l'IP validée ; Host + SNI/cert conservent le nom
            # d'origine (httpcore lit l'extension `sni_hostname`). Aucune
            # fenêtre TOCTOU : on valide et on épingle dans le même geste.
            request.url = request.url.copy_with(host=pinned)
            request.headers["Host"] = _host_header(target.host, target.port, target.scheme)
            if target.scheme == "https":
                request.extensions = {**request.extensions, "sni_hostname": target.host}
            return await super().handle_async_request(request)

    def _factory(headers=None, timeout=None, auth=None):
        import httpx as _httpx
        if timeout is None:
            timeout = _httpx.Timeout(30.0, read=300.0)
        return _httpx.AsyncClient(
            transport=_SsrfGuardTransport(),
            follow_redirects=True,
            timeout=timeout,
            headers=headers,
            auth=auth,
        )

    return _factory
