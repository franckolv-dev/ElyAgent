# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/missions/nodes.py
# @brief      Persistence-loop nodes — real Plan / Act / Eval / Replan logic
# =============================================================================
"""Persistence-loop nodes — real Plan / Act / Eval / Replan logic.

Each node :
  1. Reads the current state.
  2. Calls the LLM (or dispatches a tool) to do its part.
  3. Persists a `MissionStep` audit row via `mission_service.add_step`.
  4. Returns a state delta that LangGraph merges.

Design :
  - One iteration of the graph = one "tick" = exactly ONE pass through
    plan→act→eval (skipping plan if already built, optionally branching
    to replan). The graph EXITS at the end of each tick — the heartbeat
    re-invokes for the next tick. This keeps budget guards tight and the
    kill switch instant.
  - Plan / Eval / Replan use the MEDIUM tier (Gemma 4 21B REAP locally).
    Act uses the same tier with `bind_tools` for function-calling.
  - HITL requests run inline before tool dispatch — same code path as
    the chat-mode `tool_node` so the user gets a unified experience.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)

from app.agent.missions.state import MissionState
from app.services import mission_service

logger = logging.getLogger(__name__)


# ── Tool dispatch helper (factored from agent/nodes.py:tool_node) ────────────

async def dispatch_tool(
    tool_name: str,
    tool_args: dict,
    tool_call_id: str,
    user_id: str,
) -> tuple[str, bool]:
    """Run a single tool call with HITL + vault + credential injection.

    Returns (output_text, success_bool). On HITL deny / ban / vault locked,
    success=False with an explanatory output string.

    Mirrors the logic of `app.agent.nodes.tool_node` but for a single call
    instead of a batch — missions execute one tool per iteration so the
    bookkeeping is simpler.
    """
    from app.skills import get_skill_registry
    from app.agent.tool_sets import GOOGLE_TOOLS, USER_ID_TOOLS
    from app.services.security_filter import ALWAYS_CRITICAL_TOOLS, SecurityFilter
    from app.services.hitl_manager import get_hitl_manager
    from app.services.memory_manager import get_memory_manager

    tool_map = {t.name: t for t in get_skill_registry().all_tools}
    tool = tool_map.get(tool_name)
    if not tool:
        return f"Outil inconnu : {tool_name!r}", False

    # Injected args (never visible in logs/UI)
    args = dict(tool_args)
    if tool_name in GOOGLE_TOOLS:
        from app.services.credential_store import get_credential_store
        args["user_google_credentials_json"] = get_credential_store().get(user_id) or ""
    if tool_name in USER_ID_TOOLS:
        args["user_id"] = user_id

    _hidden = {"user_google_credentials_json", "user_id"}
    display_args = {k: v for k, v in args.items() if k not in _hidden}
    action_desc = f"Outil: {tool_name} | Arguments: {json.dumps(display_args, ensure_ascii=False)}"

    # Vault refs resolution
    if any(isinstance(v, str) and v.startswith("vault://") for v in args.values()):
        from app.services.vault_service import get_vault_service
        vault = get_vault_service()
        if vault.is_locked(user_id):
            return "⛔ Vault verrouillé — déverrouillez-le dans Paramètres → Vault.", False
        try:
            args, _resolved = await vault.resolve_vault_refs(user_id, args)
            if _resolved:
                logger.info("Mission: resolved vault refs %s for tool %s", _resolved, tool_name)
        except KeyError as exc:
            return f"⛔ Secret introuvable dans le Vault : {exc}", False

    # HITL gate for sensitive tools
    sf = SecurityFilter()
    needs_hitl = (tool_name in ALWAYS_CRITICAL_TOOLS) or sf.is_critical(action_desc)
    if needs_hitl:
        logger.info("Mission HITL required: %s", action_desc)
        hitl = get_hitl_manager()
        decision, reason = await hitl.request_validation(description=action_desc, user_id=user_id)
        if decision == "ban":
            rule = f"INTERDICTION PERMANENTE: {action_desc}"
            if reason:
                rule += f" — Raison: {reason}"
            await get_memory_manager().store_constraint(rule, user_id)
            return "Action interdite définitivement et règle de sécurité enregistrée.", False
        if decision != "allow":
            return "Action refusée par l'utilisateur pour cette occurrence.", False

    # Actually run the tool
    try:
        t0 = time.monotonic()
        result = await tool.ainvoke(args)
        elapsed = time.monotonic() - t0
        logger.warning("⏱ TIMING[mission_tool:%s] %.2fs", tool_name, elapsed)
        return str(result), True
    except Exception as exc:
        logger.warning("Mission tool %s failed: %s", tool_name, exc)
        return f"Erreur d'exécution: {exc}", False


# ── LLM helpers ──────────────────────────────────────────────────────────────

def _get_planner_llm():
    """LLM used for plan / replan — needs reasoning, not tool-calling."""
    from app.services.llm_provider import get_llm_for_tier, ComplexityTier
    return get_llm_for_tier(ComplexityTier.MEDIUM)


def _filter_tools_for_step(all_tools: list, tool_hint: Optional[str], goal: str) -> list:
    """Reduce the tool inventory to a manageable subset for this iteration.

    With 76 tools binded simultaneously, smaller models (xLAM-2-8B,
    Gemini-flash) hit payload-size limits or get confused. We pre-filter
    to ~10-15 tools using two signals :

    1. `tool_hint` from the plan step (most reliable) — strict match by
       prefix/family. Ex: hint="weather_get" → all tools starting with
       "weather_" or containing "weather".
    2. Keyword extraction from the goal text (fallback) — match tool
       names against significant words in the goal.

    If neither yields enough candidates, we top up with a few "generic"
    tools (web_search, web_browse) so the model always has something
    to fall back to.
    """
    if not all_tools:
        return all_tools

    # If hint is set, prioritise tools matching its family
    candidates: list = []
    seen: set[str] = set()

    def _add(t):
        if t.name not in seen:
            candidates.append(t)
            seen.add(t.name)

    if tool_hint:
        hint_low = tool_hint.lower()
        # Try exact match first
        for t in all_tools:
            if t.name == tool_hint:
                _add(t)
        # Then prefix match (e.g. weather_ → weather_get, weather_forecast)
        prefix = hint_low.split("_")[0] if "_" in hint_low else hint_low
        for t in all_tools:
            if t.name.lower().startswith(prefix):
                _add(t)
        # Then substring match (broader)
        if prefix and len(prefix) >= 4:
            for t in all_tools:
                if prefix in t.name.lower() or prefix in (t.description or "").lower()[:200]:
                    _add(t)

    # Keyword extraction from goal — pick significant nouns
    if len(candidates) < 10:
        goal_low = goal.lower()
        # Common ELY tool families to keyword-match
        FAMILY_KEYWORDS = {
            "weather":  ["météo", "meteo", "weather", "temperature", "pluie", "soleil"],
            "news":     ["news", "actualité", "actualites", "info", "article"],
            "gmail":    ["mail", "email", "courrier", "boîte"],
            "calendar": ["agenda", "calendrier", "rendez-vous", "rdv", "réunion", "événement"],
            "drive":    ["drive", "fichier", "document", "doc", "dossier"],
            "tasks":    ["tâche", "tache", "todo", "task"],
            "web":      ["web", "internet", "site", "url", "page"],
            "ssh":      ["ssh", "serveur", "vps", "shell", "commande"],
            "translate":["traduis", "traduction", "translate"],
            "image":    ["image", "photo", "picture", "imagen", "dessin"],
        }
        for family, kws in FAMILY_KEYWORDS.items():
            if any(kw in goal_low for kw in kws):
                for t in all_tools:
                    if family in t.name.lower():
                        _add(t)

    # Top up with generic must-haves so we always have a safety net
    GENERIC = {"web_search", "web_browse", "smart_knowledge_query"}
    for t in all_tools:
        if t.name in GENERIC:
            _add(t)

    # Cap to avoid payload bloat (~15 tools handles 99% of cases)
    return candidates[:15] if candidates else all_tools[:15]


def _get_actor_llms(tool_hint: Optional[str] = None, goal: str = "") -> tuple[Any, list[tuple[str, Any]], list[Any]]:
    """Return (primary_llm_bound, [(label, fallback_llm_bound)], raw_tools).

    `primary` is the local model (xLAM-2-8B or Gemma 4 21B REAP) — fast
    and free but smaller models choke on too many tool schemas in the
    bind payload. We pre-filter via `_filter_tools_for_step` so the
    model only sees ≤15 tools relevant to the current step.

    `fallbacks` are cloud LLMs (Gemini, Claude Haiku) — handle larger
    tool sets reliably but cost API credits.

    We DON'T pass `tool_choice="any"` at bind-time because Gemini's
    bind_tools handles it as a sticky kwarg that interferes with
    serialization (raises "tool_choice but no formatted_tools" at invoke
    time on some provider versions). The prompt instead instructs the
    model to emit a tool_call.
    """
    from app.services.llm_provider import get_llm_for_tier, get_fallback_llms, ComplexityTier
    from app.skills import get_skill_registry

    all_tools = get_skill_registry().all_tools
    tools = _filter_tools_for_step(all_tools, tool_hint, goal)
    logger.info("act: filtered %d → %d tools (hint=%s)", len(all_tools), len(tools), tool_hint)

    primary = get_llm_for_tier(ComplexityTier.MEDIUM)
    primary_bound = primary.bind_tools(tools)

    fallbacks_bound = [(label, fb.bind_tools(tools)) for label, fb in get_fallback_llms()]
    return primary_bound, fallbacks_bound, tools


def _get_evaluator_llm():
    """LLM used for eval — judgment, no tools."""
    from app.services.llm_provider import get_llm_for_tier, ComplexityTier
    return get_llm_for_tier(ComplexityTier.MEDIUM)


def _strip_json_fence(raw: str) -> str:
    """LLMs often wrap JSON in ```json …``` blocks. Strip them."""
    raw = raw.strip()
    if raw.startswith("```"):
        # Drop the opening fence and any "json" tag
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
    return raw.strip()


# ── plan_node ────────────────────────────────────────────────────────────────

_PLAN_SYSTEM = """Tu es un planificateur d'agent IA. L'utilisateur te confie un objectif (goal) à atteindre.
Décompose-le en une suite d'étapes ATOMIQUES, chacune réalisable par UN seul appel d'outil.

