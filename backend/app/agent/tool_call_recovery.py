# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tool_call_recovery.py
# @brief      Recover tool calls emitted as TEXT instead of structured JSON
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Tool call recovery — fixes models that emit tool calls as text content.

Problem
-------
Several LLM providers (Moonshot Kimi K2.x, Qwen via DashScope sometimes,
DeepSeek occasionally) **violate the OpenAI tool_calls contract** by
emitting the tool call inside the message ``content`` field as text
instead of populating the structured ``tool_calls`` array.

Patterns observed in production:

1. ``<tool_call>{"name":"X","arguments":{...}}</tool_call>`` (Kimi K2)
2. ``<function_call>{"name":"X","arguments":"..."}</function_call>``
3. Pure JSON block at the start of content (Qwen 3.6 Flash)
4. Markdown JSON code fence ` ```json\\n{"name":"X",...}\\n``` `

In every case, ELY's LangGraph receives ``response.tool_calls = []``
and the workflow stalls because no tool was scheduled to run.

Solution
--------
After every LLM inference, this module inspects the content for the
above patterns. If a parseable tool call is found, we ALSO apply
fuzzy name matching to fix hallucinated tool names like ``send_email``
→ ``gmail_send_email`` or ``capture_website`` → ``browser_screenshot``.

Recovered calls are injected into ``response.tool_calls`` so LangGraph
can schedule them as if the model had emitted them properly.

This is a workaround for cloud-side bugs we can't fix.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger(__name__)


# Patterns ordered by likelihood / specificity. Each captures the JSON
# payload as group(1).
_TOOL_CALL_PATTERNS: list[re.Pattern] = [
    # <tool_call>{...}</tool_call>  — Kimi K2.x main pattern
    re.compile(
        r"<tool_call(?:\s[^>]*)?>\s*(\{.*?\})\s*</tool_call>",
        re.DOTALL | re.IGNORECASE,
    ),
    # <function_call>{...}</function_call>
    re.compile(
        r"<function_call(?:\s[^>]*)?>\s*(\{.*?\})\s*</function_call>",
        re.DOTALL | re.IGNORECASE,
    ),
    # Markdown JSON code fence: ```json {...} ```
    re.compile(
        r"```(?:json)?\s*(\{[^`]*?\"name\"[^`]*?\})\s*```",
        re.DOTALL | re.IGNORECASE,
    ),
]

# Lines starting with `{` are candidate roots for balanced-brace extraction
# (Qwen DashScope sometimes emits a multi-line raw JSON object in content).
_BRACE_LINE_RE = re.compile(r"(?m)^\s*\{")


# Semantic synonyms for fuzzy name matching. Maps a token that often
# appears in hallucinated names to a list of real tool names that should
# be tried first. Keys are lowercase substrings; values are real ELY
# tool names that semantically fit.
#
# Order within a value list = priority (try first item first).
_SEMANTIC_HINTS: dict[str, list[str]] = {
    # Email send variants
    "send_email": ["gmail_send_email"],
    "send_mail": ["gmail_send_email"],
    "send_attachment": ["gmail_send_with_attachment", "gmail_send_with_local_attachment"],
    "send_with_attachment": ["gmail_send_with_attachment", "gmail_send_with_local_attachment"],
    "send_with_local_attachment": ["gmail_send_with_local_attachment"],
    "email_send": ["gmail_send_email"],
    "mail_send": ["gmail_send_email"],
    # Screenshot / capture
    "capture_website": ["browser_screenshot"],
    "capture_page": ["browser_screenshot"],
    "screenshot_website": ["browser_screenshot"],
    "take_screenshot": ["browser_screenshot", "os_screenshot"],
    # Browse / navigate
    "navigate_to": ["browser_navigate"],
    "open_url": ["browser_navigate"],
    "open_website": ["browser_navigate"],
    "load_page": ["browser_navigate"],
    "visit_website": ["browser_navigate"],
    # Search
    "search_web": ["browser_search_web", "web_search"],
    "google_search": ["browser_search_web", "web_search"],
    "search_internet": ["web_search"],
    # Calendar
    "create_event": ["calendar_create_event"],
    "schedule_event": ["calendar_create_event"],
    "create_meeting": ["calendar_create_meet_event", "calendar_create_event"],
    # Tasks
    "create_task": ["tasks_create", "scheduler_create_task"],
    "add_task": ["tasks_create"],
    # Contacts
    "find_contact": ["contacts_search"],
    "search_contact": ["contacts_search"],
}

