# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/tool_output_spill.py
# @brief      Débordement des sorties d'outil vers fichier — une grande sortie
#             est conservée EN ENTIER et paginée, au lieu d'être tronquée.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Débordement des sorties d'outil volumineuses vers un fichier de travail.

⚠️ CE QUE ÇA CORRIGE (02/09/2026) : quand un outil rendait un texte trop
grand, il était TRONQUÉ et le reste PERDU. Une page lue par l'extension
Chrome est coupée à 8 000 caractères ; une sortie archivée dans une mission
à 5 000. Le modèle voyait le début, n'avait AUCUN moyen d'obtenir la suite,
relisait la même page — et repayait la même troncature.

Ici, au-delà d'un seuil, la sortie entière part dans un fichier et le modèle
reçoit un bloc de remplacement qui dit : la taille réelle, un aperçu du
début, l'identifiant du débordement, et la consigne de pager avec
``tool_output_read`` plutôt que de redemander la même donnée.

Sécurité
--------
- **Identité hors de portée du modèle** : le propriétaire d'un débordement
  n'est pas un argument d'outil (le modèle pourrait l'inventer) mais une
  ContextVar posée par la passerelle autour de l'exécution
  (``owner_scope``). Aucun ``InjectedToolArg user_id`` non plus : il aurait
  fallu l'inscrire dans ``agent/tool_sets.USER_ID_TOOLS``, et un oubli là-bas
  est une panne silencieuse (incident du 17/05, cf.
  ``tests/test_user_id_injection_completeness.py``).
- **Scoping par répertoire** : chaque utilisateur écrit dans un sous-répertoire
  dérivé du hachage de son identifiant. Un identifiant de débordement résolu
  pour un autre utilisateur ne désigne aucun fichier existant — l'isolation
  ne dépend pas d'un test d'égalité qu'on peut oublier d'écrire.
- **Chemin borné** : identifiant contraint à ``[A-Za-z0-9_-]{16,64}`` (ni
  séparateur, ni point, ni NUL), puis résolution canonique et vérification
  d'appartenance au répertoire du propriétaire — même discipline que
  ``agent/tools/file_tool._assert_path_allowed`` et
  ``routers/attachments._resolve_safe_path``.
- **Chemin absolu jamais rendu au modèle** : ``file_tool.analyze_file``
  autorise la lecture de tout ``/tmp``. Publier le chemin d'un débordement
  offrirait un contournement du scoping ci-dessus. Le modèle ne reçoit que
  l'identifiant, qui ne vaut que dans SON répertoire.
- **Ce module ne garantit PAS que le fichier est anonymisé.** La passerelle
  l'appelle après sa frontière PII, donc sur le chemin du chat le contenu
  écrit est déjà masqué — mais c'est une propriété de l'APPELANT, pas d'ici :
  un appelant qui pose ``anonymize_results=False``, ou dont ``pii_filter``
  est ``None``, écrit du texte brut. Le fichier est en 0600 dans un
  répertoire 0700 : c'est ÇA la garantie de ce module. Un commentaire qui
  affirmerait la garantie plus large est ce qui fait sauter un contrôle plus
  tard (02/09/2026).

Ménage
------
``purge_old`` retire les fichiers plus vieux que le TTL, dans l'esprit de
``services/journal_service.purge_expired`` : idempotent, best-effort, jamais
bloquant, retourne le nombre supprimé. Appelé au fil de l'eau à chaque
débordement (throttlé), sans tâche de fond à surveiller.

Réglages (variables d'environnement)
------------------------------------
- ``TOOL_OUTPUT_SPILL_CHARS``   — seuil de débordement (0 = désactivé).
- ``TOOL_OUTPUT_SPILL_TTL_HOURS`` — âge au-delà duquel un fichier est purgé.
- ``TOOL_OUTPUT_SPILL_DIR``     — répertoire racine (par défaut sous le
  tempdir SYSTÈME, comme les pièces jointes : "/tmp" en conteneur Linux,
  "/var/folders/…" sur macOS — un chemin en dur casserait hors Docker).
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

logger = logging.getLogger(__name__)


# Seuil par défaut. 12 000 caractères ≈ 3 000 tokens : au-delà, une seule
# sortie d'outil pèse plus qu'un tour de conversation complet, et elle est
# REPAYÉE à chaque tour suivant tant qu'elle reste dans l'historique (mesure
# du 01/08 : 0,88 % des tours consommaient 52,5 % des tokens). En dessous,
# déborder coûterait plus cher que garder — un aller-retour d'outil
# supplémentaire pour économiser quelques centaines de tokens est perdant.
_DEFAULT_THRESHOLD_CHARS = 12_000

# Aperçu rendu dans le bloc de remplacement : assez pour que le modèle juge
# si la suite l'intéresse, assez peu pour que le bloc reste petit.
_PREVIEW_CHARS = 1_500

# 24 h, comme la durée de vie des URL signées de pièces jointes : personne ne
# revient sur une sortie d'outil le lendemain, et une conversation reprise
# après ce délai a de toute façon perdu son historique d'outils.
_DEFAULT_TTL_HOURS = 24

# ⚠️ CE QUE ÇA CORRIGE (02/09/2026) : la borne était une CONSTANTE à 20 000,
# au-dessus du seuil de débordement (12 000). La réponse de `tool_output_read`
# repassait donc par la passerelle, redébordait, et rendait un NOUVEL
# identifiant pointant sur une tranche de l'ancien — plus un fichier de plus
# sur disque, qui redéborderait à son tour. Un modèle qui suivait le maximum
# documenté ne s'arrêtait jamais.
#
# Choix : BORNER la tranche sous le seuil, plutôt qu'exempter
# `tool_output_read` du débordement. Exempter ferait entrer 20 000 caractères
# (~5 000 tokens) d'un coup dans le contexte et les ferait REPAYER à chaque
# tour suivant — précisément ce que le débordement existe pour éviter (mesure
# du 01/08 : 0,88 % des tours = 52,5 % des tokens). La borne rend la boucle
# terminante ET garde la propriété qu'on voulait.
#
# Évaluée à l'APPEL, jamais figée : le seuil est réglable par
# TOOL_OUTPUT_SPILL_CHARS, et une borne calculée à l'import repasserait
# au-dessus du seuil dès qu'on l'abaisse.
_SLICE_HEADROOM_CHARS = 500   # entête + pied de tranche, avec de la marge
_HARD_MAX_SLICE_CHARS = 20_000
_DEFAULT_SLICE_CHARS = 4_000

# Ni séparateur de chemin, ni point, ni NUL : la traversée est impossible
# avant même la résolution canonique.
_ID_RE = re.compile(r"\A[A-Za-z0-9_-]{16,64}\Z")

# Le débordement écrit rarement ; inutile de balayer le répertoire à chaque
# fois.
_PURGE_EVERY_S = 300.0
_last_purge = 0.0


# ── Propriétaire courant (posé par la passerelle) ────────────────────────────

_OWNER: ContextVar[str] = ContextVar("tool_output_spill_owner", default="")


@contextmanager
def owner_scope(user_id: str):
    """Déclare à qui appartiennent les débordements lus/écrits dans ce scope.

    Posé par ``tool_gateway`` autour de l'exécution d'un outil : le modèle ne
    voit jamais cette valeur et ne peut donc pas la falsifier.
    """
    token = _OWNER.set(str(user_id or ""))
    try:
        yield
    finally:
        _OWNER.reset(token)


def current_owner() -> str:
    """Utilisateur au nom duquel l'outil courant s'exécute (vide hors scope)."""
    return _OWNER.get()


# ── Réglages ─────────────────────────────────────────────────────────────────

def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r n'est pas un entier — repli sur %d", name, raw, default)
        return default


def spill_threshold_chars() -> int:
    """Taille au-delà de laquelle une sortie déborde (0 = jamais)."""
    return max(0, _env_int("TOOL_OUTPUT_SPILL_CHARS", _DEFAULT_THRESHOLD_CHARS))


def max_slice_chars() -> int:
    """Plus grande tranche qu'on peut servir sans qu'elle redéborde.

    Débordement désactivé (seuil 0) ⇒ pas de boucle possible, on garde le
    plafond historique.
    """
    seuil = spill_threshold_chars()
    if seuil <= 0:
        return _HARD_MAX_SLICE_CHARS
    return max(1, min(_HARD_MAX_SLICE_CHARS, seuil - _SLICE_HEADROOM_CHARS))


def spill_ttl_seconds() -> float:
    return max(1, _env_int("TOOL_OUTPUT_SPILL_TTL_HOURS", _DEFAULT_TTL_HOURS)) * 3600.0


def spill_root() -> Path:
    raw = os.getenv("TOOL_OUTPUT_SPILL_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path(tempfile.gettempdir()) / "ely-tool-spill"


# ── Chemins ──────────────────────────────────────────────────────────────────

def _owner_dir(user_id: str) -> Path:
    """Répertoire d'un utilisateur — haché, pour ne pas écrire un identifiant
    de compte en clair dans un répertoire temporaire lisible par la machine."""
    digest = hashlib.sha256(f"ely-tool-spill:{user_id or ''}".encode()).hexdigest()[:32]
    return spill_root() / digest


def _resolve(spill_id: str, user_id: str) -> Path:
    """Chemin canonique du débordement ``spill_id`` POUR ``user_id``.

    Lève ``PermissionError`` si l'identifiant n'a pas la forme attendue ou si
    le chemin résolu sort du répertoire du propriétaire (lien symbolique).
    """
    if not _ID_RE.match(spill_id or ""):
        raise PermissionError(f"Identifiant de débordement invalide : {spill_id!r}")
    base = _owner_dir(user_id).resolve(strict=False)
    target = (base / f"{spill_id}.txt").resolve(strict=False)
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise PermissionError(f"Identifiant de débordement invalide : {spill_id!r}") from exc
    return target


# ── Écriture ─────────────────────────────────────────────────────────────────

def write_spill(text: str, *, user_id: str, tool_name: str) -> tuple[str, Path]:
    """Écrit ``text`` en entier et retourne ``(spill_id, chemin)``.

    L'identifiant est un jeton aléatoire : non devinable, donc inutilisable
    par un tiers même s'il connaissait le répertoire.
    """
    directory = _owner_dir(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:  # pragma: no cover — systèmes de fichiers sans permissions
        pass
    spill_id = secrets.token_urlsafe(24)
    path = directory / f"{spill_id}.txt"
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover
        pass
    logger.info(
        "[tool_output_spill] %s: %d caractères conservés (%s)",
        tool_name, len(text), spill_id,
    )
    return spill_id, path


def _notice(spill_id: str, total: int, preview: str, tool_name: str) -> str:
    """Bloc rendu au modèle à la place de la sortie."""
    return (
        f"[sortie volumineuse — {total} caractères au total. Rien n'est perdu : "
        f"la sortie complète de « {tool_name} » est conservée dans un fichier de "
        f"travail, seul l'aperçu ci-dessous est dans le contexte.]\n\n"
        f"--- aperçu ({len(preview)} premiers caractères) ---\n"
        f"{preview}\n"
        f"--- fin de l'aperçu ---\n\n"
        f"[Pour lire la suite : appelle `tool_output_read` avec "
        f'spill_id="{spill_id}", offset={len(preview)}, length={_DEFAULT_SLICE_CHARS}, '
        f"puis avance l'offset de tranche en tranche jusqu'à ce que tu aies ce "
        f"qu'il te faut. NE rappelle PAS « {tool_name} » avec les mêmes arguments : "
        f"la réponse serait identique et coûterait le même prix.]"
    )


def spill_if_large(
    text: str,
    *,
    user_id: str,
    tool_name: str,
    threshold: int | None = None,
) -> str:
    """Retourne ``text`` tel quel, ou le bloc de remplacement s'il déborde.

    Ne lève jamais : un débordement impossible (disque plein, répertoire non
    inscriptible) rend la sortie brute — dégradé, jamais cassé.
    """
    limit = spill_threshold_chars() if threshold is None else threshold
    if limit <= 0 or not text or len(text) <= limit:
        return text
    try:
        spill_id, _path = write_spill(text, user_id=user_id, tool_name=tool_name)
    except OSError as exc:  # pragma: no cover — best-effort
        logger.warning("débordement impossible (%s) — sortie rendue telle quelle", exc)
        return text
    purge_old()
    return _notice(spill_id, len(text), text[:_PREVIEW_CHARS], tool_name)


# ── Lecture ──────────────────────────────────────────────────────────────────

def read_slice(
    spill_id: str,
    offset: int = 0,
    length: int = _DEFAULT_SLICE_CHARS,
    *,
    user_id: str | None = None,
) -> str:
    """Rend la tranche ``[offset, offset+length)`` d'un débordement.

    ``user_id`` par défaut = le propriétaire du scope courant. Lève
    ``PermissionError`` (identifiant malformé) ou ``FileNotFoundError``
    (débordement inconnu POUR CET utilisateur, ou purgé).
    """
    owner = current_owner() if user_id is None else user_id
    path = _resolve(spill_id, owner)
    if not path.is_file():
        raise FileNotFoundError(
            f"Débordement introuvable : {spill_id} (expiré, purgé, ou appartenant "
            "à quelqu'un d'autre)."
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    start = max(0, int(offset))
    span = min(max(1, int(length)), max_slice_chars())
    chunk = text[start:start + span]
    reste = max(0, len(text) - (start + len(chunk)))
    entete = (
        f"[débordement {spill_id} — caractères {start}-{start + len(chunk)} "
        f"sur {len(text)}]\n"
    )
    if reste:
        pied = (
            f"\n\n[il reste {reste} caractères : rappelle `tool_output_read` avec "
            f"offset={start + len(chunk)}.]"
        )
    else:
        pied = "\n\n[fin du débordement — tout a été lu.]"
    return entete + chunk + pied


# ── Ménage ───────────────────────────────────────────────────────────────────

def purge_old(max_age_s: float | None = None, *, force: bool = False) -> int:
    """Supprime les débordements plus vieux que le TTL. Retourne le compte.

    Idempotent et best-effort — un ménage qui échoue ne doit jamais faire
    échouer l'appel d'outil qui l'a déclenché. Throttlé : hors ``force``, un
    balayage au plus toutes les 5 minutes.
    """
    global _last_purge
    now = time.time()
    if not force and (now - _last_purge) < _PURGE_EVERY_S:
        return 0
    _last_purge = now
    ttl = spill_ttl_seconds() if max_age_s is None else float(max_age_s)
    root = spill_root()
    if not root.is_dir():
        return 0
    removed = 0
    try:
        candidats = list(root.glob("*/*.txt"))
    except OSError as exc:  # pragma: no cover — best-effort
        logger.debug("purge des débordements: balayage impossible (%s)", exc)
        return 0
    for path in candidats:
        try:
            if (now - path.stat().st_mtime) > ttl:
                path.unlink()
                removed += 1
        except OSError:  # pragma: no cover — course avec un autre purgeur
            continue
    if removed:
        logger.info("débordements: %d fichier(s) expiré(s) purgé(s)", removed)
    return removed
