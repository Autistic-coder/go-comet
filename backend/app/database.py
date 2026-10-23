from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "rfq.db"


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _demo_data_enabled() -> bool:
    return os.getenv("SEED_DEMO_DATA", "false").lower() in {"1", "true", "yes", "on"}


def get_db_path() -> Path:
    return Path(os.getenv("RFQ_DATABASE_PATH", str(DEFAULT_DB_PATH)))


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(get_db_path(), check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
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
            """
        )
        if _demo_data_enabled():
            seed_demo_data(db)


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

