# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/mcp_server.py
# @brief      MCPServer / MCPTool / MCPToolPermission — config d'un serveur MCP
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Modèle de données du client MCP universel.

Un serveur MCP expose des outils que l'agent peut utiliser. Transports :
  - ``stdio``           : un processus local lancé par ELY
  - ``streamable_http`` : un serveur HTTP distant (transport MCP moderne)
  - ``legacy_sse``      : ancien transport HTTP+SSE, conservé en compatibilité
                          (``sse`` reste accepté comme alias historique)

Lot 0 (chantier client MCP, 2026-06) — ce module porte trois tables :

* ``mcp_servers``           : la configuration + l'état de confiance/santé ;
* ``mcp_tools``             : le catalogue des outils découverts (substrat du
                              bridge, peuplé au Lot 2 / J3) ;
* ``mcp_tool_permissions``  : l'ACL par utilisateur / serveur / outil
                              (substrat de la policy, peuplé au Lot 3 / J4).

Invariants Lot 0 :

* les secrets (``env_json``) ne sont JAMAIS renvoyés en clair par l'API ;
* le nom local d'un outil est namespacé ``mcp__<slug>__<tool>`` — aucun
  outil MCP ne peut masquer un outil natif d'ELY ;
* ``kill_switch`` coupe immédiatement un serveur, indépendamment du flag
  global ``mcp_client_v2_enabled``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── États de confiance ───────────────────────────────────────────────────
# draft → quarantined → pending_approval → active   (↘ blocked)
# Un serveur créé par un admin via l'UI existante démarre `active`
# (l'admin EST l'approbateur). Le parcours quarantaine sert la voie
# model-facing (J4) où le modèle PROPOSE et l'humain approuve.
TRUST_STATES = ("draft", "quarantined", "pending_approval", "active", "blocked")

