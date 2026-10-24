from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import (
    SESSION_COOKIE,
    SlidingWindowLimiter,
    UserContext,
    clear_auth_cookies,
    create_session,
    current_user,
    require_csrf,
    require_role,
    set_auth_cookies,
)
from .database import connection, init_db
from .schemas import AuctionStatus, BidCreate, LoginRequest, RfqCreate
from .security import token_hash, verify_password


MAX_API_BODY_BYTES = 32 * 1024
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")
login_limiter = SlidingWindowLimiter(attempts=5, window_seconds=300)
DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$180000$00112233445566778899aabbccddeeff$"
    "974edb851e78b8b609e8c279354cbbd9e2bc633dcf68acfc31561ec2df39392d"
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Timestamp must include a timezone",
        )
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
        "SELECT * FROM bids WHERE rfq_id = ? ORDER BY total_price ASC, submitted_at ASC, id ASC",
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
            "bidder_user_id": row["bidder_user_id"],
            "rank": rank,
        }
        for rank, row in enumerate(rows, start=1)
    ]


def _visible_bids(db: sqlite3.Connection, rfq_id: int, viewer: UserContext) -> list[dict]:
    result = []
    for bid in ranked_bids(db, rfq_id):
        is_own = bid["bidder_user_id"] == viewer.id
        if viewer.role == "bidder" and not is_own:
            bid["supplier_name"] = "Anonymous supplier"
            bid["carrier_name"] = "Hidden during auction"
        bid["is_own"] = is_own
        bid.pop("bidder_user_id", None)
        result.append(bid)
    return result


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


def _visible_events(db: sqlite3.Connection, rfq_id: int, viewer: UserContext) -> list[dict]:
    rows = db.execute(
        """SELECT id, event_type, message, metadata_json, created_at
        FROM auction_events WHERE rfq_id = ?
        ORDER BY created_at DESC, id DESC""",
        (rfq_id,),
    ).fetchall()
    events: list[dict] = []
    for row in rows:
        message = row["message"]
        if viewer.role == "bidder" and row["event_type"] == "bid_submitted":
            metadata = json.loads(row["metadata_json"] or "{}")
            message = (
                f"You submitted a bid of {metadata.get('total', 0):,.2f}"
                if metadata.get("bidder_user_id") == viewer.id
                else "A supplier submitted a bid"
            )
        events.append(
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "message": message,
                "created_at": row["created_at"],
            }
        )
    return events


def serialize_detail(
    db: sqlite3.Connection,
    rfq: sqlite3.Row,
    now: datetime,
    viewer: UserContext,
) -> dict:
    payload = serialize_summary(db, rfq, now)
    payload.update(
        {
            "original_close_at": rfq["original_close_at"],
            "pickup_service_at": rfq["pickup_service_at"],
            "trigger_window_minutes": rfq["trigger_window_minutes"],
            "extension_minutes": rfq["extension_minutes"],
            "extension_trigger": rfq["extension_trigger"],
            "bids": _visible_bids(db, rfq["id"], viewer),
            "events": _visible_events(db, rfq["id"], viewer),
        }
    )
    return payload


def _payload_hash(payload: RfqCreate | BidCreate) -> str:
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _idempotency_key(raw: str) -> str:
    if not IDEMPOTENCY_PATTERN.fullmatch(raw):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key must be 8-128 safe ASCII characters",
        )
    return raw


def _replay_or_conflict(
    db: sqlite3.Connection,
    user_id: int,
    operation: str,
    key: str,
    request_hash: str,
) -> JSONResponse | None:
    row = db.execute(
        """SELECT request_hash, response_status, response_json
        FROM idempotency_records
        WHERE user_id = ? AND operation = ? AND idempotency_key = ?""",
        (user_id, operation, key),
    ).fetchone()
    if not row:
        return None
    if row["request_hash"] != request_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used with a different request",
        )
    return JSONResponse(
        status_code=row["response_status"],
        content=json.loads(row["response_json"]),
        headers={"Idempotency-Replayed": "true"},
    )


