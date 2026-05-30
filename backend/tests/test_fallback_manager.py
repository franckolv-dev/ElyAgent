# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_fallback_manager.py
# @brief      Unit tests for fallback_manager (Hermes Chantier 4)
# =============================================================================
"""Unit tests for ``app.services.fallback_manager``.

The module under test is pure Python with module-level state — every test
calls ``_reset_for_tests()`` first to start from a clean slate.
"""
from __future__ import annotations

import pytest

from app.services.fallback_manager import (
    FailoverReason,
    classify_exception,
    discard,
    drain_events,
    get_or_create,
    get_state,
    record_response,
    reset_to_primary,
    should_retry_primary,
    state_count,
    try_activate,
    _reset_for_tests,
)


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset module state before AND after every test."""
    _reset_for_tests()
    yield
    _reset_for_tests()


# ──────────────────────────────────────────────────────────────────────────────
# classify_exception
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("msg, expected", [
    # Rate limit family
    ("HTTP 429 Too Many Requests",                FailoverReason.RATE_LIMIT),
    ("Error: rate limit reached",                  FailoverReason.RATE_LIMIT),
    ("RateLimitError(...)",                        FailoverReason.RATE_LIMIT),
    ("Too many requests",                          FailoverReason.RATE_LIMIT),
    # Billing
    ("402 Payment Required",                       FailoverReason.BILLING),
    ("Insufficient balance",                       FailoverReason.BILLING),
    ("Quota exceeded for project",                 FailoverReason.BILLING),
    # Auth
    ("HTTP 401 Unauthorized",                      FailoverReason.AUTH),
    ("403 Forbidden",                              FailoverReason.AUTH),
    ("Invalid API key provided",                   FailoverReason.AUTH),
    # Unavailable
    ("503 Service Unavailable",                    FailoverReason.UNAVAILABLE),
    ("Server overloaded, please retry later",      FailoverReason.UNAVAILABLE),
    ("Model deprecated, no longer available",      FailoverReason.UNAVAILABLE),
    ("404 Not Found",                              FailoverReason.UNAVAILABLE),
    # Timeout
    ("Read timeout after 90s",                     FailoverReason.TIMEOUT),
    ("Operation timed out",                        FailoverReason.TIMEOUT),
    # Bad request
    ("400 Bad Request — invalid_argument",         FailoverReason.BAD_REQUEST),
    # H1 synthetic
    ("h1_fallback: local LLM hallucinated",        FailoverReason.H1_HALLUCINATION),
    # Local-model failure modes (hotfix v1.11.1) — none contain "400" yet
    # must be recoverable so the chain falls back instead of crashing.
    ('Error rendering prompt with jinja template: got UndefinedValue',
                                                   FailoverReason.UNAVAILABLE),
    ("The number of tokens to keep from the initial prompt is greater "
     "than the context length",                    FailoverReason.UNAVAILABLE),
    ("exceeds the context window",                 FailoverReason.UNAVAILABLE),
    ("maximum context length is 4096",             FailoverReason.UNAVAILABLE),
    ("prompt template rendering failed",           FailoverReason.UNAVAILABLE),
])
def test_classify_exception_recognised(msg, expected):
    """All known operational failures map to the right reason."""
    assert classify_exception(Exception(msg)) is expected


@pytest.mark.parametrize("msg", [
    "",                                          # empty message
    "Some unexpected internal bug",              # unknown / true bug
    "KeyError: 'foo'",                           # programmer error
    "AttributeError: 'NoneType' object has no…",
])
def test_classify_exception_unrecognised(msg):
    """Generic / programmer errors return None — they should propagate."""
    assert classify_exception(Exception(msg)) is None


def test_classify_exception_handles_none_input():
    assert classify_exception(None) is None  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────────
# get_or_create — chain frozen at first use
# ──────────────────────────────────────────────────────────────────────────────


def test_get_or_create_creates_state_on_first_call():
    state = get_or_create("conv-1", "medium", ["qwen_api", "anthropic", "gemini"])
    assert state.tier == "medium"
    assert state.chain == ["qwen_api", "anthropic", "gemini"]
    assert state.current_index == 0
    assert state.current_provider == "qwen_api"
    assert state.is_active_fallback is False
    assert state.is_exhausted is False


def test_get_or_create_returns_same_state_on_subsequent_calls():
    """Subsequent calls return the SAME state object — chain is frozen."""
    s1 = get_or_create("conv-1", "medium", ["qwen_api", "anthropic"])
    s2 = get_or_create("conv-1", "medium", ["DIFFERENT", "PROVIDERS"])
    assert s1 is s2
    # Chain stays the original — different chain argument is ignored.
    assert s2.chain == ["qwen_api", "anthropic"]


def test_get_or_create_isolates_conversations():
    s1 = get_or_create("conv-1", "medium", ["a", "b"])
    s2 = get_or_create("conv-2", "complex", ["c", "d"])
    assert s1 is not s2
    assert state_count() == 2


def test_get_or_create_chain_is_copied_not_referenced():
    """Mutating the source list after creation must not affect state."""
    src = ["qwen_api", "anthropic"]
    state = get_or_create("conv-1", "medium", src)
    src.append("INJECTED")
    assert state.chain == ["qwen_api", "anthropic"]


# ──────────────────────────────────────────────────────────────────────────────
# try_activate
# ──────────────────────────────────────────────────────────────────────────────


def test_try_activate_advances_to_next_provider():
    get_or_create("conv-1", "medium", ["qwen_api", "anthropic", "gemini"])
    new = try_activate("conv-1", FailoverReason.RATE_LIMIT)
    assert new == "anthropic"
    state = get_state("conv-1")
    assert state.current_index == 1
    assert state.current_provider == "anthropic"
    assert state.is_active_fallback is True


def test_try_activate_records_history():
    get_or_create("conv-1", "medium", ["a", "b", "c"])
    try_activate("conv-1", FailoverReason.RATE_LIMIT)
    try_activate("conv-1", FailoverReason.TIMEOUT)
    state = get_state("conv-1")
    assert len(state.reason_history) == 2
    assert state.reason_history[0][0] is FailoverReason.RATE_LIMIT
    assert state.reason_history[0][1] == "a"
    assert state.reason_history[0][2] == "b"
    assert state.reason_history[1][0] is FailoverReason.TIMEOUT
    assert state.reason_history[1][1] == "b"
    assert state.reason_history[1][2] == "c"


def test_try_activate_returns_none_when_chain_exhausted():
    get_or_create("conv-1", "medium", ["a", "b"])
    assert try_activate("conv-1", FailoverReason.RATE_LIMIT) == "b"
    assert try_activate("conv-1", FailoverReason.RATE_LIMIT) is None
    state = get_state("conv-1")
    assert state.is_exhausted is True
    # Last entry in history records the failed attempt with empty target
    assert state.reason_history[-1][2] == ""


def test_try_activate_returns_none_when_no_state():
    """Calling without a prior get_or_create just returns None — no crash."""
    assert try_activate("ghost-conv", FailoverReason.RATE_LIMIT) is None


def test_try_activate_resets_empty_count():
    get_or_create("conv-1", "medium", ["a", "b", "c"])
    state = get_state("conv-1")
    state.empty_count = 2
    try_activate("conv-1", FailoverReason.TIMEOUT)
    assert state.empty_count == 0


def test_try_activate_emits_ws_event():
    get_or_create("conv-1", "medium", ["a", "b"])
    try_activate("conv-1", FailoverReason.RATE_LIMIT)
    events = drain_events("conv-1")
    assert len(events) == 1
    e = events[0]
    assert e["type"] == "provider.switched"
    assert e["from"] == "a"
    assert e["to"] == "b"
    assert e["reason"] == "rate_limit"
    assert isinstance(e["ts"], float)


def test_drain_events_clears_queue():
    get_or_create("conv-1", "medium", ["a", "b", "c"])
    try_activate("conv-1", FailoverReason.RATE_LIMIT)
    assert len(drain_events("conv-1")) == 1
    # Second drain returns empty list.
    assert drain_events("conv-1") == []


def test_drain_events_for_unknown_conversation_returns_empty():
    assert drain_events("never-existed") == []


# ──────────────────────────────────────────────────────────────────────────────
# record_response — empty-content trigger
# ──────────────────────────────────────────────────────────────────────────────


def test_record_response_non_empty_resets_counter():
    get_or_create("conv-1", "medium", ["a", "b"])
    state = get_state("conv-1")
    # Build up to 2 empties
    record_response("conv-1", "", False)
    record_response("conv-1", "", False)
    assert state.empty_count == 2
    # Non-empty resets
    triggered = record_response("conv-1", "Hello!", False)
    assert triggered is False
    assert state.empty_count == 0


def test_record_response_with_tool_calls_is_not_empty():
    """Empty content + tool_calls is NORMAL (model decided to act)."""
    get_or_create("conv-1", "medium", ["a", "b"])
    triggered = record_response("conv-1", "", True)
    assert triggered is False
    assert get_state("conv-1").empty_count == 0


def test_record_response_three_empties_triggers_fallback():
    get_or_create("conv-1", "medium", ["a", "b", "c"])
    assert record_response("conv-1", "", False) is False
    assert record_response("conv-1", "   ", False) is False  # whitespace = empty
    triggered = record_response("conv-1", "", False)
    assert triggered is True
    state = get_state("conv-1")
    assert state.current_provider == "b"
    assert state.empty_count == 0  # reset after switch
    history = state.reason_history
    assert history[-1][0] is FailoverReason.EMPTY_RESPONSE


def test_record_response_returns_false_when_chain_exhausted_on_empty():
    """Three empties on a chain of one provider → can't switch, returns False."""
    get_or_create("conv-1", "medium", ["only-one"])
    record_response("conv-1", "", False)
    record_response("conv-1", "", False)
    triggered = record_response("conv-1", "", False)
    # try_activate ran but found no next provider → returns False
    assert triggered is False
    assert get_state("conv-1").is_exhausted is True


