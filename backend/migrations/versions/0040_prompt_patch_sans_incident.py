"""Un correctif de consigne n'a plus besoin d'un incident.

19/09/2026 : la page « Incidents & propositions » et le diagnostic automatique
sont retirés. Un correctif se demande depuis la fiche d'une tâche planifiée.

- ``proposed_patches.execution_diagnosis_id`` devient NULLABLE.
- Les liaisons d'outils appliquées depuis un incident passent « reverted » :
  plus aucun code ne les lit, et plus aucun écran ne permet de les annuler.
  Un état actif invisible est pire qu'un état absent.
- La table ``execution_diagnoses`` n'est PAS supprimée : ses lignes restent en
  base, sans lecteur. La supprimer est une décision à part.
"""

from alembic import op
import sqlalchemy as sa

revision = "0040_prompt_patch_sans_incident"
down_revision = "0039_memory_context"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("proposed_patches"):
        return
    # `resolve_fks=False` : le mode batch recrée la table après l'avoir relue ;
    # sans lui, la relecture charge aussi `users` et `execution_diagnoses`, et
    # échoue sur une base héritée qui ne les a pas encore.
    with op.batch_alter_table("proposed_patches", reflect_kwargs={"resolve_fks": False}) as batch:
        batch.alter_column("execution_diagnosis_id", existing_type=sa.Integer(), nullable=True)
    op.execute(
        "UPDATE proposed_patches SET status = 'reverted', applied_at = NULL "
        "WHERE kind = 'tool_binding' AND status = 'applied'"
    )
    op.execute(
        "UPDATE proposed_patches SET status = 'rejected' "
        "WHERE kind = 'tool_binding' AND status = 'proposed'"
    )


def downgrade():
    # Les liaisons passées « reverted » ne sont pas réactivées : on ne sait plus
    # lesquelles étaient appliquées. La colonne redevient obligatoire seulement
    # si aucune ligne sans incident n'a été créée entre-temps.
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("proposed_patches"):
        return
    sans_incident = bind.execute(sa.text(
        "SELECT COUNT(*) FROM proposed_patches WHERE execution_diagnosis_id IS NULL"
    )).scalar()
    if not sans_incident:
        with op.batch_alter_table("proposed_patches", reflect_kwargs={"resolve_fks": False}) as batch:
            batch.alter_column("execution_diagnosis_id", existing_type=sa.Integer(), nullable=False)