Réponds STRICTEMENT en JSON, sans texte autour, au format suivant :
{
  "steps": [
    {"id": "1", "description": "...", "tool_hint": "<nom_outil_pressenti_ou_null>"},
    {"id": "2", "description": "...", "tool_hint": "..."}
  ],
  "estimated_iterations": <int>
}

Règles :
- Chaque "description" doit être ce que l'agent doit FAIRE à cette étape (pas ce qu'il doit savoir).
- "tool_hint" peut être null si tu ne sais pas quel outil utiliser.
- Maximum 8 étapes. Si le goal demande plus, regroupe.
- Les étapes seront exécutées en ORDRE séquentiel.
- N'invente pas d'outils — si tu ne connais pas un outil, mets null."""


async def plan_node(state: MissionState) -> dict:
    """Build (or refresh) the plan for the mission.

    First iteration → builds plan v1 from the goal.
    Subsequent iterations → no-op (plan was built in v1; replan_node updates it).
    """
    mission_id = state["mission_id"]
    user_id = state["user_id"]
    goal = state["goal"]
    iteration = state.get("iteration", 0) + 1
    plan_version = state.get("plan_version", 0)

    # Already planned → just bump iteration counter
    if plan_version > 0:
        logger.info("[mission %s] plan: existing v%d, skipping (iter=%d)", mission_id, plan_version, iteration)
        return {"iteration": iteration}

    # Generate v1 plan
    t0 = time.monotonic()
    llm = _get_planner_llm()
    messages: list[BaseMessage] = [
        SystemMessage(content=_PLAN_SYSTEM),
        HumanMessage(content=f"Goal de l'utilisateur :\n\n{goal}"),
    ]
    response = await llm.ainvoke(messages)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    raw = getattr(response, "content", "") or ""

    # Parse JSON
    try:
        plan_json = json.loads(_strip_json_fence(raw))
        steps = plan_json.get("steps", [])
    except Exception as exc:
        logger.warning("[mission %s] plan: JSON parse failed (%s) — using fallback", mission_id, exc)
        plan_json = {"steps": [{"id": "1", "description": goal[:200], "tool_hint": None}]}
        steps = plan_json["steps"]

    # Render markdown for human readability
    plan_text = "# Plan v1\n\n" + "\n".join(
        f"- [ ] **{s.get('id','?')}** {s.get('description','?')}"
        + (f"  *(outil envisagé : `{s.get('tool_hint')}`)*" if s.get("tool_hint") else "")
        for s in steps
    )

    # Persist
    await mission_service.add_plan(mission_id, plan_text=plan_text, plan_json=plan_json)
    await mission_service.add_step(
        mission_id, phase="plan",
        thought=raw[:2000],
        evaluation=f"Plan v1 généré ({len(steps)} étapes)",
        success=True,
        duration_ms=elapsed_ms,
        model_used="medium-tier",
    )
    logger.info("[mission %s] plan: v1 with %d steps (%.1fs)", mission_id, len(steps), elapsed_ms / 1000)

    return {
        "iteration": iteration,
        "plan_version": 1,
        "plan_text": plan_text,
        "plan_json": plan_json,
        "consecutive_failures": 0,
    }


# ── act_node ─────────────────────────────────────────────────────────────────

_ACT_SYSTEM = """Tu es l'agent ELY exécutant une mission. Voici le plan en cours :

