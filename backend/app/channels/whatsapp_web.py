# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/channels/whatsapp_web.py
# @brief      WhatsApp Web bridge via neonize (QR-code pairing, no Meta API)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""WhatsApp Web channel adapter via neonize (whatsmeow port).

Unlike the Meta Cloud API adapter (`whatsapp.py`), this one :
  - Pairs with the user's PERSONAL WhatsApp account via QR code
  - Uses the same protocol as WhatsApp Web / Desktop (multi-device)
  - Does NOT require a Meta Business App, no phone number ID, no token
  - Works offline to Meta (only needs WhatsApp servers)

Trade-offs :
  - Unofficial — against WhatsApp ToS (use at your own risk, ban possible)
  - Requires persistent session storage (device-level keys)
  - Each user = one session = one WhatsApp account

Architecture :
  - 1 neonize `NewClient` per ELY user_id
  - Session persistence in `data/whatsapp_web_sessions/{user_id}.sqlite`
  - Incoming messages → dispatched to the same ELY agent pipeline that
    powers /ws/chat, reusing `process_whatsapp_message` for DRY
  - Outgoing messages → sent via the user's own client

Session lifecycle :
  - `start_session(user_id)` → spawns client, returns QR as base64 PNG
  - User scans QR with WhatsApp → paired, status flips to "linked"
  - Subsequent starts reuse the SQLite session (no re-scan)
  - `logout(user_id)` → wipes keys + disconnects
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Session storage root (persistent — keys must survive restarts).
# Kept outside the Python package so `docker cp` hot-reload doesn't wipe it.
_SESSION_DIR = Path("/app/data/whatsapp_web_sessions")


# In-memory registry of active clients, keyed by ELY user_id.
# Values: dict with keys:
#   - "client"      : neonize.NewClient instance
#   - "status"      : "pending_qr" | "linked" | "disconnected" | "error"
#   - "qr_png_b64"  : last QR code as base64 PNG (only while pending_qr)
#   - "phone"       : linked phone number once paired (E.164)
#   - "task"        : asyncio.Task for the connection loop
#   - "last_error"  : str (when status == "error")
_sessions: dict[str, dict[str, Any]] = {}

# IDs of messages WE (ELY) just sent through a neonize session. Used to skip
# them in `_on_message` — otherwise every outgoing reply would echo back in
# the inbound handler (multi-device sync) and the agent would loop forever.
# Bounded at 1000 entries to keep memory flat.
_ely_sent_msg_ids: set[str] = set()
_MAX_SENT_IDS = 1000


def _session_path(user_id: str) -> Path:
    """Return the SQLite path that persists this user's WhatsApp keys."""
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    # Sanitize user_id (UUID format, no risk of path traversal in normal use,
    # but defensive anyway).
    safe = "".join(c for c in user_id if c.isalnum() or c in ("-", "_"))
    return _SESSION_DIR / f"{safe}.sqlite"


def get_status(user_id: str) -> dict[str, Any]:
    """Return a UI-safe snapshot of a user's session state."""
    sess = _sessions.get(user_id)
    if not sess:
        return {"status": "not_started"}
    return {
        "status":     sess.get("status", "unknown"),
        "qr_png_b64": sess.get("qr_png_b64") if sess.get("status") == "pending_qr" else None,
        "phone":      sess.get("phone"),
        "last_error": sess.get("last_error"),
    }


