#!/usr/bin/env python3
# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/run_architecture_ab.py
# @brief      V2-2 — banc A/B mono-agent contre sous-agents, sur des demandes
#             réellement formulées par les utilisateurs en production.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.0.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Banc A/B des deux architectures d'agent.

**Pourquoi ce banc existe.** La comparaison ne peut PAS se faire sur les
données de production : sur la fenêtre 07/05 → 24/07, le chat web (mono-agent)
totalise 378 conversations et les canaux (sous-agents) 11. Il n'y a pas
d'échantillon en face — cf. `docs_internes/v2_mesure_architectures.md`.

**Ce que le banc mesure, et pourquoi comme ça.** La seule chose qui diffère
entre les deux architectures, c'est *le jeu d'outils exposé au modèle* et,
pour les sous-agents, *un appel LLM de routage en plus*. Le banc isole donc
exactement ça :

- **mono-agent** : un appel modèle avec les ~80 outils du profil `default` ;
- **sous-agents** : un appel de routage, puis un appel modèle avec les seuls
  outils du domaine choisi.

**Aucun outil n'est exécuté.** On observe quel outil le modèle *choisit*, pas
ce qu'il ferait. C'est volontaire : le banc ne touche donc ni la boîte mail,
ni le Drive, ni le calendrier, il est reproductible, et il n'a besoin d'aucun
compte de test. La contrepartie est assumée : il ne mesure pas la réussite
d'une tâche multi-étapes — seulement le premier choix, la latence et le coût
de prompt, qui sont les trois postes où les architectures divergent.

Usage :
    cd backend && uv run python ../bench/run_architecture_ab.py            # les 20 tâches
    cd backend && uv run python ../bench/run_architecture_ab.py --tier simple
    cd backend && uv run python ../bench/run_architecture_ab.py --repeat 3 --json out.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Le banc doit tourner DANS le conteneur : la configuration des tiers LLM
# (table `llm_instances`, clé `tier_routing_config`) vit en base de production.
# Lancé depuis le dépôt, il tomberait sur le défaut codé en dur — mesurant une
# chaîne que personne n'utilise. Le bootstrap accepte les deux dispositions.
for _candidate in (Path("/app"), Path(__file__).resolve().parent.parent / "backend"):
    if (_candidate / "app").is_dir():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break
os.environ.setdefault("ENVIRONMENT", "test")


# ────────────────────────────────────────────────────────────────────────────
# Le jeu de tâches — formulations RÉELLES relevées en base de production.
# `expected` = l'outil attendu. Un ensemble : plusieurs outils sont parfois
# également corrects (lister vs chercher des mails), et compter comme faux un
# choix défendable fausserait la comparaison.
# ────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Task:
    prompt: str
    expected: frozenset[str]
    note: str = ""