# Threshold below which we refuse to fuzzy-match (avoid wrong tool calls)
_SIM_THRESHOLD = 0.62


def parse_text_tool_calls(content: str) -> list[dict[str, Any]]:
    """Extract tool calls embedded as text in the LLM response content.

    Returns a list of ``{"name": str, "arguments": dict}`` dicts. Empty
    list if no recoverable call was found.
    """
    if not content or not isinstance(content, str):
        return []

    found: list[dict[str, Any]] = []
    seen_payloads: set[str] = set()

    for pat in _TOOL_CALL_PATTERNS:
        for m in pat.finditer(content):
            payload_str = m.group(1).strip()
            # De-dup identical matches (same call seen via 2 patterns)
            if payload_str in seen_payloads:
                continue
            seen_payloads.add(payload_str)

            try:
                obj = json.loads(payload_str)
            except json.JSONDecodeError:
                # Some models emit invalid JSON (single quotes, trailing
                # commas, comments). Be lenient: best-effort cleanup.
                cleaned = _cleanup_loose_json(payload_str)
                try:
                    obj = json.loads(cleaned)
                except json.JSONDecodeError as exc:
                    logger.debug("Tool call recovery: skipping unparseable payload (%s): %r",
                                 exc, payload_str[:120])
                    continue

            if not isinstance(obj, dict):
                continue
            if "name" not in obj:
                continue

            # Arguments can be a dict OR a JSON string (some models stringify it)
            args = obj.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_raw": args}
            if not isinstance(args, dict):
                args = {"_value": args}

            found.append({"name": str(obj["name"]), "arguments": args})

    # Fallback: balanced-brace extraction for raw multi-line JSON objects
    # (Qwen DashScope pattern). Skip if we already found something via regex.
    if not found:
        for m in _BRACE_LINE_RE.finditer(content):
            start = m.end() - 1  # position of the `{`
            payload_str = _extract_balanced_braces(content, start)
            if not payload_str:
                continue
            if payload_str in seen_payloads:
                continue
            seen_payloads.add(payload_str)
            # Only consider objects that look like a tool call shape
            if '"name"' not in payload_str or '"arguments"' not in payload_str:
                continue
            try:
                obj = json.loads(payload_str)
            except json.JSONDecodeError:
                try:
                    obj = json.loads(_cleanup_loose_json(payload_str))
                except json.JSONDecodeError:
                    continue
            if not isinstance(obj, dict) or "name" not in obj:
                continue
            args = obj.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_raw": args}
            if not isinstance(args, dict):
                args = {"_value": args}
            found.append({"name": str(obj["name"]), "arguments": args})

    return found


def _extract_balanced_braces(s: str, start: int) -> str | None:
    """Return the substring s[start:end] containing a balanced {...} block,
    or None if no balanced match exists. Honours JSON string escaping so
    braces inside strings don't disturb the count.
    """
    if start >= len(s) or s[start] != "{":
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def _cleanup_loose_json(s: str) -> str:
    """Best-effort cleanup of common LLM JSON formatting bugs."""
    # Replace single quotes with double quotes (only if no double quotes
    # are present, to avoid breaking valid JSON with quotes inside)
    if '"' not in s and "'" in s:
        s = s.replace("'", '"')
    # Remove trailing commas before } or ]
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    # Remove single-line // comments
    s = re.sub(r"//[^\n]*", "", s)
    return s


def fuzzy_match_tool_name(hallucinated: str, real_names: set[str]) -> str | None:
    """Map a possibly hallucinated tool name to the closest real ELY tool.

    Strategy (in priority order):
      1. Exact match (already correct, just normalize case)
      2. Substring match — hallucinated is contained in real or vice versa
      3. Semantic hints lookup (manual mapping of common paraphrases)
      4. SequenceMatcher similarity ≥ ``_SIM_THRESHOLD``

    Returns None if no acceptable match is found.
    """
    if not hallucinated or not real_names:
        return None

    h_lower = hallucinated.lower().strip()
    real_lower_map = {r.lower(): r for r in real_names}

    # 1. Exact match (case-insensitive)
    if h_lower in real_lower_map:
        return real_lower_map[h_lower]

    # 2. Substring match — prefer real names that contain the hallucinated
    # name as a substring (e.g. send_email → gmail_send_email)
    for r_lower, r_real in real_lower_map.items():
        if h_lower in r_lower or r_lower in h_lower:
            return r_real

    # 3. Semantic hints
    for hint_kw, candidates in _SEMANTIC_HINTS.items():
        if hint_kw in h_lower:
            for cand in candidates:
                if cand.lower() in real_lower_map:
                    return real_lower_map[cand.lower()]

    # 4. SequenceMatcher fuzzy similarity
    best_match: str | None = None
    best_ratio = _SIM_THRESHOLD
    for r_lower, r_real in real_lower_map.items():
        ratio = SequenceMatcher(None, h_lower, r_lower).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = r_real

    if best_match:
        logger.info(
            "fuzzy_match_tool_name: '%s' → '%s' (similarity=%.2f)",
            hallucinated, best_match, best_ratio,
        )
    return best_match


