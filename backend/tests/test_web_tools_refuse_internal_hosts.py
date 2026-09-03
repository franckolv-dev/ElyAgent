# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_web_tools_refuse_internal_hosts.py
# @brief      Les outils web refusent les hôtes internes : boucle locale,
#             réseau privé, métadonnées cloud. Le garde existait, il n'était
#             branché que sur MCP.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""SSRF par les outils web (audit du 02/09/2026).

`web_screenshot`, `web_to_pdf`, `web_extract` et `web_compare` pilotent un
Chromium vers l'URL que le modèle leur donne. `_valider_url` ne vérifiait que
le schéma : `http://169.254.169.254/` (métadonnées cloud), `http://qdrant:6333`
(la base vectorielle du réseau Docker) ou `http://127.0.0.1:8000` (le backend
lui-même) passaient. Un modèle convaincu par le contenu d'une page pouvait
lire ce que le réseau interne expose.

Le garde complet existe depuis le client MCP (`services/mcp_egress.py`) :
boucle locale, lien local, adresses privées, CGNAT, formes obfusquées. Il est
désormais appelé par les outils web, en acceptant http (le web n'est pas un
serveur MCP) et sans dépendre du DNS dans les tests.
"""
from __future__ import annotations

import pytest

import app.agent.tools.web_tool as wt


def _resolveur(table: dict[str, list[str]]):
    def _r(host: str) -> list[str]:
        if host not in table:
            raise OSError(f"résolution simulée : {host} inconnu")
        return table[host]
    return _r


@pytest.fixture
def dns(monkeypatch):
    """Un DNS simulé : les tests ne touchent pas le réseau."""
    import app.services.mcp_egress as eg
    monkeypatch.setattr(eg, "_default_resolver", _resolveur({
        "www.example.com": ["93.184.216.34"],
        "qdrant": ["172.18.0.5"],
        "intranet.local": ["10.0.0.12"],
    }))


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1:8000/api/admin/metrics",
    "http://localhost:6333/collections",
    "http://qdrant:6333/collections",
    "http://intranet.local/",
    "http://0x7f000001/",
    "http://10.0.0.1/",
])
def test_un_hote_interne_est_refuse(dns, url) -> None:
    refus = wt._valider_url(url)
    assert refus, f"{url} devrait être refusée"
    assert "refusée" in refus.lower() or "interne" in refus.lower()


def test_une_url_publique_passe_toujours(dns) -> None:
    assert wt._valider_url("https://www.example.com/page") is None
    assert wt._valider_url("http://www.example.com/page") is None, "http reste accepté : le web n'est pas un serveur MCP"


def test_le_refus_reste_explicite_sur_le_schema(dns) -> None:
    """Le message historique sur file:// et javascript: ne change pas."""
    refus = wt._valider_url("file:///etc/passwd")
    assert refus and "http://" in refus
