import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { MapPin } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import {
  exportBrief,
  getBrief,
  getCredits,
  listBriefs,
  markBriefOrdered,
  resolveGeoFromIp,
  runDealFinder,
  setBriefFakeCheap,
  shareBrief,
  type BriefSummary,
  type CompareToPrior,
  type CreditStatus,
  type ModeResult,
  type SupplierCompareRow,
} from '../lib/api';
import { setApiRegion } from '../lib/apiBase';
import { CURRENCIES } from '../lib/currencies';
import {
  MARKET_COUNTRIES,
  OTHER_CITY,
  countryByCode,
  formatMarketLocation,
  matchMarketFromLabel,
} from '../lib/locations';
import { clientQueryHint } from '../lib/queryHint';
import { DashboardShell, DeskHeader, AgentsEmpty, TranscriptBlock } from '../components/DashboardShell';
import { RiskScoreMeter } from '../components/RiskScoreMeter';
import { NegotiationScript } from '../components/NegotiationScript';
import { RiskAlertBanner } from '../components/RiskAlertBanner';
import { ActionItems } from '../components/ActionItems';
import { BuyChecklist } from '../components/BuyChecklist';
import { RiskCostChart } from '../components/RiskCostChart';
import {
  SellerLinksTable,
  formatSellerLinksClipboard,
  cleanHttpUrl,
  type SellerRow,
} from '../components/SellerLinksTable';
import { friendlyExpertName, friendlyVerdict } from '../lib/friendlyLabels';
import { ExpandableText } from '../components/ux/ExpandableText';
import { ExpandableDebate } from '../lib/debateProse';
import { MarketStatus } from '../components/ux/MarketStatus';
import { ResultTabs } from '../components/ux/ResultTabs';
import { SteppedLoading } from '../components/ux/SteppedLoading';
import { StickyExportBar } from '../components/ux/StickyExportBar';
import { ScopeStrip, VerdictReceipts } from '../components/VerdictReceipts';
import {
  BriefHistory,
  CompareToPriorStrip,
  FakeCheapToggle,
} from '../components/BriefHistory';
import { SupplierCompareTable } from '../components/SupplierCompareTable';
import { AlertsInbox } from '../components/AlertsInbox';
import { WatchlistPanel } from '../components/WatchlistPanel';

function cleanDisplay(value: unknown): string {
  const text = String(value ?? '').trim();
  if (!text) return '';
  const lowered = text.toLowerCase();
  if (['none', 'null', 'n/a', 'na', '-', '—', 'unknown'].includes(lowered)) return '';
  return text;
}

