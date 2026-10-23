from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def client_for(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("RFQ_DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("SEED_DEMO_DATA", "false")
    from app import main

    importlib.reload(main)
    return TestClient(main.app)


def create_auction(client: TestClient, trigger: str = "bid_received") -> tuple[int, datetime]:
    start = datetime(2030, 1, 1, 10, 0, tzinfo=timezone.utc)
    response = client.post(
        "/api/rfqs",
        json={
            "reference_id": f"RFQ-{trigger}",
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
    assert response.status_code == 201
    return response.json()["id"], start


def bid(client: TestClient, rfq_id: int, supplier: str, total: float, at: datetime):
    return client.post(
        f"/api/rfqs/{rfq_id}/bids",
        json={
            "supplier_name": supplier,
            "carrier_name": f"{supplier} Logistics",
            "freight_charges": total,
            "origin_charges": 0,
            "destination_charges": 0,
            "transit_time_days": 3,
            "validity_date": (at + timedelta(days=7)).isoformat(),
            "submitted_at": at.isoformat(),
        },
    )


def test_bid_inside_window_extends_but_never_past_forced_close(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        rfq_id, start = create_auction(client)
        first = bid(client, rfq_id, "Northstar", 1200, start + timedelta(minutes=55))
        assert first.status_code == 201
        assert first.json()["current_close_at"].endswith("11:05:00+00:00")

        second = bid(client, rfq_id, "Blue Dart", 1100, start + timedelta(minutes=64))
        assert second.json()["current_close_at"].endswith("11:10:00+00:00")

        third = bid(client, rfq_id, "ExpressCo", 1000, start + timedelta(minutes=69))
        assert third.json()["current_close_at"].endswith("11:12:00+00:00")


def test_l1_trigger_only_extends_when_leader_changes(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        rfq_id, start = create_auction(client, "lowest_bidder_change")
        first = bid(client, rfq_id, "Northstar", 1000, start + timedelta(minutes=45))
        assert first.status_code == 201

        losing_bid = bid(client, rfq_id, "Blue Dart", 1200, start + timedelta(minutes=55))
        assert losing_bid.json()["current_close_at"].endswith("11:00:00+00:00")

        winning_bid = bid(client, rfq_id, "Blue Dart", 900, start + timedelta(minutes=56))
        assert winning_bid.json()["current_close_at"].endswith("11:05:00+00:00")


def test_demo_seed_exposes_portfolio_to_frontend(tmp_path, monkeypatch):
    monkeypatch.setenv("RFQ_DATABASE_PATH", str(tmp_path / "demo.db"))
    monkeypatch.setenv("SEED_DEMO_DATA", "true")
    from app import main

    importlib.reload(main)
    with TestClient(main.app) as client:
        auctions = client.get("/api/rfqs").json()
        assert len(auctions) == 4
        assert {auction["status"] for auction in auctions} == {"active", "scheduled", "closed", "force_closed"}
        active = next(auction for auction in auctions if auction["status"] == "active")
        detail = client.get(f"/api/rfqs/{active['id']}").json()
        assert detail["bid_count"] == 4
        assert detail["bids"][0]["supplier_name"] == "Rivigo Express"