def _store_idempotency(
    db: sqlite3.Connection,
    user_id: int,
    operation: str,
    key: str,
    request_hash: str,
    response_status: int,
    payload: dict,
) -> None:
    db.execute(
        """INSERT INTO idempotency_records (
            user_id, operation, idempotency_key, request_hash,
            response_status, response_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            operation,
            key,
            request_hash,
            response_status,
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            iso(utc_now()),
        ),
    )


def _allowed_origins() -> list[str]:
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return ["http://localhost:5173", "http://127.0.0.1:5173"]


def _allowed_hosts() -> list[str]:
    configured = os.getenv("ALLOWED_HOSTS", "")
    if configured:
        return [host.strip() for host in configured.split(",") if host.strip()]
    return ["localhost", "127.0.0.1", "testserver", "*.vercel.app", "*.onrender.com"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="GoComet British Auction API",
    version="2.0.0",
    description="Role-aware RFQ bidding with idempotent writes and hard forced-close rules.",
    lifespan=lifespan,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts())
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token", "X-Request-ID"],
    max_age=600,
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    request_id_header = request.headers.get("X-Request-ID", "")
    request_id = (
        request_id_header
        if REQUEST_ID_PATTERN.fullmatch(request_id_header)
        else str(uuid.uuid4())
    )
    if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH"}:
        raw_length = request.headers.get("content-length")
        try:
            content_length = int(raw_length) if raw_length else 0
        except ValueError:
            content_length = MAX_API_BODY_BYTES + 1
        if content_length > MAX_API_BODY_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": "Request body is too large"},
                headers={"X-Request-ID": request_id},
            )
        body = await request.body()
        if len(body) > MAX_API_BODY_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": "Request body is too large"},
                headers={"X-Request-ID": request_id},
            )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(sqlite3.OperationalError)
async def database_error_handler(_: Request, __: sqlite3.OperationalError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "The auction service is temporarily unavailable"},
        headers={"Retry-After": "2"},
    )


@app.get("/api/health")
def health() -> dict:
    with connection() as db:
        db.execute("SELECT 1").fetchone()
    return {"status": "ok", "service": "gocomet-auctions", "version": "2.0.0"}


@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    email = str(payload.email).lower()
    client_host = request.client.host if request.client else "unknown"
    rate_key = f"{client_host}:{email}"
    login_limiter.check(rate_key)
    with connection() as db:
        row = db.execute(
            "SELECT * FROM users WHERE email = ? AND is_active = 1",
            (email,),
        ).fetchone()
    valid_password = verify_password(
        payload.password,
        row["password_hash"] if row else DUMMY_PASSWORD_HASH,
    )
    if not row or not valid_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    session_token, csrf_token = create_session(row["id"])
    set_auth_cookies(response, session_token, csrf_token)
    login_limiter.reset(rate_key)
    return {
        "user": {
            "id": row["id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "role": row["role"],
            "supplier_name": row["supplier_name"],
            "carrier_name": row["carrier_name"],
        }
    }


@app.get("/api/auth/session")
def session(user: UserContext = Depends(current_user)) -> dict:
    return {"user": user.public()}


@app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    _: UserContext = Depends(require_csrf),
) -> Response:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        with connection() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(raw_token),))
    clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


@app.post("/api/rfqs", status_code=status.HTTP_201_CREATED)
def create_rfq(
    payload: RfqCreate,
    idempotency_key: IdempotencyHeader,
    user: UserContext = Depends(require_role("buyer")),
    _: UserContext = Depends(require_csrf),
) -> JSONResponse:
    key = _idempotency_key(idempotency_key)
    request_hash = _payload_hash(payload)
    operation = "create_rfq"
    now = utc_now()
    values = (
        payload.reference_id,
        payload.name,
        iso(payload.bid_start_at),
        iso(payload.bid_close_at),
        iso(payload.bid_close_at),
        iso(payload.forced_close_at),
        iso(payload.pickup_service_at),
        payload.trigger_window_minutes,
        payload.extension_minutes,
        payload.extension_trigger.value,
        user.id,
        iso(now),
    )
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        replay = _replay_or_conflict(db, user.id, operation, key, request_hash)
        if replay:
            return replay
        try:
            cursor = db.execute(
                """INSERT INTO rfqs (
                    reference_id, name, bid_start_at, original_close_at, current_close_at,
                    forced_close_at, pickup_service_at, trigger_window_minutes,
                    extension_minutes, extension_trigger, created_by_user_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="RFQ reference ID already exists") from exc
        rfq_id = int(cursor.lastrowid)
        db.execute(
            """INSERT INTO auction_events (
                rfq_id, event_type, message, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?)""",
            (
                rfq_id,
                "auction_created",
                "British auction created",
                json.dumps({"actor_user_id": user.id, "actor_role": user.role}),
                iso(now),
            ),
        )
        rfq = db.execute("SELECT * FROM rfqs WHERE id = ?", (rfq_id,)).fetchone()
        result = serialize_detail(db, rfq, now, user)
        _store_idempotency(db, user.id, operation, key, request_hash, 201, result)
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=result,
            headers={"Idempotency-Replayed": "false"},
        )


