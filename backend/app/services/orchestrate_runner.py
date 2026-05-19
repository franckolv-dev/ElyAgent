# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/orchestrate_runner.py
# @brief      Programmatic Tool Calling — façade publique du sandbox orchestrate.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    0.1.0-skeleton
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""Programmatic Tool Calling — Sprint 2.7 (``orchestrate``).

Le LLM principal émet **un seul tool call** ``orchestrate(code=...)`` dont
le contenu est un script Python qui chaîne N appels d'outils en local.
Le script tourne dans un sandbox isolé (subprocess), parle au parent via
un RPC sur Unix Domain Socket, et seul son ``stdout`` final remonte au
contexte du LLM. Économies tokens attendues : 70-95% sur les workflows
multi-tools.

Pattern d'inspiration : Hermes Agent ``tools/code_execution_tool.py``
(Nous Research, MIT). Design note de référence dans le repo local :
``docs/external-references/hermes-zero-context-cost-turns.md``.
Implémentation : code maison, adapté à l'archi ELY (HITL, anonymisation,
multi-tier, Docker).

Décisions consolidées (19 mai 2026 — validées Franck)
=====================================================

§4.5 — Isolation du child Python
--------------------------------
Choix : **subprocess + PYTHONPATH whitelist**, *pas* Docker-in-Docker.

- ``subprocess.Popen`` lance le script dans le même container Docker que
  le backend.
- ``PYTHONPATH`` du child = ``{tmpdir}`` uniquement (où vivent
  ``script.py`` et ``ely_tools.py``). Le path ``backend/`` n'est jamais
  exposé — donc le script LLM ne peut PAS faire
  ``from app.services.vault_service import VAULT_KEY``.
- ``env`` du child filtré par préfixe : on ne laisse passer que
  ``PATH``, ``HOME``, ``USER``, ``LANG``, ``LC_*``, ``TERM``, ``TMPDIR``,
  ``SHELL``, ``LOGNAME``, ``XDG_*``, ``PYTHONDONTWRITEBYTECODE``, ``TZ``,
  ``ELY_RPC_SOCKET``. Toute var contenant ``KEY``, ``TOKEN``, ``SECRET``,
  ``PASSWORD``, ``CREDENTIAL``, ``PASSWD``, ``AUTH`` est bloquée même si
  son préfixe est whitelisté.
- ``HOME`` réécrit vers ``{tmpdir}/home/`` pour ne pas exposer le vrai
  ``~`` du process backend.
- ``os.setsid`` pour isoler le process group → kill propre si timeout.