def test_record_response_no_state_returns_false():
    assert record_response("ghost", "anything", False) is False


# ──────────────────────────────────────────────────────────────────────────────
# discard
# ──────────────────────────────────────────────────────────────────────────────


def test_discard_removes_state_and_events():
    get_or_create("conv-1", "medium", ["a", "b"])
    try_activate("conv-1", FailoverReason.RATE_LIMIT)
    discard("conv-1")
    assert get_state("conv-1") is None
    assert drain_events("conv-1") == []
    assert state_count() == 0


def test_discard_idempotent():
    """Discarding a non-existent conv must not raise."""
    discard("never-existed")  # should be a no-op
    assert state_count() == 0


# ──────────────────────────────────────────────────────────────────────────────
# Retry-primary hotfix (audit Gemini §1.3, 2026-05-25)
# ──────────────────────────────────────────────────────────────────────────────


def test_should_retry_primary_false_when_no_state():
    """No conv → no retry decision possible."""
    assert should_retry_primary("ghost-conv") is False


def test_should_retry_primary_false_when_primary_active():
    """Fresh conv with primary still active → nothing to retry."""
    get_or_create("conv-1", "medium", ["primary", "fb1"])
    assert should_retry_primary("conv-1") is False


def test_try_activate_sets_fallback_activated_at(monkeypatch):
    """When the chain advances, `fallback_activated_at` must be stamped."""
    get_or_create("conv-1", "medium", ["primary", "fb1"])
    try_activate("conv-1", FailoverReason.TIMEOUT)
    state = get_state("conv-1")
    assert state.fallback_activated_at is not None
    assert state.is_active_fallback is True


