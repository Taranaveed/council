# Deploy Council — Vercel (frontend) + Render (API + market)

## Architecture

```
Browser (Vercel)  →  FastAPI (Render council-api)  →  Node market-service (Render)
                           ↓                              ↓
                        Groq LLM                       SerpApi
                           ↓
                    SQLite on disk (DB_PATH)
```

| Piece | Where | URL (current) |
|-------|--------|----------------|
| Frontend | Vercel | `https://project-nsy5u.vercel.app` (or your project URL) |
| API | Render | `https://council-api-rbod.onrender.com` |
| Market | Render | `https://council-market.onrender.com` |

Repo wired to Render today: **`https://github.com/Taranaveed/council`**, branch **`master`**.

## Persistent disk (required before inviting testers)

### Plan reality (plain language)

| Plan | Persistent disk? | What happens on restart / redeploy | Scaling |
|------|------------------|--------------------------------------|---------|
| **Free** | **No.** Cannot attach a disk. | Ephemeral filesystem. SQLite (`users.db`) and anything under the service root is **wiped**. Users/briefs disappear. | Single instance; sleeps when idle. |
| **Starter** (and above) | **Yes.** Attach a disk in the dashboard or via `render.yaml`. | Disk contents **survive** deploys and restarts. App code still rebuilds; only the mount path persists. | Still typically one web instance. A disk is bound to **one** instance — do **not** scale SQLite horizontally. |
| **Multi-instance / HA** | Disk alone is not enough. | Use **Postgres** (or similar) instead of SQLite+disk. | Shared DB across instances. |

**Free plan does not support a persistent disk.** The blueprint sets `council-api` to `plan: starter` so a disk can be defined. Keep `council-market` on free if you want (it has no durable local state).

### Blueprint values (`render.yaml`)

| Setting | Value |
|---------|--------|
| Disk name | `council-api-data` |
| Mount path | `/var/data` |
| Size | `1` GB |
| `DB_PATH` | `/var/data/users.db` |
| `PERSISTENT_DISK_MOUNT` | `/var/data` |

`/health` returns `db_persistent: true` only when `DB_PATH` is under `PERSISTENT_DISK_MOUNT` **and** both share the same real filesystem mount point (symlink off-disk → false). It also reports `disk` (total/used/free bytes for the DB volume) and `run_logs` (ephemeral diagnostic dir size).

### Manual dashboard steps (if not using Blueprint)

1. Upgrade **council-api** to **Starter** (or higher). Free cannot add a disk.
2. Service → **Disks** → add disk, mount path `/var/data`, size ≥ 1 GB.
3. Environment:
   - `DB_PATH=/var/data/users.db`
   - `PERSISTENT_DISK_MOUNT=/var/data`
4. Redeploy. Confirm startup log: `DB_PATH=/var/data/users.db existed=... db_persistent=True`.
5. `GET /health` → `"db_persistent": true`.

### Runtime paths written on disk (audit)

Only the API writes durable/local files. Market-service keeps caches **in memory** only.

| Path | Purpose | Must persist for testers? |
|------|---------|---------------------------|
| `$DB_PATH` (default `backend/data/users.db`) | Users, briefs, share tokens, watchlist, notifications, credits | **Yes** |
| `<db_dir>/marketplaces.db` | Marketplace seed profiles (rebuilt on boot if missing) | Nice-to-have; re-seedable |
| `$BUYER_COUNCIL_RUN_LOG_DIR` or `<temp>/council-run-logs/*.json` | Deal-finder JSON diagnostics (rotated; default **off** the data disk) | **No** |
| `$DB_BACKUP_DIR` or `<db_dir>/backups/users-*.db` | Online SQLite backups (`scripts/backup_sqlite_db.py`) | Backup copies only |

Not written to local disk for persistence:

