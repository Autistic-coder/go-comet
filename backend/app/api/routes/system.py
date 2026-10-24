from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException

from ...database import connection, using_postgres
from ...services.outbox import drain as drain_outbox

router = APIRouter(tags=["operations"])


@router.get("/api/health")
def health() -> dict:
    with connection() as db:
        db.execute("SELECT 1").fetchone()
    return {"status": "ok", "service": "gocomet-auctions", "version": "4.0.0",
            "database": "postgresql" if using_postgres() else "sqlite-demo"}


@router.post("/api/internal/outbox/drain", include_in_schema=False)
def process_outbox(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> dict:
    expected = os.getenv("OUTBOX_WORKER_TOKEN", "")
    presented = authorization.removeprefix("Bearer ") if authorization else ""
    if not expected or not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="Invalid worker credential")
    with connection() as db:
        return drain_outbox(db)
