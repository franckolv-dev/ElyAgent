# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/helpers/bind_tools.py
# @brief      Sprint refactor nodes.py Phase 1.4 — smart bind_tools that
#             toggles `parallel_tool_calls` based on model family.
# @license    PolyForm Strict License 1.0.0
# @version    1.7.1
# =============================================================================
"""Smart bind_tools — disable parallel_tool_calls for permissive / openai-family.

Bug observed 2026-05-08 on Qwen 2.5 14B local (and reproducible on most
permissive instruct models) :

  Turn 1 → modèle émet 3 tool_calls EN PARALLÈLE :
    browser_navigate(url="https://catalogmaker.fr")
    browser_screenshot()
    gmail_send_with_local_attachment(local_path="/tmp/.../screenshot-catalogmaker.png", ...)

  Le modèle INVENTE le ``local_path`` parce qu'il n'a pas encore reçu le
  résultat de browser_screenshot (qui retourne un uuid réel). gmail_send
  échoue avec « fichier introuvable ». 2 tours de retry gaspillés avant
  que le modèle ne corrige son tir au tour 3.

Fix : ``parallel_tool_calls=False`` au bind. Force le modèle à émettre UN
tool_call par tour. Au tour 1 : browser_navigate. Au tour 2 (avec le retour
de tour 1) : browser_screenshot. Au tour 3 (avec le local_path RÉEL) :
gmail_send_with_local_attachment. Workflow propre en 3 tours au lieu de 4-5.

Famille du modèle
-----------------
- **Disciplined** (Claude / Anthropic) : NE PAS passer le kwarg, leur API
  ne le supporte pas. Claude sait quand chaîner sans qu'on le force.
- **OpenAI family** (gpt-oss, gpt-4o, Codex) : `parallel_tool_calls=False`.
  Ils tendent à parallel-call abusivement comme Qwen 2.5.
- **Permissive** (Qwen, Mistral, Gemma, Llama, Gemini, DeepSeek, GLM, …) :
  `parallel_tool_calls=False`. Les plus à risque pour l'invention d'args.

Logging ultra-verbose
---------------------
Hier soir (2026-05-08), la 1ère tentative de ce fix (commits 96569a7 +
b7c6c6d, rollbackés) plantait silencieusement chez Franck. Sans logs,
diagnostic impossible. Cette version logge à WARNING level sur TOUS les
code paths (entrée, succès, échec, fallback) avec ``exc_info=True`` sur
les exceptions — toute future régression produira une stack trace lisible
dans ``docker logs cyberentity-backend``.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


_BTS_TAG: str = "[bind_tools_smart]"


def _classify_model_family(model_name: str | None) -> str:
    """Return one of "disciplined", "openai_family", "permissive".

    Robust to None / empty / mixed-case. Default = permissive (over-instruct
    is safer than under-instruct).
    """
    if not model_name:
        return "permissive"
    name_lc = model_name.lower()
    # Claude / Anthropic — disciplined, parameter not supported
    if "claude" in name_lc or "anthropic" in name_lc:
        return "disciplined"
    # OpenAI family
    for kw in ("gpt-oss", "gpt_oss", "openai/gpt", "gpt-4", "gpt-3.5", "gpt-4o",
               "codex", "o1-", "o3-", "openai-"):
        if kw in name_lc:
            return "openai_family"
    return "permissive"


def _extract_model_name(llm) -> str:
    """Best-effort introspection of the model name from a LangChain ChatModel.

    Tries the common attribute names used by ChatOpenAI, ChatAnthropic,
    ChatOllama, and the various providers. Returns an empty string if
    nothing is found — safe to pass to ``_classify_model_family``
    (defaults to permissive).
    """
    if llm is None:
        return ""
    for attr in ("model_name", "model", "deployment_name"):
        val = getattr(llm, attr, None)
        if val:
            return str(val)
    return ""


def _bind_tools_smart(llm, tools, model_name: str | None = None):
    """Bind tools with a parallel-tool-calls policy chosen by model family.

    NEVER raises. Every exception path falls back to a plain
    ``llm.bind_tools(tools)`` while logging the cause with full traceback.
    Better a sub-optimal bind than a crashed agent turn.

    If ``model_name`` is None, it is auto-extracted from the LLM instance.
    """
    if model_name is None:
        model_name = _extract_model_name(llm)
    family = _classify_model_family(model_name)
    try:
        _tools_count = len(list(tools)) if hasattr(tools, "__len__") else -1
    except Exception:
        _tools_count = -1
    logger.info(
        "%s model=%r family=%r tools=%d",
        _BTS_TAG, model_name, family, _tools_count,
    )

    if family in ("permissive", "openai_family"):
        try:
            bound = llm.bind_tools(tools, parallel_tool_calls=False)
            logger.info(
                "%s bound with parallel_tool_calls=False (model=%r)",
                _BTS_TAG, model_name,
            )
            return bound
        except Exception as exc:
            # Catch ALL exceptions — some adapters validate the kwarg lazily
            # at runtime, raising on first invoke or in a wrapped chain.
            logger.warning(
                "%s parallel_tool_calls=False rejected (model=%r, %s: %s) "
                "— falling back to plain bind_tools",
                _BTS_TAG, model_name, type(exc).__name__, exc,
                exc_info=True,
            )

    # Disciplined → plain bind. Permissive/openai with failed parametrised
    # bind → also plain bind. If even this fails, we cannot continue.
    try:
        return llm.bind_tools(tools)
    except Exception as exc:
        logger.error(
            "%s plain bind_tools also failed (model=%r, %s: %s)",
            _BTS_TAG, model_name, type(exc).__name__, exc,
            exc_info=True,
        )
        raise
