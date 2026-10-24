from __future__ import annotations

from datetime import timedelta

from app.database import connection
from conftest import create_auction, csrf_headers, login, submit_bid


def test_cross_tenant_object_is_indistinguishable_from_missing(app_client):
    client, main = app_client
    login(client, "buyer")
    created, _ = create_auction(client, main)
    assert created.status_code == 201
    rfq_id = created.json()["id"]

    with connection() as db:
        db.execute("UPDATE users SET tenant_id = 'adversarial-tenant' WHERE email = ?", ("buyer.demo@example.com",))

    assert client.get(f"/api/rfqs/{rfq_id}").status_code == 404
    assert all(item["id"] != rfq_id for item in client.get("/api/rfqs").json())


def test_decimal_money_and_outbox_are_atomic(app_client, monkeypatch):
    client, main = app_client
    login(client, "buyer")
    created, start = create_auction(client, main)
    rfq_id = created.json()["id"]
    with connection() as db:
        assert db.execute(
            "SELECT COUNT(*) AS count FROM notification_outbox WHERE aggregate_id = ?", (str(rfq_id),)
        ).fetchone()["count"] == 1

    client.post("/api/auth/logout", headers=csrf_headers(client))
    login(client, "bidder")
    bid = client.post(
        f"/api/rfqs/{rfq_id}/bids",
        headers=csrf_headers(client, key="decimal-bid-key-0001"),
        json={"freight_charges": "0.10", "origin_charges": "0.20", "destination_charges": "0.30",
              "transit_time_days": 1, "validity_date": (start + timedelta(days=1)).isoformat()},
    )
    assert bid.status_code == 201, bid.text
    own = next(item for item in bid.json()["bids"] if item["is_own"])
    assert own["total_price"] == "0.60"
    with connection() as db:
        assert str(db.execute("SELECT total_price FROM bids WHERE rfq_id = ?", (rfq_id,)).fetchone()["total_price"]) in {"0.6", "0.60"}
        assert db.execute("SELECT COUNT(*) AS count FROM notification_outbox WHERE aggregate_id = ?", (str(rfq_id),)).fetchone()["count"] == 2

    assert client.post("/api/internal/outbox/drain").status_code == 401
    with connection() as db:
        db.execute("UPDATE notification_outbox SET available_at = '2000-01-01T00:00:00+00:00'")
    monkeypatch.setenv("OUTBOX_WORKER_TOKEN", "test-worker-secret")
    drained = client.post("/api/internal/outbox/drain", headers={"Authorization": "Bearer test-worker-secret"})
    assert drained.status_code == 200
    assert drained.json()["delivered"] == 2


def test_prometheus_metrics_are_exposed(app_client):
    client, _ = app_client
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "gocomet_http_requests_total" in response.text
