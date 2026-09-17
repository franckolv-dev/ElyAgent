"""Evidence and recovery instructions shared by chat and autonomous missions.

Recovery is a new, accountable attempt through the existing tool gateway. It
never replays a write automatically or interprets a provider error as consent.
"""
from __future__ import annotations

import hashlib
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.helpers.message_content import content_to_text
from app.agent.tool_failure import dit_un_echec

RETRY_MARKER = "[Vérification"


def current_turn(messages: list) -> list:
    """Keep the last user request and its attempts, excluding previous turns."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, HumanMessage) and not content_to_text(
            message.content
        ).lstrip().startswith(RETRY_MARKER):
            return messages[index:]
    return messages


def successful_evidence(messages: list) -> list[str]:
    """Stable fingerprints of successful, distinct calls (no raw data in state).

    Different call ids or repeated retrievals cannot masquerade as progress.
    Actual compliance remains the judge's decision; this only grants a bounded
    chance to use newly acquired evidence before abandoning a complex task.
    """
    calls: dict[str, dict] = {}
    evidence: set[str] = set()
    for message in current_turn(messages):
        if isinstance(message, AIMessage):
            calls.update({call["id"]: call for call in message.tool_calls})
        elif isinstance(message, ToolMessage):
            call = calls.get(message.tool_call_id)
            if not call or message.status == "error" or dit_un_echec(message.content):
                continue
            if not content_to_text(message.content).strip():
                continue
            if call["name"] in {"report_missing_capability", "session_todo", "ask_user"}:
                continue
            payload = json.dumps(
                [call["name"], call.get("args", {})], sort_keys=True,
                ensure_ascii=False, default=str,
            )
            evidence.add(hashlib.sha256(payload.encode()).hexdigest())
    return sorted(evidence)


MESSAGE_COMPTE_GOOGLE_DECONNECTE = (
    "Compte Google déconnecté : l'autorisation Google est absente, expirée ou "
    "révoquée. Reconnecte ton compte Google dans Réglages, puis relance."
)


def dit_compte_google_deconnecte(texte: object) -> bool:
    """Ce retour d'outil dit-il que le compte Google n'est pas (ou plus) connecté ?"""
    value = content_to_text(texte).lstrip("⚠️❌⛔ ").lower()
    return value.startswith(("google non connecté", "google drive non connecté"))


def recovery_hint(tool_name: str, error: str) -> str:
    """Make the next step explicit, without retrying an uncertain side effect."""
    lower = error.lower()
    if dit_compte_google_deconnecte(error) or "invalid_grant" in lower:
        # Aucun outil Google ne marchera, et passer par le navigateur ou un
        # script reviendrait à forcer une porte que l'utilisateur doit rouvrir.
        return (
            f"\n\n[Reprise de {tool_name}] {MESSAGE_COMPTE_GOOGLE_DECONNECTE} "
            "Aucun outil Google ne fonctionnera d'ici là : n'essaie aucune autre "
            "voie pour atteindre Gmail, Drive, Agenda ou Sheets. Traite ce qui ne "
            "dépend pas de Google, puis dis clairement à l'utilisateur : "
            "« Compte Google déconnecté »."
        )
    if any(word in lower for word in ("403", "401", "unauthorized", "credential", "oauth", "permission", "interdit", "refus")):
        action = (
            "Vérifie le compte et les autorisations. Ne contourne pas un refus. "
            "Prépare les parties indépendantes ; ne demande que l'accès réellement manquant."
        )
    elif any(word in lower for word in ("timeout", "timed out", "429", "503", "502", "quota", "délai")):
        action = (
            "Vérifie d'abord si l'action a déjà abouti avant de la rejouer. "
            "Pour une lecture, change de source ou de fournisseur ; évite les répétitions identiques."
        )
    elif any(word in lower for word in ("argument", "validation", "parameter", "paramètre", "required", "typeerror")):
        action = "Relis le schéma exact avec find_tool, corrige les paramètres puis réessaie."
    else:
        action = (
            "Analyse cette erreur, puis change de méthode : find_tool pour une autre capacité, "
            "composition d'outils, navigateur ou python_execute en bac à sable. "
            "Si la capacité manque réellement, consigne-la avec report_missing_capability "
            "et poursuis les parties réalisables de la demande."
        )
    return (
        f"\n\n[Reprise de {tool_name}] {action} "
        "Consulte memory_recall(memory_type='error') si ce problème revient. "
        "Ne déclare pas cette action réussie sans preuve."
    )


def recovered_in_turn(messages: list) -> bool:
    """A verified turn corrected an actual error, even without judge retries."""
    failed = False
    for message in current_turn(messages):
        if not isinstance(message, ToolMessage):
            continue
        if message.status == "error" or dit_un_echec(message.content):
            failed = True
        elif failed and content_to_text(message.content).strip():
            return True
    return False
