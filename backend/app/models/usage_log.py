# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/usage_log.py
# @brief      Usage log model — tracks LLM token usage and skill invocations.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Usage log model — tracks LLM token usage and skill invocations."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, DateTime, Index, Text
from app.database import Base


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    # LLM usage
    model = Column(String, nullable=True)          # e.g. "claude-sonnet-4-5"
    provider = Column(String, nullable=True)       # "anthropic", "mistral", etc.
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)          # estimated cost

    # Context
    skill_used = Column(String, nullable=True)     # which skill/tool was invoked
    conversation_id = Column(String, nullable=True)
    channel = Column(String, default="web")        # "web", "telegram", "whatsapp"

    # HITL
    hitl_decision = Column(String, nullable=True)  # "allow", "deny", "ban", None
    hitl_action = Column(Text, nullable=True)      # what action was validated

    # V2-1 — pilotabilité (vague 2). Sans ces deux colonnes, la question
    # « mono-agent ou sous-agents ? » n'est pas mesurable : 8 938 lignes
    # d'usage ne disaient ni combien de temps le tour a pris, ni quelle
    # architecture l'a servi.
    #
    # NULL et non 0 quand la mesure est absente : une latence nulle serait
    # une mesure, l'absence de mesure n'en est pas une.
    latency_ms = Column(Integer, nullable=True)    # durée du tour, bout en bout
    # "mono" | "sub_agent:<domaine>" | "flat" | "mission" | "unknown"
    architecture = Column(String(32), nullable=True, index=True)

    # P2 — d'où viennent les tokens de ce tour (port Hermes v0.19). JSON plat
    # et compact : {"system_prompt":…,"tool_definitions":…,"conversation":…,
    # "total":…,"pct":…}. Mesuré en prod, certains tours pèsent 230 000 tokens
    # d'entrée sans qu'on sache lequel de ces postes les porte. NULL quand la
    # ventilation n'a rien à dire — une colonne vide vaut mieux qu'un JSON
    # vide qui donnerait l'illusion d'une mesure.
    # ── Cache de préfixe (27/07/2026) ─────────────────────────────────────
    #
    # Ely découpe son prompt système exprès pour maximiser le cache de préfixe
    # (segment stable puis segment dynamique), mais `usage_metadata` remontait
    # déjà ces compteurs et personne ne les lisait : stratégie soignée, aucun
    # moyen de savoir si elle mord.
    #
    # DEUX compteurs, pas un : `cached_input_tokens` est un SUCCÈS (tokens
    # relus, facturés au rabais), `cache_creation_tokens` une ÉCRITURE (parfois
    # facturée plus cher chez Anthropic). Les additionner masquerait un cache
    # qui écrit sans jamais relire — inutile ET coûteux.
    cached_input_tokens = Column(Integer, default=0)
    cache_creation_tokens = Column(Integer, default=0)
    context_breakdown = Column(Text, nullable=True)

    # ⚠️ CE QUE ÇA CORRIGE (audit 02/09/2026) : `user_id` et `timestamp`
    # étaient indexés SÉPARÉMENT, alors que les six lecteurs de cette table
    # filtrent sur les DEUX — les cinq agrégations de analytics_service
    # (résumé, usage quotidien, par skill, HITL, par fournisseur) et le
    # garde-budget (budget_guard, appelé à chaque tour) :
    #
    #     where user_id = ? and timestamp >= ?
    #
    # SQLite ne retient qu'un index par table et par requête : il prenait
    # celui de `user_id` puis balayait TOUTES les lignes de l'utilisateur
    # pour n'en garder qu'une fenêtre de dates. 11 280 lignes en prod, et la
    # table ne fait que grossir. L'ordre des colonnes n'est pas décoratif :
    # égalité d'abord (`user_id`), intervalle ensuite (`timestamp`).
    __table_args__ = (
        Index("ix_usage_logs_user_timestamp", "user_id", "timestamp"),
    )
