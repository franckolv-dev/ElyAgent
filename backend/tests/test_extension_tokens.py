# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_extension_tokens.py
# @brief      Pure-function coverage for the extension-token helpers.
#
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Sanity tests for the Sprint 0.5 extension-token helpers.

We keep these tests dependency-free (no DB, no FastAPI client) so they
run in <100ms and survive any future refactor of the persistence layer.
End-to-end tests of the REST + WS handshake live with the integration
suite that boots a real backend.
"""
from __future__ import annotations

from app.routers.extension_tokens import (
    TOKEN_PREFIX,
    TOKEN_ENTROPY_BYTES,
    _generate_plaintext,
    hash_token,
)


def test_token_format() -> None:
    """Generated tokens carry the public prefix and the right entropy width."""
    tok = _generate_plaintext()
    assert tok.startswith(TOKEN_PREFIX)
    body = tok[len(TOKEN_PREFIX):]
    # token_hex(N) → 2N hex chars.
    assert len(body) == TOKEN_ENTROPY_BYTES * 2
    assert all(c in "0123456789abcdef" for c in body)


def test_tokens_are_unique() -> None:
    """Two consecutive calls return different tokens (entropy sanity)."""
    samples = {_generate_plaintext() for _ in range(20)}
    assert len(samples) == 20


def test_hash_token_is_deterministic_and_hex() -> None:
    """SHA-256 returns the same 64-char hex digest for the same input."""
    tok = "ely_ext_" + "a" * 48
    digest_a = hash_token(tok)
    digest_b = hash_token(tok)
    assert digest_a == digest_b
    assert len(digest_a) == 64
    assert all(c in "0123456789abcdef" for c in digest_a)


def test_hash_token_differs_across_tokens() -> None:
    """Distinct tokens produce distinct digests (collision sanity check)."""
    a = hash_token("ely_ext_" + "a" * 48)
    b = hash_token("ely_ext_" + "b" * 48)
    assert a != b
