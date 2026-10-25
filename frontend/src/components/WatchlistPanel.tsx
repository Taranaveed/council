import { useEffect, useState } from 'react';
import {
  addWatchlistItem,
  checkWatchlistItem,
  dismissReminder,
  getCredits,
  listReminders,
  listWatchlist,
  removeWatchlistItem,
  type CreditStatus,
  type WatchItem,
} from '../lib/api';

type Props = {
  defaultItem?: string;
  location?: string;
  currency?: string;
  quantity?: number;
  credits?: CreditStatus | null;
  /** Parent already shows the meter — don't repeat it. */
  hideCredits?: boolean;
  onReorderItem?: (itemName: string, briefId?: number) => void;
  trackedListing?: {
    link: string;
    title?: string;
    vendor?: string;
    price: string;
    currency: string;
    priceSource?: string;
  } | null;
};

/** Phase 3 — reorder nudges + watchlist (collapsed by default). */
export function WatchlistPanel({
  defaultItem,
  location,
  currency,
  quantity,
  credits: creditsProp,
  hideCredits = false,
  onReorderItem,
  trackedListing,
}: Props) {
  const [creditsLocal, setCreditsLocal] = useState<CreditStatus | null>(null);
  const [items, setItems] = useState<WatchItem[]>([]);
  const [reminders, setReminders] = useState<Array<Record<string, unknown>>>([]);
  const [maxPrice, setMaxPrice] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const credits = creditsProp ?? creditsLocal;

  const refresh = async () => {
    try {
      const [c, w, r] = await Promise.all([
        hideCredits ? Promise.resolve(null) : getCredits(),
        listWatchlist(),
        listReminders(),
      ]);
      if (c) setCreditsLocal(c);
      setItems(w.items || []);
      setReminders(r.reminders || []);
    } catch {
      /* best-effort */
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const onWatch = async () => {
    const name = (defaultItem || '').trim();
    if (name.length < 2) {
      setMsg('Enter a product above, then watch it.');
      return;
    }
    if (!trackedListing?.link || !trackedListing.price || !trackedListing.currency) {
      setMsg('Run a brief and choose a priced listing before adding a watch.');
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const n = Number.parseFloat(maxPrice);
      await addWatchlistItem({
        item_name: name,
        tracked_url: trackedListing.link,
        listing_title: trackedListing.title,
        listing_vendor: trackedListing.vendor,
        native_currency: trackedListing.currency,
        saved_price: trackedListing.price,
        saved_price_source: trackedListing.priceSource || 'snippet',
        location,
        currency,
        quantity,
        max_unit_price: Number.isFinite(n) && n > 0 ? n : undefined,
      });
      setMaxPrice('');
      await refresh();
      setMsg(
        Number.isFinite(n) && n > 0
          ? 'Watching — we’ll alert when price hits your max (or drops ~5%).'
          : 'Watching — we’ll alert on a ~5% drop vs the first check.',
      );
    } catch (err) {
      setMsg(err instanceof Error ? err.message : 'Could not add watch');
    } finally {
      setBusy(false);
    }
  };

  const openByDefault = items.length > 0 || reminders.length > 0;

  return (
    <details className="watch-panel" open={openByDefault}>
      <summary className="watch-panel__summary">
        Watchlist & reminders
        {items.length > 0 ? <span className="watch-panel__count">{items.length}</span> : null}
      </summary>

      {!hideCredits && credits ? (
        <p className="watch-panel__credits" role="status">
          {credits.remaining ?? 0} free briefs left this month
        </p>
      ) : null}

      {reminders.length > 0 ? (
        <div className="watch-panel__reminders">
          <p className="watch-panel__label">Reorder nudges</p>
          <ul>
            {reminders.slice(0, 4).map((r) => {
              const id = Number(r.id);
              const name = String(r.item_name || '');
              return (
                <li key={String(r.id)}>
                  Stock check: <strong>{name}</strong>
                  {r.quantity != null ? ` · qty ${String(r.quantity)}` : ''}
                  <div className="watch-panel__row-actions" style={{ flexDirection: 'row', marginTop: 6 }}>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        onReorderItem?.(name, Number.isFinite(id) ? id : undefined);
                      }}
                    >
                      Re-run
                    </button>
                    <button
                      type="button"
                      disabled={busy || !Number.isFinite(id)}
                      onClick={() => {
                        setBusy(true);
                        void dismissReminder(id)
                          .then(() => refresh())
                          .finally(() => setBusy(false));
                      }}
                    >
                      Dismiss
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      <div className="watch-panel__add">
        <input
          type="number"
          inputMode="decimal"
          placeholder="Max unit price (optional)"
          value={maxPrice}
          onChange={(e) => setMaxPrice(e.target.value)}
          aria-label="Max unit price"
        />
        <button
          type="button"
          disabled={busy || !defaultItem?.trim() || !trackedListing?.link}
          onClick={() => void onWatch()}
        >
          Watch
        </button>
      </div>
      {msg ? <p className="watch-panel__msg">{msg}</p> : null}

      {items.length === 0 ? (
        <p className="dash-meta">After a brief, set a max price and watch for drops.</p>
      ) : (
        <ul className="watch-panel__list">
          {items.map((w) => (
            <li key={w.id}>
              <div>
                <strong>{w.item_name}</strong>
                {w.listing_vendor || w.listing_title ? (
                  <span className="watch-panel__meta">
                    {' '}
                    · {w.listing_vendor || w.listing_title}
                  </span>
                ) : null}
                {w.saved_price ? (
                  <span className="watch-panel__meta">
                    {' '}
                    · saved {w.saved_price} {w.native_currency || ''}
                    {w.saved_price_source === 'page' ? ' (page)' : ' (snippet price)'}
                  </span>
                ) : null}
                {w.max_unit_price != null ? (
                  <span className="watch-panel__meta"> · max {w.max_unit_price}</span>
                ) : null}
                {w.last_checked_at ? (
                  <span className="watch-panel__meta">
                    {' '}
                    · checked {String(w.last_checked_at).slice(0, 16).replace('T', ' ')}
                  </span>
                ) : (
                  <span className="watch-panel__meta"> · awaiting first auto-check</span>
                )}
                {w.last_alert ? <p className="watch-panel__alert">{w.last_alert}</p> : null}
                {w.last_best_link ? (
                  <a href={w.last_best_link} target="_blank" rel="noreferrer">
                    Open best seen
                  </a>
                ) : null}
              </div>
              <div className="watch-panel__row-actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setBusy(true);
                    void checkWatchlistItem(w.id)
                      .then((row) => {
                        void refresh();
                        if ((row as WatchItem & { alert_fired?: boolean }).alert_fired) {
                          setMsg('Alert fired — see Alerts inbox.');
                        }
                      })
                      .finally(() => setBusy(false));
                  }}
                >
                  Check
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setBusy(true);
                    void removeWatchlistItem(w.id)
                      .then(() => refresh())
                      .finally(() => setBusy(false));
                  }}
                >
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
