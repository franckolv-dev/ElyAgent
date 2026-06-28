# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_stdio_launcher.py
# @brief      Client MCP v2 — J5 : launcher de confinement d'un serveur stdio.
# @license    Elastic License 2.0
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Launcher de confinement d'un serveur MCP stdio (J5).

Le SDK MCP (``StdioServerParameters``) n'expose que ``command/args/env/cwd`` —
aucun ``preexec_fn`` ni ``start_new_session``. Pour borner les ressources et
garantir le kill de l'arbre de processus, on **préfixe** la commande réelle par
ce launcher : le backend lance ``python -S mcp_stdio_launcher.py … -- CMD ARGS``,
le launcher s'installe en chef de groupe (``setsid``), pose ses limites, écrit
son PGID dans un fichier sentinelle (lu par ``_StdioConnection.close()`` pour le
kill-arbre), puis ``execvp`` la commande réelle — qui **remplace** le launcher
(même PID, donc le contrat stdio que pilote le SDK est préservé) en héritant des
rlimits et du nouveau groupe.

Module **autonome** : il s'exécute dans l'enfant AVANT ``execvp`` et ne doit
importer aucun symbole ``app.*`` (l'interpréteur tourne avec ``-S``). Seule la
fabrique ``build_launcher_argv`` est importée côté backend (sans effet de bord).

Limites appliquées (per-process, sûres) : ``RLIMIT_AS`` (mémoire virtuelle,
best-effort — inactif sur macOS), ``RLIMIT_NOFILE`` (descripteurs),
``RLIMIT_FSIZE`` (taille de fichier écrit). Volontairement EXCLUS :
``RLIMIT_CPU`` (un serveur persistant l'accumulerait et se ferait tuer) et
``RLIMIT_NPROC`` (compteur par-UID partagé avec le backend → casserait les forks
légitimes). Le confinement réseau/user/mounts n'est PAS du ressort de ce
launcher (nécessite des namespaces / un conteneur sidecar — backlog).
"""
from __future__ import annotations

import os
import sys


def build_launcher_argv(real_executable: str, real_args: list[str], *,
                        profile: dict, pgid_file: str) -> tuple[str, list[str]]:
    """Construit ``(executable, args)`` pour lancer la commande réelle confinée.

    ``executable`` = l'interpréteur Python courant ; ``args`` = ``-S`` + ce
    module + les options de profil + ``--`` + la commande réelle. À passer tel
    quel à ``StdioServerParameters(command=executable, args=args, …)``."""
    launcher = os.path.abspath(__file__)
    args: list[str] = ["-S", launcher]
    mem = int(profile.get("mem_bytes") or 0)
    nofile = int(profile.get("nofile") or 0)
    fsize = int(profile.get("fsize_bytes") or 0)
    if mem > 0:
        args += ["--mem-bytes", str(mem)]
    if nofile > 0:
        args += ["--nofile", str(nofile)]
    if fsize > 0:
        args += ["--fsize", str(fsize)]
    if pgid_file:
        args += ["--pgid-file", pgid_file]
    args += ["--", real_executable, *real_args]
    return sys.executable, args


def _set_rlimit(which_name: str, value: int) -> None:
    """Pose une rlimit best-effort (ignore OSError/ValueError, ex. macOS AS)."""
    import resource

    which = getattr(resource, which_name, None)
    if which is None:
        return
    try:
        resource.setrlimit(which, (value, value))
    except (OSError, ValueError):
        # macOS refuse RLIMIT_AS ; valeur > hard limit, etc. → best-effort.
        pass


def _parse(argv: list[str]) -> tuple[dict, list[str]]:
    """Parse manuel (sans argparse, plus léger sous -S) : options puis -- CMD."""
    opts: dict[str, str] = {}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            return opts, argv[i + 1:]
        if tok.startswith("--"):
            opts[tok[2:]] = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
            continue
        i += 1
    return opts, []


def main(argv: list[str]) -> int:
    opts, cmd = _parse(argv)
    if not cmd:
        sys.stderr.write("mcp-stdio-launcher: aucune commande à exécuter\n")
        return 2

    # 1. Nouveau groupe/session → kill-arbre fiable depuis le backend.
    try:
        os.setsid()
    except OSError as exc:
        # Déjà chef de groupe (rare) → on reste dans le groupe parent. Le close()
        # backend ne tuera alors PAS ce groupe (garde pgid == getpgrp du backend),
        # ce qui évite tout auto-dommage au prix d'un kill-arbre best-effort.
        sys.stderr.write(f"mcp-stdio-launcher: setsid a échoué ({exc})\n")

    # 2. Écrire le PGID réel (== notre PID après un setsid réussi ; sinon le
    #    groupe courant) pour le kill-arbre côté backend. getpgrp() est correct
    #    dans les deux cas, contrairement à getpid().
    pgid_file = opts.get("pgid-file")
    if pgid_file:
        try:
            with open(pgid_file, "w") as fh:
                fh.write(str(os.getpgrp()))
        except OSError:
            pass  # best-effort : sans sentinelle, close() retombe en legacy

    # 3. Limites de ressources (per-process, sûres). cwd est géré par le SDK.
    if opts.get("mem-bytes"):
        _set_rlimit("RLIMIT_AS", int(opts["mem-bytes"]))
    if opts.get("nofile"):
        _set_rlimit("RLIMIT_NOFILE", int(opts["nofile"]))
    if opts.get("fsize"):
        _set_rlimit("RLIMIT_FSIZE", int(opts["fsize"]))

    # 4. Remplacement par la commande réelle (hérite rlimits + groupe).
    try:
        os.execvp(cmd[0], cmd)
    except OSError as exc:
        sys.stderr.write(f"mcp-stdio-launcher: exec « {cmd[0]} » a échoué : {exc}\n")
        return 127
    return 0  # inatteignable si execvp réussit


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
