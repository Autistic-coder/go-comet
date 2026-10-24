from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from types import ModuleType
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


DEMO_CREDENTIALS = {
    "buyer": ("buyer.demo@example.com", "BuyerDemo!2026"),
    "bidder": ("bidder.demo@example.com", "BidderDemo!2026"),
}


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("RFQ_DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("SEED_DEMO_DATA", "false")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("PASSWORD_HASH_ITERATIONS", "1000")
    from app import main

    importlib.reload(main)
    with TestClient(main.app) as client:
        yield client, main


@pytest.fixture
def demo_client(tmp_path, monkeypatch):
    monkeypatch.setenv("RFQ_DATABASE_PATH", str(tmp_path / "demo.db"))
    monkeypatch.setenv("SEED_DEMO_DATA", "true")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("PASSWORD_HASH_ITERATIONS", "1000")
    from app import main

    importlib.reload(main)
    with TestClient(main.app) as client:
        yield client, main


def login(client: TestClient, role: str) -> dict:
    email, password = DEMO_CREDENTIALS[role]
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["user"]


def csrf_headers(client: TestClient, *, key: str | None = None) -> dict[str, str]:
    token = client.cookies.get("gocomet_csrf")
    assert token
    headers = {"X-CSRF-Token": token}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def create_auction(
    client: TestClient,
    main: ModuleType,
    *,
    trigger: str = "bid_received",
    reference_id: str | None = None,
    base: datetime | None = None,
    key: str | None = None,
):
    start = base or datetime(2030, 1, 1, 10, 0, tzinfo=timezone.utc)
    main.utc_now = lambda: start
    response = client.post(
        "/api/rfqs",
        headers=csrf_headers(client, key=key or f"create-{uuid4()}"),
        json={
            "reference_id": reference_id or f"RFQ-{uuid4().hex[:10]}",
            "name": "Mumbai to Delhi lane",
            "bid_start_at": start.isoformat(),
            "bid_close_at": (start + timedelta(hours=1)).isoformat(),
            "forced_close_at": (start + timedelta(hours=1, minutes=12)).isoformat(),
            "pickup_service_at": (start + timedelta(days=2)).isoformat(),
            "trigger_window_minutes": 10,
            "extension_minutes": 5,
            "extension_trigger": trigger,
        },
    )
    return response, start


def submit_bid(
    client: TestClient,
    main: ModuleType,
    rfq_id: int,
    total: float,
    at: datetime,
    *,
    key: str | None = None,
):
    main.utc_now = lambda: at
    return client.post(
        f"/api/rfqs/{rfq_id}/bids",
        headers=csrf_headers(client, key=key or f"bid-{uuid4()}"),
        json={
            "freight_charges": total,
            "origin_charges": 0,
            "destination_charges": 0,
            "transit_time_days": 3,
            "validity_date": (at + timedelta(days=7)).isoformat(),
        },
    )
