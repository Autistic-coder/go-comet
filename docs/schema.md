# Database Schema

```mermaid
erDiagram
    USERS ||--o{ SESSIONS : owns
    USERS ||--o{ RFQS : creates
    USERS ||--o{ BIDS : submits
    USERS ||--o{ IDEMPOTENCY_RECORDS : scopes
    RFQS ||--o{ BIDS : receives
    RFQS ||--o{ AUCTION_EVENTS : records

    USERS {
      integer id PK
      text email UK
      text display_name
      text role
      text supplier_name
      text carrier_name
      text password_hash
      boolean is_active
      datetime created_at
    }
    SESSIONS {
      integer id PK
      integer user_id FK
      text token_hash UK
      text csrf_hash
      datetime expires_at
      datetime created_at
      datetime last_seen_at
    }
    RFQS {
      integer id PK
      text reference_id UK
      text name
      datetime bid_start_at
      datetime original_close_at
      datetime current_close_at
      datetime forced_close_at
      datetime pickup_service_at
      integer trigger_window_minutes
      integer extension_minutes
      text extension_trigger
      integer created_by_user_id FK
      datetime created_at
    }
    BIDS {
      integer id PK
      integer rfq_id FK
      integer bidder_user_id FK
      text supplier_name
      text carrier_name
      decimal freight_charges
      decimal origin_charges
      decimal destination_charges
      integer transit_time_days
      datetime validity_date
      decimal total_price
      datetime submitted_at
    }
    AUCTION_EVENTS {
      integer id PK
      integer rfq_id FK
      text event_type
      text message
      json metadata_json
      datetime created_at
    }
    IDEMPOTENCY_RECORDS {
      integer id PK
      integer user_id FK
      text operation
      text idempotency_key
      text request_hash
      integer response_status
      json response_json
      datetime created_at
    }
```

## Integrity rules

- User emails and RFQ references are unique.
- Roles are constrained to `buyer` or `bidder`.
- Session and CSRF secrets are stored as one-way digests.
- Session expiry is checked on every authenticated request.
- Bid charges must be non-negative and transit time must be positive.
- Auction extension policies are constrained to the three supported trigger values.
- `(user_id, operation, idempotency_key)` is unique, preventing duplicate mutation processing.
- Foreign keys cascade session and idempotency cleanup when a user is removed.
- RFQ deletion cascades bids and auction events.

## Indexes

| Index | Purpose |
| --- | --- |
| `sessions(token_hash, expires_at)` | Fast session lookup and expiry checks |
| `bids(rfq_id, total_price, submitted_at)` | Deterministic auction ranking |
| `bids(bidder_user_id, submitted_at)` | Bidder activity lookup |
| `auction_events(rfq_id, created_at)` | Reverse chronological audit trail |
| `idempotency_records(created_at)` | 24-hour retention and cleanup operations |

## Migration behavior

`init_db()` creates all tables for a new installation and adds ownership columns to databases created by earlier versions. Demo records are inserted only when `SEED_DEMO_DATA=true` and the RFQ table is empty.