{plan_text}

Étape courante à exécuter : « {current_step_desc} »

Choisis UN outil disponible dans ton inventaire pour avancer sur cette étape.
Émets UN SEUL appel d'outil. Tu ne dois pas répondre en texte — uniquement émettre un tool_call.
Si aucun outil ne semble adapté, choisis l'outil qui s'en rapproche le plus."""


def _next_pending_step(plan_json: Optional[dict]) -> Optional[dict]:
    """Return the first step with status != 'done' (or no status)."""
    if not plan_json:
        return None
    for s in plan_json.get("steps", []):
        if s.get("status") not in {"done", "skipped"}:
            return s
    return None


async def act_node(state: MissionState) -> dict:
    """Pick a tool via LLM, dispatch it, capture the result."""
    mission_id = state["mission_id"]
    user_id = state["user_id"]
    plan_json = state.get("plan_json") or {}
    plan_text = state.get("plan_text", "")

    current_step = _next_pending_step(plan_json)
    if not current_step:
        # No pending steps → nothing to do, treat as done
        logger.info("[mission %s] act: no pending step — marking done", mission_id)
        return {
            "last_eval_success": True,
            "done": True,
            "final_summary": "Toutes les étapes du plan sont terminées.",
        }

    current_step_id = current_step.get("id", "?")
    current_step_desc = current_step.get("description", "?")
    current_tool_hint = current_step.get("tool_hint")

    # Build prompt and invoke primary tool-bound LLM, with fallback.
    # Tool list is pre-filtered to ~15 tools max (smaller models choke on
    # 76 simultaneous tool schemas — payload too big for LM Studio etc.)
    primary_llm, fallbacks, _tools = _get_actor_llms(
        tool_hint=current_tool_hint,
        goal=state.get("goal", ""),
    )
    messages: list[BaseMessage] = [
        SystemMessage(content=_ACT_SYSTEM.format(plan_text=plan_text, current_step_desc=current_step_desc)),
        HumanMessage(content=f"Goal : {state.get('goal','?')}"),
    ]

    t0 = time.monotonic()
    response = None
    tool_calls = []
    model_used = "medium-tier (primary)"
    try:
        response = await primary_llm.ainvoke(messages)
        tool_calls = getattr(response, "tool_calls", []) or []
    except Exception as exc:
        # Known MLX limitation : Gemma 4 21B REAP-4bit + 76 tools bound
        # → "RotatingKVCache Quantization NYI". Fallthrough to Gemini.
        logger.warning("[mission %s] act: primary LLM raised %s — falling back", mission_id, type(exc).__name__)
        response = None

    # Fallback if primary didn't emit a tool_call OR raised. Typical for
    # Gemma 4 21B REAP : either crashes on tool binding (MLX bug) or
    # silently returns text (tool_choice ignored). Try each fallback
    # until one returns ≥1 tool_call. Mirrors chat-mode pattern in
    # app/agent/sub_agents/factory.py.
    if not tool_calls:
        logger.warning(
            "[mission %s] act: primary LLM emitted 0 tool_calls — falling back",
            mission_id,
        )
        for label, fb_llm in fallbacks:
            try:
                t_fb = time.monotonic()
                response = await fb_llm.ainvoke(messages)
                tool_calls = getattr(response, "tool_calls", []) or []
                logger.warning(
                    "[mission %s] act.fallback %.1fs %s → tool_calls=%d",
                    mission_id, time.monotonic() - t_fb, label, len(tool_calls),
                )
                if tool_calls:
                    model_used = f"medium-tier (fallback {label})"
                    break
            except Exception as exc:
                logger.warning("[mission %s] act.fallback %s failed: %s", mission_id, label, exc)

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if not tool_calls:
        # All providers refused to emit a tool call — count as iteration failure
        thought_txt = ""
        if response is not None:
            thought_txt = getattr(response, "content", "") or "(no content)"
        await mission_service.add_step(
            mission_id, phase="act",
            thought=thought_txt or "(primary crashed, fallbacks exhausted)",
            evaluation="Aucun LLM n'a émis de tool_call (primary + fallbacks épuisés)",
            success=False,
            duration_ms=elapsed_ms,
            model_used=model_used,
        )
        return {
            "current_step_id": current_step_id,
            "last_eval_success": False,
            "last_eval_reason": "Aucun outil sélectionné — tous les LLM ont retourné du texte.",
            "consecutive_failures": state.get("consecutive_failures", 0) + 1,
        }

    # Take only the first tool call (one action per tick)
    call = tool_calls[0]
    tool_name = call["name"]
    tool_args = dict(call.get("args") or {})
    tool_id = call.get("id", "act-" + mission_id[:6])

    output, ok = await dispatch_tool(tool_name, tool_args, tool_id, user_id)

    # Persist audit row
    await mission_service.add_step(
        mission_id, phase="act",
        thought=f"Étape « {current_step_desc} »",
        tool_name=tool_name,
        tool_input={k: v for k, v in tool_args.items() if k not in {"user_google_credentials_json", "user_id"}},
        tool_output=output[:5000],
        success=ok,
        duration_ms=elapsed_ms,
        model_used=model_used,
    )
    logger.info(
        "[mission %s] act: tool=%s ok=%s (%.1fs) step=%s",
        mission_id, tool_name, ok, elapsed_ms / 1000, current_step_id,
    )

    return {
        "current_step_id": current_step_id,
        "last_tool_name": tool_name,
        "last_tool_input": tool_args,
        "last_tool_output": output,
        # IMPORTANT : clear stale eval flags from the previous tick so
        # `eval_node` runs fresh on this iteration. Without this, the
        # checkpointer-restored `last_eval_success=False` would short-circuit
        # eval and `consecutive_failures` would never bump → replan dead.
        "last_eval_success": None,
        "last_eval_reason": None,
    }


# ── eval_node ────────────────────────────────────────────────────────────────

_EVAL_SYSTEM = """Tu es l'évaluateur de l'agent ELY. Voici le contexte d'une étape qui vient d'être exécutée :