Trade-off accepté : la sécurité repose sur le rigueur du scrubbing. Tout
ajout d'une nouvelle classe de secret au backend doit penser au sandbox
(d'où le fuzz testing au jalon 4).

§4.4 — Adapter completion_guard
-------------------------------
Choix : **le RPC server logge les tools dispatchés + union dans le guard**.

- À chaque dispatch RPC, le serveur ajoute le nom du tool à un set
  ``tools_dispatched_via_sandbox`` exposé via la méthode
  ``OrchestrateRunner.last_run_tools_dispatched()``.
- Le retour du tool ``orchestrate`` au LLM inclut, *en plus du stdout du
  script*, un champ structuré indiquant la liste des tools réellement
  appelés. Le nœud agent récupère cette liste et la fournit à
  ``completion_guard.detect_unbacked_completion_claim`` comme nouvelle
  source ``tools_called_via_sandbox``. Le guard fait l'union avec les
  tools appelés directement (hors sandbox) — pas de bypass, pas de
  faux positif sur les scripts read-only.
- Avantage vs « bypass guard quand orchestrate est appelé » : on garde
  la protection anti-hallu même si un script ment dans son print final
  (« j'ai supprimé ») sans qu'aucun tool destructif n'ait été
  effectivement appelé.

Allow-list V1 (15 tools read-only)
==================================
Voir ``SANDBOX_ALLOWED_TOOLS_V1`` plus bas. Aucun tool destructif n'est
exposé au sandbox en V1 (cf. design note §4.1 — option A). Toute action
qui modifie l'état (gmail_trash_*, drive_delete_file, gmail_send_*,
notes_create, …) doit revenir au LLM principal qui passera par le flow
HITL standard.

Status : SKELETON
=================
Ce module est le squelette du Jalon 1. Les méthodes lèvent
``NotImplementedError`` pour l'instant. La logique sera ajoutée par les
jalons 2 (RPC), 3 (stubs), 4 (subprocess), 5 (wiring), 6 (anonymisation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────
# Allow-list V1 — 15 tools read-only
# ──────────────────────────────────────────────────────────────────────
#
# Cette frozenset est la **source de vérité** pour ce que le sandbox peut
# appeler. Le stub generator (jalon 3) lit cette liste pour produire
# ``ely_tools.py``. Le RPC server (jalon 2) la lit pour rejeter tout
# appel hors-liste avec une erreur explicite.
#
# Critères de sélection V1 :
#   - read-only (aucun side-effect persistant côté user)
#   - bien testé en prod (utilisé dans le scénario screencast ou
#     manuellement par Franck depuis ≥ 1 semaine)
#   - signature simple (pas de InjectedToolArg autre que user_id)
#
# Tools intentionnellement exclus en V1 (à ajouter en V2 après usage) :
#   - gmail_trash_*, drive_delete_*, gmail_send_*  → destructifs
#   - notes_create / notes_update / notes_delete   → écriture
#   - memory_archive / save_user_preference        → écriture mémoire
#   - browser_click / browser_fill                 → side-effect web
SANDBOX_ALLOWED_TOOLS_V1: frozenset[str] = frozenset({
    # Gmail (read)
    "gmail_list_emails",
    "gmail_read_email",
    "gmail_search_for_cleanup",
    # Calendar (read)
    "calendar_list_events",
    # Drive (read)
    "drive_list_files",
    "drive_read_file",
    # Web (read — search only, no fetch in V1 to stay strictly read-only.
    # ``browser_get_text`` is excluded because it requires a prior
    # ``browser_navigate`` that mutates the user's Playwright session.)
    "web_search",
    # System read-only diagnostics — useful for audits inside scripts.
    "system_list_scheduled_tasks",
    # Knowledge / mémoire (read)
    "knowledge_search",
    "knowledge_list",
    "memory_search",
    "memory_recent",
    "search_past_conversations_tool",
    # GitHub (read)
    "github_repo_stats",
    "github_traffic_stats",
})


# ──────────────────────────────────────────────────────────────────────
# Limites de ressources (configurables plus tard via app.config)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OrchestrateLimits:
    """Limites de ressources appliquées au sandbox.

    Les valeurs par défaut suivent celles de Hermes (validées sur des
    workflows réels), légèrement plus conservatives sur ``stdout`` pour
    rester compatible avec nos contraintes de fenêtre LLM tier C.
    """

    timeout_seconds: int = 300
    max_tool_calls: int = 50
    max_stdout_bytes: int = 50_000
    max_stderr_bytes: int = 10_000
    # head/tail split de la troncature stdout : 40% début, 60% fin —
    # garantit que la conclusion du script (généralement la dernière
    # ligne) arrive toujours au LLM.
    stdout_head_ratio: float = 0.4


# ──────────────────────────────────────────────────────────────────────
# Résultat d'un run sandbox
# ──────────────────────────────────────────────────────────────────────


@dataclass
class OrchestrateResult:
    """Résultat structuré d'un run ``orchestrate``.

    Le champ ``tools_dispatched`` est consommé par le wiring
    ``completion_guard`` (§4.4 — décision actée). Le LLM principal ne
    voit que ``stdout`` (re-formaté), pas la mécanique RPC.
    """

    stdout: str
    stderr: str
    exit_code: int
    duration_seconds: float
    # Liste ordonnée des tools réellement appelés via RPC pendant le run.
    # Utilisé par le completion_guard (§4.4) pour la détection d'unbacked
    # completion claims.
    tools_dispatched: list[str] = field(default_factory=list)
    # True si timeout ou OOM — le LLM doit le savoir pour ne pas mentir.
    truncated: bool = False
    truncation_reason: str = ""


# ──────────────────────────────────────────────────────────────────────
# Façade publique
# ──────────────────────────────────────────────────────────────────────


class OrchestrateRunner:
    """Façade publique du sandbox orchestrate.

    Usage typique (depuis ``orchestrate_tool.py``) :

        runner = OrchestrateRunner(user_id=user_id, limits=OrchestrateLimits())
        result = await runner.run(code=llm_generated_python)
        return result.stdout, result.tools_dispatched

    Cycle de vie d'un run :
        1. Création d'un ``tmpdir`` éphémère.
        2. Génération de ``ely_tools.py`` (stub) via ``orchestrate_stubs``.
        3. Écriture du script LLM dans ``{tmpdir}/script.py``.
        4. Démarrage du RPC server UDS (``orchestrate_rpc``).
        5. ``subprocess.Popen`` du script avec env scrubbée + PYTHONPATH
           = tmpdir uniquement.
        6. Attente de la fin (timeout 300s) ou kill.
        7. Lecture stdout / stderr + récupération de la liste des tools
           dispatchés.
        8. Cleanup du tmpdir et du socket UDS.
    """

    def __init__(
        self,
        *,
        user_id: str,
        limits: OrchestrateLimits | None = None,
    ) -> None:
        if not user_id:
            raise ValueError("OrchestrateRunner requires a non-empty user_id")
        self.user_id = user_id
        self.limits = limits or OrchestrateLimits()
        self._tmpdir: Path | None = None
        self._tools_dispatched: list[str] = []

    async def run(self, code: str) -> OrchestrateResult:
        """Exécute ``code`` dans le sandbox et retourne le résultat.

        Args:
            code: script Python complet, fourni par le LLM principal.
                Doit utiliser uniquement les noms de fonctions du module
                ``ely_tools`` (stub auto-généré depuis
                ``SANDBOX_ALLOWED_TOOLS_V1``).

        Returns:
            ``OrchestrateResult`` avec stdout, stderr, exit_code,
            durée, et la liste des tools effectivement dispatchés.

        Raises:
            ValueError: si ``code`` est vide.
            NotImplementedError: tant que les jalons 2-4 ne sont pas
                terminés.
        """
        if not code or not code.strip():
            raise ValueError("orchestrate.run() requires non-empty code")
        # TODO Jalon 2 : démarrer le RPC server UDS.
        # TODO Jalon 3 : générer ely_tools.py.
        # TODO Jalon 4 : Popen avec env scrubbée + PYTHONPATH whitelist.
        # TODO Jalon 4 : timeout + truncation head+tail stdout.
        raise NotImplementedError(
            "OrchestrateRunner.run() is a skeleton — Jalons 2-4 pending"
        )

    def last_run_tools_dispatched(self) -> list[str]:
        """Liste des tools dispatchés pendant le dernier ``run()``.

        Utilisé par le wiring ``completion_guard`` (§4.4) côté nœud
        agent : le retour vers ``detect_unbacked_completion_claim`` se
        fait via cette source supplémentaire.
        """
        return list(self._tools_dispatched)


__all__ = [
    "SANDBOX_ALLOWED_TOOLS_V1",
    "OrchestrateLimits",
    "OrchestrateResult",
    "OrchestrateRunner",
]
