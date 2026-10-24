from __future__ import annotations

from datetime import timedelta

from app.database import connection
from conftest import create_auction, csrf_headers, login, submit_bid


def test_private_routes_require_authentication(app_client):
    client, _ = app_client
    assert client.get("/api/rfqs").status_code == 401
    assert client.get("/api/rfqs/1").status_code == 401


def test_mock_login_returns_role_and_session(app_client):
    client, _ = app_client
    user = login(client, "buyer")
    assert user["role"] == "buyer"
    assert user["email"] == "buyer.demo@example.com"
    assert client.cookies.get("gocomet_session")
    assert client.cookies.get("gocomet_csrf")
    session = client.get("/api/auth/session")
    assert session.status_code == 200
    assert session.json()["user"]["id"] == user["id"]
    with connection() as db:
        stored = db.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    assert stored["password_hash"].startswith("pbkdf2_sha256$")
    assert "BuyerDemo!2026" not in stored["password_hash"]


def test_invalid_login_is_generic_and_rate_limited(app_client):
    client, _ = app_client
    payload = {"email": "buyer.demo@example.com", "password": "WrongPassword!"}
    for _ in range(5):
        response = client.post("/api/auth/login", json=payload)
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"
    limited = client.post("/api/auth/login", json=payload)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "300"


def test_logout_revokes_session(app_client):
    client, _ = app_client
    login(client, "buyer")
    response = client.post("/api/auth/logout", headers=csrf_headers(client))
    assert response.status_code == 204
    assert client.get("/api/auth/session").status_code == 401


def test_csrf_is_required_for_writes(app_client):
    client, main = app_client
    login(client, "buyer")
    main.utc_now = lambda: __import__("datetime").datetime(2030, 1, 1, 10, tzinfo=__import__("datetime").timezone.utc)
    payload = {
        "reference_id": "RFQ-NO-CSRF",
        "name": "Blocked request",
        "bid_start_at": "2030-01-01T10:00:00+00:00",
        "bid_close_at": "2030-01-01T11:00:00+00:00",
        "forced_close_at": "2030-01-01T11:10:00+00:00",
        "pickup_service_at": "2030-01-02T10:00:00+00:00",
        "trigger_window_minutes": 10,
        "extension_minutes": 5,
        "extension_trigger": "bid_received",
    }
    blocked = client.post("/api/rfqs", headers={"Idempotency-Key": "missing-csrf-01"}, json=payload)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "CSRF validation failed"
    wrong = client.post(
        "/api/rfqs",
        headers={"Idempotency-Key": "wrong-csrf-0001", "X-CSRF-Token": "not-the-cookie"},
        json=payload,
    )
    assert wrong.status_code == 403


def test_idempotency_key_is_required_for_mutations(app_client):
    client, main = app_client
    login(client, "buyer")
    main.utc_now = lambda: __import__("datetime").datetime(2030, 1, 1, 10, tzinfo=__import__("datetime").timezone.utc)
    payload = {
        "reference_id": "RFQ-NO-KEY",
        "name": "Missing key request",
        "bid_start_at": "2030-01-01T10:00:00+00:00",
        "bid_close_at": "2030-01-01T11:00:00+00:00",
        "forced_close_at": "2030-01-01T11:10:00+00:00",
        "pickup_service_at": "2030-01-02T10:00:00+00:00",
        "trigger_window_minutes": 10,
        "extension_minutes": 5,
        "extension_trigger": "bid_received",
    }
    response = client.post("/api/rfqs", headers=csrf_headers(client), json=payload)
    assert response.status_code == 422


def test_roles_are_enforced_at_api_boundary(app_client):
    client, main = app_client
    login(client, "buyer")
    response, start = create_auction(client, main)
    rfq_id = response.json()["id"]
    buyer_bid = submit_bid(client, main, rfq_id, 1000, start + timedelta(minutes=30))
    assert buyer_bid.status_code == 403
    login(client, "bidder")
    bidder_create, _ = create_auction(client, main, reference_id="RFQ-FORBIDDEN")
    assert bidder_create.status_code == 403


