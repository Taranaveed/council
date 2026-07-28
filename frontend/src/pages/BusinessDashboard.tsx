import { useEffect, useState, type FormEvent } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  runAudienceDiscovery,
  runLaunchPack,
  runPriceBargaining,
  type LaunchPackResult,
  type LaunchPackVariant,
  type ModeResult,
} from '../lib/api';
import { SellerLaunchSections } from '../components/SellerLaunchSections';
import { CURRENCIES } from '../lib/currencies';
import { DashboardShell, DeskHeader, AgentsEmpty, TranscriptBlock } from '../components/DashboardShell';
import { friendlyExpertName } from '../lib/friendlyLabels';
import {
  clearSellerRuns,
  loadSellerRuns,
  saveSellerRun,
  type SellerRunSnapshot,
} from '../lib/sellerHistory';
import { ExpandableText } from '../components/ux/ExpandableText';
import { MarketStatus, marketSeverityFromCounts } from '../components/ux/MarketStatus';
import { ResultTabs } from '../components/ux/ResultTabs';
import { SteppedLoading } from '../components/ux/SteppedLoading';

type Service = 'launch' | 'price' | 'audience';
type ServiceResult =
  | { mode: 'price' | 'audience'; data: ModeResult }
  | { mode: 'launch'; data: LaunchPackResult };

const PREFS_KEY = 'sf_seller_prefs';

type SellerPrefs = {
  service?: Service;
  currency?: string;
  location?: string;
};

function loadPrefs(): SellerPrefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    return raw ? (JSON.parse(raw) as SellerPrefs) : {};
  } catch {
    return {};
  }
}

function savePrefs(p: SellerPrefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* ignore */
  }
}

