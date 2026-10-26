import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { fetchSharedBrief } from '../lib/api';
import { friendlyVerdict } from '../lib/friendlyLabels';

/** Public read-only deal brief share page. */
export function SharedBriefPage() {
  const { token } = useParams<{ token: string }>();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const row = await fetchSharedBrief(token);
        if (!cancelled) setData(row);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Brief not found');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (error) {
    return (
      <div className="shared-brief">
        <p className="dash-error">{error}</p>
        <Link to="/login">Go to Council</Link>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="shared-brief">
        <p className="dash-meta">Loading shared brief…</p>
      </div>
    );
  }

  const payload = (data.payload as Record<string, unknown>) || {};
  const verdict = (payload.verdict as Record<string, unknown>) || {};
  const listings = (payload.market_listings as Array<Record<string, unknown>>) || [];

  return (
    <div className="shared-brief">
      <header className="shared-brief__head">
        <p className="shared-brief__brand">Council</p>
        <p className="shared-brief__kicker">Shared deal brief · read only</p>
      </header>
      <span className="dash-verdict-pill dash-verdict-pill--maybe">
        {friendlyVerdict(data.verdict_tag || verdict.verdict)}
      </span>
      <h1 className="shared-brief__title">{String(data.item_name || '')}</h1>
      <p className="shared-brief__meta">
        {[data.location, data.quantity != null ? `qty ${data.quantity}` : null, data.buying_mode]
          .filter(Boolean)
          .join(' · ')}
      </p>
      {data.winner_title || data.winner_vendor ? (
        <div className="shared-brief__card">
          <p className="shared-brief__label">Winner</p>
          <p>
            <strong>{String(data.winner_title || data.winner_vendor || '')}</strong>
          </p>
          <p>
            {[data.winner_vendor, data.winner_price, data.landed_mid].filter(Boolean).join(' · ')}
          </p>
          {data.winner_link ? (
            <a href={String(data.winner_link)} target="_blank" rel="noreferrer">
              Open listing
            </a>
          ) : null}
        </div>
      ) : null}
      {data.summary ? <p className="shared-brief__summary">{String(data.summary)}</p> : null}
      {listings.length > 0 ? (
        <ul className="shared-brief__list">
          {listings.slice(0, 8).map((row, i) => (
            <li key={i}>
              <strong>{String(row.vendor || 'Seller')}</strong> · {String(row.price || 'n/a')}
              {row.link ? (
                <>
                  {' '}
                  ·{' '}
                  <a href={String(row.link)} target="_blank" rel="noreferrer">
                    Open
                  </a>
                </>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="shared-brief__disclaimer">
        Council ranks live listings. It does not verify sellers, customs, or stock.
      </p>
      <Link to="/login" className="shared-brief__cta">
        Run your own brief
      </Link>
    </div>
  );
}
