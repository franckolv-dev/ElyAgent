"""Tests for media_router — extracts attachments from LLM responses."""
import os
import tempfile

import pytest

from app.services.media_router import extract_media


@pytest.fixture
def tmp_attach(monkeypatch):
    """Create a temp file under a whitelisted-style path for testing."""
    # Patch the whitelist to include /tmp directly so we can use real files.
    import app.services.media_router as mr
    real_attach_dir = "/tmp/ely-attachments"
    os.makedirs(real_attach_dir, mode=0o700, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="screenshot-", suffix=".png", dir=real_attach_dir, delete=False
    ) as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"x" * 100)  # minimal PNG header
        path = f.name
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


def test_extract_media_sentinel(tmp_attach):
    text = (
        "Voici la capture du site.\n"
        f"MEDIA:{tmp_attach}\n"
        "Tu peux la consulter ci-dessus."
    )
    result = extract_media(text)
    assert len(result.attachments) == 1
    assert result.attachments[0]["path"] == tmp_attach
    assert result.attachments[0]["mime_type"] == "image/png"
    assert "MEDIA:" not in result.cleaned_text
    assert "Voici la capture" in result.cleaned_text
    assert "ci-dessus" in result.cleaned_text


def test_extract_media_bare_path(tmp_attach):
    text = f"Le fichier est sauvegardé dans {tmp_attach} si tu veux."
    result = extract_media(text)
    assert len(result.attachments) == 1
    # Bare path is preserved in text
    assert tmp_attach in result.cleaned_text


def test_extract_media_dedup(tmp_attach):
    text = f"MEDIA:{tmp_attach}\nLe fichier {tmp_attach} contient la capture."
    result = extract_media(text)
    assert len(result.attachments) == 1  # de-duped


def test_extract_media_rejects_unauthorized_path():
    """Path with extension but outside whitelist → no attachment, sentinel stripped."""
    text = "MEDIA:/etc/shadow.conf"
    result = extract_media(text)
    assert result.attachments == []
    # Sentinel still stripped from prose (defense in depth)
    assert "MEDIA:/etc/shadow.conf" not in result.cleaned_text


def test_extract_media_ignores_extensionless_path():
    """Without an extension, the sentinel regex doesn't match — no leak risk."""
    text = "MEDIA:/etc/passwd"
    result = extract_media(text)
    assert result.attachments == []
    # Regex doesn't match (no extension) so prose is unchanged — that's fine,
    # the path can't be extracted as an attachment anyway.


def test_extract_media_rejects_path_traversal():
    text = "MEDIA:/tmp/ely-attachments/../etc/passwd"
    result = extract_media(text)
    assert result.attachments == []


def test_extract_media_rejects_nonexistent():
    text = "MEDIA:/tmp/ely-attachments/does-not-exist.png"
    result = extract_media(text)
    assert result.attachments == []


def test_extract_media_no_match():
    text = "Bonjour Franck, voici ma réponse sans aucun fichier."
    result = extract_media(text)
    assert result.attachments == []
    assert result.cleaned_text == text


def test_extract_media_empty():
    assert extract_media("").attachments == []
    assert extract_media(None).attachments == []  # type: ignore[arg-type]


def test_extract_media_multiple_files(tmp_attach):
    """Multiple distinct sentinels return multiple attachments."""
    # Create a second file
    real_dir = "/tmp/ely-attachments"
    second_path = f"{real_dir}/second-{os.path.basename(tmp_attach)}"
    with open(second_path, "wb") as f:
        f.write(b"second content")
    try:
        text = f"MEDIA:{tmp_attach}\n\nMEDIA:{second_path}\nVoilà tes 2 fichiers."
        result = extract_media(text)
        assert len(result.attachments) == 2
        paths = {a["path"] for a in result.attachments}
        assert tmp_attach in paths
        assert second_path in paths
    finally:
        os.unlink(second_path)


def test_extract_media_quoted_sentinel(tmp_attach):
    """Sentinel with quotes around the path also works."""
    text = f'Capture sauvegardée. MEDIA:"{tmp_attach}" — voici le résultat.'
    result = extract_media(text)
    assert len(result.attachments) == 1


def test_signed_url_roundtrip(tmp_attach):
    """A freshly-signed URL verifies; tampering breaks the signature."""
    from app.services.media_router import sign_path, verify_signature

    sig, exp = sign_path(tmp_attach)
    assert verify_signature(tmp_attach, exp, sig) is True
    # Wrong path
    assert verify_signature("/tmp/ely-attachments/other.png", exp, sig) is False
    # Wrong sig
    assert verify_signature(tmp_attach, exp, "deadbeef") is False
    # Expired
    assert verify_signature(tmp_attach, exp - 999_999, sig) is False
    # Garbage exp
    assert verify_signature(tmp_attach, "not-a-number", sig) is False  # type: ignore[arg-type]


def test_attachment_includes_signature(tmp_attach):
    """Extracted attachments carry exp + sig fields ready for the URL."""
    text = f"MEDIA:{tmp_attach}"
    result = extract_media(text)
    assert len(result.attachments) == 1
    att = result.attachments[0]
    assert "exp" in att and isinstance(att["exp"], int)
    assert "sig" in att and len(att["sig"]) == 64  # SHA256 hex length
