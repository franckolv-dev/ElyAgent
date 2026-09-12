"""Resolve explicit account context from owned records; never from model output."""

import re
from sqlalchemy import select
from app.database import async_session
from app.models.google_account import GoogleAccount


def allowed_scopes(scope: str) -> list[str]:
    return [""] + [s for s in scope.split("|") if s]


async def account_scope(user_id: str, query: str) -> str:
    async with async_session() as db:
        accounts = (
            await db.execute(select(GoogleAccount.id, GoogleAccount.alias).where(GoogleAccount.user_id == user_id))
        ).all()
    found = [
        a.id for a in accounts if re.search(r"\bcompte\s+[\"«']?" + re.escape(a.alias) + r"\b", query, re.IGNORECASE)
    ]
    return f"account:{found[0]}" if len(found) == 1 else ""