def test_should_retry_primary_false_before_cooldown(monkeypatch):
    """Cool-down not yet elapsed → don't retry."""
    monkeypatch.setenv("FALLBACK_RETRY_PRIMARY_MINUTES", "10")
    get_or_create("conv-1", "medium", ["primary", "fb1"])
    try_activate("conv-1", FailoverReason.TIMEOUT)
    state = get_state("conv-1")
    # 5 minutes after activation : not enough
    fake_now = state.fallback_activated_at + 5 * 60
    assert should_retry_primary("conv-1", now=fake_now) is False


def test_should_retry_primary_true_after_cooldown(monkeypatch):
    """Once cool-down elapsed, retry is signaled."""
    monkeypatch.setenv("FALLBACK_RETRY_PRIMARY_MINUTES", "10")
    get_or_create("conv-1", "medium", ["primary", "fb1"])
    try_activate("conv-1", FailoverReason.TIMEOUT)
    state = get_state("conv-1")
    fake_now = state.fallback_activated_at + 11 * 60
    assert should_retry_primary("conv-1", now=fake_now) is True


def test_should_retry_primary_disabled_by_env(monkeypatch):
    """FALLBACK_RETRY_PRIMARY_MINUTES=0 → legacy sticky-forever behaviour."""
    monkeypatch.setenv("FALLBACK_RETRY_PRIMARY_MINUTES", "0")
    get_or_create("conv-1", "medium", ["primary", "fb1"])
    try_activate("conv-1", FailoverReason.TIMEOUT)
    state = get_state("conv-1")
    # Even 1 hour later, no retry
    fake_now = state.fallback_activated_at + 60 * 60
    assert should_retry_primary("conv-1", now=fake_now) is False


