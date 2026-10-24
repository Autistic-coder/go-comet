from __future__ import annotations

from datetime import timedelta

from conftest import create_auction, login, submit_bid


def test_bid_inside_window_extends_but_never_past_forced_close(app_client):
    client, main = app_client
    login(client, "buyer")
    response, start = create_auction(client, main)
    assert response.status_code == 201
    rfq_id = response.json()["id"]

    login(client, "bidder")
    first = submit_bid(client, main, rfq_id, 1200, start + timedelta(minutes=55))
    assert first.status_code == 201
    assert first.json()["current_close_at"].endswith("11:05:00+00:00")
    second = submit_bid(client, main, rfq_id, 1100, start + timedelta(minutes=64))
    assert second.status_code == 201
    assert second.json()["current_close_at"].endswith("11:10:00+00:00")
    third = submit_bid(client, main, rfq_id, 1000, start + timedelta(minutes=69))
    assert third.status_code == 201
    assert third.json()["current_close_at"].endswith("11:12:00+00:00")


def test_l1_trigger_does_not_extend_for_losing_repeat_bid(app_client):
    client, main = app_client
    login(client, "buyer")
    response, start = create_auction(client, main, trigger="lowest_bidder_change")
    rfq_id = response.json()["id"]
    login(client, "bidder")
    first = submit_bid(client, main, rfq_id, 1000, start + timedelta(minutes=45))
    assert first.status_code == 201
    losing = submit_bid(client, main, rfq_id, 1200, start + timedelta(minutes=55))
    assert losing.status_code == 201
    assert losing.json()["current_close_at"].endswith("11:00:00+00:00")


def test_bid_outside_active_interval_is_rejected(app_client):
    client, main = app_client
    login(client, "buyer")
    response, start = create_auction(client, main)
    rfq_id = response.json()["id"]
    login(client, "bidder")
    result = submit_bid(client, main, rfq_id, 1000, start + timedelta(hours=2))
    assert result.status_code == 409
    assert result.json()["detail"] == "Auction is not active"


def test_demo_seed_exposes_portfolio_to_authenticated_buyer(demo_client):
    client, _ = demo_client
    login(client, "buyer")
    auctions = client.get("/api/rfqs").json()
    assert len(auctions) == 4
    assert {auction["status"] for auction in auctions} == {
        "active",
        "scheduled",
        "closed",
        "force_closed",
    }
    active = next(auction for auction in auctions if auction["status"] == "active")
    detail = client.get(f"/api/rfqs/{active['id']}").json()
    assert detail["bid_count"] == 4
    assert detail["bids"][0]["supplier_name"] == "Rivigo Express"


def test_bidder_cannot_see_competitor_identities(demo_client):
    client, _ = demo_client
    login(client, "bidder")
    active = next(item for item in client.get("/api/rfqs").json() if item["status"] == "active")
    detail = client.get(f"/api/rfqs/{active['id']}").json()
    assert all(bid["supplier_name"] == "Anonymous supplier" for bid in detail["bids"])
    assert all(bid["carrier_name"] == "Hidden during auction" for bid in detail["bids"])
    bid_events = [event for event in detail["events"] if event["event_type"] == "bid_submitted"]
    assert all(event["message"] == "A supplier submitted a bid" for event in bid_events)
