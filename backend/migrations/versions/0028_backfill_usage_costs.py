"""Reprise des coûts déjà écrits dans usage_logs.

Revision ID: 0028_backfill_usage_costs
Revises: 0027_instance_max_output
Create Date: 2026-07-26

`cost_usd` est calculé À L'ÉCRITURE puis sommé à l'affichage. Les lignes
existantes portent donc définitivement les tarifs en vigueur au moment du tour
— pour la plupart le générique inventé de 1,0/3,0 USD par million. Mesuré sur
la base réelle : 123,29 USD affichés, dont 26,62 USD facturés à un modèle
LOCAL gratuit.

Renseigner les tarifs sur les instances (#272) corrige les tours à venir ;
seule cette reprise corrige le passé.

Deux traitements :

1. RECALCUL — pour les modèles encore configurés, on applique leurs tarifs
   réels depuis `llm_instances`. Arithmétique pure, aucune interprétation.

2. NEUTRALISATION — pour des modèles RETIRÉS dont on sait qu'ils ne coûtaient
   rien à l'appel :
     • `gpt-5.5` — consommé via l'abonnement ChatGPT. Établi le 26/07 en
       remontant le chemin `_make_openai_codex`, qui forçait ce modèle dès
       qu'un tier référençait « openai_codex » par son nom. 22,59 USD à lui
       seul.
     • les noms portant un marqueur de modèle local : `mlx`,
       `lmstudio-community/`, `LiquidAI/`.

Les modèles cloud retirés (kimi-k2.6, qwen3.6-flash, ministral…) ont bien
coûté quelque chose. On ne sait pas combien, on n'invente pas : leur valeur
d'origine est conservée.

⚠️ CORRECTION UNIQUE, PAS UNE RÈGLE. Ces motifs vivent ici, dans une migration
datée, et non dans le code de calcul : une heuristique sur les noms de modèles
vieillirait en silence — la classe de défaut même que ce chantier supprime.

Le nom du modèle peut porter un suffixe « +tools » : on compare sur la partie
qui précède.
"""
from alembic import op
import sqlalchemy as sa

revision = "0028_backfill_usage_costs"
down_revision = "0027_instance_max_output"
branch_labels = None
depends_on = None

# Modèles retirés qui ne coûtaient rien à l'appel.
_FREE_EXACT = ("gpt-5.5",)
_FREE_LIKE = ("%mlx%", "%lmstudio-community/%", "%LiquidAI/%")


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("usage_logs") or not insp.has_table("llm_instances"):
        return

    base = "substr(usage_logs.model, 1, instr(usage_logs.model || '+', '+') - 1)"

    # 1. Recalcul depuis les tarifs déclarés sur les instances.
    bind.execute(sa.text(f"""
        UPDATE usage_logs
           SET cost_usd = (
                SELECT (COALESCE(usage_logs.input_tokens, 0) * i.input_price_per_million
                      + COALESCE(usage_logs.output_tokens, 0) * i.output_price_per_million)
                      / 1000000.0
                  FROM llm_instances i
                 WHERE i.model = {base}
                   AND i.input_price_per_million IS NOT NULL
                   AND i.output_price_per_million IS NOT NULL
                 LIMIT 1)
         WHERE EXISTS (
                SELECT 1 FROM llm_instances i
                 WHERE i.model = {base}
                   AND i.input_price_per_million IS NOT NULL
                   AND i.output_price_per_million IS NOT NULL)
    """))

    # 2. Neutralisation des modèles retirés gratuits à l'appel.
    for exact in _FREE_EXACT:
        bind.execute(
            sa.text(f"UPDATE usage_logs SET cost_usd = 0.0 WHERE {base} = :m"),
            {"m": exact},
        )
    for pattern in _FREE_LIKE:
        bind.execute(
            sa.text("UPDATE usage_logs SET cost_usd = 0.0 WHERE model LIKE :p"),
            {"p": pattern},
        )


def downgrade() -> None:
    """Sans objet : les coûts d'origine étaient faux, il n'y a rien à restaurer.

    Les rétablir demanderait de reconstituer les tarifs en vigueur à chaque
    tour, information que personne n'a jamais conservée — c'est précisément le
    problème que cette migration répare.
    """
