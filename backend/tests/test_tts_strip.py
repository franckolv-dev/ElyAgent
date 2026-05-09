# =============================================================================
# @project    Ely — Exactly Like You
# @file       backend/tests/test_tts_strip.py
# @brief      Tests for the TTS text sanitizer
# =============================================================================
"""Tests for ``_strip_markdown``.

User feedback (mai 2026): Éli was reading aloud raw URLs character-by-
character (« H, T, T, P, S, deux-points, slash, slash, … »), JSON blocks
verbatim (« inférieur, slash, parameter, supérieur, … »), and long Drive
file IDs as a string of letters and digits. These tests lock the
sanitization behaviour against regression.
"""
from __future__ import annotations

from app.routers.tts import _strip_markdown


# ── URLs ─────────────────────────────────────────────────────────────────────


def test_https_url_replaced_by_placeholder():
    out = _strip_markdown("Voici la source : https://example.com/api/v1/users.")
    assert "https" not in out
    assert "example.com" not in out
    assert "[lien]" in out


def test_http_and_ftp_urls_replaced():
    out = _strip_markdown("ftp://server/file or http://x.y/z")
    assert "ftp" not in out
    assert "http" not in out
    assert out.count("[lien]") == 2


def test_www_url_without_scheme_replaced():
    out = _strip_markdown("Va sur www.lemonde.fr aujourd'hui.")
    assert "www" not in out
    assert "lemonde" not in out
    assert "[lien]" in out


def test_mailto_replaced():
    out = _strip_markdown("Écris à mailto:franck@example.org svp.")
    assert "mailto" not in out
    assert "[lien]" in out


def test_url_in_parentheses_does_not_eat_close_paren():
    """Make sure the URL regex stops at `)` — otherwise « (https://x.y/z) »
    swallows the closing paren and produces unbalanced output."""
    out = _strip_markdown("Voir le site (https://example.com) pour plus d'infos.")
    assert "(" in out and ")" in out
    assert "[lien]" in out


# ── JSON blocks ──────────────────────────────────────────────────────────────


def test_multiline_json_block_removed():
    text = """Voici la requête :
{
  "name": "test",
  "value": 42,
  "nested": {"key": "v"}
}
Continue après."""
    out = _strip_markdown(text)
    assert '"name"' not in out
    assert '"value"' not in out
    assert "Voici la requête" in out
    assert "Continue après" in out


def test_inline_short_object_kept_as_is():
    """{x: 1} on a single line is rare and harmless — don't aggressively
    strip it. The regex requires 3+ lines."""
    out = _strip_markdown("Le résultat est {x: 1, y: 2}, c'est tout.")
    assert "résultat" in out


# ── XML / function-call tags ─────────────────────────────────────────────────


def test_function_call_tags_removed():
    """Mistral-style function-call tokens that occasionally leak into
    plain text content shouldn't be read aloud."""
    text = (
        "Je vais appeler <function=gmail_list_emails>"
        "<parameter=category>spam</parameter></function>"
    )
    out = _strip_markdown(text)
    assert "<" not in out
    assert ">" not in out
    assert "function" not in out.lower() or "Je vais appeler" in out


def test_html_tags_removed():
    out = _strip_markdown("Ceci est <strong>important</strong> à retenir.")
    assert "<" not in out
    assert ">" not in out
    assert "important" in out


# ── Long IDs ─────────────────────────────────────────────────────────────────


def test_drive_file_id_replaced():
    """Google Drive IDs are 25-44 char alphanumerics — totally unspeakable."""
    out = _strip_markdown(
        "Le fichier 14cIm_gIGYsfG99Rj8ieMkRHEXqGBOlcl est dans /perso."
    )
    assert "14cIm" not in out
    assert "[identifiant]" in out


def test_short_token_kept():
    """Don't replace short alphanumerics like « M3 » or « 2026 »."""
    out = _strip_markdown("J'ai un Mac Studio M3 acheté en 2026.")
    assert "M3" in out
    assert "2026" in out
    assert "[identifiant]" not in out


def test_pure_letters_or_digits_not_replaced():
    """The « long ID » rule requires both letters AND digits — pure words
    or pure numbers stay readable."""
    out = _strip_markdown("Caractéristiques: longueurdiameetre vraiment grand 123456789.")
    assert "[identifiant]" not in out


# ── Markdown tables ──────────────────────────────────────────────────────────


def test_table_removed():
    text = """Voici le résumé :
| Catégorie | Compte |
|-----------|--------|
| Spam      | 11     |
| Newsletters | 96   |

Total : 107 emails."""
    out = _strip_markdown(text)
    assert "Catégorie" not in out
    assert "|" not in out
    assert "Voici le résumé" in out
    assert "Total" in out


# ── Code blocks (legacy, must keep working) ──────────────────────────────────


def test_fenced_code_block_removed():
    text = """Lance ça :
```bash
docker restart cyberentity-backend
```
Et c'est bon."""
    out = _strip_markdown(text)
    assert "docker" not in out
    assert "Lance ça" in out
    assert "c'est bon" in out


# ── Combined real-world fixture ──────────────────────────────────────────────


def test_real_audit_response_cleanup():
    """Snapshot of a real ELY audit reply that triggered Franck's complaint."""
    text = """Voici l'audit :

| Catégorie | Emails |
|-----------|--------|
| Spam | 11 |

Le détail est sur https://mail.google.com/mail/u/0/#trash et le fichier
14cIm_gIGYsfG99Rj8ieMkRHEXqGBOlcl contient les IDs.

```json
{"name": "x", "v": 1, "y": [1, 2, 3]}
```

Tu veux que je supprime ?"""
    out = _strip_markdown(text)
    # Header sentence preserved
    assert "Voici l'audit" in out
    assert "Tu veux que je supprime" in out
    # Noise removed
    assert "https" not in out
    assert "14cIm" not in out
    assert "|" not in out
    assert '"name"' not in out
    assert "```" not in out
    # Placeholders inserted where helpful
    assert "[lien]" in out
    assert "[identifiant]" in out


def test_multiple_consecutive_placeholders_collapsed():
    out = _strip_markdown(
        "Trois liens : https://a.com https://b.org https://c.net fin."
    )
    # Should collapse « [lien] [lien] [lien] » → « [lien] »
    assert out.count("[lien]") == 1


# ── Empty / edge ─────────────────────────────────────────────────────────────


def test_empty_text():
    assert _strip_markdown("") == ""


def test_whitespace_only():
    assert _strip_markdown("   \n\n   ") == ""


def test_plain_french_unchanged():
    """Plain French sentences must stay untouched."""
    text = "Bonjour Franck, je suis Ely. Comment puis-je t'aider aujourd'hui ?"
    out = _strip_markdown(text)
    assert out == text
