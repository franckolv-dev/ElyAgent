# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_outbound.py
# @brief      J4 — politique de données sortantes (secrets bloqués, PII tracée).
# @license    MIT
# =============================================================================
from __future__ import annotations

import pytest

from app.services.mcp_outbound import enforce_outbound, scan_outbound


@pytest.mark.parametrize("value", [
    "sk-abcdefghijklmnopqrstuvwx0123",        # OpenAI key
    "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",   # GitHub token
    "AKIAIOSFODNN7EXAMPLE",                    # AWS key
    "vault://my_secret",                       # référence Vault résiduelle
    "xoxb-123456789-abcdefghijklmnop",         # Slack token
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fw",  # JWT
    "-----BEGIN RSA PRIVATE KEY-----",         # clé privée
])
def test_secrets_are_blocked(value):
    verdict = enforce_outbound({"field": value})
    assert verdict.allowed is False
    assert verdict.reason and "bloqué" in verdict.reason.lower()


def test_clean_args_pass():
    verdict = enforce_outbound({"query": "météo à Paris", "limit": 5})
    assert verdict.allowed is True
    assert verdict.findings == []


def test_pii_is_flagged_not_blocked():
    verdict = enforce_outbound({"to": "jean.dupont@example.com"})
    assert verdict.allowed is True            # PII autorisée…
    assert any(f.severity == "pii" for f in verdict.findings)  # …mais tracée


def test_nested_args_are_scanned():
    verdict = enforce_outbound({"outer": {"inner": ["x", "ghp_ABCDEFGHIJKLMNOP012345"]}})
    assert verdict.allowed is False


def test_vault_ref_is_a_secret():
    findings = scan_outbound({"token": "vault://github"})
    assert any(f.kind == "VAULT_REF" and f.severity == "secret" for f in findings)
