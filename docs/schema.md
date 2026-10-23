# Database Schema

```mermaid
erDiagram
    RFQS ||--o{ BIDS : receives
    RFQS ||--o{ AUCTION_EVENTS : records
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
      datetime created_at
    }
    BIDS {
      integer id PK
      integer rfq_id FK
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
```

## Constraints and indexes

- `reference_id` is unique.
- Forced-close ordering is validated at the API boundary; bid and extension transactions always cap the close at `forced_close_at`.
- Charges are non-negative and transit time is positive.
- `extension_trigger` is restricted to the three supported policies.
- `bids(rfq_id, total_price, submitted_at)` supports ranking.
- `auction_events(rfq_id, created_at)` supports reverse-chronological audit views.

