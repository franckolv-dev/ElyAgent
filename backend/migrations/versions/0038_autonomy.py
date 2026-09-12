"""Durable automations, action receipts, mission checks and procedure outcomes."""

from alembic import op
import sqlalchemy as sa

revision = "0038_autonomy"
down_revision = "0037_mission_pending_question"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("automation_rules"):
        op.create_table(
            "automation_rules",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("account", sa.String(length=160), nullable=False),
            sa.Column("filters_json", sa.Text(), nullable=False),
            sa.Column("goal", sa.Text(), nullable=False),
            sa.Column("checks_json", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("daily_limit", sa.Integer(), nullable=False),
            sa.Column("cursor_json", sa.Text(), nullable=False),
            sa.Column("last_poll_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_automation_rules_user_id"), "automation_rules", ["user_id"], unique=False)
    if not sa.inspect(op.get_bind()).has_table("automation_events"):
        op.create_table(
            "automation_events",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("rule_id", sa.String(), nullable=False),
            sa.Column("event_key", sa.String(length=64), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("mission_id", sa.String(), nullable=True),
            sa.Column("dispatched_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["rule_id"], ["automation_rules.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("mission_id"),
            sa.UniqueConstraint("rule_id", "event_key", name="uq_automation_event"),
        )
        op.create_index(op.f("ix_automation_events_rule_id"), "automation_events", ["rule_id"], unique=False)
        op.create_index(op.f("ix_automation_events_user_id"), "automation_events", ["user_id"], unique=False)
    if not sa.inspect(op.get_bind()).has_table("mission_assurance"):
        op.create_table(
            "mission_assurance",
            sa.Column("mission_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("checks_json", sa.Text(), nullable=False),
            sa.Column("results_json", sa.Text(), nullable=False),
            sa.Column("waiting_for", sa.String(length=32), nullable=True),
            sa.Column("waiting_since", sa.DateTime(), nullable=True),
            sa.Column("retries", sa.Integer(), nullable=False),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("mission_id"),
        )
        op.create_index(op.f("ix_mission_assurance_user_id"), "mission_assurance", ["user_id"], unique=False)
    if not sa.inspect(op.get_bind()).has_table("autonomy_preferences"):
        op.create_table(
            "autonomy_preferences",
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("rules_json", sa.Text(), nullable=False),
            sa.Column("notifications", sa.String(length=20), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("user_id"),
        )
    if not sa.inspect(op.get_bind()).has_table("procedure_trials"):
        op.create_table(
            "procedure_trials",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("skill_id", sa.String(), nullable=False),
            sa.Column("run_key", sa.String(length=160), nullable=False),
            sa.Column("outcome", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["skill_id"], ["learned_skills.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("skill_id", "run_key", name="uq_procedure_trial"),
        )
        op.create_index(op.f("ix_procedure_trials_skill_id"), "procedure_trials", ["skill_id"], unique=False)
        op.create_index(op.f("ix_procedure_trials_user_id"), "procedure_trials", ["user_id"], unique=False)
    if not sa.inspect(op.get_bind()).has_table("autonomy_action_receipts"):
        op.create_table(
            "autonomy_action_receipts",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("mission_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("action_key", sa.String(length=64), nullable=False),
            sa.Column("tool_name", sa.String(length=160), nullable=False),
            sa.Column("effect", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("result", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("mission_id", "action_key", name="uq_mission_action"),
        )
        op.create_index(
            op.f("ix_autonomy_action_receipts_mission_id"), "autonomy_action_receipts", ["mission_id"], unique=False
        )
        op.create_index(
            op.f("ix_autonomy_action_receipts_user_id"), "autonomy_action_receipts", ["user_id"], unique=False
        )


def downgrade():
    for name in (
        "autonomy_action_receipts",
        "procedure_trials",
        "autonomy_preferences",
        "mission_assurance",
        "automation_events",
        "automation_rules",
    ):
        if sa.inspect(op.get_bind()).has_table(name):
            op.drop_table(name)
