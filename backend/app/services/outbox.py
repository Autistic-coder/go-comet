from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib import request

from ..database import using_postgres

logger = logging.getLogger("gocomet.outbox")


def enqueue(db, *, tenant_id: str, aggregate_id: int, event_type: str, payload: dict, created_at: str) -> None:
    db.execute(
        """INSERT INTO notification_outbox (
        tenant_id, aggregate_type, aggregate_id, event_type, payload_json,
        status, attempts, available_at, created_at
        ) VALUES (?, 'rfq', ?, ?, ?, 'pending', 0, ?, ?)""",
        (tenant_id, str(aggregate_id), event_type, json.dumps(payload, separators=(",", ":")), created_at, created_at),
    )


def drain(db, *, batch_size: int = 25) -> dict[str, int]:
    """Claim and deliver a small outbox batch. Retriable failures use bounded backoff."""
    now = datetime.now(timezone.utc)
    sql = """SELECT * FROM notification_outbox
        WHERE status IN ('pending','failed') AND available_at <= ?
        ORDER BY id LIMIT ?"""
    if using_postgres():
        sql += " FOR UPDATE SKIP LOCKED"
    rows = db.execute(sql, (now.isoformat(), batch_size)).fetchall()
    delivered = failed = 0
    for row in rows:
        db.execute(
            "UPDATE notification_outbox SET status = 'processing', locked_at = ?, attempts = attempts + 1 WHERE id = ?",
            (now.isoformat(), row["id"]),
        )
        try:
            _deliver(json.loads(row["payload_json"]))
            db.execute(
                "UPDATE notification_outbox SET status = 'delivered', delivered_at = ?, last_error = NULL WHERE id = ?",
                (now.isoformat(), row["id"]),
            )
            delivered += 1
        except Exception as exc:  # delivery failures must never roll back domain writes
            retry_at = now + timedelta(seconds=min(3600, 2 ** min(int(row["attempts"]) + 1, 10)))
            db.execute(
                "UPDATE notification_outbox SET status = 'failed', available_at = ?, last_error = ? WHERE id = ?",
                (retry_at.isoformat(), str(exc)[:500], row["id"]),
            )
            failed += 1
    return {"claimed": len(rows), "delivered": delivered, "failed": failed}


def _deliver(payload: dict) -> None:
    webhook = os.getenv("NOTIFICATION_WEBHOOK_URL")
    if not webhook:
        logger.info("notification_delivered sink=log event=%s", payload.get("event_type", "auction"))
        return
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(webhook, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=5) as response:  # nosec B310 - operator-controlled HTTPS URL
        if response.status >= 300:
            raise RuntimeError(f"notification webhook returned {response.status}")
