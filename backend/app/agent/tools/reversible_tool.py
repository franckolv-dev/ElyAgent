# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/reversible_tool.py
# @brief      Outils d'annulation — « annule ce que tu viens de faire ».
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Surfaces model-facing du Reversible Action Journal (substrat / J2).

Permettent à l'agent d'annuler une action mutante précédente sur demande de
l'utilisateur (« annule ça », « remets le fichier que tu as supprimé »). Les
outils délèguent au ``journal_service`` (fail-closed, par utilisateur). Quand le
journal est désactivé (flag OFF) ou vide, ils répondent simplement qu'il n'y a
rien à annuler.
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services import journal_service


async def _resolve_id(user_id: str, partial: str) -> str | None:
    """Retrouve l'id complet d'une action annulable depuis un id (même partiel).

    Ne cherche que parmi les actions encore annulables de l'utilisateur, donc
    un id qui ne matche pas = déjà annulé / expiré / inexistant / autre user."""
    partial = (partial or "").strip()
    if not partial:
        return None
    for it in await journal_service.list_reversible(user_id, limit=50):
        if it["id"] == partial or it["id"].startswith(partial):
            return it["id"]
    return None


def _fmt_undo(res: dict) -> str:
    if res.get("ok"):
        cap = res.get("capability_id", "")
        suffix = f" ({cap})" if cap else ""
        if res.get("verified") is False:
            return (f"Action annulée{suffix}, mais je n'ai pas pu confirmer le "
                    f"résultat côté service — vérifie manuellement par précaution.")
        return f"Action annulée ✅{suffix}."
    reason = (res.get("reason") or "").split(":")[0]
    return {
        "not_found": "Action introuvable (déjà annulée, expirée, ou inconnue).",
        "forbidden": "Action introuvable (déjà annulée, expirée, ou inconnue).",
        "not_revertible": "Cette action a déjà été annulée ou n'est plus annulable.",
        "expired": "Trop tard : la fenêtre d'annulation est dépassée.",
        "unknown_compensation": "Cette action n'est pas annulable automatiquement.",
        "revert_failed": "L'annulation a échoué (réessaie, ou vérifie l'accès au service concerné).",
    }.get(reason, f"Annulation impossible ({reason or 'raison inconnue'}).")


@tool
async def list_revertible_actions(
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Liste les actions récentes que tu peux ANNULER (ex. un fichier Drive
    supprimé). À utiliser avant `revert_action` pour retrouver l'identifiant."""
    items = await journal_service.list_reversible(user_id)
    if not items:
        return "Aucune action annulable récente."
    lines = [
        f"• [{it['id'][:8]}] {it['capability_id']} — annulable jusqu'au {it['expires_at'][:10]}"
        for it in items
    ]
    return f"{len(items)} action(s) annulable(s) :\n" + "\n".join(lines)


@tool
async def revert_action(
    record_id: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Annule une action précédente par son identifiant (cf. `list_revertible_actions`).

    Ex. ressort de la corbeille un fichier Drive que tu avais supprimé.
    L'identifiant peut être partiel (les 8 premiers caractères suffisent).

    Args:
        record_id: identifiant de l'action à annuler
    """
    rid = await _resolve_id(user_id, record_id)
    if rid is None:
        return "Action introuvable (déjà annulée, expirée, ou inconnue)."
    return _fmt_undo(await journal_service.undo(rid, user_id))


@tool
async def undo_last_action(
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Annule la DERNIÈRE action annulable (« annule ce que tu viens de faire »).

    Raccourci de `list_revertible_actions` + `revert_action` sur la plus récente."""
    items = await journal_service.list_reversible(user_id, limit=1)
    if not items:
        return "Aucune action récente à annuler."
    return _fmt_undo(await journal_service.undo(items[0]["id"], user_id))
