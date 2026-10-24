"""Initial multi-tenant auction schema."""
from alembic import op

revision = "20261024_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        """CREATE TABLE users (id BIGSERIAL PRIMARY KEY, email TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 2 AND 100),
        role TEXT NOT NULL CHECK (role IN ('buyer','bidder')), supplier_name TEXT,
        carrier_name TEXT, password_hash TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, tenant_id TEXT NOT NULL DEFAULT 'demo-logistics')""",
        """CREATE TABLE sessions (id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE, csrf_hash TEXT NOT NULL, expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL)""",
        """CREATE TABLE rfqs (id BIGSERIAL PRIMARY KEY, reference_id TEXT NOT NULL, name TEXT NOT NULL,
        bid_start_at TEXT NOT NULL, original_close_at TEXT NOT NULL, current_close_at TEXT NOT NULL,
        forced_close_at TEXT NOT NULL, pickup_service_at TEXT NOT NULL,
        trigger_window_minutes INTEGER NOT NULL CHECK (trigger_window_minutes > 0),
        extension_minutes INTEGER NOT NULL CHECK (extension_minutes > 0),
        extension_trigger TEXT NOT NULL CHECK (extension_trigger IN ('bid_received','any_rank_change','lowest_bidder_change')),
        created_by_user_id BIGINT REFERENCES users(id), created_at TEXT NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT 'demo-logistics', lifecycle_state TEXT NOT NULL DEFAULT 'published',
        bid_visibility TEXT NOT NULL DEFAULT 'exact_price', awarded_bid_id BIGINT, version INTEGER NOT NULL DEFAULT 1,
        UNIQUE(tenant_id, reference_id))""",
        """CREATE TABLE bids (id BIGSERIAL PRIMARY KEY, rfq_id BIGINT NOT NULL REFERENCES rfqs(id) ON DELETE CASCADE,
        supplier_name TEXT NOT NULL, carrier_name TEXT NOT NULL,
        freight_charges NUMERIC(18,2) NOT NULL CHECK (freight_charges >= 0),
        origin_charges NUMERIC(18,2) NOT NULL CHECK (origin_charges >= 0),
        destination_charges NUMERIC(18,2) NOT NULL CHECK (destination_charges >= 0),
        transit_time_days INTEGER NOT NULL CHECK (transit_time_days > 0), validity_date TEXT NOT NULL,
        total_price NUMERIC(18,2) NOT NULL CHECK (total_price >= 0), bidder_user_id BIGINT REFERENCES users(id),
        submitted_at TEXT NOT NULL)""",
        "ALTER TABLE rfqs ADD CONSTRAINT fk_rfqs_awarded_bid FOREIGN KEY (awarded_bid_id) REFERENCES bids(id)",
        """CREATE TABLE auction_events (id BIGSERIAL PRIMARY KEY, rfq_id BIGINT NOT NULL REFERENCES rfqs(id) ON DELETE CASCADE,
        event_type TEXT NOT NULL, message TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)""",
        """CREATE TABLE idempotency_records (id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        operation TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
        response_status INTEGER NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(user_id, operation, idempotency_key))""",
        """CREATE TABLE security_audit_log (id BIGSERIAL PRIMARY KEY, tenant_id TEXT,
        actor_user_id BIGINT REFERENCES users(id), action TEXT NOT NULL, outcome TEXT NOT NULL,
        resource_type TEXT, resource_id TEXT, request_id TEXT, ip_hash TEXT,
        details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)""",
        "CREATE TABLE login_attempts (id BIGSERIAL PRIMARY KEY, key_hash TEXT NOT NULL, attempted_at TEXT NOT NULL)",
        "CREATE INDEX idx_sessions_token_expiry ON sessions(token_hash, expires_at)",
        "CREATE INDEX idx_rfqs_tenant_created ON rfqs(tenant_id, created_at DESC)",
        "CREATE INDEX idx_users_tenant_role ON users(tenant_id, role)",
        "CREATE INDEX idx_bids_rfq_price ON bids(rfq_id, total_price, submitted_at)",
        "CREATE INDEX idx_bids_bidder ON bids(bidder_user_id, submitted_at DESC)",
        "CREATE INDEX idx_events_rfq_created ON auction_events(rfq_id, created_at DESC)",
        "CREATE INDEX idx_idempotency_created ON idempotency_records(created_at)",
        "CREATE INDEX idx_security_audit_tenant_created ON security_audit_log(tenant_id, created_at DESC)",
        "CREATE INDEX idx_login_attempts_key_time ON login_attempts(key_hash, attempted_at)",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    for table in ("login_attempts", "security_audit_log", "idempotency_records", "auction_events", "bids", "rfqs", "sessions", "users"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
