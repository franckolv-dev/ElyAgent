"""Neutralise les modèles RETIRÉS qui tournaient en local.

Revision ID: 0029_only_paid_apis_cost
Revises: 0028_backfill_usage_costs
Create Date: 2026-07-26

La reprise 0028 avait ramené le total de 123,29 à 56,13 USD. Restaient des
modèles RETIRÉS dont le nom ne portait aucun marqueur exploitable, pour
lesquels inventer aurait été pire que de laisser un chiffre imparfait.

Franck a tranché : hors DeepSeek et Anthropic, ce qui tournait à l'époque était
local — **à l'exception de qwen3.6-flash et kimi-k2.6**, deux API cloud qui ont
bien consommé un peu.

LE CRITÈRE RETENU, ET POURQUOI IL A CHANGÉ. Une première version filtrait sur
des PRÉFIXES DE NOM (« deepseek- », « claude- »). Elle aurait effacé les ~12 USD
de `mistral-large-latest`, une API payante que Franck a bel et bien configurée
avec ses tarifs. Le critère est donc devenu : **une ligne n'est neutralisée que
si son modèle n'existe plus dans `llm_instances`** — la source de vérité que ce
chantier a mise en place. Un modèle encore déclaré a déjà été recalculé par
0028 avec ses vrais tarifs ; on n'y touche pas.

Deux exceptions nommées, qui gardent leur estimation : `qwen3.6-flash` et
`kimi-k2.6`, retirés mais bien facturés. Leur coût reste approximatif — les
tarifs de l'époque ne sont plus connus, et on ne les invente pas.

Le nom du modèle peut porter un suffixe « +tools » : la comparaison se fait sur
le préfixe, sans quoi `kimi-k2.6+tools` échapperait à l'exception.

⚠️ Reprise UNIQUE sur les lignes existantes. Les tours à venir passent par les
tarifs déclarés sur les instances (#272) : rien ici ne devient une règle
permanente.

`downgrade` sans objet : les coûts d'origine étaient faux.
"""
from alembic import op
import sqlalchemy as sa

revision = "0029_only_paid_apis_cost"
down_revision = "0028_backfill_usage_costs"
branch_labels = None
depends_on = None

# Retirés de la configuration, mais réellement facturés (Franck, 26/07).
_RETIRED_BUT_PAID = ("qwen3.6-flash", "kimi-k2.6")


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("usage_logs") or not insp.has_table("llm_instances"):
        return

    # QUALIFIER la table : dans la sous-requête corrélée ci-dessous, un `model`
    # nu se résout sur `llm_instances` (table interne), pas sur `usage_logs` —
    # la comparaison se ferait alors avec elle-même et ne filtrerait rien.
    base = ("substr(usage_logs.model, 1, "
            "instr(usage_logs.model || '+', '+') - 1)")
    spared = " OR ".join(f"{base} = :k{i}" for i in range(len(_RETIRED_BUT_PAID)))
    params = {f"k{i}": m for i, m in enumerate(_RETIRED_BUT_PAID)}

    bind.execute(sa.text(f"""
        UPDATE usage_logs SET cost_usd = 0.0
         WHERE NOT EXISTS (SELECT 1 FROM llm_instances i WHERE i.model = {base})
           AND NOT ({spared})
    """), params)


def downgrade() -> None:
    """Sans objet : les coûts d'origine étaient faux, il n'y a rien à
    restaurer."""