def test_create_rfq_is_idempotent_and_detects_key_reuse(app_client):
    client, main = app_client
    login(client, "buyer")
    key = "create-same-request-01"
    first, _ = create_auction(client, main, reference_id="RFQ-IDEMPOTENT", key=key)
    second, _ = create_auction(client, main, reference_id="RFQ-IDEMPOTENT", key=key)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.headers["idempotency-replayed"] == "true"
    conflict, _ = create_auction(client, main, reference_id="RFQ-DIFFERENT", key=key)
    assert conflict.status_code == 409
    assert "different request" in conflict.json()["detail"]
    assert len(client.get("/api/rfqs").json()) == 1


def test_bid_idempotency_prevents_duplicate_bid_and_extension(app_client):
    client, main = app_client
    login(client, "buyer")
    auction, start = create_auction(client, main)
    rfq_id = auction.json()["id"]
    login(client, "bidder")
    key = "bid-same-request-0001"
    first = submit_bid(client, main, rfq_id, 1000, start + timedelta(minutes=55), key=key)
    replay = submit_bid(client, main, rfq_id, 1000, start + timedelta(minutes=55), key=key)
    assert first.status_code == replay.status_code == 201
    assert replay.headers["idempotency-replayed"] == "true"
    assert replay.json()["bid_count"] == 1
    assert replay.json()["current_close_at"] == first.json()["current_close_at"]
    conflict = submit_bid(client, main, rfq_id, 900, start + timedelta(minutes=55), key=key)
    assert conflict.status_code == 409


def test_payload_validation_rejects_spoofing_naive_dates_and_large_money(app_client):
    client, main = app_client
    login(client, "buyer")
    response, start = create_auction(client, main)
    rfq_id = response.json()["id"]
    login(client, "bidder")
    base = {
        "freight_charges": 1000,
        "origin_charges": 0,
        "destination_charges": 0,
        "transit_time_days": 3,
        "validity_date": (start + timedelta(days=7)).isoformat(),
    }
    extra = client.post(
        f"/api/rfqs/{rfq_id}/bids",
        headers=csrf_headers(client, key="validation-check-01"),
        json={**base, "supplier_name": "Spoofed"},
    )
    assert extra.status_code == 422
    naive = client.post(
        f"/api/rfqs/{rfq_id}/bids",
        headers=csrf_headers(client, key="validation-check-02"),
        json={**base, "validity_date": "2030-01-08T10:00:00"},
    )
    assert naive.status_code == 422
    oversized = client.post(
        f"/api/rfqs/{rfq_id}/bids",
        headers=csrf_headers(client, key="validation-check-03"),
        json={**base, "freight_charges": 100_000_001},
    )
    assert oversized.status_code == 422


def test_invalid_filters_and_pagination_are_rejected(app_client):
    client, _ = app_client
    login(client, "buyer")
    assert client.get("/api/rfqs?status=unknown").status_code == 422
    assert client.get("/api/rfqs?limit=101").status_code == 422
    assert client.get("/api/rfqs?offset=-1").status_code == 422
    assert client.get("/api/rfqs?now=2030-01-01T10:00:00").status_code == 422


def test_security_headers_request_ids_and_body_limit(app_client):
    client, _ = app_client
    health = client.get("/api/health", headers={"X-Request-ID": "request-12345678"})
    assert health.status_code == 200
    assert health.headers["x-request-id"] == "request-12345678"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in health.headers["content-security-policy"]
    assert health.headers["cache-control"] == "no-store"
    too_large = client.post(
        "/api/auth/login",
        content="x" * (33 * 1024),
        headers={"Content-Type": "application/json"},
    )
    assert too_large.status_code == 413


def test_untrusted_host_is_rejected(app_client):
    client, _ = app_client
    response = client.get("/api/health", headers={"Host": "attacker.invalid"})
    assert response.status_code == 400


def test_expired_session_is_rejected(app_client):
    client, _ = app_client
    login(client, "buyer")
    raw_session = client.cookies.get("gocomet_session")
    from app.security import token_hash

    with connection() as db:
        db.execute(
            "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
            ("2000-01-01T00:00:00+00:00", token_hash(raw_session)),
        )
    assert client.get("/api/auth/session").status_code == 401
