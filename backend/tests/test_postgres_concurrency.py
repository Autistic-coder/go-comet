from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(os.getenv("TEST_POSTGRES") != "1", reason="requires PostgreSQL")


def _login(client: TestClient, role: str) -> None:
    credentials = {
        "buyer": ("buyer.demo@example.com", "BuyerDemo!2026"),
        "bidder": ("bidder.demo@example.com", "BidderDemo!2026"),
    }
    assert client.post("/api/auth/login", json=dict(zip(("email", "password"), credentials[role]))).status_code == 200


def _headers(client: TestClient, key: str) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["gocomet_csrf"], "Idempotency-Key": key}


def test_same_idempotency_key_racing_creates_one_bid(monkeypatch):
    monkeypatch.setenv("SEED_DEMO_DATA", "false")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("PASSWORD_HASH_ITERATIONS", "1000")
    from app import main

    now = datetime.now(timezone.utc).replace(microsecond=0)
    main.utc_now = lambda: now
    with TestClient(main.app) as buyer:
        _login(buyer, "buyer")
        create = buyer.post("/api/rfqs", headers=_headers(buyer, f"create-{uuid4()}"), json={
            "reference_id": f"PG-{uuid4().hex}", "name": "Postgres concurrency lane",
            "bid_start_at": (now - timedelta(minutes=1)).isoformat(),
            "bid_close_at": (now + timedelta(minutes=10)).isoformat(),
            "forced_close_at": (now + timedelta(minutes=20)).isoformat(),
            "pickup_service_at": (now + timedelta(days=1)).isoformat(),
            "trigger_window_minutes": 5, "extension_minutes": 2, "extension_trigger": "bid_received",
        })
        assert create.status_code == 201, create.text
        rfq_id = create.json()["id"]

        clients = [TestClient(main.app), TestClient(main.app)]
        for client in clients:
            client.__enter__()
            _login(client, "bidder")
        payload = {"freight_charges": "100.10", "origin_charges": "2.20", "destination_charges": "3.30",
                   "transit_time_days": 2, "validity_date": (now + timedelta(days=1)).isoformat()}
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(
                    lambda client: client.post(f"/api/rfqs/{rfq_id}/bids", headers=_headers(client, "pg-race-key-0001"), json=payload),
                    clients,
                ))
            assert [response.status_code for response in responses] == [201, 201]
            assert sum(response.headers.get("Idempotency-Replayed") == "true" for response in responses) == 1
            assert responses[0].json()["bid_count"] == responses[1].json()["bid_count"] == 1
        finally:
            for client in clients:
                client.__exit__(None, None, None)
