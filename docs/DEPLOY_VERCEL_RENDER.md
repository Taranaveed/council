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

## Tester accounts (invite-only)

Set `SIGNUP_CODE` on **council-api** to a long random string (not committed). Unset = open registration (local default).

**Create a tester account**

1. Give the tester the site URL, their email, and the invite code (out of band — not in public chat).
2. They open Register, enter email + password + **Invite code**, submit.
3. Wrong/missing code → clear message; correct code → account created.

You can also register yourself first with the code, then share login credentials for a shared tester user (less ideal).

Set `FREE_BRIEFS_PER_MONTH=3` so each account sees “N of 3 free briefs left this month”. At the limit the API returns 402 with: *You've used all free briefs for this month (3 of 3). Try again next month.*

## Environment variable audit

| Name | Service | Required | Default | Secret | Notes |
|------|---------|----------|---------|--------|-------|
| `JWT_SECRET` | API | **Prod yes** | insecure `dev-secret-…` | yes | **Refuses to start** if `RENDER`/`ENV=production` and missing/short/dev default |
| `GROQ_API_KEY` | API | yes (for briefs) | unset | yes | Briefs fail without it |
| `MARKET_SERVICE_URL` | API | yes | `http://localhost:3001` | no | Must be Render market URL in prod |
| `MARKET_SERVICE_SECRET` | API + market | **Prod yes (24+ chars)** | empty | yes | **Same value on both.** Production **refuses to start** if missing/short. Non-prod: market open if unset |
| `FRONTEND_ORIGIN` / `CORS_ORIGINS` | API | prod yes | localhost list | no | **Unsafe if empty in prod:** browser CORS may miss your Vercel URL |
| `DB_PATH` | API | yes with disk | `backend/data/users.db` | no | `/var/data/users.db` on Render |
| `PERSISTENT_DISK_MOUNT` | API | yes with disk | unset → `db_persistent=false` | no | `/var/data` |
| `SIGNUP_CODE` | API | for closed signup | unset = open | yes | Set before inviting testers. Prod logs “registration is OPEN” if unset; `/health.signup_open` |
| `SUPPORT_CONTACT` | API | optional | `the team` | no | Used in free-brief limit message (“Contact … for more.”) |
| `FREE_BRIEFS_PER_MONTH` | API | optional | `12` | no | Use `3` for testers |
| `ALERTS_SCHEDULER` | API | optional | `1` | no | Use `0` for testers |
| `RENDER` or `ENV=production` | API + market | **prod yes** | unset | no | Enables JWT / market-secret fail-fast and signup-open warning. Render sets `RENDER` automatically |
| `SERPAPI_KEY` | market | yes | unset | yes | Searches fail without it |
| `SERP_BUDGET_PK` | market | optional | `5` | no | Cap SerpApi calls per PK brief |
| `DEFAULT_REGION` / `DEFAULT_COUNTRY_CODE` / `DEFAULT_LOCATION` / `DEFAULT_LANGUAGE` | API + market | optional | uk / United Kingdom / en | no | |
| `GROQ_MODEL` / `GROQ_FALLBACK_MODEL` | API | optional | gpt-oss-120b / 20b | no | |
| `JWT_EXPIRE_HOURS` | API | optional | `72` | no | |
| `MARKET_CACHE_TTL_SEC` | API | optional | `90` | no | |
| `BUYER_COUNCIL_RUN_LOG_*` | API | optional | temp dir; keep 40; 500KiB/file; 8MiB total | no | Ephemeral diagnostics |
| `DB_BACKUP_DIR` | API/script | optional | `<db_dir>/backups` | no | |
| `SMTP_*` / `ALERT_EMAIL_*` | API | optional | email off | yes (password) | Leave unset for testers |
| `ALERTS_CRON_SECRET` / `EMAIL_BOUNCE_SECRET` | API | if using cron/bounce | unset | yes | |
| `PORT` | market | optional | `3001` | no | Render injects |
| `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` | market | optional | unset | no | Use `1` on Render |
| `REGION_PROFILES_DIR` | API + market | optional | repo `shared/region_profiles` | no | |
| `RENDER` / `ENV` / `ENVIRONMENT` | API | auto/prod flag | unset | no | Triggers JWT production check |
| `VITE_API_URL` | frontend (build) | prod yes | localhost fallback | no | Set on Vercel |

**Do not apply the Blueprint to existing services** — it can recreate them and clear secrets. Prefer manual plan/disk/env edits. Copy every current env value to a safe place **outside chat** before changes.

## Pre-deploy / go-live checklist (do in this order)

1. **Env var backup** — export/screenshot every env on `council-api` and `council-market` to a secure offline note.
2. **Plan upgrade + disk** — upgrade `council-api` off free; add disk mount `/var/data`, size **1 GB**. Do **not** apply Blueprint.
3. **Set env (API + market)** — `DB_PATH=/var/data/users.db`, `PERSISTENT_DISK_MOUNT=/var/data`, `SIGNUP_CODE` (invite), `SUPPORT_CONTACT` (e.g. your email), `FREE_BRIEFS_PER_MONTH=3`, `ALERTS_SCHEDULER=0`, SMTP unset; **`MARKET_SERVICE_SECRET`** same on **both** services, **≥24 chars** (fresh if ever leaked). Confirm `RENDER` is present (Render sets it) or set `ENV=production` on both.
4. **Branch switch** — point **both** services at `uk-region-fixes` (Settings → Branch). Leave `master` alone until persistence passes.
5. **Deploy** and **confirm commit hash** on both dashboards matches the intended SHA.
6. **`/health` check** — API must show `"db_persistent": true`, `db_path` under `/var/data`, and **`signup_open`: false**.
7. **Persistence test** — register (with invite code), save a brief, redeploy/restart API, confirm login + brief survive.
8. **Market 401 check** — `POST` market URL without secret header → **401**.
9. **Signup-closed check** — `/health` shows `signup_open=false`; register without code / wrong code → 403; with code → OK.
10. **SerpApi before/after** — note dashboard usage; run one UK + one Pakistan brief; compare delta to budget (~≤5 searches/PK brief).
11. **Backup + off-disk restore test** — `python scripts/backup_sqlite_db.py --db /var/data/users.db`; copy a backup **off** the disk; restore to a temp path or verify `--restore` on a copy.
12. **Rollback** — if any step fails, switch both services’ branch back to the **last verified commit/branch** (do not debug live with testers waiting).

### SQLite backup / restore commands

```bash
python scripts/backup_sqlite_db.py --db /var/data/users.db --dir /var/data/backups
# Keep last 7. Copy a file off-disk, then:
python scripts/backup_sqlite_db.py --db /tmp/users-restore-test.db \
  --restore /path/to/copied/users-….db
```

## Vercel — frontend

- `VITE_API_URL` = `https://council-api-rbod.onrender.com`
- Root: `frontend`; build: `npm run build`; output: `dist`

## Blueprint (optional, new stacks only)

Repo `render.yaml` is for greenfield Blueprint creates. **Do not** re-apply onto live `council-api` / `council-market` if that would wipe env.
