from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import connection, init_db
from .schemas import BidCreate, RfqCreate


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return as_utc(value).isoformat()


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def auction_status(rfq: sqlite3.Row, now: datetime) -> str:
    forced_close = parse(rfq["forced_close_at"])
    current_close = parse(rfq["current_close_at"])
    if now >= forced_close and current_close >= forced_close:
        return "force_closed"
    if now >= current_close:
        return "closed"
    if now < parse(rfq["bid_start_at"]):
        return "scheduled"
    return "active"


def ranked_bids(db: sqlite3.Connection, rfq_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM bids WHERE rfq_id = ? ORDER BY total_price ASC, submitted_at ASC",
        (rfq_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "supplier_name": row["supplier_name"],
            "carrier_name": row["carrier_name"],
            "freight_charges": row["freight_charges"],
            "origin_charges": row["origin_charges"],
            "destination_charges": row["destination_charges"],
            "transit_time_days": row["transit_time_days"],
            "validity_date": row["validity_date"],
            "total_price": row["total_price"],
            "submitted_at": row["submitted_at"],
            "rank": rank,
        }
        for rank, row in enumerate(rows, start=1)
    ]


def serialize_summary(db: sqlite3.Connection, rfq: sqlite3.Row, now: datetime) -> dict:
    aggregate = db.execute(
        "SELECT MIN(total_price) AS lowest_bid, COUNT(*) AS bid_count FROM bids WHERE rfq_id = ?",
        (rfq["id"],),
    ).fetchone()
    return {
        "id": rfq["id"],
        "reference_id": rfq["reference_id"],
        "name": rfq["name"],
        "bid_start_at": rfq["bid_start_at"],
        "current_close_at": rfq["current_close_at"],
        "forced_close_at": rfq["forced_close_at"],
        "status": auction_status(rfq, now),
        "lowest_bid": aggregate["lowest_bid"],
        "bid_count": aggregate["bid_count"],
    }


def serialize_detail(db: sqlite3.Connection, rfq: sqlite3.Row, now: datetime) -> dict:
    payload = serialize_summary(db, rfq, now)
    events = db.execute(
        "SELECT id, event_type, message, created_at FROM auction_events WHERE rfq_id = ? ORDER BY created_at DESC, id DESC",
        (rfq["id"],),
    ).fetchall()
    payload.update(
        {
            "original_close_at": rfq["original_close_at"],
            "pickup_service_at": rfq["pickup_service_at"],
            "trigger_window_minutes": rfq["trigger_window_minutes"],
            "extension_minutes": rfq["extension_minutes"],
            "extension_trigger": rfq["extension_trigger"],
            "bids": ranked_bids(db, rfq["id"]),
            "events": [dict(event) for event in events],
        }
    )
    return payload


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="GoComet British Auction API",
    version="1.0.0",
    description="RFQ bidding with configurable anti-sniping extensions and a hard forced close.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "gocomet-auctions"}


