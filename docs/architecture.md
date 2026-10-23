# High-Level Design

## Architecture

```mermaid
flowchart LR
    U[Buyer / Supplier] -->|HTTPS| R[React Web App]
    R -->|JSON REST API| F[FastAPI Service]
    F --> V[Request validation\nPydantic]
    F --> E[Auction engine\nranking + extension rules]
    E --> D[(SQLite / relational DB)]
    D --> E
    E --> L[Activity log]
    L --> D
```

The React client is a procurement control tower for creating and monitoring auctions, reviewing live rankings, submitting test supplier quotes, and reading the audit trail. FastAPI is the source of truth for auction status, validation, ranking, and extension behavior. SQLite keeps the assignment runnable with no external services; the schema is portable to PostgreSQL for production.

## Request flow: bid submission

```mermaid
sequenceDiagram
    participant S as Supplier UI
    participant A as FastAPI
    participant D as Database
    S->>A: POST /api/rfqs/{id}/bids
    A->>D: Load RFQ and current ranking
    A->>A: Validate active interval and quote
    A->>D: Save bid and bid event
    A->>D: Recompute ranking
    A->>A: Evaluate trigger inside X-minute window
    alt trigger matches
        A->>A: min(close + Y, forced close)
        A->>D: Update close and save extension event
    end
    A-->>S: Updated auction, bids, rankings, events
```

## Key design decisions

- The server accepts an optional `submitted_at` in the assignment implementation so extension rules can be tested deterministically. A production API should derive it exclusively from server time.
- `current_close_at` is stored independently from `original_close_at` to make every extension explicit and auditable.
- Status is derived from timestamps instead of persisted, preventing stale status values.
- Bid totals are calculated on the server from freight, origin, and destination charges.
- Each bid is immutable; a supplier improvement is a new bid, preserving price history.

## Production hardening

Use PostgreSQL transactions with row-level locking around bid placement, authenticated buyer/supplier roles, tenant isolation, idempotency keys, currency fields stored as integer minor units, background notifications, and WebSockets or server-sent events for instant live updates.

