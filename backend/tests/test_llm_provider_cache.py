"""Regression tests for the tier-config versioning that drives LLM cache
invalidation downstream.

Bug context (audit C-4, fixed 2026-05-06):
    `_tier_llm_cache` in `app/agent/nodes.py` was only invalidated on
    tool-registry version changes — never on tier routing config changes.
    Consequence: switching a model in Settings → Routing had no runtime
    effect, the previous client (e.g. Devstral) stayed in cache.

Fix:
    `set_tier_config()` now bumps `_tier_config_version`, exposed via
    `get_tier_config_version()`. `agent_node` checks both versions.
"""
from app.services import llm_provider as lp


def test_set_tier_config_bumps_version():
    """Each set_tier_config() call must bump the version monotonically."""
    initial = lp.get_tier_config_version()

    lp.set_tier_config({"medium": {"providers": ["ollama"], "fallback_enabled": True}})
    v1 = lp.get_tier_config_version()
    assert v1 > initial, f"version should increase, was {initial} now {v1}"

    lp.set_tier_config({"medium": {"providers": ["anthropic"], "fallback_enabled": True}})
    v2 = lp.get_tier_config_version()
    assert v2 > v1, f"version should increase again, was {v1} now {v2}"


def test_set_tier_config_replaces_in_memory_state():
    """set_tier_config() must actually replace _tier_config dict (not append)."""
    lp.set_tier_config({"simple": {"providers": ["ollama"]}})
    assert "simple" in lp.get_tier_config()
    assert "medium" not in lp.get_tier_config()

    lp.set_tier_config({"medium": {"providers": ["anthropic"]}})
    cfg = lp.get_tier_config()
    assert "medium" in cfg
    assert "simple" not in cfg, "set_tier_config must replace, not merge"


def test_get_tier_config_version_is_monotonic():
    """Version must never go backwards."""
    versions = []
    for i in range(5):
        lp.set_tier_config({"medium": {"providers": [f"prov_{i}"]}})
        versions.append(lp.get_tier_config_version())
    assert versions == sorted(versions), f"versions not monotonic: {versions}"
    assert len(set(versions)) == len(versions), f"duplicate versions: {versions}"