TASKS: tuple[Task, ...] = (
    Task("Est-ce que j'ai reçu de nouveaux mails ?",
         frozenset({"gmail_list_emails", "gmail_search_emails"}), "Telegram, récurrent"),
    Task("Est ce que de nouveaux mails sont arrivés ?",
         frozenset({"gmail_list_emails", "gmail_search_emails"}), "Telegram"),
    Task("Peux tu vérifier si j'ai reçu de nouveaux mails ?",
         frozenset({"gmail_list_emails", "gmail_search_emails"}), "Telegram"),
    Task("Quelle est la météo à Vendeuvre-du-Poitou ?",
         frozenset({"weather_get"}), "posé sur 4 canaux différents"),
    Task("Il y a de nouvelles news IA et LLM depuis hier ?",
         frozenset({"web_search", "web_search_news"}), "Telegram"),
    Task("Cherche les dernières actualités sur les modèles de langage.",
         frozenset({"web_search", "web_search_news"}), ""),
    Task("Quels sont mes rendez-vous cette semaine ?",
         frozenset({"calendar_list_events", "calendar_search_events"}), ""),
    Task("Liste les fichiers récents de mon Drive.",
         frozenset({"drive_list_files", "drive_search_files"}), ""),
    Task("Où est le fichier que je t'ai envoyé hier ?",
         frozenset({"drive_search_files", "drive_list_files",
                    "search_past_conversations_tool"}), "formulation réelle"),
    Task("De quoi avons-nous parlé la semaine dernière au sujet du catalogue ?",
         frozenset({"search_past_conversations_tool", "memory_recall"}), ""),
    Task("Qu'est-ce que je t'ai dit sur mes préférences de rédaction ?",
         frozenset({"memory_recall", "search_past_conversations_tool",
                    "memory_view_profile", "knowledge_search"}), ""),
    Task("Mets les mails qui sont des promotions dans la corbeille.",
         frozenset({"gmail_search_emails", "gmail_list_emails", "gmail_trash_email",
                    "gmail_search_for_cleanup"}),
         "Telegram — action, on n'observe que le CHOIX"),
    Task("Calcule la distance de Levenshtein entre \"bonjour le monde\" et \"bonjour tout le monde\".",
         frozenset({"levenshtein_distance", "python_execute", "code_execute"}),
         "a déclenché la fabrique en prod"),
    Task("Quelles sont mes tâches planifiées en ce moment ?",
         frozenset({"scheduler_list_tasks", "tasks_list"}), ""),
    Task("Fais-moi un résumé de la page que j'ai ouverte dans mon navigateur.",
         frozenset({"browser_tab_read_text", "browser_list_tabs"}), ""),
    Task("Quel temps fera-t-il demain à Lyon ?",
         frozenset({"weather_get"}), ""),
    Task("Envoie un message WhatsApp à Gert pour lui dire que je m'en occupe.",
         frozenset({"whatsapp_send", "whatsapp_send_template"}),
         "formulation réelle — action, choix seulement"),
    Task("Cherche dans mes mails ceux qui viennent de Gert.",
         frozenset({"gmail_search_emails", "gmail_list_emails"}), ""),
    Task("Ajoute un rendez-vous demain à 14h avec Marc.",
         frozenset({"calendar_create_event", "calendar_check_availability"}),
         "action, choix seulement — vérifier la dispo d abord est défendable"),
    Task("Résume-moi les documents de mon dossier surveillé.",
         frozenset({"drive_list_files", "drive_search_files", "watchdog_list",
                    "knowledge_list"}), ""),
)


# ────────────────────────────────────────────────────────────────────────────
# Mesure
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class Turn:
    """Un tour mesuré, pour une tâche et une architecture."""
    architecture: str
    task: str
    chosen: list[str] = field(default_factory=list)
    correct: bool = False
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 1
    domain: str | None = None
    error: str | None = None


def _tool_schema_tokens(tools: list) -> int:
    """Poids en tokens des schémas — le poste que le superviseur devait alléger."""
    import json as _json
    try:
        import tiktoken
        from langchain_core.utils.function_calling import convert_to_openai_tool
        enc = tiktoken.get_encoding("cl100k_base")
        return sum(
            len(enc.encode(_json.dumps(convert_to_openai_tool(t), ensure_ascii=False)))
            for t in tools
        )
    except Exception:
        return 0


def _chosen_tools(response) -> list[str]:
    out = []
    for call in getattr(response, "tool_calls", None) or []:
        name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
        if name:
            out.append(name)
    return out


async def _one_call(llm, tools: list, prompt: str) -> tuple[list[str], float, dict]:
    """Un appel modèle outillé. Rend (outils choisis, latence ms, usage)."""
    from langchain_core.messages import HumanMessage

    bound = llm.bind_tools(tools) if tools else llm
    started = time.monotonic()
    response = await bound.ainvoke([HumanMessage(content=prompt)])
    elapsed = (time.monotonic() - started) * 1000
    return _chosen_tools(response), elapsed, (getattr(response, "usage_metadata", None) or {})