async def start_session(user_id: str) -> dict[str, Any]:
    """Start (or resume) a WhatsApp Web session for *user_id*.

    If a session already exists and is linked, we just return its status.
    If the SQLite session file exists but the client isn't connected,
    we reconnect (no QR needed).
    Otherwise we boot a fresh client and the user will get a QR to scan.

    Returns the same payload as `get_status()`.
    """
    if user_id in _sessions and _sessions[user_id].get("status") == "linked":
        return get_status(user_id)

    try:
        # Lazy import so the backend can boot even if neonize isn't installed yet
        # (dev environments where the user hasn't run `uv sync` yet).
        from neonize.aioze.client import NewAClient
        from neonize.events import ConnectedEv, PairStatusEv, MessageEv
    except ImportError as exc:
        logger.error("neonize not available: %s", exc)
        return {"status": "error", "last_error": f"neonize missing: {exc}"}

    sess_path = _session_path(user_id)

    # Create the client — persists keys to sess_path (SQLite).
    client = NewAClient(str(sess_path))

    sess_entry: dict[str, Any] = {
        "client":     client,
        "status":     "connecting",
        "qr_png_b64": None,
        "phone":      None,
        "task":       None,
        "last_error": None,
    }
    _sessions[user_id] = sess_entry

    # ── Event handlers ──────────────────────────────────────────────────
    # neonize >= 0.3.17 exposes three handler categories :
    #   - client.event.qr(fn)        : QR bytes pushed when fresh scan needed
    #   - client.event.paircode(fn)  : alternate phone-number pairing flow
    #   - client.event(SomeEv)(fn)   : classical per-event decorator (messages, pair status, etc.)
    # The QR callback receives raw bytes — we convert to a PNG via `qrcode`.

    async def _on_qr(_client, qr_bytes):
        """Fresh QR ready — render to base64 PNG for the UI.

        We render at a very generous resolution (box_size=20 → ~1300×1300 PNG
        for WhatsApp's version-9 QR) because iPhone cameras struggle to decode
        dense WhatsApp QRs when displayed too small. Combined with the UI's
        w-[420px] (420 px) container, scans succeed first-try even at arm's
        length or with moderate screen brightness. Higher error-correction
        (ERROR_CORRECT_H, ~30% recoverable) also helps on screens with
        glare or sub-pixel rendering blur.
        """
        import qrcode
        from io import BytesIO
        qr_text = qr_bytes.decode("utf-8", errors="replace") if isinstance(qr_bytes, (bytes, bytearray)) else str(qr_bytes)
        qr = qrcode.QRCode(
            version=None,  # auto-detect
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=20,   # bigger modules → bigger PNG → easier camera scan
            border=4,      # standard quiet zone for reliable scan
        )
        qr.add_data(qr_text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        sess_entry["qr_png_b64"] = base64.b64encode(buf.getvalue()).decode("ascii")
        sess_entry["status"] = "pending_qr"
        logger.info("WhatsApp Web: QR generated for user %s (version=%s)", user_id, qr.version)

    # Register the QR callback (override the default "print to stdout" handler).
    client.event.qr(_on_qr)

    @client.event(PairStatusEv)
    async def _on_pair(_client, ev):  # noqa: ARG001
        """Pairing finished (QR scanned) — extract linked phone, flip status."""
        # neonize exposes the JID as a protobuf message whose `str()` looks
        # like `User: "33617433543" Agent: 0 Device: 0 Server: "s.whatsapp.net"`.
        # We prefer `.User` directly (a plain str). Fallback to a regex to
        # handle every representation the protobuf emits.
        jid = getattr(ev, "ID", None) or getattr(ev, "id", None)
        phone = None
        if jid is not None:
            # Preferred path: protobuf attribute access
            user_attr = getattr(jid, "User", None)
            if user_attr:
                phone = str(user_attr)
            else:
                # Fallback: parse the string form
                import re
                s = str(jid)
                m = re.search(r'User:\s*"?(\d+)"?', s)
                if m:
                    phone = m.group(1)
                else:
                    # Last resort: strip everything up to first digit sequence
                    m2 = re.search(r"(\d{10,15})", s)
                    phone = m2.group(1) if m2 else None
        sess_entry["phone"] = phone
        sess_entry["qr_png_b64"] = None
        sess_entry["status"] = "linked"
        logger.info("WhatsApp Web: paired user %s with phone %s", user_id, phone)
        # Persist the link to the User row so inbound messages route correctly
        # (same table/column as the Meta Cloud channel).
        try:
            from app.database import async_session as _async_session
            from app.models.user import User
            from sqlalchemy import select
            async with _async_session() as db:
                r = await db.execute(select(User).where(User.id == user_id))
                u = r.scalar_one_or_none()
                if u and phone:
                    u.whatsapp_phone = phone
                    await db.commit()
                    # Also update the in-memory mapping used by whatsapp.py
                    from app.channels.whatsapp import _linked_users
                    _linked_users[phone] = user_id
        except Exception as exc:
            logger.warning("Failed to persist WhatsApp link for user %s: %s", user_id, exc)

    @client.event(ConnectedEv)
    async def _on_connected(_c, _ev):  # noqa: ARG001
        """Fires on every successful (re)connect.

        Critical side-effect : repopulate `sess_entry["phone"]` from the
        client's own JID. Without this, sessions restored from SQLite at
        startup would have phone=None (because PairStatusEv only fires on
        the INITIAL pairing, not on reconnect) — which then makes outbound
        replies fall back to the unconfigured Meta Cloud transport.

        Also ensures the DB-persisted `whatsapp_phone` and the global
        `_linked_users` map stay in sync with whatever neonize reports now.
        """
        if sess_entry["status"] != "linked":
            sess_entry["status"] = "linked"

        own_phone = None
        # Primary source: read the phone we already persisted in DB (set by
        # `_on_pair` at first pairing, possibly corrected manually). This is
        # reliable across restarts where `_on_pair` doesn't re-fire.
        try:
            from app.database import async_session as _async_session
            from app.models.user import User as _U
            from sqlalchemy import select as _select
            async with _async_session() as db:
                r = await db.execute(_select(_U).where(_U.id == user_id))
                u = r.scalar_one_or_none()
                if u and u.whatsapp_phone:
                    own_phone = u.whatsapp_phone
        except Exception as exc:
            logger.debug("DB phone lookup failed: %s", exc)

        # Fallback: try neonize's get_me() (some versions expose JID via a
        # different path — we tolerate any shape).
        if not own_phone:
            try:
                device = _c.get_me() if hasattr(_c, "get_me") else None
                if device is not None:
                    import re
                    m = re.search(r'User:\s*"?(\d+)"?', str(device))
                    if m:
                        own_phone = m.group(1)
            except Exception as exc:
                logger.debug("get_me() fallback extraction failed: %s", exc)

        if own_phone and not sess_entry.get("phone"):
            sess_entry["phone"] = own_phone
            # Keep DB + in-memory linked_users map aligned with the truth
            try:
                from app.database import async_session as _async_session
                from app.models.user import User
                from sqlalchemy import select
                async with _async_session() as db:
                    r = await db.execute(select(User).where(User.id == user_id))
                    u = r.scalar_one_or_none()
                    if u and u.whatsapp_phone != own_phone:
                        u.whatsapp_phone = own_phone
                        await db.commit()
                from app.channels.whatsapp import _linked_users
                _linked_users[own_phone] = user_id
            except Exception as exc:
                logger.warning("Failed to sync phone on reconnect for %s: %s", user_id, exc)

        logger.info("WhatsApp Web: connected for user %s (phone=%s)", user_id, sess_entry.get("phone"))

    @client.event(MessageEv)
    async def _on_message(_client, ev):
        """Inbound text message handler.

        Policy : ELY intervient UNIQUEMENT dans le "self-chat" de l'utilisateur
        (conversation avec soi-même sur WhatsApp). Les messages entrants
        provenant d'autres contacts ne sont PAS interceptés — l'utilisateur
        les lit et y répond lui-même depuis son iPhone, comme d'habitude.

        Cela évite que le fait d'avoir scanné le QR ELY transforme ton
        WhatsApp en répondeur IA pour tout le monde.

        Plus tard on pourra ajouter un mode "whitelist" (liste de contacts
        que l'user autorise à discuter avec ELY) ou un préfixe déclencheur.
        """
        try:
            # ── Anti-loop : skip our own sends ────────────────────────────
            msg_id = getattr(ev.Info, "ID", None) if hasattr(ev, "Info") else None
            if msg_id and msg_id in _ely_sent_msg_ids:
                return

            msg = ev.Message
            text = (
                getattr(msg, "conversation", None)
                or getattr(getattr(msg, "extendedTextMessage", None), "text", None)
                or ""
            )
            if not text:
                return  # media / sticker / etc — ignored

            # Determine if this is a self-chat message (user typing from their
            # phone to themselves). `IsFromMe=True` on MessageSource means the
            # message was sent by one of the user's own devices; the primary
            # iPhone in a multi-device setup triggers this when the user types
            # in the "Me" chat.
            info = ev.Info if hasattr(ev, "Info") else None
            source = info.MessageSource if info and hasattr(info, "MessageSource") else None
            is_from_me = bool(getattr(source, "IsFromMe", False))

            if not is_from_me:
                # Someone else is writing to the user → leave it alone.
                # Their WhatsApp inbox behaves normally, ELY doesn't respond.
                return

            # Self-message from the user. Route as if the user typed it in the
            # ELY web UI. The response will be sent back via neonize so it
            # appears in the same self-chat conversation.
            own_phone = sess_entry.get("phone") or ""
            from app.channels.whatsapp import process_whatsapp_message
            await process_whatsapp_message(own_phone, text)
        except Exception as exc:
            logger.exception("Error handling inbound WA Web message: %s", exc)

    # ── Spawn the connection loop in the background ─────────────────────
    async def _run():
        try:
            await client.connect()
        except Exception as exc:
            logger.exception("WhatsApp Web connect failed for user %s: %s", user_id, exc)
            sess_entry["status"] = "error"
            sess_entry["last_error"] = str(exc)

    sess_entry["task"] = asyncio.create_task(_run())

    # Give neonize a moment to emit the QR event before we return.
    for _ in range(20):
        await asyncio.sleep(0.25)
        if sess_entry["status"] in ("pending_qr", "linked", "error"):
            break

    return get_status(user_id)


async def request_pair_code(user_id: str, phone_number: str) -> dict[str, Any]:
    """Alternative pairing flow : user enters their phone number, WhatsApp
    generates an 8-character code that the user types in
    *WhatsApp → Appareils connectés → "Lier avec un numéro de téléphone"*.

    This bypasses the QR scan entirely — useful when WhatsApp's QR flow
    rejects the device (e.g. "Impossible de connecter l'appareil" error
    despite a correctly-formed QR).

    Requires an active (or startable) neonize session for the user. The
    session must stay connected until the user enters the code.

    Args:
        user_id: The ELY user who wants to link a WhatsApp account.
        phone_number: E.164 format without the + (e.g. "33612345678").

    Returns:
        {"code": "XXXX-XXXX"} on success, {"error": "..."} otherwise.
    """
    # Make sure a session is booted (same flow as start_session, but we skip
    # QR generation because we'll use phone-number pairing instead).
    if user_id not in _sessions or _sessions[user_id].get("status") not in ("connecting", "pending_qr", "linked"):
        # Need to start a session first so neonize.PairPhone has a live client.
        await start_session(user_id)

    sess = _sessions.get(user_id)
    if not sess:
        return {"error": "Could not start WhatsApp session"}
    if sess.get("status") == "linked":
        return {"error": "Already linked — logout first if you want to re-pair"}

    client = sess.get("client")
    if client is None:
        return {"error": "No client available"}

    # Normalise the phone number (strip +, spaces)
    phone = phone_number.lstrip("+").replace(" ", "").replace("-", "")
    if not phone.isdigit() or len(phone) < 10:
        return {"error": f"Invalid phone number: {phone_number}"}

    try:
        # `show_push_notification=True` → WhatsApp sends a popup on the phone
        # to prompt the user to enter the code.
        code = await asyncio.to_thread(client.PairPhone, phone, True)
        logger.info("WhatsApp Web: pairing code generated for user %s phone %s", user_id, phone)
        # Format for display: "ABCD-EFGH" (WhatsApp likes this format)
        code_str = str(code)
        formatted = f"{code_str[:4]}-{code_str[4:]}" if len(code_str) == 8 else code_str
        return {"code": formatted, "phone": phone}
    except Exception as exc:
        logger.exception("Pair code generation failed: %s", exc)
        return {"error": str(exc)}


async def logout(user_id: str) -> bool:
    """Log out + delete the session file. User will need to re-scan QR."""
    sess = _sessions.pop(user_id, None)
    if sess:
        client = sess.get("client")
        task = sess.get("task")
        try:
            if client is not None:
                await client.logout()  # type: ignore[attr-defined]
        except Exception:
            pass
        if task and not task.done():
            task.cancel()
    # Remove the SQLite session file
    try:
        _session_path(user_id).unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Could not delete WA Web session file for %s: %s", user_id, exc)
    return True


async def send_text(to_phone: str, text: str, from_user_id: Optional[str] = None) -> bool:
    """Send a text message via the user's WhatsApp Web session.

    If `from_user_id` is provided we use that user's session. Otherwise we
    pick the first linked session (single-admin-account scenario).

    Returns True on success.
    """
    # Resolve which session to use
    sess: Optional[dict[str, Any]] = None
    if from_user_id:
        sess = _sessions.get(from_user_id)
    else:
        # Pick the first linked session
        sess = next(
            (s for s in _sessions.values() if s.get("status") == "linked"),
            None,
        )
    if not sess or sess.get("status") != "linked":
        logger.warning("No linked WhatsApp Web session available")
        return False
    client = sess["client"]
    try:
        from neonize.utils.jid import build_jid
        jid = build_jid(to_phone)
        logger.debug("WhatsApp Web: sending to %s (len=%d)", to_phone, len(text))
        result = await client.send_message(jid, text)  # type: ignore[attr-defined]
        # Track the outgoing message ID so the inbound handler skips its echo
        # (multi-device sync delivers our own sends back as MessageEv).
        sent_id = getattr(result, "ID", None) if result is not None else None
        if sent_id:
            _ely_sent_msg_ids.add(str(sent_id))
            # Bound the set
            while len(_ely_sent_msg_ids) > _MAX_SENT_IDS:
                _ely_sent_msg_ids.pop()
        return True
    except Exception as exc:
        logger.warning("WhatsApp Web send to %s failed: %s", to_phone, exc)
        return False


async def load_existing_sessions() -> None:
    """On backend startup, auto-reconnect every user who had an active
    session last time (their SQLite file still exists)."""
    if not _SESSION_DIR.exists():
        return
    for fp in _SESSION_DIR.glob("*.sqlite"):
        user_id = fp.stem
        try:
            await start_session(user_id)
        except Exception as exc:
            logger.warning("Failed to resume WA Web session for %s: %s", user_id, exc)
    logger.info(
        "WhatsApp Web: %d session(s) restored at startup",
        sum(1 for s in _sessions.values() if s.get("status") == "linked"),
    )
