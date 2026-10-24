from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .security import hash_password


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "rfq.db"


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _demo_data_enabled() -> bool:
    return os.getenv("SEED_DEMO_DATA", "false").lower() in {"1", "true", "yes", "on"}


def get_db_path() -> Path:
    return Path(os.getenv("RFQ_DATABASE_PATH", str(DEFAULT_DB_PATH)))


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 10000")
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA synchronous = NORMAL")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    with connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 2 AND 100),
                role TEXT NOT NULL CHECK (role IN ('buyer', 'bidder')),
                supplier_name TEXT,
                carrier_name TEXT,
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                csrf_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_token_expiry
            ON sessions(token_hash, expires_at);

            CREATE TABLE IF NOT EXISTS rfqs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                bid_start_at TEXT NOT NULL,
                original_close_at TEXT NOT NULL,
                current_close_at TEXT NOT NULL,
                forced_close_at TEXT NOT NULL,
                pickup_service_at TEXT NOT NULL,
                trigger_window_minutes INTEGER NOT NULL CHECK (trigger_window_minutes > 0),
                extension_minutes INTEGER NOT NULL CHECK (extension_minutes > 0),
                extension_trigger TEXT NOT NULL CHECK (
                    extension_trigger IN ('bid_received', 'any_rank_change', 'lowest_bidder_change')
                ),
                created_by_user_id INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rfq_id INTEGER NOT NULL REFERENCES rfqs(id) ON DELETE CASCADE,
                supplier_name TEXT NOT NULL,
                carrier_name TEXT NOT NULL,
                freight_charges REAL NOT NULL CHECK (freight_charges >= 0),
                origin_charges REAL NOT NULL CHECK (origin_charges >= 0),
                destination_charges REAL NOT NULL CHECK (destination_charges >= 0),
                transit_time_days INTEGER NOT NULL CHECK (transit_time_days > 0),
                validity_date TEXT NOT NULL,
                total_price REAL NOT NULL CHECK (total_price >= 0),
                bidder_user_id INTEGER REFERENCES users(id),
                submitted_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_bids_rfq_price
            ON bids(rfq_id, total_price, submitted_at);

            CREATE TABLE IF NOT EXISTS auction_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rfq_id INTEGER NOT NULL REFERENCES rfqs(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_events_rfq_created
            ON auction_events(rfq_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS idempotency_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                operation TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                response_status INTEGER NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, operation, idempotency_key)
            );

            CREATE INDEX IF NOT EXISTS idx_idempotency_created
            ON idempotency_records(created_at);
            """
        )
        _migrate_legacy_schema(db)
        seed_mock_users(db)
        retention_cutoff = _stamp(datetime.now(timezone.utc) - timedelta(hours=24))
        db.execute("DELETE FROM idempotency_records WHERE created_at < ?", (retention_cutoff,))
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (_stamp(datetime.now(timezone.utc)),))
        if _demo_data_enabled():
            seed_demo_data(db)


def _column_names(db: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_legacy_schema(db: sqlite3.Connection) -> None:
    if "created_by_user_id" not in _column_names(db, "rfqs"):
        db.execute("ALTER TABLE rfqs ADD COLUMN created_by_user_id INTEGER REFERENCES users(id)")
    if "bidder_user_id" not in _column_names(db, "bids"):
        db.execute("ALTER TABLE bids ADD COLUMN bidder_user_id INTEGER REFERENCES users(id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_bids_bidder ON bids(bidder_user_id, submitted_at DESC)")


def seed_mock_users(db: sqlite3.Connection) -> None:
    now = _stamp(datetime.now(timezone.utc))
    demo_users = (
        (
            "buyer.demo@example.com",
            "Aarav Mehta",
            "buyer",
            None,
            None,
            "BuyerDemo!2026",
        ),
        (
            "bidder.demo@example.com",
            "Neha Sharma",
            "bidder",
            "Northstar Logistics",
            "Northstar Roadways",
            "BidderDemo!2026",
        ),
    )
    for email, display_name, role, supplier_name, carrier_name, password in demo_users:
        exists = db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
        if exists:
            continue
        db.execute(
            """INSERT INTO users (
                email, display_name, role, supplier_name, carrier_name,
                password_hash, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
            (
                email,
                display_name,
                role,
                supplier_name,
                carrier_name,
                hash_password(password),
                now,
            ),
        )


