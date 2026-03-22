"""Google OAuth2 helpers — handles the authorization flow and token refresh."""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_flow():
    """Build an OAuth2 flow from settings."""
    from google_auth_oauthlib.flow import Flow
    s = get_settings()
    if not s.google_client_id or not s.google_client_secret:
        raise ValueError("Google OAuth2 credentials not configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)")

    client_config = {
        "web": {
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [s.google_redirect_uri],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = s.google_redirect_uri
    return flow


def build_auth_url(state: str) -> str:
    """Generate the Google authorization URL."""
    flow = get_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return auth_url


def exchange_code(code: str) -> dict:
    """Exchange authorization code for tokens."""
    flow = get_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }


def build_credentials(creds_dict: dict):
    """Rebuild a Credentials object from stored dict."""
    from google.oauth2.credentials import Credentials
    return Credentials(
        token=creds_dict.get("token"),
        refresh_token=creds_dict.get("refresh_token"),
        token_uri=creds_dict.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=creds_dict.get("client_id"),
        client_secret=creds_dict.get("client_secret"),
        scopes=creds_dict.get("scopes"),
    )


def get_user_credentials(google_credentials_json: str | None):
    """Get refreshed credentials from stored JSON, or None if not connected."""
    if not google_credentials_json:
        return None
    try:
        creds_dict = json.loads(google_credentials_json)
        creds = build_credentials(creds_dict)
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        return creds
    except Exception as exc:
        logger.warning("Failed to load Google credentials: %s", exc)
        return None
