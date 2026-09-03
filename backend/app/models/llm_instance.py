# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/llm_instance.py
# @brief      LLM instances — named provider+model combinations stored in DB.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""LLM instances — named provider+model combinations stored in DB."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LLMInstance(Base):
    """A named LLM instance: provider + model + optional API key + label.

    Multiple instances can be created for the same provider (e.g. several
    Ollama models) and assigned freely to routing tiers via their UUID.
    """
    __tablename__ = "llm_instances"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    label: Mapped[str] = mapped_column(String(255))
    # "ollama" | "anthropic" | "gemini" | "deepseek" | "mistral" | "zhipu" | "openrouter"
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(255))
    # Stored in plain text for now (SQLite local DB), masked as "***" in API responses.
    # None for Ollama (no key needed).
    api_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # ── Fenêtre et tarifs portés par l'instance (26/07/2026) ──────────────
    #
    # Avant, ces valeurs vivaient dans des tables du CODE
    # (`context_manager._CONTEXT_WINDOWS`, `analytics_service._PRICING`), que
    # l'utilisateur ne peut pas éditer. Résultat : il ajoutait un modèle depuis
    # l'interface, aucune table ne le savait, et Ely tronquait à 8 192 tokens
    # en facturant un tarif générique inventé — sans une erreur, pendant des
    # mois. Chaque correction manuelle était rattrapée par la suivante : la
    # passe de #263 a oublié 5 modèles sur 16, trouvés le lendemain par le
    # contrôle de réalité.
    #
    # Les porter ICI supprime la dérive : la valeur est saisie au moment où le
    # modèle est déclaré, par la personne qui lit la page tarifaire.
    #
    # NULLABLE à dessein : « non déclaré » doit rester distinct de « déclaré à
    # zéro ». Un modèle local à 0,0 est gratuit ; un modèle sans tarif est
    # inconnu, et le contrôle de réalité continue de le signaler.
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # En USD par MILLION de tokens, comme les fournisseurs les publient.
    # Convertir à la saisie donnerait une valeur vraie un jour, puis
    # vieillissant en silence ; la conversion en euros est un réglage
    # d'affichage, pas une donnée stockée.
    # Plafond de tokens en SORTIE. Valait 4 096 en dur à douze endroits de
    # llm_provider, quand Gemini 3.6 Flash en autorise 65 536 : une réponse
    # longue était coupée net, sans erreur et sans avertissement.
    #
    # Par modèle et non par constante généreuse : un fournisseur REFUSE une
    # valeur au-dessus de sa limite, et sur les serveurs locaux ce plafond est
    # PRÉLEVÉ SUR LA FENÊTRE — 65 536 en sortie sur un modèle à 32 768 ne
    # laisserait rien pour l'entrée.
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_price_per_million: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_price_per_million: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