async def run_mono(task: Task, llm, tools_by_name: dict) -> Turn:
    from app.agent.toolset_profiles import _DEFAULT_TOOLS

    turn = Turn(architecture="mono", task=task.prompt)
    tools = [tools_by_name[n] for n in _DEFAULT_TOOLS if n in tools_by_name]
    try:
        chosen, ms, usage = await _one_call(llm, tools, task.prompt)
    except Exception as exc:  # noqa: BLE001
        turn.error = f"{type(exc).__name__}: {exc}"
        return turn
    turn.chosen = chosen
    turn.correct = bool(set(chosen) & task.expected)
    turn.latency_ms = ms
    turn.prompt_tokens = usage.get("input_tokens", 0) or _tool_schema_tokens(tools)
    turn.completion_tokens = usage.get("output_tokens", 0)
    return turn


async def run_sub_agents(task: Task, llm, router_llm, tools_by_name: dict) -> Turn:
    """Routage puis exécution — les DEUX appels sont comptés.

    Le surcoût structurel des sous-agents est cet aller-retour supplémentaire ;
    l'ignorer reviendrait à comparer une architecture à une demi-architecture.
    """
    from app.agent.sub_agents.config import ALL_AGENTS
    from langchain_core.messages import HumanMessage, SystemMessage

    turn = Turn(architecture="sub_agents", task=task.prompt, llm_calls=2)
    domains = sorted({c.domain for c in ALL_AGENTS})

    routing_prompt = (
        "Tu es un routeur. Choisis LE domaine le plus adapté à la demande, "
        f"parmi : {', '.join(domains)}. Réponds par le seul nom du domaine."
    )
    try:
        started = time.monotonic()
        routed = await router_llm.ainvoke([
            SystemMessage(content=routing_prompt),
            HumanMessage(content=task.prompt),
        ])
        router_ms = (time.monotonic() - started) * 1000
        raw = (getattr(routed, "content", "") or "").strip().lower()
        domain = next((d for d in domains if d in raw), "workspace")
        turn.domain = domain
        router_usage = getattr(routed, "usage_metadata", None) or {}

        cfg = next((c for c in ALL_AGENTS if c.domain == domain), None)
        names = cfg.resolve_tool_names() if cfg else set()
        tools = [tools_by_name[n] for n in sorted(names) if n in tools_by_name]

        chosen, agent_ms, usage = await _one_call(llm, tools, task.prompt)
    except Exception as exc:  # noqa: BLE001
        turn.error = f"{type(exc).__name__}: {exc}"
        return turn

    turn.chosen = chosen
    turn.correct = bool(set(chosen) & task.expected)
    turn.latency_ms = router_ms + agent_ms
    turn.prompt_tokens = (
        (router_usage.get("input_tokens", 0) or 0)
        + (usage.get("input_tokens", 0) or _tool_schema_tokens(tools))
    )
    turn.completion_tokens = (
        (router_usage.get("output_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)
    )
    return turn


# ────────────────────────────────────────────────────────────────────────────
# Restitution
# ────────────────────────────────────────────────────────────────────────────

def _pct(part: int, total: int) -> str:
    return f"{100.0 * part / total:.0f} %" if total else "n/a"


def _summarise(turns: list[Turn]) -> dict:
    ok = [t for t in turns if t.error is None]
    lat = sorted(t.latency_ms for t in ok)
    return {
        "n": len(turns),
        "erreurs": len(turns) - len(ok),
        "reussite_choix": sum(1 for t in ok if t.correct),
        "p50_ms": statistics.median(lat) if lat else 0.0,
        "p95_ms": (lat[int(len(lat) * 0.95)] if len(lat) > 1 else (lat[0] if lat else 0.0)),
        "prompt_tokens_moy": statistics.mean([t.prompt_tokens for t in ok]) if ok else 0,
        "appels_llm": sum(t.llm_calls for t in ok),
    }


def render(mono: list[Turn], subs: list[Turn]) -> str:
    m, s = _summarise(mono), _summarise(subs)
    lines = [
        "",
        "=" * 74,
        "BANC A/B — MONO-AGENT CONTRE SOUS-AGENTS",
        "=" * 74,
        f"{'Critère':<34}{'Mono-agent':>19}{'Sous-agents':>19}",
        "-" * 74,
        f"{'1. Latence p50':<34}{m['p50_ms']:>16.0f} ms{s['p50_ms']:>16.0f} ms",
        f"{'   Latence p95':<34}{m['p95_ms']:>16.0f} ms{s['p95_ms']:>16.0f} ms",
        f"{'2. Tokens de prompt (moy.)':<34}{m['prompt_tokens_moy']:>19,.0f}{s['prompt_tokens_moy']:>19,.0f}".replace(",", " "),
        f"{'   Appels LLM':<34}{m['appels_llm']:>19}{s['appels_llm']:>19}",
        f"{'4. Choix d outil correct':<34}"
        f"{_pct(m['reussite_choix'], m['n'] - m['erreurs']):>19}"
        f"{_pct(s['reussite_choix'], s['n'] - s['erreurs']):>19}",
        f"{'   Erreurs d appel':<34}{m['erreurs']:>19}{s['erreurs']:>19}",
        "-" * 74,
    ]
    if m["p50_ms"] and s["p50_ms"]:
        delta = s["p50_ms"] - m["p50_ms"]
        signe = "plus LENTS" if delta > 0 else "plus RAPIDES"
        lines.append(f"  Les sous-agents sont {abs(delta):.0f} ms {signe} au p50.")
    lines += [
        "",
        "  Le banc n'exécute AUCUN outil : il mesure le CHOIX, la latence et le",
        "  coût de prompt — les trois postes où les architectures divergent.",
        "  Il ne mesure donc pas la réussite d'une tâche multi-étapes.",
        "",
    ]
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Banc A/B des architectures d'agent")
    parser.add_argument("--tier", default="medium",
                        choices=["simple", "medium", "complex"],
                        help="tier LLM de l'agent (défaut: medium)")
    parser.add_argument("--router-tier", default="simple",
                        help="tier du routeur (défaut: simple — c'est son réglage réel)")
    parser.add_argument("--repeat", type=int, default=1,
                        help="répétitions par tâche (lisse la variance réseau)")
    parser.add_argument("--limit", type=int, default=0, help="n premières tâches")
    parser.add_argument("--json", default="", help="écrire les tours bruts ici")
    args = parser.parse_args(argv)

    from app.services.llm_provider import (
        ComplexityTier,
        get_llm_for_tier,
        load_llm_instances_from_db,
        load_llm_settings_from_db,
    )
    from app.skills.builtin import register_all

    # ATTENDRE la configuration des tiers. L'application la charge en tâche de
    # fond au démarrage ; un script qui ne l'attend pas mesure les DÉFAUTS
    # codés en dur (gemini-2.5-flash, qwen2.5:3b) — c'est-à-dire une chaîne
    # que personne n'utilise, et dont un modèle n'est même pas installé.
    await load_llm_settings_from_db()
    await load_llm_instances_from_db()

    register_all()
    from app.skills import get_skill_registry
    tools_by_name = {t.name: t for t in get_skill_registry().all_tools}
    print(f"Catalogue : {len(tools_by_name)} outils")

    llm = get_llm_for_tier(ComplexityTier(args.tier))
    router_llm = get_llm_for_tier(ComplexityTier(args.router_tier))

    tasks = TASKS[: args.limit] if args.limit else TASKS
    mono_turns: list[Turn] = []
    sub_turns: list[Turn] = []

    for rep in range(args.repeat):
        for i, task in enumerate(tasks, 1):
            print(f"  [{rep + 1}/{args.repeat}] {i:>2}/{len(tasks)} {task.prompt[:58]}…")
            mono_turns.append(await run_mono(task, llm, tools_by_name))
            sub_turns.append(await run_sub_agents(task, llm, router_llm, tools_by_name))

    print(render(mono_turns, sub_turns))

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"mono": [t.__dict__ for t in mono_turns],
             "sub_agents": [t.__dict__ for t in sub_turns]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Tours bruts → {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