@app.post("/api/rfqs", status_code=status.HTTP_201_CREATED)
def create_rfq(payload: RfqCreate) -> dict:
    now = utc_now()
    values = (
        payload.reference_id.strip(),
        payload.name.strip(),
        iso(payload.bid_start_at),
        iso(payload.bid_close_at),
        iso(payload.bid_close_at),
        iso(payload.forced_close_at),
        iso(payload.pickup_service_at),
        payload.trigger_window_minutes,
        payload.extension_minutes,
        payload.extension_trigger.value,
        iso(now),
    )
    with connection() as db:
        try:
            cursor = db.execute(
                """INSERT INTO rfqs (
                    reference_id, name, bid_start_at, original_close_at, current_close_at,
                    forced_close_at, pickup_service_at, trigger_window_minutes,
                    extension_minutes, extension_trigger, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="RFQ reference ID already exists") from exc
        rfq_id = cursor.lastrowid
        db.execute(
            "INSERT INTO auction_events (rfq_id, event_type, message, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (rfq_id, "auction_created", "British auction created", "{}", iso(now)),
        )
        rfq = db.execute("SELECT * FROM rfqs WHERE id = ?", (rfq_id,)).fetchone()
        return serialize_detail(db, rfq, now)


@app.get("/api/rfqs")
def list_rfqs(
    status_filter: str | None = Query(default=None, alias="status"),
    now: datetime | None = Query(default=None),
) -> list[dict]:
    moment = as_utc(now) if now else utc_now()
    with connection() as db:
        rows = db.execute("SELECT * FROM rfqs ORDER BY created_at DESC").fetchall()
        items = [serialize_summary(db, row, moment) for row in rows]
        if status_filter and status_filter != "all":
            items = [item for item in items if item["status"] == status_filter]
        return items


@app.get("/api/rfqs/{rfq_id}")
def get_rfq(rfq_id: int, now: datetime | None = Query(default=None)) -> dict:
    moment = as_utc(now) if now else utc_now()
    with connection() as db:
        rfq = db.execute("SELECT * FROM rfqs WHERE id = ?", (rfq_id,)).fetchone()
        if not rfq:
            raise HTTPException(status_code=404, detail="RFQ not found")
        return serialize_detail(db, rfq, moment)


@app.post("/api/rfqs/{rfq_id}/bids", status_code=status.HTTP_201_CREATED)
def submit_bid(rfq_id: int, payload: BidCreate) -> dict:
    submitted_at = as_utc(payload.submitted_at) if payload.submitted_at else utc_now()
    total = round(payload.freight_charges + payload.origin_charges + payload.destination_charges, 2)

    with connection() as db:
        rfq = db.execute("SELECT * FROM rfqs WHERE id = ?", (rfq_id,)).fetchone()
        if not rfq:
            raise HTTPException(status_code=404, detail="RFQ not found")
        if auction_status(rfq, submitted_at) != "active":
            raise HTTPException(status_code=409, detail="Auction is not active at the submitted time")
        if as_utc(payload.validity_date) <= submitted_at:
            raise HTTPException(status_code=422, detail="Quote validity must be after bid submission")

        previous = ranked_bids(db, rfq_id)
        previous_order = [bid["supplier_name"] for bid in previous]
        previous_l1 = previous_order[0] if previous_order else None

        db.execute(
            """INSERT INTO bids (
                rfq_id, supplier_name, carrier_name, freight_charges, origin_charges,
                destination_charges, transit_time_days, validity_date, total_price, submitted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rfq_id,
                payload.supplier_name.strip(),
                payload.carrier_name.strip(),
                payload.freight_charges,
                payload.origin_charges,
                payload.destination_charges,
                payload.transit_time_days,
                iso(payload.validity_date),
                total,
                iso(submitted_at),
            ),
        )
        db.execute(
            "INSERT INTO auction_events (rfq_id, event_type, message, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                rfq_id,
                "bid_submitted",
                f"{payload.supplier_name.strip()} submitted a bid of {total:,.2f}",
                json.dumps({"supplier": payload.supplier_name.strip(), "total": total}),
                iso(submitted_at),
            ),
        )

        current = ranked_bids(db, rfq_id)
        current_order = [bid["supplier_name"] for bid in current]
        current_l1 = current_order[0] if current_order else None
        in_window = submitted_at >= parse(rfq["current_close_at"]) - timedelta(
            minutes=rfq["trigger_window_minutes"]
        )
        trigger = rfq["extension_trigger"]
        should_extend = in_window and (
            trigger == "bid_received"
            or (trigger == "any_rank_change" and previous_order != current_order)
            or (trigger == "lowest_bidder_change" and previous_l1 != current_l1)
        )

        if should_extend:
            old_close = parse(rfq["current_close_at"])
            forced_close = parse(rfq["forced_close_at"])
            new_close = min(old_close + timedelta(minutes=rfq["extension_minutes"]), forced_close)
            if new_close > old_close:
                reason = {
                    "bid_received": "bid received inside the trigger window",
                    "any_rank_change": "supplier ranking changed inside the trigger window",
                    "lowest_bidder_change": "the lowest bidder changed inside the trigger window",
                }[trigger]
                db.execute("UPDATE rfqs SET current_close_at = ? WHERE id = ?", (iso(new_close), rfq_id))
                db.execute(
                    "INSERT INTO auction_events (rfq_id, event_type, message, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        rfq_id,
                        "auction_extended",
                        f"Auction extended to {new_close.isoformat()} because {reason}",
                        json.dumps({"old_close": iso(old_close), "new_close": iso(new_close), "reason": reason}),
                        iso(submitted_at),
                    ),
                )

        updated = db.execute("SELECT * FROM rfqs WHERE id = ?", (rfq_id,)).fetchone()
        return serialize_detail(db, updated, submitted_at)


# In production the Docker build places Vite's output here. API routes are
# registered first so this SPA fallback can safely handle all remaining paths.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str) -> FileResponse:
        candidate = (FRONTEND_DIST / full_path).resolve()
        if candidate.is_relative_to(FRONTEND_DIST.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

