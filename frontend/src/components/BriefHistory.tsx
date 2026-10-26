import type { BriefSummary, CompareToPrior } from '../lib/api';

type HistoryProps = {
  briefs: BriefSummary[];
  activeId?: number | null;
  loading?: boolean;
  onSelect: (id: number) => void;
  onRefresh?: () => void;
};

export function BriefHistory({
  briefs,
  activeId,
  loading,
  onSelect,
  onRefresh,
}: HistoryProps) {
  return (
    <div className="brief-history">
      <div className="brief-history__head">
        <p className="brief-history__title">Saved briefs</p>
        {onRefresh ? (
          <button
            type="button"
            className="brief-history__refresh"
            onClick={onRefresh}
            disabled={loading}
          >
            Refresh
          </button>
        ) : null}
      </div>
      {loading && !briefs.length ? (
        <p className="dash-meta">Loading history…</p>
      ) : null}
      {!loading && !briefs.length ? (
        <p className="dash-meta">
          Runs you finish will appear here — so you can compare the next quote to the last one.
        </p>
      ) : null}
      {briefs.length > 0 ? (
        <ul className="brief-history__list">
          {briefs.map((b) => {
            const tag = String(b.verdict_tag || '').toUpperCase();
            const label =
              tag === 'PASS' || tag === 'SKIP' ? 'SKIP' : tag || '—';
            return (
              <li key={b.id}>
                <button
                  type="button"
                  className={`brief-history__item${activeId === b.id ? ' brief-history__item--active' : ''}`}
                  onClick={() => onSelect(b.id)}
                >
                  <span className="brief-history__row">
                    <span className="brief-history__name">{b.item_name}</span>
                    <span
                      className={`brief-history__tag brief-history__tag--${label.toLowerCase().replace(/\s+/g, '-')}`}
                    >
                      {label}
                    </span>
                  </span>
                  <span className="brief-history__meta">
                    {[b.winner_vendor || b.supplier_host, b.winner_price || b.landed_mid]
                      .filter(Boolean)
                      .join(' · ') || 'No pick'}
                    {b.fake_cheap ? ' · flagged fake-cheap' : ''}
                    {(b.supplier_fake_cheap_count || 0) > 0 && !b.fake_cheap
                      ? ` · supplier flagged ${b.supplier_fake_cheap_count}×`
                      : ''}
                  </span>
                  {b.created_at ? (
                    <span className="brief-history__when">{formatWhen(b.created_at)}</span>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

type CompareProps = {
  compare: CompareToPrior;
};

export function CompareToPriorStrip({ compare }: CompareProps) {
  const priorTag = String(compare.prior_verdict || '').toUpperCase();
  const curTag = String(compare.current_verdict || '').toUpperCase();
  const priorLabel = priorTag === 'PASS' || priorTag === 'SKIP' ? 'SKIP' : priorTag || '—';
  const curLabel = curTag === 'PASS' || curTag === 'SKIP' ? 'SKIP' : curTag || '—';

  return (
    <div className="compare-prior" role="status">
      <p className="compare-prior__label">
        Compared to last {compare.match_basis === 'same_supplier' ? 'supplier' : 'query'} brief
        {compare.prior_created_at ? ` (${formatWhen(compare.prior_created_at)})` : ''}
      </p>
      <p className="compare-prior__body">
        Was <strong>{priorLabel}</strong>
        {compare.prior_winner_price ? ` · ${compare.prior_winner_price}` : ''}
        {compare.prior_landed_mid ? ` · landed ${compare.prior_landed_mid}` : ''}
        {compare.prior_winner_vendor ? ` · ${compare.prior_winner_vendor}` : ''}
        {' → now '}
        <strong>{curLabel}</strong>
        {compare.current_winner_price ? ` · ${compare.current_winner_price}` : ''}
        {compare.current_landed_mid ? ` · landed ${compare.current_landed_mid}` : ''}
        {compare.verdict_flipped ? ' · verdict flipped' : ''}
      </p>
    </div>
  );
}

type FakeCheapProps = {
  briefId: number;
  fakeCheap: boolean;
  supplierHost?: string | null;
  supplierFlagCount?: number;
  busy?: boolean;
  onToggle: (next: boolean) => void;
};

export function FakeCheapToggle({
  briefId: _briefId,
  fakeCheap,
  supplierHost,
  supplierFlagCount = 0,
  busy,
  onToggle,
}: FakeCheapProps) {
  return (
    <div className="fake-cheap">
      <button
        type="button"
        className={`fake-cheap__btn${fakeCheap ? ' fake-cheap__btn--on' : ''}`}
        disabled={busy}
        onClick={() => onToggle(!fakeCheap)}
      >
        {fakeCheap ? 'Marked fake-cheap' : 'Mark as fake-cheap'}
      </button>
      {supplierHost && supplierFlagCount > 0 ? (
        <p className="fake-cheap__note">
          You’ve flagged {supplierHost} as fake-cheap {supplierFlagCount} time
          {supplierFlagCount === 1 ? '' : 's'} before.
        </p>
      ) : (
        <p className="fake-cheap__note">
          Use this when a quote looked real but turned out wrong — builds your supplier memory.
        </p>
      )}
    </div>
  );
}

function formatWhen(iso: string): string {
  try {
    const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z');
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}
