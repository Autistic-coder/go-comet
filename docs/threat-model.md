# Threat model

## Assets and trust boundaries

The primary assets are supplier identities, commercial bid values, RFQ documents, award decisions, sessions, and the immutable audit history. The browser is untrusted; FastAPI is the policy boundary; the relational store is the consistency boundary; identity providers, queues, mail providers, and object storage are external trust boundaries.

## STRIDE register

| Threat | Example | Existing control | Remaining production work |
| --- | --- | --- | --- |
| Spoofing | Supplier submits as another carrier | Server session, role guard, server-owned supplier identity | Managed IdP, MFA, account recovery |
| Tampering | Retry creates duplicate bids | Transactional idempotency ledger and request hash | PostgreSQL unique constraint under multi-instance load |
| Repudiation | Buyer denies an award | Auction events and security audit ledger with request ID | Export logs to append-only external storage |
| Information disclosure | Bidder discovers competitors | Tenant filtering and bidder event/bid redaction | Per-auction visibility policy tests |
| Denial of service | Login or bid flood | Body limits and login throttling | Shared Redis limits, WAF and capacity alerts |
| Elevation of privilege | Bidder calls buyer endpoint | API-side RBAC and CSRF | Managed organization roles and periodic access review |

## Abuse cases

- Concurrent final-second bids must serialize against one auction and never pass the forced close.
- Reusing an idempotency key with a different payload must fail closed.
- A tenant identifier supplied by a client must never influence authorization.
- SSE messages must apply the same identity redaction as REST responses.
- Awarding requires a closed auction and a bid belonging to that auction.

Review this document whenever a new role, external provider, file upload, notification channel, or pricing rule is added.