export function BuyerDashboard() {
  const { user, logout } = useAuth();
  const [itemName, setItemName] = useState('');
  const [countryCode, setCountryCode] = useState('PK');
  const [city, setCity] = useState('Lahore');
  const [customCity, setCustomCity] = useState('');
  const [currency, setCurrency] = useState('PKR');
  const [currencyTouched, setCurrencyTouched] = useState(false);
  const [geoSource, setGeoSource] = useState<string | null>(null);
  const [geoLoading, setGeoLoading] = useState(true);
  const [maxBudget, setMaxBudget] = useState('');
  const [quantity, setQuantity] = useState('');
  const [buyingBulk, setBuyingBulk] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ModeResult | null>(null);
  const [resultWasBulk, setResultWasBulk] = useState(false);
  const [copiedLinks, setCopiedLinks] = useState(false);
  const [copyHint, setCopyHint] = useState<string | null>(null);
  const [queryHint, setQueryHint] = useState<string | null>(null);
  const [briefs, setBriefs] = useState<BriefSummary[]>([]);
  const [briefsLoading, setBriefsLoading] = useState(false);
  const [activeBriefId, setActiveBriefId] = useState<number | null>(null);
  const [comparePrior, setComparePrior] = useState<CompareToPrior | null>(null);
  const [fakeCheap, setFakeCheap] = useState(false);
  const [fakeBusy, setFakeBusy] = useState(false);
  const [supplierFlagCount, setSupplierFlagCount] = useState(0);
  const [credits, setCredits] = useState<CreditStatus | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [shareHint, setShareHint] = useState<string | null>(null);
  const [orderedHint, setOrderedHint] = useState<string | null>(null);

  const selectedCountry = useMemo(() => countryByCode(countryCode), [countryCode]);
  const cityOptions = selectedCountry?.cities ?? [];
  const location = formatMarketLocation(countryCode, city, customCity);

  const refreshBriefs = async () => {
    setBriefsLoading(true);
    try {
      const data = await listBriefs(40);
      setBriefs(data.briefs || []);
    } catch {
      /* history is best-effort */
    } finally {
      setBriefsLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setGeoLoading(true);
      try {
        const geo = await resolveGeoFromIp();
        if (cancelled) return;
        setApiRegion(geo.nearest_api_region);
        setGeoSource(geo.source);
        const matched = matchMarketFromLabel(geo.location_label, geo.country_code);
        if (matched) {
          setCountryCode(matched.countryCode);
          setCity(matched.city);
          setCurrency((prev) => {
            // Only auto-set currency if user hasn't picked one yet (still default PKR
            // or matches previous country default).
            const c = countryByCode(matched.countryCode);
            return c && !currencyTouched ? c.currency : prev;
          });
        }
      } catch {
        if (!cancelled) setGeoSource(null);
      } finally {
        if (!cancelled) setGeoLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- geo once on mount
  }, []);

  useEffect(() => {
    void refreshBriefs();
    void getCredits()
      .then(setCredits)
      .catch(() => undefined);
  }, []);

  const openBrief = async (id: number) => {
    try {
      const detail = await getBrief(id);
      const payload = detail.payload || {};
      const qm = (payload.query_meta as ModeResult['query_meta']) || null;
      const restored: ModeResult = {
        transcript: (payload.transcript as Record<string, string>) || {},
        verdict: (payload.verdict as Record<string, unknown>) || {},
        market_listings: (payload.market_listings as Array<Record<string, unknown>>) || [],
        market_warning: (payload.market_warning as string | null) || null,
        risk_score: (payload.risk_score as ModeResult['risk_score']) || null,
        query_meta: qm,
        brief_id: detail.id,
        compare_to_prior: detail.compare_to_prior || null,
        supplier_table: (qm?.supplier_table as SupplierCompareRow[]) || [],
        negotiation_message: (qm?.negotiation_message as string) || null,
        negotiation_script: [],
        buy_checklist: [],
      };
      // Older saves may not have transcript in payload — keep empty
      if (!payload.transcript && payload.verdict) {
        restored.transcript = {};
      }
      setResult(restored);
      setResultWasBulk(String(detail.buying_mode || '') === 'bulk');
      setActiveBriefId(detail.id);
      setComparePrior(detail.compare_to_prior || null);
      setFakeCheap(Boolean(detail.fake_cheap));
      setSupplierFlagCount(detail.supplier_fake_cheap_count || 0);
      if (detail.item_name) setItemName(detail.item_name);
      if (detail.quantity != null) setQuantity(String(detail.quantity));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not open brief');
    }
  };

  const onToggleFakeCheap = async (next: boolean) => {
    if (!activeBriefId) return;
    setFakeBusy(true);
    try {
      const updated = await setBriefFakeCheap(activeBriefId, next);
      setFakeCheap(Boolean(updated.fake_cheap));
      setSupplierFlagCount(updated.supplier_fake_cheap_count || 0);
      await refreshBriefs();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update flag');
    } finally {
      setFakeBusy(false);
    }
  };

  const onCopyBriefExport = async () => {
    setExportBusy(true);
    setShareHint(null);
    try {
      let text = result?.export_text || '';
      if (activeBriefId) {
        const exported = await exportBrief(activeBriefId);
        text = exported.text || text;
        if (exported.share_url) setShareHint(exported.share_url);
      }
      if (!text) throw new Error('Nothing to export yet');
      await navigator.clipboard.writeText(text);
      setCopyHint('Brief copied — paste into Notes / WhatsApp / email.');
      window.setTimeout(() => setCopyHint(null), 2200);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setExportBusy(false);
    }
  };

  const onShareBrief = async () => {
    if (!activeBriefId) return;
    setExportBusy(true);
    try {
      const shared = await shareBrief(activeBriefId);
      setShareHint(shared.url);
      await navigator.clipboard.writeText(shared.url);
      setCopyHint('Share link copied.');
      window.setTimeout(() => setCopyHint(null), 2200);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Share failed');
    } finally {
      setExportBusy(false);
    }
  };

  const onMarkOrdered = async () => {
    if (!activeBriefId) return;
    try {
      await markBriefOrdered(activeBriefId, 30);
      setOrderedHint('Marked ordered — we’ll nudge you in ~30 days to re-check stock.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not mark ordered');
    }
  };

  const qtyParsed = (() => {
    const n = Number.parseInt(quantity, 10);
    return Number.isFinite(n) && n >= 1 ? n : undefined;
  })();
  const isBulk = buyingBulk || (qtyParsed !== undefined && qtyParsed >= 5);
  const locationOk =
    city === OTHER_CITY ? customCity.trim().length >= 2 : Boolean(countryCode && city);
  const canSubmit = itemName.trim().length >= 3 && locationOk;

  const onCountryChange = (code: string) => {
    setCountryCode(code);
    const next = countryByCode(code);
    const nextCity = next?.cities[0] || OTHER_CITY;
    setCity(nextCity);
    setCustomCity('');
    if (next && !currencyTouched) setCurrency(next.currency);
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) {
      setError('Enter what you want and pick a country and city.');
      return;
    }
    const vague = clientQueryHint(itemName);
    if (vague?.vague && vague.suggestion && !queryHint) {
      const opts =
        vague.options && vague.options.length
          ? ` Pick one: ${vague.options.slice(0, 4).join(' · ')}.`
          : '';
      setQueryHint(
        `“${itemName.trim()}” is vague — try “${vague.suggestion}”, or search anyway to auto-narrow.${opts}`,
      );
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setCopiedLinks(false);
    setActiveBriefId(null);
    setComparePrior(null);
    setFakeCheap(false);
    setSupplierFlagCount(0);
    try {
      const data = await runDealFinder({
        item_name: itemName,
        location,
        max_budget: maxBudget || undefined,
        currency: currency || undefined,
        marketplace: 'local_retailers',
        quantity: qtyParsed,
        buying_mode: isBulk ? 'bulk' : 'retail',
      });
      setResult(data);
      setResultWasBulk(isBulk);
      setActiveBriefId(data.brief_id ?? (typeof data.verdict?.brief_id === 'number' ? data.verdict.brief_id : null));
      setComparePrior(data.compare_to_prior || null);
      setFakeCheap(false);
      setShareHint(null);
      setOrderedHint(null);
      if (data.credits) setCredits(data.credits);
      else void getCredits().then(setCredits).catch(() => undefined);
      void refreshBriefs();
      if (data.query_meta?.auto_narrowed) {
        setQueryHint(
          `Searched “${data.query_meta.used_query}” (narrowed from “${data.query_meta.original}”).`,
        );
      } else if (data.query_meta?.suggestion && data.query_meta.vague) {
        setQueryHint(`Tip: a clearer query like “${data.query_meta.suggestion}” usually ranks better.`);
      } else {
        setQueryHint(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  };

  const v = result?.verdict || {};
  const winner =
    (v.winner as {
      title?: string;
      vendor?: string;
      price?: string;
      link?: string;
      reason?: string;
    } | undefined) || {};
  const verdictTag = String(v.verdict || '').toUpperCase();
  const winnerListingLink = cleanHttpUrl(winner.link);
  const listingRows: SellerRow[] = Array.isArray(result?.market_listings)
    ? (result.market_listings as SellerRow[])
    : [];
  const trackedWatchRow =
    listingRows.find((row) => cleanHttpUrl(row.link) === winnerListingLink) ||
    listingRows.find((row) => row.best_pick && cleanHttpUrl(row.link)) ||
    listingRows.find(
      (row) =>
        cleanHttpUrl(row.link) &&
        row.price &&
        !/^see\s+listing/i.test(String(row.price)),
    );
  const trackedListing =
    trackedWatchRow?.link && trackedWatchRow.price
      ? {
          link: cleanHttpUrl(trackedWatchRow.link),
          title: trackedWatchRow.title,
          vendor: trackedWatchRow.vendor,
          price: String(trackedWatchRow.price),
          currency: String(trackedWatchRow.currency || currency).toUpperCase(),
          priceSource: trackedWatchRow.price_source || 'snippet',
        }
      : null;
  // Single source of truth: same row set drives tab label, status banner, and table title
  const pricedListings = listingRows.filter(
    (r) =>
      r.counts_as_live_listing !== false &&
      r.is_product_page !== false &&
      !/^(see listing|price n\/a|n\/?a)$/i.test(String(r.price || '')) &&
      !(r as { price_outlier?: boolean }).price_outlier,
  );
  const liveListingCount = pricedListings.length;
  /** Prefer host over generic marketplace brand ("Alibaba") so distinct shops aren't collapsed. */
  const vendorKey = (r: SellerRow) => {
    let host = '';
    try {
      host = r.link ? new URL(r.link).hostname.replace(/^www\./, '').toLowerCase() : '';
    } catch {
      host = '';
    }
    // Treat marketplace subdomains as distinct sellers when path/shop id differs enough
    if (host) return host;
    return String(r.vendor || '').trim().toLowerCase() || String(r.link || '');
  };
  const distinctSellers = new Set(pricedListings.map(vendorKey).filter(Boolean)).size;
  const dataGap = liveListingCount === 0;
  const winnerTitle =
    cleanDisplay(winner.title) ||
    (verdictTag === 'NO_MATCH'
      ? liveListingCount > 0
        ? 'Confirm price on seller pages'
        : 'No good matches — refine your query'
      : verdictTag === 'PASS' || verdictTag === 'SKIP'
        ? dataGap
          ? 'Live listings unavailable'
          : 'Skip this deal'
        : verdictTag === 'MAYBE'
          ? 'Maybe — verify first'
          : 'Best option');
  const winnerVendor = cleanDisplay(winner.vendor);
  const winnerPrice = cleanDisplay(winner.price);
  const winnerReason = cleanDisplay(winner.reason) || String(v.summary || '');
  const winnerLink = cleanHttpUrl(winner.link);
  const landedCost =
    v.landed_cost && typeof v.landed_cost === 'object'
      ? (v.landed_cost as {
          formula?: string;
          estimated_total?: string;
          duty_assumption?: string;
          shipping_assumption?: string;
          freight_assumption?: string;
          weight_assumption?: string;
          moq_assumption?: string;
          unit_price?: string;
          quantity?: number;
          range_low?: string;
          range_high?: string;
          package_weight_kg?: number;
          freight_rate?: number;
          duty_rate?: number;
          assumptions?: string[];
          verdict_flips_in_range?: boolean;
          budget_display?: string;
          cost_vs_budget?: string;
          fits_budget_mid?: boolean;
          max_units_that_fit?: number;
          max_units_note?: string;
        })
      : null;
  const sourcingAction =
    v.sourcing_action && typeof v.sourcing_action === 'object'
      ? (v.sourcing_action as { action?: string; message?: string })
      : null;
  const mustHaves = Array.isArray(v.must_haves)
    ? (v.must_haves as Array<{ id?: string; label?: string }>)
    : [];
  const briefId = cleanDisplay(v.run_id) || null;
  const costAssumptions =
    v.cost_assumptions && typeof v.cost_assumptions === 'object'
      ? (v.cost_assumptions as {
          duty_rate_mid?: number;
          duty_rate_low?: number;
          duty_rate_high?: number;
          sales_tax_rate?: number;
          freight_usd_per_kg_mid?: number;
          label?: string;
        })
      : null;
  const relevanceMeta =
    result?.query_meta?.relevance && typeof result.query_meta.relevance === 'object'
      ? result.query_meta.relevance
      : null;
  const alternatives = Array.isArray(v.alternatives)
    ? (v.alternatives as Array<{
        title?: string;
        vendor?: string;
        price?: string;
        link?: string;
        note?: string;
        vendor_status?: string;
      }>)
    : [];
  const breakdown =
    v.agent_breakdown && typeof v.agent_breakdown === 'object'
      ? (v.agent_breakdown as Record<string, unknown>)
      : null;

  const linkedListings = pricedListings.filter((row) => cleanHttpUrl(row.link));
  const optionRows: SellerRow[] =
    alternatives.length > 0
      ? alternatives.map((a) => ({
          title: a.title,
          vendor: a.vendor,
          price: a.price,
          link: a.link,
          note: a.note,
          vendor_status: a.vendor_status,
        }))
      : linkedListings;
  const linkCount = linkedListings.length;

  const copyAllLinks = async () => {
    const text = formatSellerLinksClipboard(linkedListings.length ? linkedListings : optionRows);
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedLinks(true);
      window.setTimeout(() => setCopiedLinks(false), 2000);
    } catch {
      setCopyHint('Could not copy — select links from the Sellers tab instead.');
      window.setTimeout(() => setCopyHint(null), 4000);
    }
  };

  const aside = (
    <>
      <p className="dash-proto__aside-kicker">Reorder brief</p>
      <form onSubmit={onSubmit} className={`buyer-search${loading ? ' ux-form--dim' : ''}`}>
        <label className="dash-field">
          What are you restocking?
          <input
            required
            minLength={3}
            value={itemName}
            onChange={(e) => {
              setItemName(e.target.value);
              setQueryHint(null);
            }}
            placeholder="e.g. ceramic coffee mugs 350ml"
          />
          <span className="dash-hint dash-hint--tight">
            Be specific — model, material, or pack size. We compare local shops and import quotes.
          </span>
        </label>
        {queryHint ? (
          <div className="buyer-query-hint" role="status">
            <p>{queryHint}</p>
            {clientQueryHint(itemName)?.suggestion ? (
              <div className="buyer-query-hint__actions">
                <button
                  type="button"
                  className="dash-link"
                  onClick={() => {
                    const s = clientQueryHint(itemName)?.suggestion;
                    if (s) {
                      setItemName(s);
                      setQueryHint(null);
                    }
                  }}
                >
                  Use clearer query
                </button>
                <button type="submit" className="dash-link">
                  Search anyway
                </button>
              </div>
            ) : null}
          </div>
        ) : null}

        <fieldset className="buyer-search__group">
          <legend className="buyer-search__legend">Where you buy</legend>
          <div className="dash-field-row">
            <label className="dash-field">
              Country
              <select
                required
                value={countryCode}
                onChange={(e) => onCountryChange(e.target.value)}
                disabled={geoLoading}
                aria-label="Country"
              >
                {MARKET_COUNTRIES.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="dash-field">
              City
              <select
                required
                value={city}
                onChange={(e) => setCity(e.target.value)}
                disabled={geoLoading || !countryCode}
                aria-label="City"
              >
                {cityOptions.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
                <option value={OTHER_CITY}>Other city…</option>
              </select>
            </label>
          </div>
          {city === OTHER_CITY && (
            <label className="dash-field">
              City name
              <input
                required
                minLength={2}
                value={customCity}
                onChange={(e) => setCustomCity(e.target.value)}
                placeholder="Type your city"
              />
            </label>
          )}
          {geoSource && (
            <p className="dash-geo">
              <MapPin className="w-3 h-3" aria-hidden />
              Suggested from your location — change anytime.
            </p>
          )}
        </fieldset>

        <fieldset className="buyer-search__group">
          <legend className="buyer-search__legend">Order size</legend>
          <div className="dash-field-row">
            <label className="dash-field">
              Quantity
              <input
                inputMode="numeric"
                value={quantity}
                onChange={(e) => {
                  const next = e.target.value.replace(/[^\d]/g, '');
                  setQuantity(next);
                  const n = Number.parseInt(next, 10);
                  if (Number.isFinite(n) && n >= 5) setBuyingBulk(true);
                }}
                placeholder="e.g. 50"
              />
            </label>
            <label className="dash-field">
              Max budget
              <div className="dash-money">
                <input
                  value={maxBudget}
                  onChange={(e) => setMaxBudget(e.target.value)}
                  placeholder="Optional"
                  aria-label="Max budget amount"
                />
                <select
                  value={currency}
                  onChange={(e) => {
                    setCurrency(e.target.value);
                    setCurrencyTouched(true);
                  }}
                  aria-label="Budget currency"
                >
                  {CURRENCIES.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.code}
                    </option>
                  ))}
                </select>
              </div>
            </label>
          </div>
        </fieldset>

        <label className={`buyer-bulk${buyingBulk ? ' buyer-bulk--on' : ''}`}>
          <input
            type="checkbox"
            checked={buyingBulk}
            onChange={(e) => setBuyingBulk(e.target.checked)}
          />
          <span className="buyer-bulk__copy">
            <span className="buyer-bulk__title">Buying in bulk</span>
            <span className="buyer-bulk__hint">
              For restocks of 5+ units — we rank local + import wholesale pages. Confirm MOQ and shipping on the supplier site.
            </span>
          </span>
        </label>

        <button type="submit" disabled={loading || !canSubmit} className="dash-submit">
          <span className="dash-submit__shine" aria-hidden />
          <span style={{ position: 'relative', zIndex: 1 }}>
            {loading
              ? 'Searching…'
              : isBulk
                ? 'Should I reorder?'
                : 'Should I buy this?'}
          </span>
        </button>
        {credits ? (
          <p className="credits-meta" role="status">
            {credits.remaining ?? 0} of {credits.limit ?? 12} free briefs left this month
          </p>
        ) : null}
      </form>
      <BriefHistory
        briefs={briefs}
        activeId={activeBriefId}
        loading={briefsLoading}
        onSelect={(id) => void openBrief(id)}
        onRefresh={() => void refreshBriefs()}
      />
      <AlertsInbox
        onReorderItem={(name, briefId) => {
          if (name) setItemName(name);
          setBuyingBulk(true);
          if (briefId != null) void openBrief(briefId);
          setOrderedHint(
            briefId != null
              ? 'Reorder nudge — review this brief, then run again if stock is low.'
              : `Reorder nudge — “${name}” loaded. Hit Should I reorder? when ready.`,
          );
        }}
      />
      <WatchlistPanel
        defaultItem={itemName}
        location={location}
        currency={currency}
        quantity={qtyParsed}
        credits={credits}
        hideCredits
        trackedListing={trackedListing}
        onReorderItem={(name, briefId) => {
          if (name) setItemName(name);
          setBuyingBulk(true);
          if (briefId != null) void openBrief(briefId);
        }}
      />
    </>
  );

  return (
    <DashboardShell email={user?.email} onLogout={logout} aside={aside}>
      <DeskHeader
        title="Restock desk"
        subtitle="Should you reorder? Live supplier links, checkable landed math, and a Buy / Maybe / Skip you can audit."
      />
      <ScopeStrip />
      {loading && (
        <SteppedLoading
          steps={[
            isBulk ? 'Waking wholesale search…' : 'Waking live prices…',
            isBulk ? 'Comparing local + import suppliers…' : 'Checking live local prices…',
            'Weighing risk vs value…',
            isBulk ? 'Building your deal brief…' : 'Picking buy or skip…',
          ]}
        />
      )}
      {error && <p className="dash-error">{error}</p>}
      {copyHint && <p className="dash-meta">{copyHint}</p>}
      {!loading && !result && !error && (
        <AgentsEmpty
          headline="One brief. A grounded reorder call."
          body="Name the product and quantity. Council pulls live listings (local first, then import), shows landed-cost math, and calls Buy, Maybe, or Skip — without inventing a supplier."
        />
      )}

      {result && !loading && (
        <div className="dash-results">
          <div className="ux-hero">
            <span
              className={`ux-hero__wash${
                verdictTag === 'BUY'
                  ? ''
                  : verdictTag === 'MAYBE'
                    ? ' ux-hero__wash--amber'
                    : ' ux-hero__wash--coral'
              }`}
              aria-hidden
            />
            <span
              className={`dash-verdict-pill ${
                verdictTag === 'BUY'
                  ? 'dash-verdict-pill--buy'
                  : verdictTag === 'MAYBE'
                    ? 'dash-verdict-pill--maybe'
                    : 'dash-verdict-pill--pass'
              }`}
            >
              {friendlyVerdict(v.verdict)}
            </span>
            <p className="ux-hero__kicker" style={{ marginTop: '0.65rem' }}>
              Deal verdict
            </p>
            <p className="ux-hero__price ux-hero__price--sm">{winnerTitle}</p>
            {(winnerVendor || winnerPrice) && (
              <p className="ux-hero__confidence">
                {[winnerVendor, winnerPrice].filter(Boolean).join(' · ')}
              </p>
            )}
            <ExpandableText lines={3}>{winnerReason}</ExpandableText>
            {landedCost?.estimated_total || landedCost?.formula ? (
              <div className="landed-math" aria-label="Landed cost math">
                <p className="landed-math__label">Estimated landed cost (checkable)</p>
                {landedCost.estimated_total ? (
                  <p className="landed-math__formula">
                    Mid landed: {landedCost.estimated_total}
                  </p>
                ) : null}
                {landedCost.formula ? (
                  <p className="landed-math__formula" style={{ fontWeight: 500, fontSize: '0.8rem' }}>
                    {landedCost.formula}
                  </p>
                ) : null}
                {landedCost.range_low && landedCost.range_high ? (
                  <p className="landed-math__range">
                    Range: {landedCost.range_low} – {landedCost.range_high}
                    {landedCost.verdict_flips_in_range
                      ? ' · verdict flips inside this band → treat as Maybe'
                      : ''}
                  </p>
                ) : null}
                {landedCost.cost_vs_budget ? (
                  <p
                    className={`landed-math__budget${
                      landedCost.fits_budget_mid === false ? ' landed-math__budget--over' : ''
                    }`}
                  >
                    {landedCost.cost_vs_budget}
                  </p>
                ) : null}
                {landedCost.max_units_that_fit != null ? (
                  <p className="landed-math__units">
                    Max units that fit budget: {landedCost.max_units_that_fit}
                    {landedCost.max_units_note ? ` · ${landedCost.max_units_note}` : ''}
                  </p>
                ) : null}
                <ul className="landed-math__assumptions">
                  {(landedCost.assumptions && landedCost.assumptions.length
                    ? landedCost.assumptions
                    : [
                        landedCost.weight_assumption,
                        landedCost.freight_assumption || landedCost.shipping_assumption,
                        landedCost.duty_assumption,
                        landedCost.moq_assumption,
                      ].filter(Boolean)
                  ).map((line) => (
                    <li key={String(line)}>{line}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {sourcingAction?.message ? (
              <p className="landed-math__sourcing" role="status">
                {sourcingAction.message}
              </p>
            ) : null}
            {mustHaves.length > 0 ? (
              <p className="landed-math__specs">
                Must-haves from query:{' '}
                {mustHaves.map((h) => h.label || h.id).filter(Boolean).join(', ')}
              </p>
            ) : null}
            <div className="ux-hero__ctas">
              {winnerLink && verdictTag !== 'PASS' && verdictTag !== 'SKIP' && verdictTag !== 'NO_MATCH' ? (
                <a href={winnerLink} target="_blank" rel="noreferrer" className="dash-submit seller-pack__btn">
                  Open best seller
                </a>
              ) : null}
              {linkCount > 0 ? (
                <button type="button" className="dash-link" onClick={copyAllLinks}>
                  {copiedLinks ? 'Copied' : `Copy ${linkCount} seller link${linkCount === 1 ? '' : 's'}`}
                </button>
              ) : null}
            </div>
          </div>

          {result.risk_score && <RiskAlertBanner risk={result.risk_score} />}

          <VerdictReceipts
            briefId={briefId}
            verdictTag={verdictTag || undefined}
            winner={winner}
            winnerLink={winnerLink || undefined}
            landed={landedCost}
            costAssumptions={costAssumptions}
            relevance={relevanceMeta}
            marketWarning={result.market_warning}
            skipReason={winnerReason || String(v.summary || '')}
          />

          {comparePrior ? <CompareToPriorStrip compare={comparePrior} /> : null}

          {activeBriefId ? (
            <FakeCheapToggle
              briefId={activeBriefId}
              fakeCheap={fakeCheap}
              supplierHost={
                (() => {
                  try {
                    return winnerLink ? new URL(winnerLink).hostname.replace(/^www\./, '') : null;
                  } catch {
                    return null;
                  }
                })()
              }
              supplierFlagCount={supplierFlagCount}
              busy={fakeBusy}
              onToggle={(next) => void onToggleFakeCheap(next)}
            />
          ) : null}

          {activeBriefId ? (
            <div className="brief-actions">
              <button type="button" className="brief-actions__btn" disabled={exportBusy} onClick={() => void onCopyBriefExport()}>
                Copy brief
              </button>
              <button type="button" className="brief-actions__btn" disabled={exportBusy} onClick={() => void onShareBrief()}>
                Share link
              </button>
              {(verdictTag === 'BUY' || verdictTag === 'MAYBE') && (
                <button type="button" className="brief-actions__btn brief-actions__btn--accent" onClick={() => void onMarkOrdered()}>
                  I ordered this
                </button>
              )}
              {shareHint ? (
                <p className="brief-actions__hint">
                  Share: <a href={shareHint}>{shareHint}</a>
                </p>
              ) : null}
              {orderedHint ? <p className="brief-actions__hint">{orderedHint}</p> : null}
            </div>
          ) : null}

          {(result.supplier_table && result.supplier_table.length > 0) ||
          (result.query_meta?.supplier_table && result.query_meta.supplier_table.length > 0) ? (
            <SupplierCompareTable
              rows={
                (result.supplier_table?.length
                  ? result.supplier_table
                  : result.query_meta?.supplier_table) || []
              }
            />
          ) : null}

          <MarketStatus
            severity={
              liveListingCount >= 3 && distinctSellers >= 3
                ? 'good'
                : liveListingCount > 0
                  ? 'thin'
                  : 'empty'
            }
            message={
              liveListingCount >= 3 && distinctSellers >= 3
                ? `${liveListingCount} priced product pages · ${distinctSellers} seller${distinctSellers === 1 ? '' : 's'}`
                : liveListingCount > 0
                  ? `Thin live data (${liveListingCount} priced product page${liveListingCount === 1 ? '' : 's'}, ${distinctSellers} seller${distinctSellers === 1 ? '' : 's'}) — verify in person; same-seller rows are not a comparison`
                  : result.market_warning ||
                    'We couldn’t load live prices right now, so we won’t invent a deal.'
            }
          />

          <ResultTabs
            defaultTab={linkCount > 0 ? 'sellers' : 'risk'}
            tabs={[
              {
                id: 'sellers',
                label: `Sellers (${distinctSellers})`,
                content: (
                  <div className="ux-panel seller-links-panel">
                    <SellerLinksTable
                      rows={linkedListings.length ? linkedListings : []}
                      listingCount={liveListingCount}
                      sellerCount={distinctSellers}
                      emptyMessage="No seller links in this run. Try a clearer product name or turn on bulk mode."
                      onCopyAll={linkCount > 0 ? copyAllLinks : undefined}
                      copyLabel={copiedLinks ? 'Copied' : 'Copy all links'}
                      showBestPick={verdictTag === 'BUY' || verdictTag === 'MAYBE'}
                      hint={
                        verdictTag === 'BUY'
                          ? 'Best pick is a ranked cheap fit for your region — not a guarantee. Factory USD quotes need shipping; ask MOQ and a sample first.'
                          : verdictTag === 'MAYBE'
                            ? 'Maybe — check the Risk flags and open the product page before paying. Card price, verdict text, and landed math must agree.'
                            : verdictTag === 'NO_MATCH'
                              ? 'No good matches — fewer than 2 relevant product-detail listings. Refine your query; we will not invent a Best pick.'
                              : 'Skip — no Best pick. Open any product-detail link to verify MOQ and price tiers yourself.'
                      }
                    />
                  </div>
                ),
              },
              {
                id: 'risk',
                label: 'Risk',
                content: (
                  <div className="ux-panel">
                    {result.risk_score ? <RiskScoreMeter risk={result.risk_score} /> : null}
                    {(verdictTag === 'PASS' || alternatives.length > 0) && (
                      <RiskCostChart
                        alternatives={alternatives}
                        riskScore={result.risk_score?.score}
                        verdict={String(v.verdict || '')}
                      />
                    )}
                  </div>
                ),
              },
              {
                id: 'actions',
                label:
                  verdictTag === 'BUY'
                    ? 'Negotiate'
                    : verdictTag === 'MAYBE'
                      ? 'Verify'
                      : 'Checklist',
                content: (
                  <div className="ux-panel">
                    {!resultWasBulk ? (
                      <ActionItems
                        alternatives={alternatives}
                        location={location}
                        itemName={itemName}
                      />
                    ) : null}
                    {(verdictTag === 'BUY' || verdictTag === 'MAYBE') &&
                    ((result.negotiation_script && result.negotiation_script.length > 0) ||
                      result.negotiation_message) ? (
                      <NegotiationScript
                        questions={result.negotiation_script || []}
                        message={result.negotiation_message}
                      />
                    ) : null}
                    {(verdictTag === 'PASS' ||
                      verdictTag === 'SKIP' ||
                      verdictTag === 'NO_MATCH' ||
                      verdictTag === 'MAYBE') &&
                    result.buy_checklist &&
                    result.buy_checklist.length > 0 ? (
                      <BuyChecklist items={result.buy_checklist} />
                    ) : null}
                    {resultWasBulk &&
                    !(
                      ((verdictTag === 'BUY' || verdictTag === 'MAYBE') &&
                        result.negotiation_script &&
                        result.negotiation_script.length > 0) ||
                      ((verdictTag === 'PASS' || verdictTag === 'MAYBE') &&
                        result.buy_checklist &&
                        result.buy_checklist.length > 0)
                    ) ? (
                      <p className="dash-meta">
                        Use the Sellers tab for direct supplier links — skip local map searches for bulk.
                      </p>
                    ) : null}
                  </div>
                ),
              },
              {
                id: 'options',
                label: 'Options',
                content: (
                  <SellerLinksTable
                    rows={optionRows}
                    showNote
                    emptyMessage="No alternate options listed."
                  />
                ),
              },
              {
                id: 'views',
                label: 'Views',
                content: breakdown ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                    {Object.entries(breakdown).map(([k, val], i) => (
                      <div
                        key={k}
                        className="dash-agent"
                        style={{
                          ['--agent' as string]: ['#0f766e', '#14b8a6', '#e8913a', '#5a6b7d'][i % 4],
                          animationDelay: `${i * 0.07}s`,
                        }}
                      >
                        <p className="dash-agent__name">{friendlyExpertName(k)}</p>
                        <ExpandableDebate text={String(val || '')} lines={4} />
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="dash-meta">No agent summary.</p>
                ),
              },
              {
                id: 'discussion',
                label: 'Discussion',
                content: result.transcript ? (
                  <TranscriptBlock transcript={result.transcript} asPanel title="Full discussion" />
                ) : null,
              },
            ]}
          />

          <StickyExportBar
            primaryHref={winnerLink || undefined}
            primaryLabel="Open best listing"
            onCopy={activeBriefId ? () => void onCopyBriefExport() : linkCount > 0 ? copyAllLinks : undefined}
            copyLabel={activeBriefId ? (exportBusy ? 'Copying…' : 'Copy brief') : copiedLinks ? 'Copied' : 'Copy listing links'}
            onDownload={activeBriefId ? () => void onShareBrief() : undefined}
            downloadLabel="Share link"
          />
        </div>
      )}
    </DashboardShell>
  );
}