def test_should_retry_primary_honors_default_when_env_unset(monkeypatch):
    """Unset env → default 10 minutes."""
    monkeypatch.delenv("FALLBACK_RETRY_PRIMARY_MINUTES", raising=False)
    get_or_create("conv-1", "medium", ["primary", "fb1"])
    try_activate("conv-1", FailoverReason.TIMEOUT)
    state = get_state("conv-1")
    fake_now = state.fallback_activated_at + 11 * 60
    assert should_retry_primary("conv-1", now=fake_now) is True


def test_should_retry_primary_garbage_env_falls_back_to_default(monkeypatch):
    """Non-numeric env value → fall back to 10-minute default, no crash."""
    monkeypatch.setenv("FALLBACK_RETRY_PRIMARY_MINUTES", "totally-not-a-number")
    get_or_create("conv-1", "medium", ["primary", "fb1"])
    try_activate("conv-1", FailoverReason.TIMEOUT)
    state = get_state("conv-1")
    fake_now = state.fallback_activated_at + 11 * 60
    assert should_retry_primary("conv-1", now=fake_now) is True


def test_reset_to_primary_resets_index_and_clears_activated_at():
    get_or_create("conv-1", "medium", ["primary", "fb1", "fb2"])
    try_activate("conv-1", FailoverReason.TIMEOUT)
    state = get_state("conv-1")
    assert state.current_index == 1
    assert state.fallback_activated_at is not None

    ok = reset_to_primary("conv-1")
    assert ok is True
    state = get_state("conv-1")
    assert state.current_index == 0
    assert state.current_provider == "primary"
    assert state.fallback_activated_at is None
    assert state.is_active_fallback is False


def test_reset_to_primary_emits_ws_event():
    """A reset must emit a `provider.reset_to_primary` event the UI can react to."""
    get_or_create("conv-1", "medium", ["primary", "fb1"])
    try_activate("conv-1", FailoverReason.TIMEOUT)
    drain_events("conv-1")  # discard the switch event from try_activate
    reset_to_primary("conv-1", reason="manual_test")
    events = drain_events("conv-1")
    assert len(events) == 1
    assert events[0]["type"] == "provider.reset_to_primary"
    assert events[0]["from"] == "fb1"
    assert events[0]["to"] == "primary"
    assert events[0]["reason"] == "manual_test"


def test_reset_to_primary_noop_on_primary():
    """Calling reset when already on the primary must be a no-op (False)."""
    get_or_create("conv-1", "medium", ["primary", "fb1"])
    ok = reset_to_primary("conv-1")
    assert ok is False


def test_reset_to_primary_noop_on_missing_conv():
    """Calling reset on an unknown conv must not raise."""
    assert reset_to_primary("never-existed") is False


def test_retry_loop_after_persistent_primary_failure(monkeypatch):
    """End-to-end : a fallback is active, cool-down elapses, retry resets to
    primary, primary fails again → try_activate must STAMP a fresh
    `fallback_activated_at` so the next retry waits another full cool-down.
    Prevents busy-loop when the primary stays down."""
    monkeypatch.setenv("FALLBACK_RETRY_PRIMARY_MINUTES", "10")
    get_or_create("conv-1", "medium", ["primary", "fb1"])
    try_activate("conv-1", FailoverReason.TIMEOUT)
    state = get_state("conv-1")
    t0 = state.fallback_activated_at

    # Cool-down elapsed → reset to primary
    reset_to_primary("conv-1", reason="cooldown_elapsed")
    state = get_state("conv-1")
    assert state.current_index == 0
    assert state.fallback_activated_at is None

    # Primary fails AGAIN → try_activate re-stamps activated_at
    try_activate("conv-1", FailoverReason.RATE_LIMIT)
    state = get_state("conv-1")
    assert state.current_index == 1
    assert state.fallback_activated_at is not None
    # The new stamp is more recent than t0 (the original switch)
    assert state.fallback_activated_at >= t0
