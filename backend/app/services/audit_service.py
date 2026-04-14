# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

logger = logging.getLogger(__name__)


async def log_action(
    db: AsyncSession,
    user_id: str,
    action: str,
    target_host: str | None = None,
    command: str | None = None,
    result_code: int | None = None,
    details: str | None = None,
    channel: str | None = None,
    tool_used: str | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Enregistre une entrée d'audit dans la base de données.

    Paramètres ajoutés (Phase 2.3) :
    - channel : canal d'origine ("web", "telegram", "slack", "discord", "api")
    - tool_used : nom de l'outil agent invoqué
    - ip_address : adresse IP du client
    """
    log = AuditLog(
        user_id=user_id,
        action=action,
        target_host=target_host,
        command=command,
        result_code=result_code,
        details=details,
        channel=channel,
        tool_used=tool_used,
        ip_address=ip_address,
    )
    db.add(log)
    await db.flush()
    return log


async def log_action_standalone(
    user_id: str,
    action: str,
    target_host: str | None = None,
    command: str | None = None,
    result_code: int | None = None,
    details: str | None = None,
    channel: str | None = None,
    tool_used: str | None = None,
    ip_address: str | None = None,
) -> None:
    """Variante autonome — ouvre sa propre session DB.

    Utile dans les contextes où aucune session n'est déjà ouverte
    (ex: tool_node, channels Telegram/Slack/Discord).
    Non bloquant : les erreurs sont loguées mais ne remontent pas.
    """
    from app.database import async_session

    try:
        async with async_session() as db:
            db.add(AuditLog(
                user_id=user_id,
                action=action,
                target_host=target_host,
                command=command,
                result_code=result_code,
                details=details,
                channel=channel,
                tool_used=tool_used,
                ip_address=ip_address,
            ))
            await db.commit()
    except Exception:
        logger.warning("Échec de l'enregistrement audit (non bloquant)", exc_info=True)
