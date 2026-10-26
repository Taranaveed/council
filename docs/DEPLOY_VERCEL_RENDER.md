# Deploy Council — Vercel (frontend) + Render (API + market)

## Architecture

```
Browser (Vercel)  →  FastAPI (Render council-api)  →  Node market-service (Render)
                           ↓                              ↓
                        Groq LLM                       SerpApi
```

| Piece | Where | URL (current) |
|-------|--------|----------------|
| Frontend | Vercel | `https://project-nsy5u.vercel.app` (or your project URL) |
| API | Render | `https://council-api-rbod.onrender.com` |
| Market | Render | `https://council-market.onrender.com` |

Repo wired to Render today: **`https://github.com/Taranaveed/council`**, branch **`master`**.

## 1. Push code Render will build

Render only deploys what is on `council` / `master` (unless you change the branch in the dashboard).

```bash
# From your working branch, after committing:
git push council HEAD:master
# or: merge uk-region-fixes → master, then push
```

## 2. Render — market-service (`council-market`)

- Root Directory: `market-service`
- Build: `npm install`
- Start: `npm start`
- Health: `/health`

**Env**

| Key | Value |
|-----|--------|
| `SERPAPI_KEY` | your SerpApi key |
| `DEFAULT_REGION` | `uk` |
| `DEFAULT_COUNTRY_CODE` | `uk` |
| `DEFAULT_LOCATION` | `United Kingdom` |
| `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` | `1` |

## 3. Render — API (`council-api` / `council-api-rbod`)

- Root Directory: `backend`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health: `/health`

**Env**

| Key | Value |
|-----|--------|
| `GROQ_API_KEY` | your Groq key |
| `GROQ_MODEL` | `openai/gpt-oss-120b` (optional) |
| `GROQ_FALLBACK_MODEL` | `openai/gpt-oss-20b` (optional) |
| `JWT_SECRET` | long random string |
| `MARKET_SERVICE_URL` | `https://council-market.onrender.com` |
| `FRONTEND_ORIGIN` | your Vercel URL (no trailing slash) |
| `CORS_ORIGINS` | same Vercel URL (comma-list if previews) |
| `DEFAULT_REGION` / `DEFAULT_COUNTRY_CODE` | `uk` |
| `ALERTS_SCHEDULER` | `0` on free tier (optional) |

Free Render services sleep after idle; first request can take ~30–60s (API wakes market).

## 4. Vercel — frontend

```bash
cd frontend
npx vercel login
npx vercel link          # root = frontend/
npx vercel env add VITE_API_URL production
# paste: https://council-api-rbod.onrender.com
npx vercel --prod
```

Or Dashboard → Project → Settings → Environment Variables:

- `VITE_API_URL` = `https://council-api-rbod.onrender.com` (Production + Preview)

Build settings:

- Framework: Vite
- Root Directory: `frontend`
- Build: `npm run build`
- Output: `dist`

`vercel.json` already SPA-rewrites to `index.html`.

## 5. Smoke test

1. `https://council-market.onrender.com/health`
2. `https://council-api-rbod.onrender.com/health`
3. Open Vercel URL → register → Deal Finder with a UK query

## Blueprint (optional)

Repo root `render.yaml` can recreate services via Render → New → Blueprint.
