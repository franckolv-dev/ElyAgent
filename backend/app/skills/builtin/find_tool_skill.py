# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/find_tool_skill.py
# @brief      find_tool — semantic discovery of ELY's own tools (safety net).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""``find_tool`` — the "tool discovery is a tool" safety net.

The agent's bound toolset is a lean sticky profile (~30-41 tools) kept stable
for prompt-cache reasons. When the model needs a capability it doesn't
currently see, it calls ``find_tool("describe the capability")`` instead of
giving up. We semantic-search the FULL catalog (name + description, via the
FastEmbed encoder already used for memory), return the top matches, and record
them so ``agent_node`` binds them for the rest of the conversation.

This makes the recurring "je n'ai pas d'outil pour X" failure — which is almost
always a *binding* gap, not a real gap (e.g. the Sheets tools existed but
weren't in the default profile) — **self-healing**.

Security: ``find_tool`` only makes a tool VISIBLE. HITL / critical gates still
apply when it's actually called (``tool_node``). Discovering
``drive_delete_file`` does NOT un-gate it.

Phase 1 (this): discovery + sticky binding. Phase 2 (later): when nothing
matches well, emit a ``tool_absent_acknowledged`` signal → trigger tool
generation (Sprint 4b feature C).
"""
from __future__ import annotations

import asyncio
import logging
import math
import unicodedata

from langchain_core.tools import tool

from app.skills.base import Domain, Skill
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)

# Catalog cache — rebuilt only when the registered tool set changes.
# Ranking is HYBRID:
#   - LEXICAL (always, no embedding): normalized token overlap on name +
#     description. Catches the obvious cases the embedder misses ("sheet" ⊂
#     "spreadsheet"/"sheets"). Works everywhere — no FastEmbed dependency.
#   - SEMANTIC (best-effort): cosine on FastEmbed vectors, for paraphrases the
#     lexical misses. MiniLM-L6 is small + English-leaning, so it can't carry
#     French queries alone — it's an *enhancement*, not the backbone. If the
#     encoder is unavailable (env), we degrade to lexical-only.
_catalog_sig: frozenset[str] | None = None
_tool_text_norm: dict[str, str] = {}      # name -> normalized "name + description"
_tool_vectors: dict[str, list[float]] = {}  # name -> embedding (empty if encoder N/A)
_tool_first_sentence: dict[str, str] = {}

_SEM_WEIGHT = 0.5  # semantic is a tiebreak/enhancement; lexical leads

# Méta-outils du funnel lui-même — JAMAIS candidats d'une recherche : le
# docstring de report_missing_capability contient l'exemple « convertir un
# fichier PDF en .docx »… que le pré-check a retrouvé à score 1.0 comme
# « outil existant couvrant la capacité » (auto-empoisonnement, live 19/07).
_META_TOOLS = frozenset({"find_tool", "report_missing_capability"})


def _norm(s: str) -> str:
    """Lowercase + strip accents (so 'créé'~'cree', accent-insensitive)."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _first_sentence(desc: str) -> str:
    desc = (desc or "").strip().replace("\n", " ")
    for sep in (". ", " — ", " : "):
        if sep in desc:
            return desc.split(sep, 1)[0].strip()
    return desc[:160]


async def _ensure_catalog() -> None:
    """(Re)build the catalog cache if the registry changed.

    Lexical text is built always (cheap). Embeddings are best-effort: batch
    in ONE encoder call (~1-3 s, one-time) and left empty if the encoder
    can't init — find_tool then ranks lexical-only.
    """
    global _catalog_sig, _tool_text_norm, _tool_vectors, _tool_first_sentence
    tools = get_skill_registry().all_tools
    sig = frozenset(t.name for t in tools)
    if sig == _catalog_sig and _tool_text_norm:
        return

    _tool_text_norm = {
        t.name: _norm(f"{t.name} {getattr(t, 'description', '') or ''}") for t in tools
    }
    _tool_first_sentence = {
        t.name: _first_sentence(getattr(t, "description", "") or "") for t in tools
    }
    try:
        from app.services.memory import get_memory_infra

        infra = get_memory_infra()
        names = [t.name for t in tools]
        texts = [f"{t.name}: {getattr(t, 'description', '') or ''}" for t in tools]
        vecs = await asyncio.to_thread(lambda: [v.tolist() for v in infra.encoder.embed(texts)])
        _tool_vectors = dict(zip(names, vecs))
        logger.info("find_tool: catalog ready — %d tools (lexical + semantic)", len(names))
    except Exception as exc:  # noqa: BLE001 — semantic is optional
        _tool_vectors = {}
        logger.warning("find_tool: semantic embeddings unavailable, lexical-only (%s)", exc)
    _catalog_sig = sig


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@tool
async def find_tool(capability: str, top_k: int = 5) -> str:
    """Trouver des outils ELY correspondant à une capacité dont tu as besoin mais qui n'est pas déjà disponible.

    APPELLE CET OUTIL AVANT de conclure que tu ne peux pas faire quelque chose
    faute d'outil — Y COMPRIS quand l'utilisateur POSE LA QUESTION de tes
    capacités sans demander la tâche (« peux-tu créer un outil qui… »,
    « sais-tu faire… ») : la recherche consigne les capacités réellement
    absentes. Décris le besoin en langage naturel (ex. « lire un Google
    Sheet existant », « ajouter des lignes à un tableur », « publier sur
    Slack »). Renvoie les outils les plus pertinents, qui deviennent
    disponibles pour le reste de la conversation — appelle ensuite celui qu'il
    te faut.

    Args:
        capability: description en langage naturel de la capacité recherchée.
        top_k: nombre d'outils candidats à renvoyer (défaut 5, max 10).
    """
    capability = (capability or "").strip()
    if not capability:
        return "Précise la capacité recherchée (ex. « lire un Google Sheet existant »)."
    try:
        await _ensure_catalog()
    except Exception as exc:  # noqa: BLE001 — never break the turn
        logger.warning("find_tool: catalog build failed: %s", exc)
        return "La recherche d'outil a échoué temporairement — procède autrement ou réessaie."

    k = max(1, min(int(top_k or 5), 10))
    top = await _rank_capability(capability, k)
    if not top:
        # Nothing matched the FULL catalog → genuine capability gap (not a
        # binding gap): record + (C4-2) auto-generate via the shared path.
        return await _record_gap_and_trigger(capability)

    # Record discoveries so agent_node binds them on the next turn (sticky).
    try:
        from app.agent.discovered_tools import add_discovered
        from app.agent.tools.orchestrate_tool import ORCHESTRATE_CONVERSATION_ID

        add_discovered(ORCHESTRATE_CONVERSATION_ID.get(), top)
    except Exception as exc:  # noqa: BLE001
        logger.debug("find_tool: could not record discovery: %s", exc)

    lines = [f"Outils disponibles pour « {capability} » (utilise-les directement maintenant) :"]
    lines += [f"  • {name} — {_tool_first_sentence.get(name, '')}" for name in top]
    return "\n".join(lines)


async def _record_gap_and_trigger(capability: str, *, model_judged: bool = False) -> str:
    """Consigne un gap réel + (C4-2) lance l'auto-génération. Message inclus.

    Chemin PARTAGÉ entre le no-match de ``find_tool`` (score zéro sur tout le
    catalogue) et ``report_missing_capability`` (C4-2b : le modèle juge les
    résultats non pertinents — le cas RÉALISTE, un vrai gap a presque toujours
    des faux-matchs faibles type « pdf » ⊂ outils pdf non pertinents).
    ``model_judged=True`` : la pertinence a déjà été jugée par le modèle →
    la génération saute son pré-check lexical (pas de double veto).
    """
    _case_id = None
    _gap_user = ""
    try:
        from app.agent.tools.orchestrate_tool import ORCHESTRATE_CONVERSATION_ID
        from app.services.learning.failure_capture import record_tool_absent
        from app.services.learning.learned_tool_dispatch import LEARNED_TOOL_USER_ID

        _gap_user = LEARNED_TOOL_USER_ID.get() or ""
        _case_id = await record_tool_absent(
            user_id=_gap_user,
            capability=capability,
            conversation_id=ORCHESTRATE_CONVERSATION_ID.get() or None,
        )
    except Exception as exc:  # noqa: BLE001 — recording must never break the turn
        logger.debug("find_tool: gap recording skipped: %s", exc)
    _auto_gen = False
    if _case_id:
        try:
            from app.config import get_settings
            from app.services.background_tasks import spawn
            from app.services.learning.auto_tool_generation import (
                maybe_generate_for_gap,
            )

            _auto_gen = bool(get_settings().auto_tool_generation_enabled)
            if _auto_gen:
                spawn(
                    maybe_generate_for_gap(
                        _case_id, capability, _gap_user,
                        skip_precheck=model_judged,
                    ),
                    label="auto-tool-generation",
                )
        except Exception as exc:  # noqa: BLE001 — le déclencheur non plus
            logger.debug("find_tool: auto-generation skipped: %s", exc)
            _auto_gen = False
    if _auto_gen:
        return (
            f"Aucun outil existant ne couvre « {capability} ». "
            "Capacité réellement absente — consignée dans "
            "les « Capacités manquantes », et la génération d'un outil "
            "candidat démarre automatiquement : il sera soumis à "
            "validation humaine avant d'être utilisable."
        )
    return (
        f"Aucun outil existant ne couvre « {capability} ». "
        "Capacité réellement absente — consignée dans "
        "les « Capacités manquantes » : un outil peut y être généré "
        "puis soumis à validation humaine avant d'être utilisable."
    )


@tool
async def report_missing_capability(capability: str) -> str:
    """Consigner une capacité RÉELLEMENT absente et lancer la génération d'un outil candidat.

    APPELLE CET OUTIL quand `find_tool` a renvoyé des résultats qui ne
    couvrent PAS le besoin (faux-matchs — ex. des outils « pdf » qui ne
    convertissent pas), ou quand l'utilisateur te signale explicitement une
    capacité manquante à implémenter. La consignation apparaît dans
    « Capacités manquantes » ; un outil candidat est généré automatiquement
    puis soumis à validation humaine avant d'être utilisable.

    Args:
        capability: description en langage naturel de la capacité absente
            (ex. « convertir un fichier PDF en fichier .docx »).
    """
    capability = (capability or "").strip()
    if not capability:
        return "Précise la capacité manquante (description en langage naturel)."
    # Le modèle vient de VOIR les candidats de find_tool et les a jugés non
    # pertinents — le pré-check lexical (juge plus faible) n'a pas de droit
    # de veto sur ce jugement (leçon 19/07 : « drive_export_file » matchait
    # « fichier+pdf+docx » à 0,67 et bloquait le gap PDF→DOCX fondateur).
    # Il reste INFORMATIF : un voisin lexical fort est signalé en caveat.
    caveat = ""
    try:
        existing = await capability_has_existing_tool(capability)
        if existing:
            caveat = (
                f"\nNB : l'outil existant {existing} est lexicalement proche — "
                "si en le relisant il couvre finalement le besoin, utilise-le "
                "et signale-le."
            )
    except Exception:  # noqa: BLE001
        pass
    return await _record_gap_and_trigger(capability, model_judged=True) + caveat


async def _rank_capability(capability: str, k: int) -> list[str]:
    """Classement lexical+sémantique du catalogue COMPLET pour une capacité.

    Partagé entre ``find_tool`` (l'outil) et le pré-check anti-doublon C4-2
    (``capability_has_existing_tool``) — même leçon #56 : le lexical porte le
    résultat, le sémantique enrichit en best-effort.
    """
    await _ensure_catalog()
    q_tokens = [t for t in _norm(capability).split() if len(t) >= 3]
    qv: list[float] | None = None
    if _tool_vectors:
        try:
            from app.services.memory import get_memory_infra

            qv = await get_memory_infra().embed(capability)
        except Exception as exc:  # noqa: BLE001
            logger.debug("find_tool: query embed unavailable, lexical-only (%s)", exc)

    def _score(name: str) -> float:
        text = _tool_text_norm.get(name, "")
        lex = (sum(1 for t in q_tokens if t in text) / len(q_tokens)) if q_tokens else 0.0
        sem = _cosine(qv, _tool_vectors[name]) if (qv and name in _tool_vectors) else 0.0
        return lex + _SEM_WEIGHT * sem

    candidates = [n for n in _tool_text_norm if n not in _META_TOOLS]
    ranked = sorted(((_score(n), n) for n in candidates), reverse=True)
    return [name for score, name in ranked[:k] if score > 0.0]


# Seuil du pré-check anti-doublon (recouvrement lexical simple). Rôle :
# PRÉCISION, pas rappel — il ne bloque que sur recouvrement franc (≥ la
# moitié des tokens significatifs). Le RAPPEL des vrais gaps est porté par
# le chemin modèle : ``report_missing_capability`` consigne SANS veto du
# pré-check (leçon 19/07 : un juge lexical ne re-conteste pas un jugement
# de pertinence du modèle — « drive_export_file » matchait « fichier+pdf+
# docx » et bloquait le gap PDF→DOCX fondateur). Une pondération IDF a été
# essayée puis retirée : les tokens rares NON matchés du côté requête
# (« existant ») plombent la couverture des vrais doublons — sans gain,
# le rappel n'étant plus son travail.
_PRECHECK_MIN_SCORE = 0.5


async def capability_has_existing_tool(capability: str) -> str | None:
    """Pré-check anti-doublon (C4-2) : meilleur outil existant, ou None.

    Consommateurs : endpoint admin ``/tool-creator/run`` (bloquant, avec
    ``force``), auto-génération sur no-match (redondant par construction),
    et ``report_missing_capability`` (INFORMATIF seulement — caveat).
    Best-effort : erreur → None (la collision de nom du registration_gate
    reste le filet aval).
    """
    capability = (capability or "").strip()
    if not capability:
        return None
    try:
        await _ensure_catalog()
        q_tokens = [t for t in _norm(capability).split() if len(t) >= 3]
        if not q_tokens:
            return None
        best_score, best_name = 0.0, None
        for name, text in _tool_text_norm.items():
            if name in _META_TOOLS:
                continue
            lex = sum(1 for t in q_tokens if t in text) / len(q_tokens)
            if lex > best_score:
                best_score, best_name = lex, name
        return best_name if best_score >= _PRECHECK_MIN_SCORE else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("capability_has_existing_tool failed: %s", exc)
        return None


get_skill_registry().register(Skill(
    name="find_tool",
    display_name="Recherche d'outil",
    description=(
        "Trouver un outil ELY adapté à un besoin quand il n'est pas déjà "
        "disponible (recherche sémantique sur tout le catalogue d'outils)."
    ),
    icon="🧭",
    scopes=[],
    domains=[Domain.UNIVERSAL],
    tools=[find_tool, report_missing_capability],
))
