# GoComet — British Auction Control Tower

A full-stack freight procurement workspace for running transparent British auctions. Buyers can launch an RFQ, receive ranked carrier bids, track the current L1 price, and automatically extend competitive events when qualifying activity happens near closing time.

**Live application:** [go-comet-xi.vercel.app](https://go-comet-xi.vercel.app)

## Product highlights

- Live, scheduled, closed, and force-closed auction views
- Automatic L1 supplier ranking based on total landed bid price
- Configurable anti-sniping window and extension duration
- Hard forced-close time that extensions cannot exceed
- Supplier bid breakdowns for freight, origin, and destination charges
- Transit-time and quote-validity tracking
- Append-only auction activity timeline
- Search and status filters
- Responsive desktop and mobile interface
- Seeded demonstration auctions visible immediately after deployment

The interface uses the visual language of the MindMesh AI/ML workspace: warm paper surfaces, charcoal navigation, lime highlights, editorial serif headings, and compact data-focused labels.

## Demo data

The hosted application includes four example freight events:

| RFQ | Lane | Status | Example data |
| --- | --- | --- | --- |
| RFQ-DEMO-1043 | Bengaluru → Chennai | Scheduled | Upcoming express-cargo event |
| RFQ-DEMO-1042 | Mumbai → Delhi | Live | Four ranked supplier bids |
| RFQ-DEMO-1039 | Pune → Hyderabad | Closed | Completed refrigerated auction |
| RFQ-DEMO-1037 | Ahmedabad → Jaipur | Force closed | Completed part-load event |

Set `SEED_DEMO_DATA=true` to insert the sample records into an empty database. Existing databases are never overwritten.

## Technology

| Layer | Technology |
| --- | --- |
| Frontend | React 19, TypeScript, Vite, responsive CSS |
| Backend | FastAPI, Pydantic |
| Database | SQLite |
| Testing | Pytest, FastAPI TestClient |
| Production | Multi-stage Docker container |
| Hosting | Vercel and Render configuration included |

## Run locally

### 1. Start the FastAPI backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SEED_DEMO_DATA = "true"
uvicorn app.main:app --reload
```

The API runs at <http://127.0.0.1:8000>. Interactive documentation is available at <http://127.0.0.1:8000/docs>.

### 2. Start the React frontend

Open another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` requests to FastAPI on port 8000.

For a separately hosted backend, provide its origin through `VITE_API_URL`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `RFQ_DATABASE_PATH` | `backend/rfq.db` | Location of the SQLite database |
| `SEED_DEMO_DATA` | `false` | Adds demonstration auctions when the database is empty |
| `VITE_API_URL` | Same origin | Optional external backend origin used by the frontend |

## Auction rules

An auction can extend when a bid arrives inside its configured trigger window. Three trigger modes are available:

1. Any bid is received.
2. Any supplier ranking changes.
3. The L1 or lowest-priced supplier changes.

The updated close time is:

```text
min(current close + extension duration, forced close)
```

The API rejects bids outside the active interval. Every bid submission and auction extension is recorded in the activity log.

## API overview

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Service health check |
| `GET` | `/api/rfqs` | List and filter auctions |
| `POST` | `/api/rfqs` | Create an auction |
| `GET` | `/api/rfqs/{id}` | Get auction details, bids, and events |
| `POST` | `/api/rfqs/{id}/bids` | Submit a supplier bid |

The generated OpenAPI reference is available at `/docs` whenever the backend is running.

## Deploy

### Vercel

The production project is connected to the repository's `main` branch. Every push triggers a new deployment.

`Dockerfile.vercel` builds the React application and packages it with FastAPI as a Vercel container. The frontend and API are served from the same origin.

Vercel Functions use ephemeral storage. The included SQLite database is suitable for demonstration data, but production auctions should use durable PostgreSQL storage.

### Render

The repository also includes a Render Blueprint and production Dockerfile:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Autistic-coder/go-comet)

The free Blueprint uses ephemeral SQLite storage. For persistent data, attach a disk and set `RFQ_DATABASE_PATH=/data/rfq.db`, or migrate the schema to Render Postgres.

## Project structure

```text
backend/
  app/
    database.py       SQLite setup and demonstration records
    main.py           FastAPI routes and auction rules
    schemas.py        Request and response models
  tests/
    test_auction.py   Auction, extension, and seed tests
frontend/
  src/
    App.tsx           Auction dashboard and interaction flows
    api.ts            Typed API client
    styles.css        Responsive visual system
    types.ts          Shared frontend types
docs/
  architecture.md     High-level architecture and data flow
  schema.md           Database schema and rationale
Dockerfile            Render-compatible production image
Dockerfile.vercel     Vercel container image
render.yaml           Render Blueprint
```

## Verify

```powershell
cd backend
python -m pytest -q
python -m compileall -q app

cd ..\frontend
npm run build
```

The backend test suite covers bid ranking, trigger behavior, forced-close enforcement, and demonstration-data seeding.