def seed_demo_data(db: sqlite3.Connection) -> None:
    """Populate a new database with a useful, time-relative demo portfolio."""
    if db.execute("SELECT 1 FROM rfqs LIMIT 1").fetchone():
        return

    now = datetime.now(timezone.utc).replace(microsecond=0)
    auctions = [
        {
            "reference_id": "RFQ-DEMO-1042",
            "name": "Mumbai → Delhi · Full Truck Load",
            "bid_start_at": now - timedelta(hours=2),
            "original_close_at": now + timedelta(minutes=10),
            "current_close_at": now + timedelta(minutes=25),
            "forced_close_at": now + timedelta(minutes=50),
            "pickup_service_at": now + timedelta(days=2),
            "trigger_window_minutes": 10,
            "extension_minutes": 5,
            "extension_trigger": "lowest_bidder_change",
            "created_at": now - timedelta(hours=4),
        },
        {
            "reference_id": "RFQ-DEMO-1043",
            "name": "Bengaluru → Chennai · Express Cargo",
            "bid_start_at": now + timedelta(hours=4),
            "original_close_at": now + timedelta(hours=7),
            "current_close_at": now + timedelta(hours=7),
            "forced_close_at": now + timedelta(hours=7, minutes=30),
            "pickup_service_at": now + timedelta(days=4),
            "trigger_window_minutes": 15,
            "extension_minutes": 5,
            "extension_trigger": "bid_received",
            "created_at": now - timedelta(hours=2),
        },
        {
            "reference_id": "RFQ-DEMO-1039",
            "name": "Pune → Hyderabad · Refrigerated",
            "bid_start_at": now - timedelta(hours=30),
            "original_close_at": now - timedelta(hours=6),
            "current_close_at": now - timedelta(hours=6),
            "forced_close_at": now - timedelta(hours=5, minutes=30),
            "pickup_service_at": now + timedelta(days=1),
            "trigger_window_minutes": 10,
            "extension_minutes": 5,
            "extension_trigger": "any_rank_change",
            "created_at": now - timedelta(hours=32),
        },
        {
            "reference_id": "RFQ-DEMO-1037",
            "name": "Ahmedabad → Jaipur · Part Load",
            "bid_start_at": now - timedelta(hours=54),
            "original_close_at": now - timedelta(hours=30),
            "current_close_at": now - timedelta(hours=29, minutes=30),
            "forced_close_at": now - timedelta(hours=29, minutes=30),
            "pickup_service_at": now - timedelta(hours=20),
            "trigger_window_minutes": 10,
            "extension_minutes": 5,
            "extension_trigger": "bid_received",
            "created_at": now - timedelta(hours=56),
        },
    ]

    ids: dict[str, int] = {}
    for auction in auctions:
        cursor = db.execute(
            """INSERT INTO rfqs (
                reference_id, name, bid_start_at, original_close_at, current_close_at,
                forced_close_at, pickup_service_at, trigger_window_minutes,
                extension_minutes, extension_trigger, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                auction["reference_id"], auction["name"], _stamp(auction["bid_start_at"]),
                _stamp(auction["original_close_at"]), _stamp(auction["current_close_at"]),
                _stamp(auction["forced_close_at"]), _stamp(auction["pickup_service_at"]),
                auction["trigger_window_minutes"], auction["extension_minutes"],
                auction["extension_trigger"], _stamp(auction["created_at"]),
            ),
        )
        ids[auction["reference_id"]] = int(cursor.lastrowid)
        db.execute(
            "INSERT INTO auction_events (rfq_id, event_type, message, metadata_json, created_at) VALUES (?, ?, ?, '{}', ?)",
            (cursor.lastrowid, "auction_created", "British auction created", _stamp(auction["created_at"])),
        )

    def add_bid(
        reference: str,
        supplier: str,
        carrier: str,
        freight: float,
        origin: float,
        destination: float,
        transit_days: int,
        submitted_at: datetime,
    ) -> None:
        total = freight + origin + destination
        rfq_id = ids[reference]
        db.execute(
            """INSERT INTO bids (
                rfq_id, supplier_name, carrier_name, freight_charges, origin_charges,
                destination_charges, transit_time_days, validity_date, total_price, submitted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rfq_id, supplier, carrier, freight, origin, destination, transit_days,
                _stamp(submitted_at + timedelta(days=7)), total, _stamp(submitted_at),
            ),
        )
        db.execute(
            "INSERT INTO auction_events (rfq_id, event_type, message, metadata_json, created_at) VALUES (?, ?, ?, '{}', ?)",
            (rfq_id, "bid_submitted", f"{supplier} submitted a bid of {total:,.2f}", _stamp(submitted_at)),
        )

    add_bid("RFQ-DEMO-1042", "Swift Freight", "Swift Roadways", 82_000, 4_000, 3_500, 4, now - timedelta(minutes=95))
    add_bid("RFQ-DEMO-1042", "BlueDart Logistics", "BlueDart Surface", 84_000, 4_200, 3_600, 3, now - timedelta(minutes=70))
    add_bid("RFQ-DEMO-1042", "Delhivery", "Delhivery Freight", 80_500, 3_900, 3_400, 3, now - timedelta(minutes=40))
    add_bid("RFQ-DEMO-1042", "Rivigo Express", "Rivigo Relay", 79_500, 3_800, 3_200, 2, now - timedelta(minutes=12))
    add_bid("RFQ-DEMO-1039", "ColdChain India", "CCI Reefer", 112_000, 5_500, 4_500, 2, now - timedelta(hours=18))
    add_bid("RFQ-DEMO-1039", "Snowman Logistics", "Snowman Reefer", 108_000, 5_000, 4_200, 2, now - timedelta(hours=12))
    add_bid("RFQ-DEMO-1039", "TCI Cold Chain", "TCI Refrigerated", 106_500, 4_800, 4_000, 3, now - timedelta(hours=7))
    add_bid("RFQ-DEMO-1037", "Jaipur Golden", "JG Transport", 61_000, 3_000, 2_400, 3, now - timedelta(hours=34))
    add_bid("RFQ-DEMO-1037", "Safexpress", "Safexpress Surface", 59_500, 2_800, 2_200, 3, now - timedelta(hours=30, minutes=5))

    active_id = ids["RFQ-DEMO-1042"]
    for minutes_ago, close_delta in ((18, 15), (14, 20), (9, 25)):
        close_at = now + timedelta(minutes=close_delta)
        db.execute(
            "INSERT INTO auction_events (rfq_id, event_type, message, metadata_json, created_at) VALUES (?, ?, ?, '{}', ?)",
            (
                active_id,
                "auction_extended",
                f"Auction extended to {_stamp(close_at)} because the lowest bidder changed",
                _stamp(now - timedelta(minutes=minutes_ago)),
            ),
        )

    force_closed_id = ids["RFQ-DEMO-1037"]
    db.execute(
        "INSERT INTO auction_events (rfq_id, event_type, message, metadata_json, created_at) VALUES (?, ?, ?, '{}', ?)",
        (
            force_closed_id,
            "auction_extended",
            "Auction reached its forced close after the final qualifying bid",
            _stamp(now - timedelta(hours=29, minutes=30)),
        ),
    )

