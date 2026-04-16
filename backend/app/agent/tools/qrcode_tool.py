# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/qrcode_tool.py
# @brief      QR Code tools — generate and decode QR codes
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""QR Code tools — generate and decode QR codes.

Dependencies:
- qrcode[pil] — generation
- pillow — image rendering
- pyzbar (optional) — decoding from image bytes
"""
from __future__ import annotations

import base64
import io
import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
async def qrcode_generate(
    content: str,
    size: int = 10,
    border: int = 4,
) -> str:
    """Generate a QR code for any text, URL, contact or data.

    The QR code is displayed inline in the chat as an image.

    Args:
        content: Text, URL or data to encode (e.g. 'https://example.com', 'Hello!', 'wifi:...')
        size: Box size in pixels (5-20, default 10)
        border: Quiet zone border in boxes (1-10, default 4)
    """
    try:
        import qrcode  # type: ignore
        from qrcode.image.pil import PilImage  # type: ignore
    except ImportError:
        return (
            "Le module qrcode[pil] n'est pas installé. "
            "Ajoute 'qrcode[pil]' dans pyproject.toml."
        )

    size = max(5, min(int(size), 20))
    border = max(1, min(int(border), 10))

    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=size,
            border=border,
        )
        qr.add_data(content)
        qr.make(fit=True)

        img: PilImage = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        # Short preview of content
        preview = content if len(content) <= 60 else content[:57] + "…"

        return json.dumps({
            "type": "image",
            "data": b64,
            "mime": "image/png",
            "prompt": f"QR Code : {preview}",
        })

    except Exception as exc:
        return f"Erreur lors de la génération du QR code : {exc}"


@tool
async def qrcode_generate_wifi(
    ssid: str,
    password: str,
    security: str = "WPA",
    hidden: bool = False,
) -> str:
    """Generate a QR code to connect to a Wi-Fi network.

    Scanning it with a phone will offer to join the network automatically.

    Args:
        ssid: Wi-Fi network name
        password: Wi-Fi password
        security: Security type — 'WPA' (default), 'WEP', or '' for open networks
        hidden: Whether the network is hidden (default False)
    """
    hidden_str = "true" if hidden else "false"
    wifi_string = f"WIFI:T:{security};S:{ssid};P:{password};H:{hidden_str};;"

    try:
        import qrcode  # type: ignore
    except ImportError:
        return "Le module qrcode[pil] n'est pas installé."

    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(wifi_string)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return json.dumps({
            "type": "image",
            "data": b64,
            "mime": "image/png",
            "prompt": f"QR Code Wi-Fi — Réseau : {ssid}",
        })

    except Exception as exc:
        return f"Erreur lors de la génération du QR code Wi-Fi : {exc}"


@tool
async def qrcode_generate_vcard(
    name: str,
    phone: str = "",
    email: str = "",
    company: str = "",
    url: str = "",
) -> str:
    """Generate a QR code vCard for a contact (scan to add to contacts).

    Args:
        name: Full name
        phone: Phone number
        email: Email address
        company: Company or organisation
        url: Website URL
    """
    vcard_lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{name}",
        f"N:{name};;;;"
    ]
    if phone:
        vcard_lines.append(f"TEL:{phone}")
    if email:
        vcard_lines.append(f"EMAIL:{email}")
    if company:
        vcard_lines.append(f"ORG:{company}")
    if url:
        vcard_lines.append(f"URL:{url}")
    vcard_lines.append("END:VCARD")
    vcard_str = "\n".join(vcard_lines)

    try:
        import qrcode  # type: ignore
    except ImportError:
        return "Le module qrcode[pil] n'est pas installé."

    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(vcard_str)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return json.dumps({
            "type": "image",
            "data": b64,
            "mime": "image/png",
            "prompt": f"QR Code vCard — {name}",
        })

    except Exception as exc:
        return f"Erreur lors de la génération du QR code vCard : {exc}"
