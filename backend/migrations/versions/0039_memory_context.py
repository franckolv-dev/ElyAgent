"""Memory selection journal and immutable versions of the existing profile."""

from alembic import op
import sqlalchemy as sa

revision = "0039_memory_context"
down_revision = "0038_autonomy"
branch_labels = None
depends_on = None


def upgrade():
    # A base created by `create_all` may not carry `user_profiles` yet (tests on a
    # legacy snapshot) : the profile columns then come from the model itself.
    has_profiles = sa.inspect(op.get_bind()).has_table("user_profiles")
    for name, kind, default in [
        ("scope", sa.String(160), ""),
        ("source", sa.String(200), "consolidation"),
        ("confirmed", sa.Boolean(), "0"),
        ("pinned", sa.Boolean(), "0"),
    ]:
        if has_profiles and name not in {
            c["name"] for c in sa.inspect(op.get_bind()).get_columns("user_profiles")
        }:
            op.add_column("user_profiles", sa.Column(name, kind, nullable=False, server_default=default))
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("user_profiles") if has_profiles else []
    if any(c["name"] == "uq_user_profiles_user_key" and "scope" not in c["column_names"] for c in constraints):
        with op.batch_alter_table("user_profiles") as batch:
            batch.drop_constraint("uq_user_profiles_user_key", type_="unique")
            batch.create_unique_constraint("uq_user_profiles_user_key", ["user_id", "key", "scope"])
    # Additive schema: current facts remain in the same tables/collections.
    if not sa.inspect(op.get_bind()).has_table("memory_selections"):
        op.create_table(
            "memory_selections",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("query", sa.Text(), nullable=False),
            sa.Column("scope", sa.String(), nullable=False),
            sa.Column("selected_json", sa.Text(), nullable=False),
            sa.Column("tokens", sa.Integer(), nullable=False),
            sa.Column("elapsed_ms", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if "ix_memory_selections_user_id" not in {
        i["name"] for i in sa.inspect(op.get_bind()).get_indexes("memory_selections")
    }:
        op.create_index("ix_memory_selections_user_id", "memory_selections", ["user_id"])
    if "ix_memory_selections_conversation_id" not in {
        i["name"] for i in sa.inspect(op.get_bind()).get_indexes("memory_selections")
    }:
        op.create_index("ix_memory_selections_conversation_id", "memory_selections", ["conversation_id"])
    if not sa.inspect(op.get_bind()).has_table("memory_versions"):
        op.create_table(
            "memory_versions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("family", sa.String(), nullable=False),
            sa.Column("entry_id", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if "ix_memory_versions_user_id" not in {
        i["name"] for i in sa.inspect(op.get_bind()).get_indexes("memory_versions")
    }:
        op.create_index("ix_memory_versions_user_id", "memory_versions", ["user_id"])
    if not sa.inspect(op.get_bind()).has_table("memory_checkpoints"):
        op.create_table(
            "memory_checkpoints",
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("value", sa.Text(), nullable=False),
        )
    if has_profiles and op.get_bind().dialect.name == "sqlite":
        # Includes all existing writers (nightly consolidation, tools, profile edits).
        op.execute("""CREATE TRIGGER IF NOT EXISTS profile_memory_history BEFORE UPDATE OF value ON user_profiles
        WHEN OLD.value IS NOT NEW.value BEGIN
          INSERT INTO memory_versions(user_id,family,entry_id,content,metadata_json,created_at)
          VALUES(OLD.user_id,'profile',CAST(OLD.id AS TEXT),OLD.value,
            json_object('key',OLD.key,'source','profile','observed_at',OLD.last_seen,'expires_at',OLD.expires_at,'scope',OLD.scope,'confirmed',OLD.confirmed),datetime('now'));
        END""")


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS profile_memory_history")
    duplicates = (
        op.get_bind()
        .execute(sa.text("SELECT user_id, key FROM user_profiles GROUP BY user_id, key HAVING count(*) > 1 LIMIT 1"))
        .first()
    )
    if duplicates:
        raise RuntimeError("Downgrade would merge scoped facts. Restore a reviewed backup instead.")
    with op.batch_alter_table("user_profiles") as batch:
        batch.drop_constraint("uq_user_profiles_user_key", type_="unique")
        batch.create_unique_constraint("uq_user_profiles_user_key", ["user_id", "key"])
    for name in ("scope", "source", "confirmed", "pinned"):
        op.drop_column("user_profiles", name)
    op.drop_table("memory_checkpoints")
    op.drop_table("memory_versions")
    op.drop_table("memory_selections")