- Share tokens → columns in SQLite (`deal_briefs.share_token`)
- Market / FX / Serp caches → process memory
- Uploads → none (no upload feature)
- App logs → Render log stream (not a local file we manage)

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
| `MARKET_SERVICE_SECRET` | same value as API |
| `DEFAULT_REGION` | `uk` |
| `DEFAULT_COUNTRY_CODE` | `uk` |
| `DEFAULT_LOCATION` | `United Kingdom` |
| `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` | `1` |

## 3. Render — API (`council-api` / `council-api-rbod`)

- Root Directory: `backend`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health: `/health`
- Plan: **Starter** (for disk) — see above
- Disk: mount `/var/data`, `DB_PATH=/var/data/users.db`

**Env**

| Key | Value |
|-----|--------|
| `DB_PATH` | `/var/data/users.db` |
| `PERSISTENT_DISK_MOUNT` | `/var/data` |
| `GROQ_API_KEY` | your Groq key |
| `GROQ_MODEL` | `openai/gpt-oss-120b` (optional) |
| `GROQ_FALLBACK_MODEL` | `openai/gpt-oss-20b` (optional) |
| `JWT_SECRET` | long random string |
| `MARKET_SERVICE_URL` | `https://council-market.onrender.com` |
| `MARKET_SERVICE_SECRET` | same as market |
| `FRONTEND_ORIGIN` | your Vercel URL (no trailing slash) |
| `CORS_ORIGINS` | same Vercel URL (comma-list if previews) |
| `DEFAULT_REGION` / `DEFAULT_COUNTRY_CODE` | `uk` |
| `ALERTS_SCHEDULER` | `0` on free/starter without email |
| `FREE_BRIEFS_PER_MONTH` | e.g. `3` |

Free Render services sleep after idle; first request can take ~30–60s (API wakes market). Starter can stay up depending on settings; disk still required for SQLite survival across **deploys**.

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
2. `https://council-api-rbod.onrender.com/health` — expect `"db_persistent": true` when disk is mounted
3. Open Vercel URL → register → Deal Finder with a UK query
4. US location should show: `Region not supported: 'us'. Council currently supports UK and Pakistan.` (not a bare `Request failed (422)`)

## 6. Post-deploy persistence checklist

Do this after every API deploy that touches storage or before inviting testers:

1. Confirm `/health` has `"db_persistent": true` and `db_path` under `/var/data`.
2. Register a fresh user (unique email).
3. Run Deal Finder once (UK is enough) so a brief is saved; note `brief_id` from the response or UI.
4. Trigger a **Manual Deploy** of council-api (same commit is fine — goal is restart + new filesystem for non-disk paths).
5. After the new deploy is live, log in as the same user.
6. Confirm the brief still loads (`GET /api/briefs/{id}` or UI history).
7. If the brief is gone or login fails as “new user”, the disk/`DB_PATH` wiring is wrong — **do not invite testers**.

## 7. SQLite backup and restore

### Backup (nightly or on-demand)

Uses the **SQLite backup API** (`Connection.backup`), not a raw file copy — safe with WAL.

```bash
# On a machine/shell that can see the DB file (Render shell, or local):
python scripts/backup_sqlite_db.py
# or:
python scripts/backup_sqlite_db.py --db /var/data/users.db --dir /var/data/backups
```

- Writes `users-YYYYMMDDTHHMMSSZ.db` into the backup dir.
- Keeps the **last 7** dated files (deletes older).
- Env overrides: `DB_PATH`, `DB_BACKUP_DIR`.

Schedule on Render: Cron Job (Starter+) running the same command with the disk mounted, or run on-demand from the API shell before risky deploys.

### Restore

1. Stop or scale down writers if possible (avoid half-written DB).
2. Restore via the same API (clears live `-wal`/`-shm`):

   ```bash
   python scripts/backup_sqlite_db.py \
     --db /var/data/users.db \
     --restore /var/data/backups/users-YYYYMMDDTHHMMSSZ.db
   ```

3. Restart council-api.
4. Check startup log `existed=True` and `/health`; log in and open a known brief.

## Blueprint (optional)

Repo root `render.yaml` can recreate services via Render → New → Blueprint. Review plan + disk fields before applying so you do not accidentally stay on free without a disk.
