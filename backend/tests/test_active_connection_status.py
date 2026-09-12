"""The chat rail reports live sessions for the signed-in user only."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.routers import channels
from app.services import browser_extension_registry, desktop_registry


def test_live_connections_are_scoped_to_the_user_and_clear_on_disconnect(monkeypatch):
    monkeypatch.setattr(channels, "_resolve_channel_token", AsyncMock(return_value=""))
    monkeypatch.setattr(channels, "_is_running", AsyncMock(return_value=False))
    chrome = {"alice": object()}
    desktop = {"bob": object()}
    monkeypatch.setattr(browser_extension_registry, "_connections", chrome)
    monkeypatch.setattr(desktop_registry, "_connections", desktop)

    async def check():
        alice = await channels.active_channels(SimpleNamespace(id="alice"))
        bob = await channels.active_channels(SimpleNamespace(id="bob"))
        assert alice["chrome"] == {"connected": True}
        assert alice["system"] == {"connected": False}
        assert bob["chrome"] == {"connected": False}
        assert bob["system"] == {"connected": True}
        chrome.clear()
        desktop.clear()
        assert (await channels.active_channels(SimpleNamespace(id="alice")))["chrome"] == {"connected": False}
        assert (await channels.active_channels(SimpleNamespace(id="bob")))["system"] == {"connected": False}

    asyncio.run(check())
