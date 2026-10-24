from __future__ import annotations

from datetime import timedelta

from app.database import connection
from conftest import create_auction, csrf_headers, login, submit_bid


def transition(client, rfq_id: int, version: int, action: str, **extra):
    return client.post(
        f"/api/rfqs/{rfq_id}/transition",
        headers={**csrf_headers(client, key=f"transition-{action}-{version}-0001"), "If-Match": str(version)},
        json={"action": action, "reason": f"Test transition to {action}", **extra},
    )


def test_pause_resume_and_optimistic_lock(app_client):
    client, main = app_client
    login(client, "buyer")
    created, _ = create_auction(client, main)
    auction = created.json()
    paused = transition(client, auction["id"], auction["version"], "pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    stale = transition(client, auction["id"], auction["version"], "resume")
    assert stale.status_code == 412
    resumed = transition(client, auction["id"], paused.json()["version"], "resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "active"


def test_cancel_blocks_future_bids_and_writes_audit(app_client):
    client, main = app_client
    login(client, "buyer")
    created, start = create_auction(client, main)
    auction = created.json()
    cancelled = transition(client, auction["id"], auction["version"], "cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    audit = client.get("/api/audit").json()
    assert audit[0]["action"] == "auction.cancel"
    assert audit[0]["resource_id"] == str(auction["id"])

    login(client, "bidder")
    bid = submit_bid(client, main, auction["id"], 1000, start + timedelta(minutes=30))
    assert bid.status_code == 409


def test_award_requires_closed_auction_and_matching_bid(app_client):
    client, main = app_client
    login(client, "buyer")
    created, start = create_auction(client, main)
    auction = created.json()
    login(client, "bidder")
    bid_result = submit_bid(client, main, auction["id"], 1000, start + timedelta(minutes=30))
    bid_id = bid_result.json()["bids"][0]["id"]
    login(client, "buyer")
    active_award = transition(client, auction["id"], bid_result.json()["version"], "award", bid_id=bid_id)
    assert active_award.status_code == 409

    with connection() as db:
        db.execute(
            "UPDATE rfqs SET current_close_at = ?, forced_close_at = ? WHERE id = ?",
            ((start - timedelta(minutes=2)).isoformat(), (start - timedelta(minutes=1)).isoformat(), auction["id"]),
        )
    awarded = transition(client, auction["id"], bid_result.json()["version"], "award", bid_id=bid_id)
    assert awarded.status_code == 200
    assert awarded.json()["status"] == "awarded"
