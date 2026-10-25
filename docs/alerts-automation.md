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

## Email safety and sender setup

Email is disabled unless `ALERT_EMAIL_ENABLED=1`. SMTP settings alone do not
enable it. Each message includes:

- a `List-Unsubscribe` header,
- one-click `List-Unsubscribe-Post`,
- a visible unsubscribe link in the body.

The default cap is three alert emails per user per UTC day
(`ALERT_EMAIL_DAILY_CAP=3`). Unsubscribed users stay eligible for in-app alerts.

Before enabling production email:

1. Use a dedicated sending subdomain, such as `alerts.example.com`.
2. Publish the SMTP provider's SPF record.
3. Enable DKIM signing and publish the provider's DKIM records.
4. Publish DMARC in monitoring mode first (`p=none`), then tighten after review.
5. Set `SMTP_FROM` to an address on the authenticated domain.
6. Set `PUBLIC_API_ORIGIN` so unsubscribe links use the public HTTPS API.
7. Set `EMAIL_BOUNCE_SECRET` and configure the provider webhook to call
   `POST /api/workspace/email/bounce` with `X-Bounce-Secret`.

The bounce endpoint is provider-neutral scaffolding. It records the event and
suppresses future alert email for the address. A provider adapter still needs
to validate the provider's signed webhook and map its payload to
`email`, `event_type`, and `provider_event_id`.
