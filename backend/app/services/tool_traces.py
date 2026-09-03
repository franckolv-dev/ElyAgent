# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/tool_traces.py
# @brief      Ce qu'un outil a produit survit au tour.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""L'amnésie d'Ely sur ses propres actions — mesurée et refermée (29/07/2026).

Le constat
-----------
    messages en base par rôle : assistant 3649 · user 2993
    messages de rôle « tool » : 0   sur 6642

L'historique de conversation, lui, marchait très bien : 40 messages rechargés
à chaque tour, aucune troncature (fenêtres à 1 000 000 tokens pour un prompt
système de 3 734). Mais les ``ToolMessage`` ne vivaient que le temps du tour.

    msg 1  « convertis ce PDF »
           → l'outil rend /tmp/ely-docx/x.docx · 12 pages · 0 caractère perdu
           → Ely répond « c'est fait »
    msg 5  « dépose-le sur mon Drive »
           → elle ne voit QUE « c'est fait ». Le CHEMIN a disparu.

Elle n'oubliait pas Franck : elle oubliait **ce qu'elle avait fait**.

Ce qu'on garde, et ce qu'on jette
-----------------------------------
Le RÉSULTAT, pas le contenu transporté. ``pdf_read`` rend jusqu'à 15 000
caractères de texte de PDF : les recharger à chaque tour ferait grossir
l'historique sans fin, alors que ce qui compte tient en une ligne — l'outil
appelé, ses arguments utiles, et ce qu'il a produit.

⚠️ Deux pièges, vérifiés dans le code avant d'écrire ce module
---------------------------------------------------------------
1. **L'API des conversations ne filtre aucun rôle** et ``MessageBubble``
   affiche comme « assistant » tout ce qui n'est pas « user » : persister
   ``role="tool"`` sans filtrer ferait apparaître ces traces dans le chat.
2. **Un ``ToolMessage`` rechargé sans le ``AIMessage`` porteur de ses
   ``tool_calls`` fait REJETER la requête** par l'API du modèle. On ne les
   réinjecte donc jamais comme ``ToolMessage`` — on en fait un bloc de
   contexte lisible, étiqueté pour ce qu'il est.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from app.agent.helpers.message_content import content_to_text

logger = logging.getLogger(__name__)

# Une trace tient sur deux ou trois lignes : de quoi porter un chemin, un
# identifiant et deux mesures. Au-delà on recopierait le contenu transporté.
MAX_TRACE_CHARS: int = 400

# Combien de traces on réinjecte au tour suivant. Une conversation de 40
# messages peut porter des dizaines d'appels ; ce sont les DERNIERS qui portent
# le contexte utile — « dépose-LE sur Drive » parle du fichier de tout à
# l'heure, pas de celui d'il y a trois semaines.
#
# ⚠️ Le plafond compte des actions DISTINCTES, pas des lignes (cf. `_distinctes`).
MAX_RELOADED_TRACES: int = 8

# Combien de lignes on relit en base pour en tirer MAX_RELOADED_TRACES actions
# distinctes. Un tour qui boucle peut en écrire des dizaines d'identiques : lire
# exactement 8 lignes rendrait 8 fois la même. Mesuré le 01/08 — 54 copies d'une
# recherche ratée dans un seul tour, donc une marge de 8× n'a rien de théorique.
_RELOAD_WINDOW: int = MAX_RELOADED_TRACES * 8

# Le rôle sous lequel les traces sont persistées dans ``messages``.
TRACE_ROLE: str = "tool"

# Arguments qui ne doivent JAMAIS entrer dans une trace : elle est stockée en
# clair et relue à CHAQUE tour de la conversation. Y laisser un jeton Google,
# c'est le recopier dans le contexte envoyé au modèle à chaque message.
_SECRET_ARGS: frozenset[str] = frozenset({
    "user_google_credentials_json", "api_key", "token", "access_token",
    "refresh_token", "password", "secret", "credentials", "authorization",
})

# Ce qui mérite d'être gardé d'un retour d'outil : ce que l'utilisateur pourra
# désigner au tour suivant. Un chemin, une URL, un identifiant, un compte.
_USEFUL_LINE = re.compile(
    r"(/[\w./-]+\.\w{2,5}|https?://\S+|créé|creee?|déposé|depose|erreur|error|"
    r"⚠|échec|echec|introuvable|\b\d+\s*(page|paragraphe|caractère|caractere|"
    r"ligne|message|fichier|élément|element)s?\b)",
    re.IGNORECASE,
)


