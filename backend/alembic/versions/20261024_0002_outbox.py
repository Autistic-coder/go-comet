"""Transactional notification outbox."""
from alembic import op

revision = "20261024_0002"
down_revision = "20261024_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE notification_outbox (
        id BIGSERIAL PRIMARY KEY, tenant_id TEXT NOT NULL, aggregate_type TEXT NOT NULL,
        aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','delivered','failed')),
        attempts INTEGER NOT NULL DEFAULT 0, available_at TEXT NOT NULL, locked_at TEXT,
        delivered_at TEXT, last_error TEXT, created_at TEXT NOT NULL,
        UNIQUE(tenant_id, aggregate_type, aggregate_id, event_type, created_at)
    )""")
    op.execute("CREATE INDEX idx_outbox_delivery ON notification_outbox(status, available_at, id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notification_outbox")
