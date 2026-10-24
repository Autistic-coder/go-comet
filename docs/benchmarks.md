# Performance and concurrency gate

`load/k6-auction.js` exercises authenticated list traffic and a 20-request race using one bidder and one idempotency key. CI fails unless:

- error rate is below 1%;
- p95 latency is below 500 ms;
- p99 latency is below 1 second;
- successful checks exceed 99%.

The race is intentional: every response must succeed, while the API's idempotency ledger commits only one bid. The PostgreSQL CI job independently asserts that one response is original, one is a replay, and only one bid exists.

Run locally with `k6 run load/k6-auction.js`. Override the target with `BASE_URL=https://example.test k6 run load/k6-auction.js`. Do not publish a production benchmark without naming the Vercel plan, database region, dataset size, run date, and k6 output; CI results are the reproducible source of truth.
