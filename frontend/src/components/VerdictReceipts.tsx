/** Auditable receipts for a Buy / Maybe / Skip brief — Phase 0 trust surface. */

type Winner = {
  title?: string;
  vendor?: string;
  price?: string;
  link?: string;
  reason?: string;
};

type Landed = {
  formula?: string;
  estimated_total?: string;
  range_low?: string;
  range_high?: string;
  assumptions?: string[];
};

type CostAssumptions = {
  duty_rate_mid?: number;
  duty_rate_low?: number;
  duty_rate_high?: number;
  sales_tax_rate?: number;
  freight_usd_per_kg_mid?: number;
  label?: string;
};

type Relevance = {
  relevant_priced_count?: number;
  dropped_count?: number;
  drop_reasons?: Record<string, number>;
  no_good_matches?: boolean;
  listing_counts?: { found?: number; relevant?: number; priced?: number };
};

type Props = {
  briefId?: string | null;
  verdictTag?: string;
  winner?: Winner | null;
  winnerLink?: string;
  landed?: Landed | null;
  costAssumptions?: CostAssumptions | null;
  relevance?: Relevance | null;
  marketWarning?: string | null;
  skipReason?: string | null;
  serpSourceStatus?: Array<{ label?: string; status?: string; ok?: boolean }> | null;
};

const DROP_LABELS: Record<string, string> = {
  not_priced_product_page: 'Not a priced product page',
  off_category: 'Off-category / wrong product',
  price_outlier: 'Price outlier / unreliable unit',
  must_have_miss: 'Missing a must-have from your query',
  retail_in_bulk: 'Retail shelf price (excluded in bulk)',
  other: 'Other filter',
};

function pct(n: number | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return `${Math.round(n * 100)}%`;
}

function callLabel(tag: string | undefined): string {
  const t = String(tag || '').toUpperCase();
  if (t === 'PASS' || t === 'SKIP') return 'SKIP';
  if (t === 'NO_MATCH') return 'NO MATCH';
  return t || '—';
}

