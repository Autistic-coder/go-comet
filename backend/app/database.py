from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "rfq.db"


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