Goal global : {goal}
Étape : « {step_desc} »
Outil utilisé : {tool_name}
Résultat brut de l'outil :
---
{tool_output}
---

Question : cette étape est-elle un SUCCÈS qui permet d'avancer dans le goal ?

Réponds STRICTEMENT en JSON :
{{
  "success": true|false,
  "reason": "<une phrase max>",
  "all_done": true|false
}}

- "success" = l'étape précise est OK
- "all_done" = le goal global est complètement atteint après cette étape (true si plus rien à faire)"""


async def eval_node(state: MissionState) -> dict:
    """Judge the last action's success and update step status in plan."""
    mission_id = state["mission_id"]
    plan_json = state.get("plan_json") or {}
    current_step_id = state.get("current_step_id")

    # If act_node already concluded (mission done or unrecoverable in-tick failure)
    if state.get("done"):
        return {}
    # If act_node concluded a failure in THIS tick (e.g. no tool_call),
    # `last_tool_name` will be None but `last_eval_reason` will be set.
    # Note : act_node clears stale eval flags at entry so checkpointed
    # values from past ticks don't trigger this branch.
    if state.get("last_eval_success") is False and state.get("last_eval_reason") and not state.get("last_tool_name"):
        return {}

    # No action was taken — nothing to evaluate
    if not state.get("last_tool_name"):
        return {"last_eval_success": True, "last_eval_reason": "no-op iteration"}

    t0 = time.monotonic()
    llm = _get_evaluator_llm()
    current_step = next(
        (s for s in plan_json.get("steps", []) if s.get("id") == current_step_id),
        {"description": "?"},
    )

    prompt = _EVAL_SYSTEM.format(
        goal=state.get("goal", "?"),
        step_desc=current_step.get("description", "?"),
        tool_name=state.get("last_tool_name", "?"),
        tool_output=(state.get("last_tool_output", "") or "")[:2000],
    )
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    raw = getattr(response, "content", "") or ""

    try:
        verdict = json.loads(_strip_json_fence(raw))
        success = bool(verdict.get("success", False))
        reason = str(verdict.get("reason", ""))[:500]
        all_done = bool(verdict.get("all_done", False))
    except Exception as exc:
        logger.warning("[mission %s] eval: JSON parse failed (%s) — assuming success", mission_id, exc)
        success, reason, all_done = True, "Parse failed, assumed success", False

    # Mutate plan_json to mark step done/failed
    new_plan_json = dict(plan_json)
    new_steps = []
    for s in new_plan_json.get("steps", []):
        if s.get("id") == current_step_id:
            s = dict(s)
            s["status"] = "done" if success else "failed"
        new_steps.append(s)
    new_plan_json["steps"] = new_steps

    # Persist
    await mission_service.add_step(
        mission_id, phase="eval",
        evaluation=reason,
        success=success,
        duration_ms=elapsed_ms,
        model_used="medium-tier",
    )

    failures = state.get("consecutive_failures", 0)
    new_failures = 0 if success else failures + 1

    # If goal is reached or all steps are done, mark mission complete
    pending_after = [s for s in new_plan_json.get("steps", []) if s.get("status") not in {"done", "failed", "skipped"}]
    is_done = all_done or (success and not pending_after)

    out: dict = {
        "last_eval_success": success,
        "last_eval_reason": reason,
        "consecutive_failures": new_failures,
        "plan_json": new_plan_json,
    }
    if is_done:
        out["done"] = True
        out["final_summary"] = f"Mission accomplie. Dernière étape : {reason}"

    logger.info(
        "[mission %s] eval: success=%s done=%s consec_failures=%d",
        mission_id, success, is_done, new_failures,
    )
    return out


