"""MCPServer — configuration d'un serveur MCP externe.

Un serveur MCP expose des outils que l'agent peut utiliser.
Deux transports sont supportés :
  - stdio : un processus local lancé par ELY (ex: uvx mcp-server-filesystem /tmp)
  - sse   : un serveur HTTP SSE distant (ex: http://localhost:3000/sse)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id:          Mapped[str]  = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name:        Mapped[str]  = mapped_column(String, nullable=False)         # display name
    slug:        Mapped[str]  = mapped_column(String, unique=True, nullable=False)  # skill name in registry
    transport:   Mapped[str]  = mapped_column(String, default="stdio")        # "stdio" | "sse"
    # stdio: full shell command to launch the server, e.g. "uvx mcp-server-filesystem /tmp"
    # sse:   leave blank
    command:     Mapped[str | None] = mapped_column(Text, nullable=True)
    # sse: base URL, e.g. "http://localhost:3000/sse"
    url:         Mapped[str | None] = mapped_column(String, nullable=True)
    # JSON dict of extra environment variables injected into the stdio process
    env_json:    Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)      # shown in admin UI
    enabled:     Mapped[bool] = mapped_column(Boolean, default=True)
    created_at:  Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