# ──────────────────────────────────────────────────────────────────────────────
# Empty-promise detection (audit P3, 2026-05-06)
# ──────────────────────────────────────────────────────────────────────────────
#
# Some LLMs write things like "Je télécharge la capture sur ton Drive…" or
# "I'm sending the email now…" but FAIL TO CALL the corresponding tool.
# The user reads the prose and waits — nothing happens.
#
# We detect this by looking for two co-occurring signals in the same
# response :
#  1. A future-tense / progress phrase implying delivery is happening
#     ("je télécharge", "uploading", "I'll send…", "envoi en cours")
#  2. A reference to a delivery target (drive, mail, email, fichier, disk)
# AND the response carries NO tool_calls.
#
# When that pattern is detected, the agent_node will re-prompt the model
# with a corrective system message asking it to either call the tool or
# remove the promise.

# Future-tense / in-progress verbs (FR + EN). Word boundaries kept loose
# to catch conjugations and contractions.
_PROMISE_VERBS = re.compile(
    r"\b("
    # FR — future / present narratif d'action en cours
    r"je\s+t[ée]l[ée]charge|"
    r"je\s+vais\s+t[ée]l[ée]charger|"
    r"je\s+(suis\s+en\s+train\s+d['e]?\s*)?envoie?[srz]?|"
    r"je\s+vais\s+envoyer|"
    r"je\s+sauvegarde|"
    r"je\s+vais\s+sauvegarder|"
    r"je\s+enregistre|"
    r"je\s+vais\s+enregistrer|"
    r"je\s+m['e]?\s*en\s+occupe|"
    r"je\s+upload(e|er|erai)|"
    r"j['e]?\s*upload(e|er|erai)|"
    r"je\s+vais\s+l['e]?\s*envoyer|"
    r"je\s+vais\s+la\s+(t[ée]l[ée]charger|envoyer|sauvegarder)|"
    r"en\s+cours\s+de\s+(t[ée]l[ée]chargement|envoi|sauvegarde|upload)|"
    r"t[ée]l[ée]chargement\s+en\s+cours|"
    r"envoi\s+en\s+cours|"
    # EN
    r"i'?m\s+(sending|uploading|saving|downloading|attaching)|"
    r"i\s+(send|upload|save|attach|download)\s+(it|the\s+file|the\s+screenshot)|"
    r"i\s+will\s+(send|upload|save|attach|download)|"
    r"i'?ll\s+(send|upload|save|attach|download)|"
    r"sending\s+(now|the\s+file|the\s+screenshot)|"
    r"uploading\s+(now|to\s+drive|to\s+your)|"
    r"file\s+is\s+being\s+(sent|uploaded|saved)"
    r")",
    re.IGNORECASE,
)

# Delivery-target keywords (must appear in the same response).
_DELIVERY_TARGETS = re.compile(
    r"\b("
    r"drive|gmail|mail|email|courriel|message|fichier|file|"
    r"capture|screenshot|attachment|pi[èe]ce\s+jointe|disque|disk"
    r")\b",
    re.IGNORECASE,
)