# ── États de santé runtime ───────────────────────────────────────────────
HEALTH_STATES = (
    "unknown", "connecting", "healthy", "degraded",
    "unauthorized", "offline", "blocked",
)


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id:   Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)              # display name
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)  # skill name in registry

    # "stdio" | "streamable_http" | "legacy_sse" (alias historique : "sse")
    transport: Mapped[str] = mapped_column(String, default="stdio")

    # ── Cible ──────────────────────────────────────────────────────────
    # stdio : `command` = exécutable (legacy : ligne complète) ; `args_json`
    #         = liste d'arguments structurée. Si `args_json` est nul on
    #         retombe sur shlex.split(command) (rétro-compat). Aucun shell.
    command:   Mapped[str | None] = mapped_column(Text, nullable=True)
    args_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Répertoire de travail du sous-processus stdio. Dormant jusqu'au J5, où il
    # est câblé au spawn (cwd du serveur sandboxé). Nul ⇒ cwd du backend.
    cwd:       Mapped[str | None] = mapped_column(Text, nullable=True)
    # remote : endpoint MCP (streamable_http / legacy_sse)
    url:       Mapped[str | None] = mapped_column(String, nullable=True)

    # Variables d'environnement du sous-processus stdio (objet JSON).
    # NOTE : porte des secrets — JAMAIS renvoyé en clair par l'API (cf.
    # router : on n'expose que les *noms* de clés). Migration du stockage
    # vers le Vault / secret d'instance = Lot 3 (J4).
    env_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ── Sandbox stdio (J5) — override de profil par serveur (NON secret) ──
    # Objet JSON optionnel : {mem_bytes, nofile, fsize_bytes}. Nul ⇒ profil
    # par défaut (config). Lu seulement si `mcp_stdio_sandbox_enabled` est ON.
    sandbox_profile_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Authentification distante (J4) ─────────────────────────────────
    # "none" | "bearer" | "api_key" | "oauth2". Le secret n'est JAMAIS stocké
    # ici : `credential_ref` est une référence opaque (label Vault du
    # propriétaire). Pour oauth2, le bundle de tokens vit dans le Vault sous
    # un label dédié (cf. `mcp_credentials.oauth_label`).
    auth_type:         Mapped[str]        = mapped_column(String, default="none")
    credential_ref:    Mapped[str | None] = mapped_column(String, nullable=True)
    # Nom de header pour auth_type=api_key (ex. "X-API-Key").
    auth_header_name:  Mapped[str | None] = mapped_column(String, nullable=True)
    # Exception LAN explicite (admin, hors V1) : autorise une cible réseau privée.
    allow_private_network: Mapped[bool]   = mapped_column(Boolean, default=False)

    # ── OAuth 2.1 / PKCE (Client MCP v2, J1+) ──────────────────────────
    # Métadonnées NON secrètes du flow OAuth. Le secret (access/refresh
    # tokens) n'est JAMAIS ici : il vit en bundle JSON dans le Vault du
    # propriétaire (label `mcp::<slug>::oauth`). `oauth_client_secret_ref`
    # est une référence opaque (DCR confidentiel / serveur d'instance) — la
    # valeur n'est jamais stockée ni renvoyée par l'API.
    # Cache de découverte (RFC 9728 / 8414) : endpoints d'autorisation,
    # de token, d'enregistrement (DCR) et de révocation, sérialisés en JSON.
    oauth_metadata_json:     Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_client_id:         Mapped[str | None] = mapped_column(String, nullable=True)
    oauth_client_secret_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    # Scopes demandés (séparés par des espaces, format OAuth standard).
    oauth_scopes:            Mapped[str | None] = mapped_column(String, nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Portée & propriété ─────────────────────────────────────────────
    # "instance" (admin, partagé) | "user" (perso, isolé à son propriétaire)
    scope:         Mapped[str]        = mapped_column(String, default="instance")
    owner_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
    )

    # ── Activation & confiance ─────────────────────────────────────────
    enabled:     Mapped[bool] = mapped_column(Boolean, default=True)
    # Coupe-circuit par serveur : True ⇒ jamais chargé, déchargé au plus tôt.
    # Toujours honoré, indépendamment du flag global.
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    trust_state: Mapped[str]  = mapped_column(String, default="active")

    # ── Handshake & santé (peuplés au Lot 1 / J2) ──────────────────────
    protocol_version:  Mapped[str | None]      = mapped_column(String, nullable=True)
    server_info_json:  Mapped[str | None]      = mapped_column(Text, nullable=True)
    capabilities_json: Mapped[str | None]      = mapped_column(Text, nullable=True)
    health_state:      Mapped[str]             = mapped_column(String, default="unknown")
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Code d'erreur stable, sans secret (cf. taxonomie MCP_*).
    last_error_code:   Mapped[str | None]      = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class MCPTool(Base):
    """Catalogue local d'un outil découvert sur un serveur MCP.

    Substrat du bridge (Lot 2 / J3). Conserve le JSON Schema *complet* :
    aucune simplification silencieuse. `local_name` est le nom namespacé
    envoyé au modèle ; `remote_name` celui annoncé par le serveur.
    """
    __tablename__ = "mcp_tools"

    id:        Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    server_id: Mapped[str] = mapped_column(
        String, ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False,
    )
    remote_name: Mapped[str]        = mapped_column(String, nullable=False)
    local_name:  Mapped[str]        = mapped_column(String, nullable=False, unique=True)
    title:       Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    input_schema_json:  Mapped[str | None] = mapped_column(Text, nullable=True)
    output_schema_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Annotations MCP = indications NON FIABLES du serveur (affichage only).
    annotations_json:   Mapped[str | None] = mapped_column(Text, nullable=True)
    definition_hash:    Mapped[str | None] = mapped_column(String, nullable=True)

    # Découvert ≠ activé : un outil reste inerte tant qu'il n'est pas
    # explicitement autorisé (config ≠ exécution).
    enabled:    Mapped[bool] = mapped_column(Boolean, default=False)
    # "low" | "medium" | "high" | "critical"
    risk_level: Mapped[str]  = mapped_column(String, default="medium")

    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MCPToolPermission(Base):
    """Règle d'autorisation par (utilisateur, serveur, outil).

    Substrat de la policy (Lot 3 / J4). `tool_id` nul ⇒ règle au niveau du
    serveur. `decision` ∈ {deny, ask, allow_task, allow} ; défaut `ask`
    (fail-closed : rien n'est `allow` sans décision explicite).
    """
    __tablename__ = "mcp_tool_permissions"

    id:      Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    server_id: Mapped[str] = mapped_column(
        String, ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False,
    )
    tool_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("mcp_tools.id", ondelete="CASCADE"), nullable=True,
    )
    decision:    Mapped[str]        = mapped_column(String, default="ask")
    data_policy: Mapped[str | None] = mapped_column(String, nullable=True)
    granted_by:  Mapped[str | None] = mapped_column(String, nullable=True)
    granted_at:  Mapped[datetime]   = mapped_column(DateTime(timezone=True), default=_now)
    expires_at:  Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