@app.get("/api/rfqs")
def list_rfqs(
    status_filter: AuctionStatus | None = Query(default=None, alias="status"),
    now: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
    _: UserContext = Depends(current_user),
) -> list[dict]:
    moment = as_utc(now) if now else utc_now()
    with connection() as db:
        rows = db.execute(
            "SELECT * FROM rfqs ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        items = [serialize_summary(db, row, moment) for row in rows]
        if status_filter:
            items = [item for item in items if item["status"] == status_filter.value]
        return items


@app.get("/api/rfqs/{rfq_id}")
def get_rfq(
    rfq_id: int,
    now: datetime | None = Query(default=None),
    user: UserContext = Depends(current_user),
) -> dict:
    moment = as_utc(now) if now else utc_now()
    with connection() as db:
        rfq = db.execute("SELECT * FROM rfqs WHERE id = ?", (rfq_id,)).fetchone()
        if not rfq:
            raise HTTPException(status_code=404, detail="RFQ not found")
        return serialize_detail(db, rfq, moment, user)


@app.post("/api/rfqs/{rfq_id}/bids", status_code=status.HTTP_201_CREATED)
def submit_bid(
    rfq_id: int,
    payload: BidCreate,
    idempotency_key: IdempotencyHeader,
    user: UserContext = Depends(require_role("bidder")),
    _: UserContext = Depends(require_csrf),
) -> JSONResponse:
    key = _idempotency_key(idempotency_key)
    request_hash = _payload_hash(payload)
    operation = f"submit_bid:{rfq_id}"
    submitted_at = utc_now()
    total_decimal = (
        payload.freight_charges + payload.origin_charges + payload.destination_charges
    ).quantize(Decimal("0.01"))
    total = float(total_decimal)

    if not user.supplier_name or not user.carrier_name:
        raise HTTPException(status_code=409, detail="Bidder profile is incomplete")

    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        replay = _replay_or_conflict(db, user.id, operation, key, request_hash)
        if replay:
            return replay
        rfq = db.execute("SELECT * FROM rfqs WHERE id = ?", (rfq_id,)).fetchone()
        if not rfq:
            raise HTTPException(status_code=404, detail="RFQ not found")
        if auction_status(rfq, submitted_at) != "active":
            raise HTTPException(status_code=409, detail="Auction is not active")
        if as_utc(payload.validity_date) <= submitted_at:
            raise HTTPException(status_code=422, detail="Quote validity must be after bid submission")

        previous = ranked_bids(db, rfq_id)
        previous_order = [bid["bidder_user_id"] or bid["supplier_name"] for bid in previous]
        previous_l1 = previous_order[0] if previous_order else None

        db.execute(
            """INSERT INTO bids (
                rfq_id, supplier_name, carrier_name, freight_charges, origin_charges,
                destination_charges, transit_time_days, validity_date, total_price,
                bidder_user_id, submitted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rfq_id,
                user.supplier_name,
                user.carrier_name,
                float(payload.freight_charges),
                float(payload.origin_charges),
                float(payload.destination_charges),
                payload.transit_time_days,
                iso(payload.validity_date),
                total,
                user.id,
                iso(submitted_at),
            ),
        )
        db.execute(
            """INSERT INTO auction_events (
                rfq_id, event_type, message, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?)""",
            (
                rfq_id,
                "bid_submitted",
                f"{user.supplier_name} submitted a bid of {total:,.2f}",
                json.dumps(
                    {
                        "bidder_user_id": user.id,
                        "supplier": user.supplier_name,
                        "total": total,
                    }
                ),
                iso(submitted_at),
            ),
        )

        current = ranked_bids(db, rfq_id)
        current_order = [bid["bidder_user_id"] or bid["supplier_name"] for bid in current]
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
                    """INSERT INTO auction_events (
                        rfq_id, event_type, message, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        rfq_id,
                        "auction_extended",
                        f"Auction extended to {new_close.isoformat()} because {reason}",
                        json.dumps(
                            {
                                "old_close": iso(old_close),
                                "new_close": iso(new_close),
                                "reason": reason,
                                "actor_user_id": user.id,
                            }
                        ),
                        iso(submitted_at),
                    ),
                )

        updated = db.execute("SELECT * FROM rfqs WHERE id = ?", (rfq_id,)).fetchone()
        result = serialize_detail(db, updated, submitted_at, user)
        _store_idempotency(db, user.id, operation, key, request_hash, 201, result)
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=result,
            headers={"Idempotency-Replayed": "false"},
        )


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
