# Alerts automation operations

## Scheduler and host sleep

The in-process scheduler runs only while the backend process is awake. On a
free/sleeping host, no watch checks happen during sleep. After wake, the next
loop checks stale watches; opening the dashboard also checks that user's stale
watches.

For dependable timing, configure an external cron to call:

`POST /api/workspace/alerts/cron`

with header:

`X-Cron-Secret: <ALERTS_CRON_SECRET>`

Set a long random `ALERTS_CRON_SECRET` in the backend environment. If it is
unset, the endpoint returns 503. A wrong or missing header returns 401.

## Multiple instances

Every tick takes a leased `alerts_scheduler` lock in SQLite. Only the lock
owner runs the tick; other instances return `scheduler_lock_held`. This works
when instances share the same database file. Separate ephemeral SQLite files
cannot coordinate; use one scheduler-enabled instance or migrate the lock and
application data to a shared database before scaling horizontally.

## Relevant settings

- `ALERTS_SCHEDULER=1`: enable the in-process loop.
- `ALERTS_POLL_SECONDS=900`: loop interval.
- `ALERT_STALE_HOURS=12`: watch recheck interval.
- `WATCH_CACHE_TTL_HOURS=6`: exact-listing refresh cache.
- `ALERTS_CRON_SECRET`: protects the external cron endpoint.
