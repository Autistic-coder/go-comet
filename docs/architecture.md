# Architecture

## Backend boundaries

- `app/api/routes` contains transport-only routers and operational endpoints.
- `app/domain` contains deterministic money, status, and extension rules without I/O.
- `app/services` coordinates transactional work and notification delivery.
- `app/repositories` requires tenant scope at the persistence boundary.
- `app/database.py` owns SQLite compatibility, bounded PostgreSQL pooling, and timeouts.
- `alembic/versions` owns ordered production schema changes.

Each write transaction contains the auction mutation, domain event, idempotency/audit state, and notification-outbox row. Delivery happens afterward and retries without repeating the auction mutation. PostgreSQL row locks serialize bids per auction; advisory locks serialize each idempotency key and schema migration.

Observability has JSON request logs with request IDs, Prometheus RED/business metrics at `/metrics`, and optional OTLP traces.

## System context

```mermaid
flowchart LR
    B[Buyer browser] -->|HTTPS + session cookie| R[React application]
    S[Bidder browser] -->|HTTPS + session cookie| R
    R -->|JSON REST + CSRF + idempotency key| A[FastAPI service]
    A --> M[Security middleware]
    M --> AU[Authentication and RBAC]
    AU --> E[Auction engine]
    E --> D[(PostgreSQL production / SQLite demo)]
    E --> L[Append-only activity log]
    A --> I[Idempotency ledger]
    I --> D
    L --> D
```

The React and FastAPI applications are built into one container and served from one origin. That keeps cookies first-party and removes the need to expose session credentials to browser JavaScript. FastAPI is the source of truth for identity, role authorization, auction status, bid totals, ranking, and extension decisions.

## Trust boundaries

1. The browser is untrusted. Supplier names, roles, timestamps, totals, and auction state are never accepted as authoritative.
2. A random session token is stored only in an HttpOnly, SameSite=Strict cookie. Only its SHA-256 digest is stored in the database.
3. State-changing requests must also supply the matching CSRF token and a valid idempotency key.
4. Buyer-only and bidder-only operations are enforced in FastAPI, not only hidden in React.
5. Every business query is scoped by the authenticated tenant. PostgreSQL transactions lock the RFQ row; SQLite demo transactions use `BEGIN IMMEDIATE`.
6. Lifecycle writes use optimistic versions and an idempotency key. SSE applies the same supplier redaction as REST.

## Login and authorization flow

```mermaid
sequenceDiagram
    participant UI as React UI
    participant API as FastAPI
    participant DB as Relational store
    UI->>API: POST /api/auth/login
    API->>API: Rate limit by IP + email
    API->>DB: Load active user
    API->>API: Verify PBKDF2 password hash
    API->>DB: Store hashed session + CSRF digest
    API-->>UI: HttpOnly session cookie + CSRF cookie + role
    UI->>API: Authenticated request
    API->>DB: Resolve session and expiry
    API->>API: Enforce buyer or bidder role
    API-->>UI: Role-appropriate response
```

## Idempotent bid flow

```mermaid
sequenceDiagram
    participant UI as Bidder UI
    participant API as FastAPI
    participant DB as SQLite
    UI->>API: POST bid + CSRF + Idempotency-Key
    API->>DB: BEGIN IMMEDIATE
    API->>DB: Find key for user + operation
    alt same key and same request hash
        DB-->>API: Stored response
        API-->>UI: Replay response, Idempotency-Replayed=true
    else same key and different hash
        API-->>UI: 409 Conflict
    else new key
        API->>DB: Load RFQ and current ranking
        API->>API: Validate active interval and quote
        API->>DB: Insert immutable bid and audit event
        API->>API: Recalculate ranking and extension trigger
        opt trigger matches
            API->>DB: Update close time, capped at forced close
            API->>DB: Insert extension event
        end
        API->>DB: Store response in idempotency ledger
        API->>DB: COMMIT
        API-->>UI: 201 with updated auction
    end
```

## Deployment

- `Dockerfile.vercel` produces the Vercel container deployment.
- `Dockerfile` and `render.yaml` support Render.
- React build assets are served by FastAPI after all API routes.
- `DATABASE_URL` activates PostgreSQL and row-level auction locking; otherwise the zero-setup SQLite demonstration mode is used.
- A production deployment still requires shared rate-limit storage and a managed identity provider.

## Observability

Every response includes `X-Request-ID` and `Server-Timing`. Structured JSON request logs include route, status, duration, and request ID. Auction mutations create business events while security-sensitive actions enter a tenant-scoped audit ledger. Operational database failures return a generic 503 with `Retry-After`; internal details and secrets are not sent to clients.