def _clean_args(args: dict[str, Any] | None) -> str:
    """Les arguments utiles, sans les secrets et sans les pavés."""
    if not args:
        return ""
    parts: list[str] = []
    for key, value in args.items():
        if key.lower() in _SECRET_ARGS:
            continue
        text = str(value)
        if len(text) > 80:
            text = text[:77] + "…"
        parts.append(f"{key}={text}")
    return ", ".join(parts)


def _essence(result: str) -> str:
    """Ce qu'il faut retenir d'un retour d'outil.

    On garde les lignes qui portent un chemin, une URL, une mesure ou une
    erreur — c'est ce que l'utilisateur désignera au tour suivant. Le reste est
    du contenu transporté, qui n'a pas à revenir dans chaque prompt.

    Si rien ne ressort, on garde le début : mieux vaut un extrait qu'un trou.
    """
    text = (result or "").strip()
    if not text:
        return "(aucun retour)"
    retenues = [ln.strip() for ln in text.splitlines()
                if ln.strip() and _USEFUL_LINE.search(ln)]
    garde = " · ".join(retenues) if retenues else " ".join(text.split())
    return garde


def build_trace(*, tool: str, args: dict[str, Any] | None, result: str) -> str:
    """Une ligne qui dit ce qui a été fait, et ce que ça a produit."""
    trace = f"{tool}({_clean_args(args)}) → {_essence(result)}"
    if len(trace) > MAX_TRACE_CHARS:
        trace = trace[:MAX_TRACE_CHARS - 1] + "…"
    return trace


def traces_from_messages(messages: list[BaseMessage]) -> list[str]:
    """Les traces des outils réellement exécutés dans ce tour.

    Le nom de l'outil et ses arguments vivent dans le ``AIMessage`` qui a
    demandé l'appel ; le résultat vit dans le ``ToolMessage`` qui suit. On les
    rapproche par ``tool_call_id`` — se fier à l'ordre casserait dès qu'un tour
    lance deux outils en parallèle.

    Ne lève jamais : une trace manquante n'est pas une raison de perdre un tour.
    """
    demandes: dict[str, tuple[str, dict]] = {}
    for m in messages:
        if isinstance(m, AIMessage):
            for call in (getattr(m, "tool_calls", None) or []):
                try:
                    demandes[str(call["id"])] = (
                        str(call.get("name") or "?"), dict(call.get("args") or {}),
                    )
                except Exception as exc:  # noqa: BLE001 — un appel illisible se saute
                    logger.debug("trace : appel d'outil illisible (%s)", exc)

    traces: list[str] = []
    for m in messages:
        if not isinstance(m, ToolMessage):
            continue
        tool, args = demandes.get(str(getattr(m, "tool_call_id", "")), ("?", {}))
        if tool == "?":
            # Sans le nom, la trace n'aide personne — on préfère rien.
            continue
        traces.append(build_trace(
            tool=tool, args=args, result=content_to_text(m.content),
        ))
    return traces


def _distinctes(traces: list[str]) -> list[str]:
    """Les traces, sans les répétitions, dans l'ordre où elles sont apparues.

    ⛔ Mesuré le 01/08 sur la base réelle : un tour a bouclé sur la même
    recherche infructueuse et écrit **54 traces identiques**. Le tour suivant
    en recharge huit — il en a reçu sept fois la même. La seule trace qui
    portait un résultat, ``drive_create_file(…) → Lien : https://drive…``,
    était tombée du budget. Ely a cherché le fichier au lieu de le connaître,
    a stagné, et le panel a fini par affirmer qu'elle ne savait pas écrire de
    fichier — seize minutes après l'avoir écrit (#319).

    👉 **Une répétition n'apporte aucune information et coûte une place à ce
    qui en apporte.** On garde la PREMIÈRE occurrence : c'est le moment où
    l'action a eu lieu, et une trace est un repère chronologique.
    """
    return list(dict.fromkeys(traces))