export function VerdictReceipts({
  briefId,
  verdictTag,
  winner,
  winnerLink,
  landed,
  costAssumptions,
  relevance,
  marketWarning,
  skipReason,
  serpSourceStatus,
}: Props) {
  const tag = String(verdictTag || '').toUpperCase();
  const isBuyOrMaybe = tag === 'BUY' || tag === 'MAYBE';
  const isSkip = tag === 'PASS' || tag === 'SKIP' || tag === 'NO_MATCH';
  const dropEntries = Object.entries(relevance?.drop_reasons || {}).filter(([, n]) => n > 0);
  const hasLanded = Boolean(landed?.estimated_total || landed?.formula);
  const showAssumptions = isBuyOrMaybe && hasLanded;
  const assumptionLines =
    showAssumptions && landed?.assumptions && landed.assumptions.length
      ? landed.assumptions
      : [];
  const reasonText = (skipReason || winner?.reason || '').trim();

  return (
    <section className="verdict-receipts" aria-label="Deal brief receipts">
      <div className="verdict-receipts__head">
        <p className="verdict-receipts__label">Brief receipts</p>
        {briefId ? (
          <p className="verdict-receipts__id">
            Brief ID <code>{briefId.slice(0, 8)}</code>
          </p>
        ) : null}
      </div>

      <ul className="verdict-receipts__list">
        <li>
          <span className="verdict-receipts__k">Call</span>
          <span className="verdict-receipts__v">{callLabel(verdictTag)}</span>
        </li>
        <li>
          <span className="verdict-receipts__k">{isSkip ? 'Buy pick' : 'Listing used'}</span>
          <span className="verdict-receipts__v">
            {isSkip ? (
              <>
                None — Council did not recommend a buy.
                {reasonText ? ` ${reasonText.slice(0, 220)}${reasonText.length > 220 ? '…' : ''}` : ''}
                {' '}Open the Sellers tab to review comps yourself.
              </>
            ) : winnerLink ? (
              <>
                <a href={winnerLink} target="_blank" rel="noreferrer">
                  {[winner?.vendor, winner?.title].filter(Boolean).join(' — ') || 'Open listing'}
                </a>
                {winner?.price ? ` · ${winner.price}` : ''}
              </>
            ) : (
              winner?.title || winner?.vendor || 'No listing attached to this call'
            )}
          </span>
        </li>
        {showAssumptions ? (
          <li>
            <span className="verdict-receipts__k">Landed math</span>
            <span className="verdict-receipts__v">
              {landed?.estimated_total ? `Mid ${landed.estimated_total}` : null}
              {landed?.formula ? (
                <>
                  {landed.estimated_total ? ' · ' : null}
                  {landed.formula}
                </>
              ) : null}
              {landed?.range_low && landed?.range_high
                ? ` · Range ${landed.range_low} – ${landed.range_high}`
                : null}
            </span>
          </li>
        ) : null}
        {showAssumptions &&
        costAssumptions &&
        (costAssumptions.duty_rate_mid != null || costAssumptions.freight_usd_per_kg_mid != null) ? (
          <li>
            <span className="verdict-receipts__k">Assumption sources</span>
            <span className="verdict-receipts__v">
              Duty mid {pct(costAssumptions.duty_rate_mid)}
              {costAssumptions.duty_rate_low != null && costAssumptions.duty_rate_high != null
                ? ` (band ${pct(costAssumptions.duty_rate_low)}–${pct(costAssumptions.duty_rate_high)})`
                : ''}
              {costAssumptions.freight_usd_per_kg_mid != null
                ? ` · Freight ~$${costAssumptions.freight_usd_per_kg_mid}/kg mid`
                : ''}
              {costAssumptions.sales_tax_rate != null && costAssumptions.sales_tax_rate > 0
                ? ` · Sales tax ${pct(costAssumptions.sales_tax_rate)}`
                : ''}
              {' · '}
              Council model rates — not official customs quotes.
            </span>
          </li>
        ) : null}
        {assumptionLines.length ? (
          <li>
            <span className="verdict-receipts__k">Assumptions used</span>
            <span className="verdict-receipts__v">{assumptionLines.join(' · ')}</span>
          </li>
        ) : null}
        {relevance ? (
          <li>
            <span className="verdict-receipts__k">Listings</span>
            <span className="verdict-receipts__v">
              {(() => {
                const c = relevance.listing_counts;
                const priced = c?.priced ?? relevance.relevant_priced_count ?? 0;
                const relevant = c?.relevant ?? priced;
                const found =
                  c?.found ??
                  priced + (relevance.dropped_count ?? 0);
                return `${found} found · ${relevant} relevant · ${priced} priced`;
              })()}
            </span>
          </li>
        ) : null}
        {dropEntries.length ? (
          <li>
            <span className="verdict-receipts__k">Why dropped</span>
            <span className="verdict-receipts__v">
              {dropEntries
                .map(([k, n]) => `${DROP_LABELS[k] || k}: ${n}`)
                .join(' · ')}
            </span>
          </li>
        ) : null}
        {serpSourceStatus && serpSourceStatus.length ? (
          <li>
            <span className="verdict-receipts__k">Serp sources</span>
            <span className="verdict-receipts__v">
              {serpSourceStatus
                .map((s) => `${s.label || '?'}:${s.status || (s.ok ? 'ok' : 'fail')}`)
                .join(' · ')}
            </span>
          </li>
        ) : null}
        {marketWarning ? (
          <li>
            <span className="verdict-receipts__k">Search note</span>
            <span className="verdict-receipts__v">{marketWarning}</span>
          </li>
        ) : null}
      </ul>
    </section>
  );
}

export function ScopeStrip() {
  return (
    <p className="scope-strip" role="note">
      Council is a sourcing risk aid — Buy / Maybe / Skip from live listings and checkable landed
      math. It is not a customs broker, contract lawyer, or guarantee that a supplier will deliver.
    </p>
  );
}