# ── replan_node ──────────────────────────────────────────────────────────────

_REPLAN_SYSTEM = """Tu es le replanificateur de l'agent ELY. La stratégie actuelle a échoué plusieurs fois.

Goal initial : {goal}

Plan actuel (qui ne fonctionne pas) :
{plan_text}

Dernière tentative qui a échoué :
- Outil : {last_tool}
- Sortie : {last_output}
- Raison de l'échec : {last_reason}

Produis un NOUVEAU plan, différent du précédent, qui contourne ce blocage.
Réponds STRICTEMENT en JSON :
{{
  "reason_for_replan": "<une phrase>",
  "steps": [
    {{"id": "1", "description": "...", "tool_hint": "..."}},
    ...
  ]
}}"""


async def replan_node(state: MissionState) -> dict:
    """Build a new plan version after consecutive failures."""
    mission_id = state["mission_id"]
    new_version = state.get("plan_version", 1) + 1

    t0 = time.monotonic()
    llm = _get_planner_llm()
    prompt = _REPLAN_SYSTEM.format(
        goal=state.get("goal", "?"),
        plan_text=state.get("plan_text", "(plan vide)"),
        last_tool=state.get("last_tool_name", "(aucun)"),
        last_output=(state.get("last_tool_output", "") or "")[:1000],
        last_reason=state.get("last_eval_reason", "(non spécifié)"),
    )
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    raw = getattr(response, "content", "") or ""

    try:
        new_plan = json.loads(_strip_json_fence(raw))
        steps = new_plan.get("steps", [])
        reason = new_plan.get("reason_for_replan", "Plan révisé suite à échecs répétés")
    except Exception as exc:
        logger.warning("[mission %s] replan: JSON parse failed (%s)", mission_id, exc)
        steps = state.get("plan_json", {}).get("steps", [])
        reason = f"Replan parsing failed: {exc}"

    plan_text = f"# Plan v{new_version}\n\n*Raison du replan :* {reason}\n\n" + "\n".join(
        f"- [ ] **{s.get('id','?')}** {s.get('description','?')}"
        + (f"  *(outil envisagé : `{s.get('tool_hint')}`)*" if s.get("tool_hint") else "")
        for s in steps
    )

    plan_json = {"steps": steps, "estimated_iterations": new_plan.get("estimated_iterations", len(steps))}

    await mission_service.add_plan(
        mission_id, plan_text=plan_text, plan_json=plan_json, reason_for_replan=reason,
    )
    await mission_service.add_step(
        mission_id, phase="replan",
        thought=raw[:2000],
        evaluation=reason,
        success=True,
        duration_ms=elapsed_ms,
        model_used="medium-tier",
    )
    logger.info("[mission %s] replan: v%d with %d steps (%.1fs)", mission_id, new_version, len(steps), elapsed_ms / 1000)

    return {
        "plan_version": new_version,
        "plan_text": plan_text,
        "plan_json": plan_json,
        "consecutive_failures": 0,
    }
