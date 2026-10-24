# Operations runbook

## Service objectives

- API availability target: 99.9% monthly.
- P95 authenticated read latency target: 500 ms.
- P95 bid acceptance latency target: 1 second.
- Accepted-bid loss objective: zero.

Alert on sustained 5xx rate above 2%, bid latency above 1 second, database connection or lock exhaustion, repeated idempotency conflicts, authentication denial spikes, and an SSE reconnect spike.

## Incident triage

1. Record start time, deployment ID, request IDs, affected tenants, and symptoms.
2. Stop risky writes by pausing affected auctions; do not delete evidence.
3. Inspect structured request logs and security audit events without exposing tokens or bid payloads.
4. Roll back the deployment if the error began after a release and the schema is backward compatible.
5. Reconcile idempotency records, bids, events, and award state before reopening an auction.
6. Publish an incident timeline and corrective action after recovery.

## Database recovery

Production must use managed PostgreSQL with point-in-time recovery. Test restoration into an isolated database quarterly. Validate row counts, foreign keys, the latest auction event, and a sample idempotency replay before promoting recovered data. SQLite demo files are disposable and are not a backup strategy.

## Safe deployment

Apply backward-compatible migrations before application code. Use expand/migrate/contract for destructive schema changes. Run unit, integration, concurrency, dependency-audit, frontend-build, and container-build checks before promotion.
