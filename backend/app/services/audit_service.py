from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def log_action(
    db: AsyncSession,
    user_id: str,
    action: str,
    target_host: str | None = None,
    command: str | None = None,
    result_code: int | None = None,
    details: str | None = None,
) -> AuditLog:
    log = AuditLog(
        user_id=user_id,
        action=action,
        target_host=target_host,
        command=command,
        result_code=result_code,
        details=details,
    )
    db.add(log)
    await db.flush()
    return log
