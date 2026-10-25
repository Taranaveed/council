import { useCallback, useEffect, useState } from 'react';
import {
  dismissReminder,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  runWorkspaceAlerts,
  type AppNotification,
} from '../lib/api';

type Props = {
  /** Called when user wants to re-run a product from a reorder nudge. */
  onReorderItem?: (itemName: string, briefId?: number) => void;
};

/** Alerts & Automation — deal drops + reorder reminders inbox. */
export function AlertsInbox({ onReorderItem }: Props) {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await listNotifications({ limit: 20 });
      setItems(data.items || []);
      setUnread(data.unread ?? 0);
    } catch {
      /* best-effort */
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const tick = await runWorkspaceAlerts(false);
        if (cancelled) return;
        setItems(tick.notifications || []);
        setUnread(tick.unread ?? 0);
        if (tick.alerts_fired > 0) {
          setStatus(
            tick.alerts_fired === 1
              ? '1 new deal alert from your watches.'
              : `${tick.alerts_fired} new deal alerts from your watches.`,
          );
        } else if (tick.watches_checked > 0) {
          setStatus(`Checked ${tick.watches_checked} watch${tick.watches_checked === 1 ? '' : 'es'}.`);
        }
      } catch {
        if (!cancelled) await refresh();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  const onMarkAll = async () => {
    setBusy(true);
    try {
      await markAllNotificationsRead();
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const onOpen = async (n: AppNotification) => {
    if (n.unread) {
      try {
        await markNotificationRead(n.id);
        setItems((prev) =>
          prev.map((x) => (x.id === n.id ? { ...x, unread: false } : x)),
        );
        setUnread((u) => Math.max(0, u - 1));
      } catch {
        /* ignore */
      }
    }
    const meta = n.meta || {};
    const briefId = typeof meta.brief_id === 'number' ? meta.brief_id : undefined;
    const itemName = typeof meta.item_name === 'string' ? meta.item_name : '';
    if (n.kind === 'reorder_reminder' && onReorderItem && itemName) {
      onReorderItem(itemName, briefId);
      if (briefId != null) {
        try {
          await dismissReminder(briefId);
        } catch {
          /* ignore */
        }
      }
      return;
    }
    if (n.href && /^https?:\/\//i.test(n.href)) {
      window.open(n.href, '_blank', 'noopener,noreferrer');
    }
  };

  const openByDefault = unread > 0 || items.length > 0;

  return (
    <details className="alerts-inbox" open={openByDefault}>
      <summary className="alerts-inbox__summary">
        <span>Alerts</span>
        {unread > 0 ? <span className="alerts-inbox__badge">{unread}</span> : null}
      </summary>

      <p className="alerts-inbox__hint">
        Price drops and reorder nudges land here. Optional email needs SMTP in the backend env.
      </p>

      <div className="alerts-inbox__actions">
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setStatus(null);
            void runWorkspaceAlerts(true)
              .then((tick) => {
                setItems(tick.notifications || []);
                setUnread(tick.unread ?? 0);
                setStatus(
                  tick.alerts_fired
                    ? `${tick.alerts_fired} alert${tick.alerts_fired === 1 ? '' : 's'} fired.`
                    : `Checked ${tick.watches_checked} watch${tick.watches_checked === 1 ? '' : 'es'}.`,
                );
              })
              .catch((err) =>
                setStatus(err instanceof Error ? err.message : 'Alert check failed'),
              )
              .finally(() => setBusy(false));
          }}
        >
          {busy ? 'Checking…' : 'Check now'}
        </button>
        <button type="button" disabled={busy || unread === 0} onClick={() => void onMarkAll()}>
          Mark all read
        </button>
      </div>

      {status ? <p className="alerts-inbox__status">{status}</p> : null}

      {items.length === 0 ? (
        <p className="dash-meta">
          No alerts yet. Watch a product with a max price, or mark a brief as ordered for a 30-day
          reorder nudge.
        </p>
      ) : (
        <ul className="alerts-inbox__list">
          {items.map((n) => (
            <li key={n.id} className={n.unread ? 'is-unread' : undefined}>
              <button type="button" className="alerts-inbox__item" onClick={() => void onOpen(n)}>
                <span className="alerts-inbox__kind">
                  {n.kind === 'reorder_reminder'
                    ? 'Reorder'
                    : n.kind === 'price_drop'
                      ? 'Drop'
                      : 'Deal'}
                </span>
                <strong>{n.title}</strong>
                <span className="alerts-inbox__body">{n.body}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