# Annonces d'INVESTIGATION sans action (2026-06-12) — « Je vais faire une
# recherche web… » + zéro tool_call + fin de tour : l'utilisateur voit
# l'annonce puis plus rien, et les tours suivants confabulent (« j'attends
# les résultats du tool » — un résultat d'outil est synchrone, rien
# n'attend jamais). Vécu en prod sur « C'est quoi Choose France 2026 ? ».
# Ancrés sur l'INTENTION (je vais / en train de / laisse-moi / j'attends) —
# « voici les résultats de la recherche » ou « d'après mes recherches »
# ne matchent pas (compte rendu, pas promesse).
_SEARCH_INTENT = re.compile(
    r"\b("
    # FR — futur / présent progressif d'investigation
    r"je\s+vais\s+(faire\s+une\s+recherche|chercher|rechercher|v[ée]rifier|"
    r"regarder|consulter|lancer\s+(une\s+|la\s+)?recherche|me\s+renseigner)|"
    r"je\s+(suis\s+en\s+train\s+de|commence\s+[àa])\s+"
    r"(chercher|rechercher|lire|regarder|v[ée]rifier|consulter)|"
    r"laisse[z]?-moi\s+(chercher|rechercher|v[ée]rifier|regarder|lire|consulter)|"
    r"j['e]?\s*attends\s+(les\s+r[ée]sultats|la\s+r[ée]ponse\s+du\s+tool)|"
    r"j['e]?\s*ai\s+lanc[ée]\s+(une\s+|la\s+)?recherche|"
    # EN
    r"let\s+me\s+(search|check|look)|"
    r"i'?m\s+(searching|looking\s+(up|into)|checking)|"
    r"i(?:'ll|\s+will)\s+(search|look\s+(up|into)|check)|"
    r"searching\s+(for|the\s+web)|"
    r"i'?m\s+waiting\s+for\s+the\s+(results|tool)"
    r")",
    re.IGNORECASE,
)


def detect_empty_promise(content: str) -> bool:
    """Return True if the response ANNOUNCES an action without actually
    calling a tool. Caller must also verify ``tool_calls == []`` before
    treating this as a hallucination.

    Deux familles : promesse de LIVRAISON (verbe + cible : « je télécharge
    sur ton Drive ») et annonce d'INVESTIGATION (« je vais faire une
    recherche web ») — la seconde se suffit à elle-même, chercher implique
    l'outil.
    """
    if not content or not isinstance(content, str):
        return False
    if _SEARCH_INTENT.search(content):
        return True
    return bool(_PROMISE_VERBS.search(content) and _DELIVERY_TARGETS.search(content))


# ── L'appel « nu », à la python ────────────────────────────────────────
#
# ⚠️ 23/08 — LA FORME QU'AUCUN MOTIF NE COUVRAIT. Les quatre motifs
# ci-dessus viennent de modèles cloud (Kimi, Qwen, DeepSeek) qui émettent du
# JSON balisé. Un petit modèle local, lui, écrit ce qu'il a vu dans son
# prompt — l'appel tel qu'on le lui a décrit :
#
#     find_tool("sites de critiques de livres en ligne")
#
# Pas de balise, pas de JSON, pas de clé "name". Le message partait tel quel
# à l'utilisateur, qui lisait un appel de fonction en guise de réponse.
#
# La ligne ENTIÈRE doit être l'appel. C'est ce qui empêche d'attraper une
# mention en prose (« appelle `find_tool` pour ça ») — celle-là est une
# explication, pas une tentative d'appel.
_BARE_CALL_RE = re.compile(
    r"(?m)^[\s>*\-•]*`?([a-z][a-z0-9_]{2,63})`?\s*\(\s*(.{0,2000}?)\s*\)\s*[.…:!]*\s*$"
)

# Un nom d'outil suivi d'une parenthèse, N'IMPORTE OÙ dans le texte. Plus
# large que `_BARE_CALL_RE` à dessein : sert uniquement à constater un échec,
# jamais à fabriquer un appel.
_MENTION_APPEL_RE = re.compile(r"`?([a-z][a-z0-9_]{2,63})`?\s*\(")


def _arguments_dun_appel_nu(
    brut: str, nom: str, premier_parametre: Any,
) -> dict[str, Any] | None:
    """Les arguments d'un appel nu, ou ``None`` si on ne sait pas les lier.

    ⚠️ ``None`` plutôt qu'un dict vide, et c'est délibéré : appeler un outil
    avec de mauvais arguments est pire que ne pas l'appeler. Un appel raté se
    voit ; un appel qui part avec le mauvais paramètre produit un résultat
    plausible et faux.
    """
    if not brut:
        return {}

    if brut.startswith("{"):
        try:
            return json.loads(brut)
        except json.JSONDecodeError:
            try:
                obj = json.loads(_cleanup_loose_json(brut))
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None

    # `capability="…"` — la forme nommée, sans ambiguïté.
    nommes = re.findall(r'(\w+)\s*=\s*["\']([^"\']*)["\']', brut)
    if nommes:
        return {cle: valeur for cle, valeur in nommes}

    # `"…"` seul — positionnel. Il faut le nom du paramètre, et lui seul
    # peut venir du schéma réel de l'outil.
    positionnel = re.fullmatch(r'["\'](.*)["\']', brut, re.DOTALL)
    if positionnel:
        param = premier_parametre(nom) if callable(premier_parametre) else None
        return {param: positionnel.group(1)} if param else None

    return None


