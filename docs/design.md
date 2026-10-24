# Security and Application Design

## Goals

The demonstration should make buyer and bidder responsibilities obvious while ensuring the API remains authoritative. Duplicate client retries must not create duplicate RFQs, bids, events, or auction extensions.

## Role model

| Capability | Buyer | Bidder |
| --- | ---: | ---: |
| Sign in and view auctions | Yes | Yes |
| View supplier identities | Yes | Only their own identity |
| Create an RFQ | Yes | No |
| Submit a bid | No | Yes |
| Choose the supplier identity sent with a bid | No | No |
| Read the audit timeline | Full | Redacted supplier messages |
| Pause/resume/cancel/award | Yes | No |

The frontend uses role-aware controls for clarity. FastAPI independently enforces every permission and returns 403 when a user attempts an action outside their role.

## Mock authentication

This project intentionally publishes two demo credentials. They exercise a real session boundary but are not a production identity system.

- Passwords are stored with salted PBKDF2-HMAC-SHA256 hashes.
- Login responses set an opaque session token in an HttpOnly cookie.
- Only a SHA-256 token digest is stored server-side.
- Sessions expire after eight hours and can be revoked by logout.
- Cookies use `SameSite=Strict`; deployed containers also set `Secure`.
- Login attempts are limited per client IP and normalized email.

For production, replace the public demo identities with Clerk, Auth0, Descope, or another managed identity provider. Keep the existing server-side role checks.

## CSRF design

State-changing requests use a double-submit token:

1. Login creates a random CSRF token.
2. Its digest is attached to the server-side session.
3. The token is placed in a readable, SameSite=Strict cookie.
4. React sends the same value in `X-CSRF-Token`.
5. FastAPI checks the header, cookie, and session digest.

An attacker who can cause a cross-site form submission cannot read the CSRF cookie and therefore cannot construct the required header.

## Idempotency design

`POST /api/rfqs` and `POST /api/rfqs/{id}/bids` require an `Idempotency-Key`.

The effective identity is:

```text
(authenticated user, operation, idempotency key)
```

The server hashes a canonical JSON representation of the validated request body.

- New key: execute the mutation and persist the complete response.
- Existing key with the same hash: return the stored response with `Idempotency-Replayed: true`.
- Existing key with a different hash: return 409 Conflict.

The idempotency record is committed in the same transaction as the business mutation, so a successful bid and its extension cannot be separated from replay protection.
Successful responses remain replayable for 24 hours; older ledger entries are removed during database initialization.

## Auction consistency

- Client-provided submission timestamps are not accepted.
- Supplier and carrier identity come from the authenticated bidder profile.
- Bid totals are recomputed by the server.
- Ranking order is deterministic: total price, submission time, then row ID.
- Status is derived from timestamps instead of stored.
- A write lock covers the previous ranking, bid insert, new ranking, extension decision, events, and idempotency response.
- Extensions are capped with `min(current close + extension duration, forced close)`.

SQLite's write lock is sufficient for the demonstration. When `DATABASE_URL` is set, PostgreSQL uses a transaction plus `SELECT ... FOR UPDATE` on the RFQ row. Auction transitions also check an `If-Match` version to reject stale buyer actions.

## Input and transport controls

- Pydantic rejects unknown fields.
- All business timestamps require explicit timezones.
- Text lengths, reference formats, money values, page sizes, and offsets are bounded.
- API request bodies are limited to 32 KiB.
- CORS permits only configured origins, methods, and headers.
- Trusted-host validation blocks unexpected Host headers.
- Security headers disable framing, MIME sniffing, cameras, microphones, and geolocation.
- API responses use `Cache-Control: no-store`.
- Database error responses are generic and do not expose SQL or filesystem details.

## Privacy behavior

Buyers receive the complete ranking. Bidders receive their own identity but competing suppliers and carriers are replaced with neutral labels. Bid events shown to bidders are similarly redacted.

## Known demonstration limits

- SQLite demo mode and its in-process login limiter are local to one container instance; PostgreSQL mode uses a shared attempt ledger and advisory transaction lock.
- Public mock credentials provide workflow separation, not real account security.
- Server-sent events provide live refresh; large deployments should add a shared event broker rather than depending on database polling per connection.
- Durable production operation requires PostgreSQL and shared rate-limit storage such as Redis.
- Real authentication should add account recovery, MFA, organization membership, and identity-provider audit logs.
