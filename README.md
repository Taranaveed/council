# Council

Multi-agent AI platform for **Business Owners** (pricing + audience) and **Buyers** (local deal finder).

Agents debate like a council — then deliver one clear call.

## Architecture flow

```
Login → Role Selection → Service Form → Live Market Sync (Node/SerpApi) → 3-Agent Debate (Groq) → Judge → Dashboard
```

## Services

| Role | Service | Endpoint |
|------|---------|----------|
| Business | Price Bargaining | `POST /api/modes/price-bargaining` |
| Business | Audience Discovery | `POST /api/modes/audience-discovery` |
| Buyer | Local Deal Finder | `POST /api/modes/deal-finder` |

## Prerequisites

- Python 3.10+
- Node.js 18+
- Groq API key
- SerpApi key (for live prices; optional — agents still run with empty market data)

## Environment

### Backend (`backend/.env`)

```env
GROQ_API_KEY=your_groq_key
JWT_SECRET=change-me-in-production
JWT_EXPIRE_HOURS=72
MARKET_SERVICE_URL=http://localhost:3001

# Global defaults (do not hardcode Pakistan for worldwide launches)
DEFAULT_REGION=us
DEFAULT_COUNTRY_CODE=us
DEFAULT_LOCATION=United States
DEFAULT_LANGUAGE=en
```

### Market service (`market-service/.env`)

```env
SERPAPI_KEY=your_serpapi_key
PORT=3001
DEFAULT_REGION=us
DEFAULT_COUNTRY_CODE=us
DEFAULT_LOCATION=United States
DEFAULT_LANGUAGE=en
```

User-entered locations (Paris, New York, Lahore, etc.) still drive SerpApi `gl` / marketplaces; these env vars are only the fallback when location is missing.

## Run (3 terminals)

### 1. Market service

```bash
cd market-service
npm install
npm start
```

### 2. Backend

```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

1. Register / sign in
2. Choose Business or Buyer
3. Run a service

## Global CDN / nearest region

For production, put **Cloudflare** (or AWS CloudFront + global accelerator) in front of the app so users in Lahore, New York, or London hit the nearest edge.

1. Point your domain at Cloudflare CDN / Load Balancing.
2. Deploy API instances in regions (e.g. `us`, `eu`, `asia`).
3. Set frontend env:
   ```env
   VITE_API_URL=https://api.example.com
   VITE_API_URL_US=https://us.api.example.com
   VITE_API_URL_EU=https://eu.api.example.com
   VITE_API_URL_ASIA=https://asia.api.example.com
   ```
4. `GET /api/geo/ip` uses Cloudflare `CF-IPCountry` when present, otherwise an IP geolocation API, then:
   - pre-fills Buyer **Location**
   - selects nearest API region
   - loads marketplaces with `country_code`

## Auth

- Simple email/password (SQLite at `backend/data/users.db`)
- JWT bearer tokens
- Protected mode endpoints require `Authorization: Bearer <token>`

## Legacy

`POST /focus-group/run` and debate streaming routes remain available but are not used by the new UI.