def parse_bare_tool_calls(
    content: str, real_tool_names: set[str], premier_parametre: Any = None,
) -> list[dict[str, Any]]:
    """Les appels écrits « à la python » sur une ligne à eux.

    ⚠️ AUCUN rapprochement flou ici, contrairement aux motifs JSON. Une ligne
    de texte ordinaire ressemble bien plus à un appel qu'un bloc balisé : le
    nom doit exister TEL QUEL dans le registre, sinon on laisse passer.
    """
    if not content or not isinstance(content, str):
        return []

    trouves: list[dict[str, Any]] = []
    for m in _BARE_CALL_RE.finditer(content):
        nom = m.group(1)
        if nom not in real_tool_names:
            continue
        args = _arguments_dun_appel_nu(m.group(2).strip(), nom, premier_parametre)
        if args is None:
            logger.warning(
                "tool_call_recovery : « %s(…) » reconnu mais arguments non "
                "liables — on n'invente pas de paramètre", nom,
            )
            continue
        trouves.append({"name": nom, "arguments": args})
    return trouves


def looks_like_an_unexecuted_tool_call(
    content: str, real_tool_names: set[str],
) -> str | None:
    """Le nom de l'outil qu'un texte semble appeler — ou ``None``.

    ⚠️ À N'UTILISER QU'APRÈS avoir constaté ``tool_calls == []``. Sous cette
    condition, une mention d'appel ne peut plus être une explication de ce que
    le modèle VIENT de faire : c'est une tentative qui n'a pas abouti.

    Sert à décider d'un ÉCHEC, jamais à fabriquer un appel — d'où sa largeur.
    Rien ne part vers un outil sur la foi de cette fonction.
    """
    if not content or not isinstance(content, str):
        return None
    for m in _MENTION_APPEL_RE.finditer(content):
        if m.group(1) in real_tool_names:
            return m.group(1)
    return None


def recover_tool_calls_into_response(
    response: Any,
    real_tool_names: set[str],
    premier_parametre: Any = None,
) -> int:
    """If response has empty tool_calls but content embeds tool calls as text,
    parse them and inject into response.tool_calls.

    Mutates `response` in place (sets `tool_calls` attribute) and returns
    the number of recovered calls.

    ``premier_parametre`` : appelable ``nom d'outil -> nom du 1er paramètre``,
    nécessaire pour lier un appel nu positionnel (`find_tool("…")`). Absent,
    ces appels-là sont ignorés plutôt que devinés.
    """
    existing_tool_calls = getattr(response, "tool_calls", None) or []
    if existing_tool_calls:
        return 0  # nothing to recover, model behaved correctly

    content = getattr(response, "content", "") or ""
    if not isinstance(content, str):
        return 0  # multimodal content, leave alone

    parsed = parse_text_tool_calls(content)
    if not parsed:
        # Dernier recours : la forme nue. En dernier parce qu'elle est la
        # plus permissive — un motif balisé est une intention explicite.
        parsed = parse_bare_tool_calls(content, real_tool_names, premier_parametre)
    if not parsed:
        return 0

    recovered: list[dict[str, Any]] = []
    for call in parsed:
        raw_name = call["name"]
        real_name = fuzzy_match_tool_name(raw_name, real_tool_names)
        if not real_name:
            logger.warning(
                "tool_call_recovery: ignoring '%s' — no fuzzy match in registry",
                raw_name,
            )
            continue
        recovered.append({
            "name": real_name,
            "args": call["arguments"],
            "id": f"call_recovered_{uuid.uuid4().hex[:8]}",
            "type": "tool_call",
        })
        if real_name != raw_name:
            logger.warning(
                "tool_call_recovery: rewrote hallucinated '%s' → '%s'",
                raw_name, real_name,
            )

    if not recovered:
        return 0

    # Inject into response. LangChain's AIMessage uses `tool_calls` as a list
    # of {"name", "args", "id", "type"} dicts.
    try:
        response.tool_calls = recovered
        # Strip the text-formatted tool calls from content to avoid the
        # frontend showing the raw JSON to the user.
        # Conservatively: only strip if content is mostly the tool call.
        if content.strip().startswith("<tool_call") or content.strip().startswith("{"):
            response.content = "[Outil exécuté automatiquement]"
    except Exception as exc:
        logger.warning("tool_call_recovery: failed to inject (%s) — leaving response untouched", exc)
        return 0

    logger.warning(
        "tool_call_recovery: recovered %d tool call(s) from text content",
        len(recovered),
    )
    return len(recovered)
