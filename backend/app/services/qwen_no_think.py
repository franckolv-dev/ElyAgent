# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/qwen_no_think.py
# @brief      Disable Qwen3 thinking mode for low-latency responses
# =============================================================================
"""Qwen3 has a built-in "thinking" mode that generates a long internal monologue
before producing the actual answer (often 1-2k extra tokens). For an interactive
assistant this adds 15-40 seconds of latency per turn — unacceptable.

Per Qwen documentation, the thinking can be disabled by appending `/no_think`
to the *last user message* (system prompt directive does not work).

CRITICAL: the `/no_think` marker is a Qwen-specific control token. Non-Qwen
models (Claude, Gemini, Mistral, DeepSeek…) see it as plain text and may
even interpret it as part of the user's request (e.g. leak it back into
the response as « adresse /no_think »). Always check `is_qwen_llm()` before
injecting, and always `strip_no_think()` from messages before handing them
to a fallback LLM.

This module exposes :
  - `is_qwen_llm(llm)`            : True iff the LLM is a Qwen variant
  - `inject_no_think(messages)`   : returns a copy with /no_think appended to last user msg
  - `strip_no_think(messages)`    : removes /no_think from all messages (for fallback to non-Qwen)
  - `strip_think_block(text)`     : removes any leftover <think>...</think> blocks
"""
from __future__ import annotations

import re
from typing import Any

_THINK_RE = re.compile(r"<think>.*?</think>\s*", flags=re.DOTALL)
_NO_THINK_RE = re.compile(r"\s*/no_think\s*$")


def is_local_openai_llm(llm: Any) -> bool:
    """Return True if the LLM is a local OpenAI-compatible server (LM Studio,
    llama.cpp server, vLLM on localhost, etc.).

    Used to gate the "compact prompt" mode — we skip the verbose ELY system
    prompt (identity + 20 rules + user profile + memories + past_interactions)
    and replace it with a minimal 200-token prompt, because small local
    models (7B-14B) follow textual instructions literally and get confused
    by the 15 000-token ELY prompt, preferring to respond in text rather
    than tool-calling.

    Detection: ChatOpenAI with a base_url pointing to a private host
    (127.0.0.1 / localhost / *.local / 192.168.*.* / 10.*.*.* / host.docker.internal).
    Cloud OpenAI / DeepSeek / OpenRouter / Zhipu all use public hostnames.
    """
    if llm is None:
        return False
    if type(llm).__name__ != "ChatOpenAI":
        return False
    base_url = getattr(llm, "openai_api_base", None) or getattr(llm, "base_url", None) or ""
    base_url = str(base_url).lower()
    local_markers = (
        "localhost", "127.0.0.1", "::1",
        "host.docker.internal",
        ".local/", ".local:",
        "192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
        "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
        "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.",
    )
    return any(m in base_url for m in local_markers)


def is_qwen_llm(llm: Any) -> bool:
    """Return True if the provided LangChain chat model is a Qwen variant
    that SUPPORTS the `/no_think` soft-switch.

    Not every Qwen model supports `/no_think`:
    - Qwen 2.x (Qwen2, Qwen2.5, Qwen2.5-VL, Qwen2.5-Coder) → **no thinking**
      mode at all; `/no_think` is noise that can pollute the prompt and
      confuse the tokenizer's template. DO NOT inject.
    - Qwen 3 → thinking mode with soft switch `/think` / `/no_think`. Inject.
    - Qwen 3.5+ → thinking is on by default and the soft switch is NOT
      honored (must be controlled via `chat_template_kwargs.enable_thinking`
      at API level). Injecting `/no_think` as trailing text is harmless but
      useless. We keep True to maintain history, but the real disabling
      happens via `extra_body` in `_make_lm_studio()`.

    Providers supported:
    - `ChatOllama` (Ollama)
    - `ChatOpenAI` (LM Studio or any OpenAI-compatible local server)
    Any other class is treated as non-Qwen and must NOT receive the marker.
    """
    if llm is None:
        return False
    cls = type(llm).__name__
    if cls not in ("ChatOllama", "ChatOpenAI"):
        return False
    # ChatOllama exposes `model`; ChatOpenAI exposes `model_name` (depending
    # on langchain_openai version it may also mirror `model`).
    model = (
        getattr(llm, "model", None)
        or getattr(llm, "model_name", None)
        or ""
    )
    model_lc = str(model).lower()
    if "qwen" not in model_lc:
        return False
    # Qwen 2.x has no thinking mode — skip the /no_think injection.
    # Patterns like "qwen2", "qwen2.5", "qwen-2" all indicate no-think.
    import re as _re
    if _re.search(r"\bqwen[\s._-]?2(\.|_|-|\b)", model_lc):
        return False
    return True


def strip_think_block(text: str) -> str:
    """Remove <think>...</think> blocks that some Qwen3 variants emit
    even when thinking is supposed to be off."""
    if not text or "<think>" not in text:
        return text
    return _THINK_RE.sub("", text).strip()


def strip_no_think(messages: list[dict[str, Any]] | list[Any]) -> list[Any]:
    """Return a copy of *messages* with any trailing `/no_think` marker removed
    from every message content. Use this right before calling a non-Qwen LLM
    (notably the fallback chain) to avoid the marker leaking into the model's
    reply.
    """
    out = list(messages)
    for i, msg in enumerate(out):
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if isinstance(content, str) and "/no_think" in content:
                out[i] = {**msg, "content": _NO_THINK_RE.sub("", content).rstrip()}
        else:
            content = getattr(msg, "content", "")
            if isinstance(content, str) and "/no_think" in content:
                cleaned = _NO_THINK_RE.sub("", content).rstrip()
                if hasattr(msg, "model_copy"):
                    out[i] = msg.model_copy(update={"content": cleaned})
                else:
                    msg.content = cleaned
                    out[i] = msg
    return out


def inject_no_think(messages: list[dict[str, Any]] | list[Any]) -> list[Any]:
    """Append `/no_think` to the last user message so Qwen3 skips thinking.

    Accepts both langchain BaseMessage objects and dict-style messages.
    Returns a NEW list (does not mutate input).
    """
    if not messages:
        return list(messages)
    out = list(messages)
    # Find the last user message (dict role or BaseMessage type)
    for i in range(len(out) - 1, -1, -1):
        msg = out[i]
        is_user = False
        # dict form
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                is_user = True
        else:
            # langchain HumanMessage
            cls = type(msg).__name__
            if cls in ("HumanMessage", "Human"):
                is_user = True
            elif hasattr(msg, "type") and getattr(msg, "type", None) == "human":
                is_user = True

        if not is_user:
            continue

        # Inject the directive
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if isinstance(content, str) and "/no_think" not in content:
                out[i] = {**msg, "content": f"{content.rstrip()} /no_think"}
        else:
            content = getattr(msg, "content", "")
            if isinstance(content, str) and "/no_think" not in content:
                # Use model_copy for pydantic models (langchain v0.3+)
                if hasattr(msg, "model_copy"):
                    out[i] = msg.model_copy(update={"content": f"{content.rstrip()} /no_think"})
                else:
                    # Fallback for older versions
                    msg.content = f"{content.rstrip()} /no_think"
                    out[i] = msg
        break  # only modify the last user message

    return out
