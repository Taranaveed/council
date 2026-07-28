type SellerRow = {
  vendor?: string;
  price?: string;
  title?: string;
  link?: string;
  vendor_status?: string;
  price_source?: string;
  currency?: string;
  currency_mismatch?: boolean;
  price_local_approx?: string;
  note?: string;
};

function cleanHttpUrl(value: unknown): string {
  const text = String(value ?? '').trim();
  if (!text) return '';
  try {
    const parsed = new URL(text);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.toString() : '';
  } catch {
    return '';
  }
}

function hostLabel(href: string): string {
  try {
    return new URL(href).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

type Props = {
  rows: SellerRow[];
  emptyMessage?: string;
  showNote?: boolean;
  onCopyAll?: () => void;
  copyLabel?: string;
  hint?: string;
};

/** Live seller / listing links — primary surface for bulk buyers. */
export function SellerLinksTable({
  rows,
  emptyMessage = 'No seller links yet. Run a search to pull live offers.',
  showNote = false,
  onCopyAll,
  copyLabel = 'Copy all links',
  hint = 'Open a seller page to check MOQ, stock, and unit price.',
}: Props) {
  if (!rows.length) {
    return <p className="dash-meta">{emptyMessage}</p>;
  }

  const linkedCount = rows.filter((r) => cleanHttpUrl(r.link)).length;

  return (
    <div className="seller-links">
      <div className="seller-links__head">
        <div>
          <p className="seller-links__title">
            {linkedCount} seller{linkedCount === 1 ? '' : 's'}
          </p>
          <p className="seller-links__hint">{hint}</p>
        </div>
        {onCopyAll && linkedCount > 0 ? (
          <button type="button" className="seller-links__copy" onClick={onCopyAll}>
            {copyLabel}
          </button>
        ) : null}
      </div>

      <ul className="seller-links__list">
        {rows.map((row, i) => {
          const href = cleanHttpUrl(row.link);
          const verified = String(row.vendor_status || '').toLowerCase() === 'verified';
          const foreign = Boolean(row.currency_mismatch);
          const host = href ? hostLabel(href) : '';
          return (
            <li key={`${row.vendor}-${row.title}-${i}`} className="seller-links__row">
              <div className="seller-links__main">
                <div className="seller-links__seller">
                  <span className="seller-links__vendor">{row.vendor || 'Unknown'}</span>
                  {verified ? (
                    <span className="seller-links__chip seller-links__chip--ok" title="Verified seller site">
                      Verified
                    </span>
                  ) : null}
                  {foreign ? (
                    <span className="seller-links__chip" title="Foreign currency">
                      Foreign
                    </span>
                  ) : null}
                </div>
                <p className="seller-links__product">{row.title || (showNote ? row.note : '') || '—'}</p>
                {showNote && row.note && row.title ? (
                  <p className="seller-links__note">{row.note}</p>
                ) : null}
                {host ? <p className="seller-links__host">{host}</p> : null}
              </div>

              <div className="seller-links__aside">
                <p className="seller-links__price">{row.price || '—'}</p>
                {row.price_local_approx ? (
                  <p className="seller-links__approx">{row.price_local_approx}</p>
                ) : null}
                {href ? (
                  <a href={href} target="_blank" rel="noreferrer" className="seller-links__open">
                    Open
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
                      <path
                        d="M3 8h10M9 4l4 4-4 4"
                        stroke="currentColor"
                        strokeWidth="1.75"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </a>
                ) : (
                  <span className="seller-links__none">No link</span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function formatSellerLinksClipboard(rows: SellerRow[]): string {
  return rows
    .map((row) => {
      const href = cleanHttpUrl(row.link);
      if (!href) return '';
      const bits = [row.vendor || 'Seller', row.price, row.title].filter(Boolean);
      return `${bits.join(' · ')}\n${href}`;
    })
    .filter(Boolean)
    .join('\n\n');
}

export { cleanHttpUrl };
export type { SellerRow };
