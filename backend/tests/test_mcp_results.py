# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_results.py
# @brief      J3 — normalisation des résultats MCP (bornée, sûre, sans _meta).
# @license    MIT
# =============================================================================
from __future__ import annotations

import base64
import os

from app.services.mcp_results import normalize_call_result


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Result:
    def __init__(self, content=None, structuredContent=None, isError=False, meta=None):
        self.content = content or []
        self.structuredContent = structuredContent
        self.isError = isError
        self.meta = meta


def test_text_block():
    out = normalize_call_result(_Result(content=[_Block(type="text", text="bonjour")]))
    assert out == "bonjour"


def test_structured_content_serialized():
    out = normalize_call_result(_Result(structuredContent={"temp": 21, "unit": "C"}))
    assert "structuredContent" in out
    assert '"temp"' in out and "21" in out


def test_meta_never_leaks_to_model():
    out = normalize_call_result(_Result(
        content=[_Block(type="text", text="ok")],
        meta={"secret_internal": "SHOULD_NOT_APPEAR"},
    ))
    assert "SHOULD_NOT_APPEAR" not in out
    assert "secret_internal" not in out


def test_is_error_is_flagged():
    out = normalize_call_result(
        _Result(content=[_Block(type="text", text="boom")], isError=True),
        local_name="mcp__x__do",
    )
    assert out.startswith("⚠️")
    assert "mcp__x__do" in out


def test_image_block_saved_off_context():
    data = base64.b64encode(b"\x89PNGfakeimage").decode()
    out = normalize_call_result(_Result(content=[
        _Block(type="image", data=data, mimeType="image/png"),
    ]))
    assert "image MCP enregistrée" in out
    assert "image/png" in out
    # Le chemin est dans /tmp/ely-attachments et le fichier existe.
    path = out.split("enregistrée :")[1].split("|")[0].strip()
    assert path.startswith("/tmp/ely-attachments/")
    assert os.path.exists(path)
    os.remove(path)


def test_resource_link_block():
    out = normalize_call_result(_Result(content=[
        _Block(type="resource_link", uri="https://ex/doc", name="Doc"),
    ]))
    assert "lien ressource MCP" in out
    assert "https://ex/doc" in out


def test_embedded_resource_text_marked_untrusted():
    res = _Block(uri="file://x", mimeType="text/plain", text="payload")
    out = normalize_call_result(_Result(content=[_Block(type="resource", resource=res)]))
    assert "non vérifié" in out
    assert "payload" in out


def test_size_cap_truncates():
    big = "a" * (300 * 1024)
    out = normalize_call_result(
        _Result(content=[_Block(type="text", text=big)]),
        max_text_bytes=256 * 1024,
    )
    assert "tronqué" in out
    assert len(out.encode("utf-8")) <= 256 * 1024 + 100


def test_empty_result():
    assert normalize_call_result(_Result()) == "(résultat MCP vide)"


def test_unknown_block_type_is_reported_not_crashed():
    out = normalize_call_result(_Result(content=[_Block(type="quantum")]))
    assert "non rendu" in out