def context_from_traces(traces: list[str]) -> SystemMessage | None:
    """Les traces d'avant, rendues au modèle comme du CONTEXTE.

    ⚠️ Surtout pas comme des ``ToolMessage`` : sans le ``AIMessage`` porteur de
    leurs ``tool_calls``, les API des modèles rejettent la requête entière. Un
    ``SystemMessage`` étiqueté passe partout et se lit sans ambiguïté — sans
    étiquette, le modèle prendrait ces lignes pour une demande de l'utilisateur
    ou pour sa propre réponse.

    Returns:
        ``None`` s'il n'y a rien à dire — on n'ajoute pas un message vide que
        le modèle devrait relire à chaque tour.
    """
    utiles = _distinctes([t for t in traces if t and t.strip()])[-MAX_RELOADED_TRACES:]
    if not utiles:
        return None
    lignes = "\n".join(f"- {t}" for t in utiles)
    return SystemMessage(content=(
        "Actions déjà réalisées plus tôt dans cette conversation, avec leur "
        "résultat. Les chemins et identifiants ci-dessous sont réutilisables "
        "tels quels si l'utilisateur y fait référence :\n" + lignes
    ))


# ──────────────────────────────────────────────────────────────────────
# La persistance — même table que les messages, rôle distinct
# ──────────────────────────────────────────────────────────────────────
#
# Pourquoi `messages` plutôt qu'une table dédiée : la conversation est déjà
# indexée sur `conversation_id`, l'ordre chronologique est déjà là, et le
# nettoyage d'une conversation emporte ses traces sans code supplémentaire.
# Le rôle `tool` suffit à les distinguer — à condition de les filtrer partout
# où on affiche, ce que le pin de `conversations.py` verrouille.

from app.database import async_session  # noqa: E402


async def persist_traces(conversation_id, traces: list[str]) -> int:
    """Écrit les traces du tour. Ne lève JAMAIS.

    Une trace est un confort : si la base refuse l'écriture, l'utilisateur doit
    quand même recevoir sa réponse. On journalise et on continue.

    Returns:
        Le nombre de traces écrites (0 si rien à faire ou en cas d'échec).
    """
    utiles = _distinctes([t for t in traces if t and t.strip()])
    if not utiles:
        return 0
    try:
        from app.models.conversation import Message

        async with async_session() as db:
            for trace in utiles:
                db.add(Message(
                    conversation_id=conversation_id,
                    role=TRACE_ROLE,
                    content=trace,
                ))
            await db.commit()
        return len(utiles)
    except Exception as exc:  # noqa: BLE001 — jamais au prix du tour
        logger.warning("traces d'outils non enregistrées (%s)", exc)
        return 0


async def load_traces(conversation_id, limit: int = MAX_RELOADED_TRACES) -> list[str]:
    """Les dernières traces de CETTE conversation, dans l'ordre chronologique.

    Le filtre sur ``conversation_id`` est le cloisonnement : le chat de
    l'utilisateur et une tâche planifiée tournent en parallèle et ne doivent
    jamais mélanger leurs actions.

    ⚠️ On relit une FENÊTRE plus large que le plafond, puis on dédoublonne. Les
    conversations écrites avant ce lot portent déjà des dizaines de lignes
    identiques : lire exactement ``limit`` lignes rendrait ``limit`` fois la
    même. Dédoublonner à l'écriture ne suffit donc pas — il faut aussi réparer
    la relecture de ce qui est déjà en base.

    Ne lève jamais : sans traces, on retombe sur le comportement d'avant ce lot.
    """
    try:
        from sqlalchemy import select

        from app.models.conversation import Message

        async with async_session() as db:
            rows = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id,
                       Message.role == TRACE_ROLE)
                .order_by(Message.created_at.desc())
                .limit(max(limit, _RELOAD_WINDOW))
            )
            recentes = [m.content for m in reversed(rows.scalars().all())]
            return _distinctes(recentes)[-limit:]
    except Exception as exc:  # noqa: BLE001
        logger.warning("traces d'outils illisibles (%s)", exc)
        return []


__all__ = [
    "MAX_RELOADED_TRACES",
    "MAX_TRACE_CHARS",
    "TRACE_ROLE",
    "build_trace",
    "context_from_traces",
    "load_traces",
    "persist_traces",
    "traces_from_messages",
]