export function BusinessDashboard() {
  const { user, logout } = useAuth();
  const prefs = loadPrefs();
  const [service, setService] = useState<Service>(prefs.service || 'launch');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ServiceResult | null>(null);
  const [history, setHistory] = useState<SellerRunSnapshot[]>([]);
  const [historyPreview, setHistoryPreview] = useState<SellerRunSnapshot | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [compareVariant, setCompareVariant] = useState(false);

  const [productName, setProductName] = useState('');
  const [productSpecs, setProductSpecs] = useState('');
  const [problem, setProblem] = useState('');
  const [minPrice, setMinPrice] = useState('');
  const [maxPrice, setMaxPrice] = useState('');
  const [currency, setCurrency] = useState(() => {
    const saved = prefs.currency || 'PKR';
    return CURRENCIES.some((c) => c.code === saved) ? saved : 'PKR';
  });
  const [location, setLocation] = useState(prefs.location || '');
  const [costOfGoods, setCostOfGoods] = useState('');
  const [targetMargin, setTargetMargin] = useState('');
  const [condition, setCondition] = useState('');
  const [category, setCategory] = useState('');
  const [competitorLinks, setCompetitorLinks] = useState('');
  const [variantBName, setVariantBName] = useState('');
  const [variantBSpecs, setVariantBSpecs] = useState('');

  useEffect(() => {
    setHistory(loadSellerRuns());
  }, []);

  useEffect(() => {
    savePrefs({ service, currency, location });
  }, [service, currency, location]);

  const economics = {
    cost_of_goods: costOfGoods || undefined,
    target_margin_pct: targetMargin || undefined,
    condition: condition || undefined,
    category: category || undefined,
    competitor_links: competitorLinks || undefined,
  };

  const canSubmit =
    productName.trim().length >= 4 &&
    (service === 'audience' || (minPrice.trim() && maxPrice.trim())) &&
    (service !== 'launch' || location.trim().length >= 2);

  const resolvedSpecs = productSpecs.trim() || productName.trim();
  const resolvedProblem =
    problem.trim() || `Practical everyday needs for ${productName.trim()}`;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) {
      setError(
        service === 'launch' && location.trim().length < 2
          ? 'Add a city or country so we can pull local prices.'
          : 'Add a clear product name and your price band.',
      );
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setHistoryPreview(null);
    try {
      if (service === 'launch') {
        const data = await runLaunchPack({
          product_name: productName,
          product_specs: resolvedSpecs,
          problem_solved: resolvedProblem,
          price_range_min: minPrice,
          price_range_max: maxPrice,
          currency,
          location: location || undefined,
          variant_b_name: compareVariant ? variantBName || undefined : undefined,
          variant_b_specs: compareVariant ? variantBSpecs || undefined : undefined,
          ...economics,
        });
        setResult({ mode: 'launch', data });
        setHistory(
          saveSellerRun({
            productName,
            location,
            currency,
            mode: 'launch',
            listPrice: String(data.primary.action_pack?.list_price || ''),
            topChannel: String(data.primary.action_pack?.top_channel || ''),
            exportText: data.primary.export_text,
            summary: String(data.primary.audience_verdict?.summary || ''),
          }),
        );
      } else if (service === 'price') {
        const data = await runPriceBargaining({
          product_specs: resolvedSpecs,
          product_name: productName || undefined,
          problem_solved: problem.trim() || undefined,
          price_range_min: minPrice,
          price_range_max: maxPrice,
          currency,
          location: location || undefined,
          ...economics,
        });
        setResult({ mode: 'price', data });
        setHistory(
          saveSellerRun({
            productName: productName || productSpecs.slice(0, 40),
            location,
            currency,
            mode: 'price',
            listPrice: String(data.verdict?.recommended_price || ''),
            exportText: [
              `Price advice — ${productName || productSpecs}`,
              `Suggested: ${String(data.verdict?.recommended_price || '—')}`,
              String(data.verdict?.summary || ''),
            ].join('\n'),
            summary: String(data.verdict?.summary || ''),
          }),
        );
      } else {
        const data = await runAudienceDiscovery({
          product_name: productName,
          problem_solved: resolvedProblem,
          product_specs: productSpecs.trim() || undefined,
          location: location || undefined,
          currency,
          price_range_min: minPrice || undefined,
          price_range_max: maxPrice || undefined,
          ...economics,
        });
        setResult({ mode: 'audience', data });
        setHistory(
          saveSellerRun({
            productName,
            location,
            currency,
            mode: 'audience',
            topChannel: String(data.verdict?.top_channel_recommendation || ''),
            exportText: [
              `Audience — ${productName}`,
              String(data.verdict?.summary || ''),
              `Channel: ${String(data.verdict?.top_channel_recommendation || '—')}`,
            ].join('\n'),
            summary: String(data.verdict?.summary || ''),
          }),
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  };

  const switchService = (next: Service) => {
    setService(next);
    setResult(null);
    setError(null);
    setHistoryPreview(null);
  };

  const loadingSteps =
    service === 'launch'
      ? ['Checking live prices…', 'Comparing price views…', 'Mapping buyers…', 'Building your pack…']
      : service === 'price'
        ? ['Checking live prices…', 'Comparing views…', 'Settling on a price…']
        : ['Reading your market…', 'Building buyer profiles…', 'Picking channels…'];

  const aside = (
    <>
      <p className="dash-proto__aside-kicker">Brief</p>
      <div className="dash-tabs dash-tabs--three">
        <button
          type="button"
          className={`dash-tabs__btn${service === 'launch' ? ' dash-tabs__btn--active' : ''}`}
          onClick={() => switchService('launch')}
        >
          Launch pack
        </button>
        <button
          type="button"
          className={`dash-tabs__btn${service === 'price' ? ' dash-tabs__btn--active' : ''}`}
          onClick={() => switchService('price')}
        >
          Fair price
        </button>
        <button
          type="button"
          className={`dash-tabs__btn${service === 'audience' ? ' dash-tabs__btn--active' : ''}`}
          onClick={() => switchService('audience')}
        >
          Who buys
        </button>
      </div>

      <form onSubmit={onSubmit} className={`brief-form${loading ? ' ux-form--dim' : ''}`}>
        <div className="brief-form__body">
          <label className="dash-field">
            Product name
            <input
              required
              minLength={4}
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              placeholder="e.g. leather phone cover"
            />
          </label>

          <label className="dash-field">
            City or country{service === 'launch' ? ' *' : ''}
            <input
              required={service === 'launch'}
              value={location}
              onChange={(e) => {
                const next = e.target.value;
                setLocation(next);
                if (/\b(pakistan|lahore|karachi|islamabad)\b/i.test(next) && currency === 'USD') {
                  setCurrency('PKR');
                }
              }}
              placeholder="e.g. Lahore or New York"
            />
          </label>

          {service !== 'audience' ? (
            <div className="dash-field">
              <span className="dash-field__label">
                Your price band <em className="brief-form__cur">{currency}</em>
              </span>
              <div className="brief-form__price-row">
                <label className="dash-field brief-form__price-field">
                  Min
                  <input required value={minPrice} onChange={(e) => setMinPrice(e.target.value)} />
                </label>
                <label className="dash-field brief-form__price-field">
                  Max
                  <input required value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} />
                </label>
                <label className="dash-field brief-form__price-field">
                  Currency
                  <select
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value)}
                    aria-label="Currency"
                  >
                    {CURRENCIES.map((c) => (
                      <option key={c.code} value={c.code}>
                        {c.code}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          ) : (
            <div className="dash-field">
              <span className="dash-field__label">
                Price band <em className="brief-form__cur">(optional)</em>
              </span>
              <div className="brief-form__price-row">
                <label className="dash-field brief-form__price-field">
                  Min
                  <input value={minPrice} onChange={(e) => setMinPrice(e.target.value)} />
                </label>
                <label className="dash-field brief-form__price-field">
                  Max
                  <input value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} />
                </label>
                <label className="dash-field brief-form__price-field">
                  Currency
                  <select
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value)}
                    aria-label="Currency"
                  >
                    {CURRENCIES.map((c) => (
                      <option key={c.code} value={c.code}>
                        {c.code}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          )}

          <button
            type="button"
            className="dash-link seller-pack__toggle"
            onClick={() => setShowDetails((v) => !v)}
          >
            {showDetails ? 'Hide details' : 'More detail'} — specs & problem
          </button>
          {showDetails ? (
            <>
              {service !== 'audience' ? (
                <label className="dash-field">
                  Specs / details
                  <textarea
                    rows={2}
                    value={productSpecs}
                    onChange={(e) => setProductSpecs(e.target.value)}
                    placeholder="Materials, size, what makes it different"
                  />
                </label>
              ) : null}
              {service !== 'price' ? (
                <label className="dash-field">
                  Problem it solves
                  <textarea
                    rows={2}
                    value={problem}
                    onChange={(e) => setProblem(e.target.value)}
                    placeholder="e.g. phones scratch and cheap cases crack"
                  />
                </label>
              ) : null}
            </>
          ) : null}

          <button
            type="button"
            className="dash-link seller-pack__toggle"
            onClick={() => setShowAdvanced((v) => !v)}
          >
            {showAdvanced ? 'Hide' : 'More options'} — cost, margin, SKU compare
          </button>
          {showAdvanced ? (
            <>
              <div className="dash-field-row">
                <label className="dash-field">
                  Cost of goods
                  <input value={costOfGoods} onChange={(e) => setCostOfGoods(e.target.value)} />
                </label>
                <label className="dash-field">
                  Target margin %
                  <input
                    value={targetMargin}
                    onChange={(e) => setTargetMargin(e.target.value)}
                    placeholder="e.g. 35"
                  />
                </label>
              </div>
              <label className="dash-field">
                Condition
                <input
                  value={condition}
                  onChange={(e) => setCondition(e.target.value)}
                  placeholder="new, handmade, refurbished…"
                />
              </label>
              <label className="dash-field">
                Category
                <input
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder="e.g. phone accessories"
                />
              </label>
              <label className="dash-field">
                Competitor links / notes
                <textarea
                  rows={2}
                  value={competitorLinks}
                  onChange={(e) => setCompetitorLinks(e.target.value)}
                  placeholder="Optional URLs or rival names"
                />
              </label>
              {service === 'launch' ? (
                <>
                  <label className="dash-field dash-field--check">
                    <input
                      type="checkbox"
                      checked={compareVariant}
                      onChange={(e) => setCompareVariant(e.target.checked)}
                    />
                    Compare a second variant / SKU
                  </label>
                  {compareVariant ? (
                    <>
                      <label className="dash-field">
                        Variant B name
                        <input
                          required
                          value={variantBName}
                          onChange={(e) => setVariantBName(e.target.value)}
                          placeholder="e.g. silicone cover"
                        />
                      </label>
                      <label className="dash-field">
                        Variant B specs
                        <textarea
                          required
                          rows={2}
                          value={variantBSpecs}
                          onChange={(e) => setVariantBSpecs(e.target.value)}
                        />
                      </label>
                    </>
                  ) : null}
                </>
              ) : null}
            </>
          ) : null}
        </div>

        <div className="brief-form__footer">
          <button type="submit" disabled={loading || !canSubmit} className="dash-submit">
            <span className="dash-submit__shine" aria-hidden />
            <span style={{ position: 'relative', zIndex: 1 }}>
              {loading
                ? 'Working on it…'
                : service === 'launch'
                  ? 'Build launch pack'
                  : 'Get advice'}
            </span>
          </button>
        </div>
      </form>

      {history.length > 0 ? (
        <div className="seller-history">
          <div className="seller-history__head">
            <p className="dash-kicker">Saved runs</p>
            <button
              type="button"
              className="dash-link"
              onClick={() => {
                clearSellerRuns();
                setHistory([]);
                setHistoryPreview(null);
              }}
            >
              Clear
            </button>
          </div>
          <ul className="seller-history__list">
            {history.slice(0, 6).map((run) => (
              <li key={run.id}>
                <button
                  type="button"
                  className="seller-history__item"
                  onClick={() => {
                    setResult(null);
                    setHistoryPreview(run);
                  }}
                  title="Open saved summary"
                >
                  <span className="seller-history__title">{run.productName}</span>
                  <span className="seller-history__meta">
                    {run.mode} · {run.listPrice || run.topChannel || '—'} ·{' '}
                    {new Date(run.savedAt).toLocaleString()}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );

  const desk =
    service === 'launch'
      ? {
          title: 'Seller launch desk',
          subtitle: 'One brief → price, buyers, hooks, and channel copy.',
        }
      : service === 'price'
        ? {
            title: 'Fair price desk',
            subtitle: 'Live comps → a list price you can defend.',
          }
        : {
            title: 'Buyer map desk',
            subtitle: 'Who cares → channels and messaging that fit.',
          };

  return (
    <DashboardShell role="business" email={user?.email} onLogout={logout} aside={aside}>
      <DeskHeader title={desk.title} subtitle={desk.subtitle} />
      {loading && <SteppedLoading steps={loadingSteps} />}
      {error && <p className="dash-error">{error}</p>}
      {!loading && !result && !error && !historyPreview && (
        <AgentsEmpty
          headline={
            service === 'audience'
              ? 'Multiple agents, one buyer map'
              : service === 'price'
                ? 'Multiple agents, one fair price'
                : 'Multiple agents, one council'
          }
          body="Fill the brief on the left — product, place, and price band."
          cta={
            service === 'launch'
              ? 'Then hit Build launch pack →'
              : 'Then hit Get advice →'
          }
        />
      )}
      {!loading && historyPreview && !result && (
        <HistoryPreview
          run={historyPreview}
          onClose={() => setHistoryPreview(null)}
        />
      )}
      {!loading && result?.mode === 'launch' && <LaunchPackResults data={result.data} />}
      {!loading && result?.mode === 'price' && <PriceResults data={result.data} />}
      {!loading && result?.mode === 'audience' && <AudienceResults data={result.data} />}
    </DashboardShell>
  );
}

function HistoryPreview({ run, onClose }: { run: SellerRunSnapshot; onClose: () => void }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(run.exportText);
    } catch {
      /* ignore */
    }
  };
  return (
    <div className="dash-results">
      <div className="ux-hero">
        <p className="ux-hero__kicker">Saved run · {run.mode}</p>
        <p className="ux-hero__price ux-hero__price--sm">{run.productName}</p>
        <p className="ux-hero__confidence">
          {[run.listPrice, run.topChannel, run.location].filter(Boolean).join(' · ') || '—'}
        </p>
        {run.summary ? <ExpandableText lines={3}>{run.summary}</ExpandableText> : null}
        <div className="ux-hero__ctas seller-pack__export">
          <button type="button" className="dash-submit seller-pack__btn" onClick={copy}>
            Copy export text
          </button>
          <button type="button" className="dash-link" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function parseSortPrice(price: unknown): number {
  const text = String(price ?? '').replace(/,/g, '');
  const m = text.match(/\d+(?:\.\d+)?/);
  return m ? Number(m[0]) : Number.POSITIVE_INFINITY;
}

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

function asThirdPersonInsight(raw?: string): string {
  if (!raw) return '';
  let t = raw.trim().replace(/^["“']+|["”']+$/g, '');
  t = t
    .replace(/\bI want\b/gi, 'They want')
    .replace(/\bI'd\b/gi, "They'd")
    .replace(/\bI am\b/gi, 'They are')
    .replace(/\bI'm\b/gi, "They're")
    .replace(/\bI need\b/gi, 'They need')
    .replace(/\bI worry\b/gi, 'They worry')
    .replace(/\bmy\b/gi, 'their')
    .replace(/\bme\b/gi, 'them');
  return t;
}

function confidenceFromVerdict(v: Record<string, unknown>): {
  pct: number | null;
  hint: string;
} {
  const raw = v.confidence;
  let pct: number | null = null;
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    pct = raw <= 1 ? Math.round(raw * 100) : Math.round(raw);
    pct = Math.max(0, Math.min(100, pct));
  }
  const breakdown =
    v.confidence_breakdown && typeof v.confidence_breakdown === 'object'
      ? (v.confidence_breakdown as {
          listing_count?: number;
          local_listing_count?: number;
          foreign_listing_count?: number;
        })
      : null;
  const foreignOnly =
    (breakdown?.foreign_listing_count ?? 0) > 0 && (breakdown?.local_listing_count ?? 0) === 0;
  const hint = foreignOnly
    ? 'international refs only'
    : breakdown?.listing_count != null
      ? `from ${breakdown.listing_count} live price${breakdown.listing_count === 1 ? '' : 's'}`
      : breakdown?.local_listing_count != null
        ? `from ${breakdown.local_listing_count} local price${breakdown.local_listing_count === 1 ? '' : 's'}`
        : '';
  return { pct, hint };
}

type ComparisonRow = {
  vendor?: string;
  price?: string;
  title?: string;
  link?: string;
  vendor_status?: string;
  price_source?: string;
  currency?: string;
  currency_mismatch?: boolean;
  price_local_approx?: string;
};

function PriceComparisonTable({ rows }: { rows: ComparisonRow[] }) {
  if (!rows.length) {
    return (
      <p className="dash-meta">
        No live seller prices in this view. Try a clearer product name or another city.
      </p>
    );
  }
  return (
    <div className="ux-table-wrap">
      <table className="dash-table ux-table-mobile">
        <thead>
          <tr>
            <th>Seller</th>
            <th className="ux-hide-sm">Product</th>
            <th>Price</th>
            <th>Link</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const href = cleanHttpUrl(row.link);
            const verified = String(row.vendor_status || '').toLowerCase() === 'verified';
            const foreign = Boolean(row.currency_mismatch);
            return (
              <tr key={`${row.vendor}-${row.title}-${i}`}>
                <td>
                  <span>{row.vendor || 'Unknown'}</span>
                  {verified ? (
                    <span className="dash-table__badge" title="Verified seller site">
                      Verified
                    </span>
                  ) : null}
                  {foreign ? (
                    <span className="dash-table__badge" title="Foreign currency">
                      Foreign
                    </span>
                  ) : null}
                  <span className="ux-show-sm dash-meta">{row.title || ''}</span>
                </td>
                <td className="ux-hide-sm">{row.title || '—'}</td>
                <td>
                  {row.price || '—'}
                  {row.price_local_approx ? (
                    <span className="dash-table__source"> {row.price_local_approx}</span>
                  ) : null}
                </td>
                <td>
                  {href ? (
                    <a href={href} target="_blank" rel="noreferrer" className="dash-link">
                      Open
                    </a>
                  ) : (
                    '—'
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PersonaGrid({
  personas,
}: {
  personas: Array<{
    name?: string;
    age_range?: string;
    job_or_role?: string;
    motivation?: string;
    buying_trigger?: string;
    main_objection?: string;
    estimated_willingness_to_pay?: string;
  }>;
}) {
  if (!personas.length) return <p className="dash-meta">No buyer profiles yet.</p>;
  return (
    <div className="dash-persona-grid">
      {personas.map((p, i) => {
        const role =
          p.job_or_role &&
          p.name &&
          p.job_or_role.trim().toLowerCase() === p.name.trim().toLowerCase()
            ? null
            : p.job_or_role;
        const subtitle = [p.age_range, role].filter(Boolean).join(' · ') || '—';
        return (
          <div key={i} className="dash-persona">
            <h3>{p.name}</h3>
            <p className="dash-persona__age">{subtitle}</p>
            <p className="dash-persona__mot">{asThirdPersonInsight(p.motivation)}</p>
            <p className="dash-persona__meta">
              What makes them buy: {asThirdPersonInsight(p.buying_trigger)}
            </p>
            {p.main_objection ? (
              <p className="dash-persona__meta">
                What stops them: {asThirdPersonInsight(p.main_objection)}
              </p>
            ) : null}
            <p className="dash-persona__wtp">Likely spend: {p.estimated_willingness_to_pay}</p>
          </div>
        );
      })}
    </div>
  );
}

function LaunchPackResults({ data }: { data: LaunchPackResult }) {
  return (
    <div className="dash-results">
      <VariantBlock variant={data.primary} listings={data.market_listings} marketWarning={data.market_warning} />
      {data.variant_b ? (
        <>
          <h3 className="dash-section-title">Variant B</h3>
          <VariantBlock
            variant={data.variant_b}
            listings={data.variant_b.market_listings}
            comparisonNote={data.comparison_note}
            marketWarning={data.variant_b.market_warning}
          />
        </>
      ) : null}
    </div>
  );
}

function VariantBlock({
  variant,
  listings,
  comparisonNote,
  marketWarning,
}: {
  variant: LaunchPackVariant;
  listings?: Array<Record<string, unknown>>;
  comparisonNote?: string | null;
  marketWarning?: string | null;
}) {
  const priceV = (variant.price_verdict || {}) as Record<string, unknown>;
  const audienceV = (variant.audience_verdict || {}) as Record<string, unknown>;
  const conf = confidenceFromVerdict(priceV);
  const fromListings = Array.isArray(listings) ? (listings as ComparisonRow[]) : [];
  const fromContext = Array.isArray(priceV.market_context)
    ? (priceV.market_context as ComparisonRow[])
    : [];
  const comparisonRows = [...(fromListings.length ? fromListings : fromContext)].sort(
    (a, b) => parseSortPrice(a.price) - parseSortPrice(b.price),
  );
  const personas = Array.isArray(audienceV.personas)
    ? (audienceV.personas as Array<{
        name?: string;
        age_range?: string;
        job_or_role?: string;
        motivation?: string;
        buying_trigger?: string;
        main_objection?: string;
        estimated_willingness_to_pay?: string;
      }>)
    : [];

  const explanation = {
    ...(variant.price_explanation as Record<string, unknown>),
    local_listing_count:
      (variant.price_explanation as { local_listing_count?: number } | undefined)
        ?.local_listing_count ?? comparisonRows.filter((r) => !r.currency_mismatch).length,
  };

  return (
    <div className="seller-variant">
      <p className="dash-kicker">
        {variant.label}: {variant.product_name}
      </p>
      <SellerLaunchSections
        actionPack={variant.action_pack as never}
        explanation={explanation as never}
        creatives={(variant.channel_creatives || []) as never}
        emptyNote={variant.empty_state_note}
        marketWarning={marketWarning || variant.market_warning}
        exportText={variant.export_text}
        comparisonNote={comparisonNote}
        confidencePct={conf.pct}
        confidenceHint={conf.hint}
        extraTabs={[
          {
            id: 'buyers',
            label: 'Buyers',
            content: (
              <div className="ux-panel">
                {audienceV.summary ? (
                  <ExpandableText lines={3}>{String(audienceV.summary)}</ExpandableText>
                ) : null}
                <PersonaGrid personas={personas} />
              </div>
            ),
          },
          {
            id: 'prices',
            label: 'Prices',
            content: <PriceComparisonTable rows={comparisonRows} />,
          },
          {
            id: 'discussion',
            label: 'Discussion',
            content: (
              <div className="ux-panel">
                <TranscriptBlock
                  transcript={variant.price_transcript || {}}
                  title="Price discussion"
                  asPanel
                />
                <div style={{ marginTop: '1rem' }}>
                  <TranscriptBlock
                    transcript={variant.audience_transcript || {}}
                    title="Audience discussion"
                    asPanel
                  />
                </div>
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}

function PriceResults({ data }: { data: ModeResult }) {
  const v = data.verdict || {};
  const priceRange = (v.price_range as { min?: string; max?: string } | undefined) || {};
  const fromListings = Array.isArray(data.market_listings)
    ? (data.market_listings as ComparisonRow[])
    : [];
  const fromContext = Array.isArray(v.market_context)
    ? (v.market_context as ComparisonRow[])
    : [];
  const comparisonRows = [...(fromListings.length ? fromListings : fromContext)].sort(
    (a, b) => parseSortPrice(a.price) - parseSortPrice(b.price),
  );
  const testimony = Object.entries(data.transcript || {}).slice(0, 3);
  const conf = confidenceFromVerdict(v as Record<string, unknown>);
  const explanation = (data.price_explanation || {}) as {
    why?: string;
    vs_your_band?: string;
    local_listing_count?: number;
    foreign_listing_count?: number;
    your_band?: string;
  };
  const localCount =
    explanation.local_listing_count ?? comparisonRows.filter((r) => !r.currency_mismatch).length;
  const status = marketSeverityFromCounts(
    localCount,
    explanation.foreign_listing_count,
    data.empty_state_note,
    data.market_warning,
  );
  const actionPack = data.action_pack as
    | { first_actions?: string[]; dont_claim?: string[]; messaging_angles?: string[] }
    | undefined;

  return (
    <div className="dash-results">
      <div className="ux-hero">
        <span className="ux-hero__wash" aria-hidden />
        <p className="ux-hero__kicker">Fair price</p>
        <p className="ux-hero__label">Suggested price</p>
        <p className="ux-hero__price">{String(v.recommended_price || '—')}</p>
        <p className="ux-hero__confidence">
          Band {priceRange.min || '—'} – {priceRange.max || '—'}
          {conf.pct != null ? ` · How sure: ${conf.pct}%` : ''}
          {conf.hint ? ` · ${conf.hint}` : ''}
        </p>
      </div>
      <MarketStatus severity={status.severity} message={status.message} />
      <ResultTabs
        defaultTab="next"
        tabs={[
          {
            id: 'next',
            label: 'Do next',
            content: (
              <div className="ux-panel">
                {(actionPack?.first_actions || []).length ? (
                  <ul className="seller-pack__list">
                    {actionPack!.first_actions!.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="dash-meta">Use the suggested price and re-check comps before locking a list.</p>
                )}
                {(actionPack?.dont_claim || []).length ? (
                  <>
                    <p className="dash-meta" style={{ marginTop: '0.75rem' }}>
                      Don&apos;t claim yet
                    </p>
                    <ul className="seller-pack__list seller-pack__list--warn">
                      {actionPack!.dont_claim!.map((a, i) => (
                        <li key={i}>{a}</li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </div>
            ),
          },
          {
            id: 'why',
            label: 'Why',
            content: (
              <div className="ux-panel">
                <ExpandableText lines={3}>
                  {explanation.why || String(v.summary || '—')}
                </ExpandableText>
                {explanation.vs_your_band ? (
                  <p className="dash-meta">{explanation.vs_your_band}</p>
                ) : null}
              </div>
            ),
          },
          {
            id: 'views',
            label: 'Views',
            content: (
              <div className="groundtruth-grid">
                {testimony.map(([name, text]) => (
                  <article key={name} className="groundtruth-testimony">
                    <p className="groundtruth-agent">{friendlyExpertName(name)}</p>
                    <ExpandableText lines={2}>{String(text || '')}</ExpandableText>
                  </article>
                ))}
              </div>
            ),
          },
          {
            id: 'prices',
            label: 'Prices',
            content: <PriceComparisonTable rows={comparisonRows} />,
          },
          {
            id: 'discussion',
            label: 'Discussion',
            content: <TranscriptBlock transcript={data.transcript} asPanel title="Full discussion" />,
          },
        ]}
      />
    </div>
  );
}

function AudienceResults({ data }: { data: ModeResult }) {
  const v = data.verdict || {};
  const personas = Array.isArray(v.personas)
    ? (v.personas as Array<{
        name?: string;
        age_range?: string;
        job_or_role?: string;
        motivation?: string;
        buying_trigger?: string;
        main_objection?: string;
        estimated_willingness_to_pay?: string;
      }>)
    : [];
  const channelPlan = Array.isArray(v.channel_plan)
    ? (v.channel_plan as Array<{ channel?: string; why?: string; example_action?: string }>)
    : [];
  const creatives = Array.isArray(data.channel_creatives)
    ? data.channel_creatives
    : Array.isArray(v.channel_creatives)
      ? (v.channel_creatives as Array<Record<string, unknown>>)
      : [];
  const conf = confidenceFromVerdict(v as Record<string, unknown>);
  const status = marketSeverityFromCounts(null, null, data.empty_state_note, data.market_warning);

  return (
    <div className="dash-results">
      <div className="ux-hero">
        <span className="ux-hero__wash ux-hero__wash--coral" aria-hidden />
        <p className="ux-hero__kicker">Who buys this</p>
        <p className="ux-hero__label">Best channel</p>
        <p className="ux-hero__price ux-hero__price--sm">
          {String(v.top_channel_recommendation || '—')}
        </p>
        <p className="ux-hero__confidence">
          How sure: {conf.pct != null ? `${conf.pct}%` : '—'}
        </p>
        {v.summary ? <ExpandableText lines={3}>{String(v.summary)}</ExpandableText> : null}
      </div>
      {(data.market_warning || data.empty_state_note) && (
        <MarketStatus severity={status.severity} message={status.message} />
      )}
      <ResultTabs
        defaultTab="buyers"
        tabs={[
          {
            id: 'buyers',
            label: 'Buyers',
            content: <PersonaGrid personas={personas} />,
          },
          {
            id: 'channels',
            label: 'Channels',
            content:
              channelPlan.length > 0 ? (
                <ul className="dash-channel-plan__list">
                  {channelPlan.map((c, i) => (
                    <li key={i} className="dash-channel-plan__item">
                      <p className="dash-channel-plan__name">{c.channel || 'Channel'}</p>
                      {c.why ? <p className="dash-channel-plan__why">{c.why}</p> : null}
                      {c.example_action ? (
                        <p className="dash-channel-plan__action">Try: {c.example_action}</p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="dash-meta">No channel plan yet.</p>
              ),
          },
          {
            id: 'hooks',
            label: 'Hooks',
            content:
              creatives.length > 0 ? (
                <ul className="dash-channel-plan__list">
                  {(creatives as Array<{ channel?: string; hooks?: string[]; offer?: string }>).map(
                    (c, i) => (
                      <li key={i} className="dash-channel-plan__item">
                        <p className="dash-channel-plan__name">{c.channel || 'Channel'}</p>
                        {(c.hooks || []).map((h, j) => (
                          <p key={j} className="dash-channel-plan__why">
                            “{h}”
                          </p>
                        ))}
                        {c.offer ? (
                          <p className="dash-channel-plan__action">Offer: {c.offer}</p>
                        ) : null}
                      </li>
                    ),
                  )}
                </ul>
              ) : (
                <p className="dash-meta">No hooks yet.</p>
              ),
          },
          {
            id: 'discussion',
            label: 'Discussion',
            content: <TranscriptBlock transcript={data.transcript} asPanel title="Full discussion" />,
          },
        ]}
      />
    </div>
  );
}
