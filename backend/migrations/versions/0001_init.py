import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def _timestamp(name: str, **kwargs) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), **kwargs)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tg_id_hash", sa.String(64), nullable=False),
        sa.Column("chat_id", sa.BigInteger, nullable=True),
        sa.Column("tz", sa.String(64), nullable=False),
        _timestamp("created_at", server_default=NOW, nullable=False),
        _timestamp("last_active_at", server_default=NOW, nullable=False),
        sa.Column("notifications_enabled", sa.Boolean, nullable=False),
        sa.Column("quiet_from", sa.Integer, nullable=False),
        sa.Column("quiet_to", sa.Integer, nullable=False),
        sa.Column("ab_group", sa.String(1), nullable=False),
        _timestamp("last_proactive_at", nullable=True),
        sa.Column("state", postgresql.JSONB, nullable=False),
    )
    op.create_index("ix_users_tg_id_hash", "users", ["tg_id_hash"], unique=True)

    op.create_table(
        "profiles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("stage", sa.String(32), nullable=True),
        sa.Column("industry", sa.String(128), nullable=True),
        sa.Column("legal_form", sa.String(32), nullable=True),
        sa.Column("tax_regime", sa.String(32), nullable=True),
        sa.Column("main_task", sa.String(128), nullable=True),
        sa.Column("experience", sa.String(32), nullable=True),
        sa.Column("time_budget", sa.String(32), nullable=True),
        sa.Column("slot_confidence", postgresql.JSONB, nullable=False),
        _timestamp("updated_at", server_default=NOW, nullable=False),
    )

    op.create_table(
        "materials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ext_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("is_paid", sa.Boolean, nullable=False),
        sa.Column("price", sa.Integer, nullable=True),
        sa.Column("topics", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("stage", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("level", sa.String(32), nullable=True),
        sa.Column("format", sa.String(32), nullable=True),
        sa.Column("duration_min", sa.Integer, nullable=True),
        sa.Column("parent_ext_id", sa.String(64), nullable=True),
        sa.Column("popularity", sa.Float, nullable=False),
    )
    op.create_index("ix_materials_ext_id", "materials", ["ext_id"], unique=True)
    op.create_index("ix_materials_kind", "materials", ["kind"])
    op.create_index("ix_materials_is_paid", "materials", ["is_paid"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("material_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("materials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR, sa.Computed("to_tsvector('russian', text)", persisted=True), nullable=False),
    )
    op.create_index("ix_chunks_material_id", "chunks", ["material_id"])
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")

    op.create_table(
        "interactions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("ext_user_id", sa.String(64), nullable=True),
        sa.Column("material_ext_id", sa.String(64), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("value", sa.Float, nullable=True),
        _timestamp("created_at", nullable=True),
    )
    op.create_index("ix_interactions_ext_user_id", "interactions", ["ext_user_id"])
    op.create_index("ix_interactions_material_ext_id", "interactions", ["material_ext_id"])

    op.create_table(
        "dialog_turns",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("text_masked", sa.Text, nullable=False),
        sa.Column("intent", sa.String(32), nullable=True),
        _timestamp("created_at", server_default=NOW, nullable=False),
    )
    op.create_index("ix_dialog_turns_user_id", "dialog_turns", ["user_id"])

    op.create_table(
        "reminders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        _timestamp("run_at", nullable=True),
        sa.Column("freq", sa.String(16), nullable=True),
        sa.Column("weekdays", postgresql.ARRAY(sa.Integer), nullable=False),
        sa.Column("interval", sa.Integer, nullable=False),
        sa.Column("send_time", sa.String(5), nullable=False),
        sa.Column("lead_days", sa.Integer, nullable=False),
        sa.Column("material_ext_id", sa.String(64), nullable=True),
        sa.Column("tax_event_id", sa.String(64), nullable=True),
        sa.Column("active", sa.Boolean, nullable=False),
        _timestamp("next_run_at", nullable=True),
        _timestamp("created_at", server_default=NOW, nullable=False),
    )
    op.create_index("ix_reminders_user_id", "reminders", ["user_id"])
    op.create_index("ix_reminders_next_run_at", "reminders", ["next_run_at"])

    op.create_table(
        "recs_shown",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("material_ext_id", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("reaction", sa.String(16), nullable=True),
        _timestamp("created_at", server_default=NOW, nullable=False),
    )
    op.create_index("ix_recs_shown_user_id", "recs_shown", ["user_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        _timestamp("created_at", server_default=NOW, nullable=False),
    )
    op.create_index("ix_events_user_id", "events", ["user_id"])
    op.create_index("ix_events_name", "events", ["name"])


def downgrade() -> None:
    for table in ("events", "recs_shown", "reminders", "dialog_turns", "interactions", "chunks", "materials", "profiles", "users"):
        op.drop_table(table)
