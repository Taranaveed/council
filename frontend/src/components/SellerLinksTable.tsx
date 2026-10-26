import { knownSiteLabel, KNOWN_SITE_HINT } from '../lib/vendorStatus';

export type SellerRow = {
  vendor?: string;
  price?: string;
  title?: string;
  link?: string;
  vendor_status?: string;
  price_source?: string;
  currency?: string;
  currency_mismatch?: boolean;
  price_local_approx?: string;
  best_pick?: boolean;
  pick_reason?: string;
  supplier_origin?: string;
  note?: string;
  moq?: number | string | null;
  price_tiers?: Array<{ min_qty?: number; unit_price?: string }>;
  counts_as_live_listing?: boolean;
  is_product_page?: boolean;
  unit_price_rejected?: string | boolean;
  rank_reason?: string;
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

function displayPrice(raw: unknown, row?: SellerRow): string {
  const text = String(raw ?? '').trim();
  if (row?.counts_as_live_listing === false || row?.is_product_page === false) {
    return 'price n/a';
  }
  if (!text) return 'price n/a';
  if (/^(see listing|rs\.?|pkr|usd|\$|£|€|inr|₹)[\s,.…]*$/i.test(text)) return 'price n/a';
  if (/^(n\/?a|na|null|undefined)$/i.test(text)) return 'price n/a';
  return text;
}

type Props = {
  rows: SellerRow[];
  emptyMessage?: string;
  showNote?: boolean;
  onCopyAll?: () => void;
  copyLabel?: string;
  hint?: string;
  /** When false (Skip/PASS), never show the Best pick chip. */
  showBestPick?: boolean;
  /** Authoritative listing/seller counts from parent — must match tab/status. */
  listingCount?: number;
  sellerCount?: number;
};

/** Live seller / listing links — primary surface for bulk buyers. */
export function SellerLinksTable({
  rows,
  emptyMessage = 'No seller links yet. Run a search to pull live offers.',
  showNote = false,
  onCopyAll,
  copyLabel = 'Copy all links',
  hint = 'Open a seller page to check MOQ, stock, and unit price.',
  showBestPick = true,
  listingCount,
  sellerCount,
}: Props) {
  if (!rows.length) {
    return <p className="dash-meta">{emptyMessage}</p>;
  }

  const linkedCount = rows.filter((r) => cleanHttpUrl(r.link)).length;
  const showListings = listingCount ?? linkedCount;
  const showSellers = sellerCount ?? linkedCount;

  return (
    <div className="seller-links">
      <div className="seller-links__head">
        <div>
          <p className="seller-links__title">
            {showListings} listing{showListings === 1 ? '' : 's'} · {showSellers}{' '}
            seller{showSellers === 1 ? '' : 's'}
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
          const known = knownSiteLabel(row.vendor_status);
          const foreign = Boolean(row.currency_mismatch);
          const host = href ? hostLabel(href) : '';
          const supplier = /alibaba\.|indiamart\.|made-in-china\.|dhgate\.|globalsources\.|tradeindia\.|aliexpress\.|europages\.|thomasnet\.|faire\./i.test(host);
          const best = showBestPick && Boolean(row.best_pick);
          const rankNum =
            typeof (row as { display_rank?: number }).display_rank === 'number'
              ? Number((row as { display_rank?: number }).display_rank)
              : i + 1;
          return (
            <li key={`${row.vendor}-${row.title}-${i}`} className="seller-links__row">
              <div className="seller-links__main">
                <div className="seller-links__seller">
                  <span className="seller-links__vendor">
                    #{rankNum} · {row.vendor || 'Unknown'}
                  </span>
                  {best ? (
                    <span className="seller-links__chip seller-links__chip--ok" title={row.pick_reason || 'Ranked cheap fit for your region — not a guarantee'}>
                      Best pick
                    </span>
                  ) : null}
                  {supplier && !best ? (
                    <span className="seller-links__chip seller-links__chip--ok" title="Wholesale supplier">
                      Supplier
                    </span>
                  ) : null}
                  {known ? (
                    <span className="seller-links__chip" title={KNOWN_SITE_HINT}>
                      {known}
                    </span>
                  ) : null}
                  {foreign ? (
                    <span className="seller-links__chip" title="Foreign currency">
                      Foreign
                    </span>
                  ) : null}
                </div>
                <p className="seller-links__product">{row.title || (showNote ? row.note : '') || '—'}</p>
                {showBestPick && (row.rank_reason || row.pick_reason) ? (
                  <p className="seller-links__note">
                    {row.rank_reason || row.pick_reason}
                  </p>
                ) : !showBestPick && row.rank_reason && /does not match|rejected/i.test(row.rank_reason) ? (
                  <p className="seller-links__note">{row.rank_reason}</p>
                ) : null}
                {showNote && row.note && row.title ? (
                  <p className="seller-links__note">{row.note}</p>
                ) : null}
                {host ? <p className="seller-links__host">{host}</p> : null}
              </div>

              <div className="seller-links__aside">
                <p className="seller-links__price">{displayPrice(row.price, row)}</p>
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
