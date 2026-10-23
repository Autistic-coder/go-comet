# GoComet British Auction RFQ

A full-stack reference implementation of a British-auction workflow for freight RFQs. Buyers configure an anti-sniping window and extension duration; supplier bids are ranked automatically; qualifying last-minute activity extends the auction without ever passing its forced close.

## Stack

- Frontend: React 19, TypeScript, Vite, responsive CSS
- Backend: FastAPI, Pydantic, SQLite
- Tests: Pytest + FastAPI TestClient

## Run locally

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API docs: <http://127.0.0.1:8000/docs>

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to FastAPI on port 8000. For a separately deployed API, set `VITE_API_URL`.

## Deploy to Render

The repository includes a Render Blueprint and a production multi-stage Docker build. The container builds React, then serves the generated frontend and FastAPI API from one web service.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Autistic-coder/go-comet)

The free Blueprint uses ephemeral SQLite storage, which is appropriate for a demo but can reset during a restart or redeploy. For durable production data, attach a persistent disk and set `RFQ_DATABASE_PATH=/data/rfq.db`, or migrate the schema to Render Postgres.

## Deploy to Vercel

`Dockerfile.vercel` packages the same React frontend and FastAPI backend as a Vercel container Function. It serves both from one origin on port 80. Vercel Functions are stateless, so the demo's SQLite data is temporary; use a Marketplace Postgres integration for durable production auctions.

## Auction behavior

An auction can extend when a bid is submitted within the configured trigger window. Three trigger modes are supported:

1. Any bid is received.
2. Any supplier ranking changes.
3. The L1/lowest-priced supplier changes.

The new close is calculated as `min(current close + extension duration, forced close)`. The server rejects bids outside the active interval and records bid submissions and extensions in an append-only activity log.

## Project structure

```text
backend/
  app/             FastAPI routes, domain rules, SQLite schema
  tests/           Extension and forced-close tests
frontend/
  src/             React control tower and API client
docs/
  architecture.md  HLD, architecture diagram, data flow
  schema.md        Database schema and rationale
```

## Test and build

```powershell
cd backend
pytest -q

cd ..\frontend
npm run build
```
