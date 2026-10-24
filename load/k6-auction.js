import http from 'k6/http';
import { check } from 'k6';

const BASE = __ENV.BASE_URL || 'http://127.0.0.1:8000';

export const options = {
  scenarios: {
    reads: { executor: 'constant-vus', vus: 10, duration: '10s', exec: 'readPath' },
    idempotent_bid_race: { executor: 'shared-iterations', vus: 10, iterations: 20, exec: 'bidRace' },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
    checks: ['rate>0.99'],
  },
};

function login(email, password) {
  const response = http.post(`${BASE}/api/auth/login`, JSON.stringify({ email, password }), {
    headers: { 'Content-Type': 'application/json' },
  });
  check(response, { 'login succeeds': (r) => r.status === 200 });
  return http.cookieJar().cookiesForURL(BASE).gocomet_csrf[0];
}

export function setup() {
  const csrf = login('buyer.demo@example.com', 'BuyerDemo!2026');
  const now = new Date();
  const payload = {
    reference_id: `LOAD-${Date.now()}`,
    name: 'CI load and concurrency lane',
    bid_start_at: new Date(now.getTime() - 60000).toISOString(),
    bid_close_at: new Date(now.getTime() + 600000).toISOString(),
    forced_close_at: new Date(now.getTime() + 1200000).toISOString(),
    pickup_service_at: new Date(now.getTime() + 86400000).toISOString(),
    trigger_window_minutes: 5,
    extension_minutes: 2,
    extension_trigger: 'bid_received',
  };
  const response = http.post(`${BASE}/api/rfqs`, JSON.stringify(payload), { headers: {
    'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'Idempotency-Key': `load-create-${Date.now()}`,
  }});
  check(response, { 'load RFQ created': (r) => r.status === 201 });
  return { rfqId: response.json('id'), validity: new Date(now.getTime() + 86400000).toISOString() };
}

export function readPath() {
  const csrf = login('buyer.demo@example.com', 'BuyerDemo!2026');
  const response = http.get(`${BASE}/api/rfqs`);
  check(response, { 'auction list succeeds': (r) => r.status === 200 });
  void csrf;
}

export function bidRace(data) {
  const csrf = login('bidder.demo@example.com', 'BidderDemo!2026');
  const response = http.post(`${BASE}/api/rfqs/${data.rfqId}/bids`, JSON.stringify({
    freight_charges: '1000.10', origin_charges: '20.20', destination_charges: '30.30',
    transit_time_days: 2, validity_date: data.validity,
  }), { headers: {
    'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'Idempotency-Key': 'load-race-bid-0001',
  }});
  check(response, { 'racing retry is accepted or replayed': (r) => r.status === 201 });
}
