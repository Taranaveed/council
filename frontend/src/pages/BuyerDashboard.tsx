import { useEffect, useState, type FormEvent } from 'react';
import { MapPin } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { resolveGeoFromIp, runDealFinder, type ModeResult } from '../lib/api';
import { setApiRegion } from '../lib/apiBase';
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
  const [location, setLocation] = useState('');
  const [countryCode, setCountryCode] = useState<string | null>(null);
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

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setGeoLoading(true);
      try {
        const geo = await resolveGeoFromIp();
        if (cancelled) return;
        setApiRegion(geo.nearest_api_region);
        setCountryCode(geo.country_code || null);
        setGeoSource(geo.source);
        setLocation((prev) => prev.trim() || geo.location_label);
      } catch {
        if (!cancelled) setGeoSource(null);
      } finally {
        if (!cancelled) setGeoLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const qtyParsed = (() => {
    const n = Number.parseInt(quantity, 10);
    return Number.isFinite(n) && n >= 1 ? n : undefined;
  })();
  const isBulk = buyingBulk || (qtyParsed !== undefined && qtyParsed >= 5);
  const canSubmit = itemName.trim().length >= 3 && location.trim().length >= 2;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) {
      setError('Enter what you want and a city (at least a few characters each).');
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setCopiedLinks(false);
    try {
      const data = await runDealFinder({
        item_name: itemName,
        location,
        max_budget: maxBudget || undefined,
        marketplace: 'local_retailers',
        quantity: qtyParsed,
        buying_mode: isBulk ? 'bulk' : 'retail',
      });
      setResult(data);
      setResultWasBulk(isBulk);
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
  const winnerTitle =
    cleanDisplay(winner.title) ||
    (verdictTag === 'PASS' ? 'No safe deal found right now' : 'Best option');
  const winnerVendor = cleanDisplay(winner.vendor);
  const winnerPrice = cleanDisplay(winner.price);
  const winnerReason = cleanDisplay(winner.reason) || String(v.summary || '');
  const winnerLink = cleanHttpUrl(winner.link);
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

  const listingRows: SellerRow[] = Array.isArray(result?.market_listings)
    ? (result.market_listings as SellerRow[])
    : [];
  const linkedListings = listingRows.filter((row) => cleanHttpUrl(row.link));
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
  const listingCount = listingRows.length;
  const linkCount = linkedListings.length;

  const copyAllLinks = async () => {
    const text = formatSellerLinksClipboard(linkedListings.length ? linkedListings : optionRows);
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedLinks(true);
      window.setTimeout(() => setCopiedLinks(false), 2000);
    } catch {
      setError('Could not copy links — select them from the Sellers tab instead.');
    }
  };

  const aside = (
    <>
      <p className="dash-proto__aside-kicker">Search</p>
      <form onSubmit={onSubmit} className={loading ? 'ux-form--dim' : undefined}>
        <label className="dash-field">
          What are you looking for?
          <input
            required
            minLength={3}
            value={itemName}
            onChange={(e) => setItemName(e.target.value)}
            placeholder="e.g. ceramic mugs wholesale"
          />
          <p className="dash-hint" style={{ marginTop: '-0.35rem' }}>
            Be specific — model, material, or pack size beats vague words.
          </p>
        </label>
        <label className="dash-field">
          Your city
          <input
            required
            value={location}
            onChange={(e) => {
              setLocation(e.target.value);
              if (geoSource) setCountryCode(null);
            }}
            placeholder={geoLoading ? 'Detecting your city…' : 'City or country'}
          />
        </label>
        {geoSource && (
          <p className="dash-geo">
            <MapPin className="w-3 h-3" aria-hidden />
            We filled this in from your location
            {countryCode ? ` (${countryCode})` : ''}. You can change it.
          </p>
        )}
        <div className="dash-field-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
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
            Max budget (optional)
            <input value={maxBudget} onChange={(e) => setMaxBudget(e.target.value)} />
          </label>
        </div>
        <label
          className="dash-field"
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'flex-start',
            gap: '0.65rem',
            cursor: 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={buyingBulk}
            onChange={(e) => setBuyingBulk(e.target.checked)}
            style={{ marginTop: '0.2rem' }}
          />
          <span>
            Buying in bulk
            <span className="dash-hint" style={{ display: 'block', marginTop: '0.2rem' }}>
              Searches wholesale / supplier listings and prioritizes seller links.
            </span>
          </span>
        </label>
        <button type="submit" disabled={loading || !canSubmit} className="dash-submit">
          <span className="dash-submit__shine" aria-hidden />
          <span style={{ position: 'relative', zIndex: 1 }}>
            {loading ? 'Searching…' : isBulk ? 'Find sellers & deals' : 'Find the best deal'}
          </span>
        </button>
      </form>
    </>
  );

  return (
    <DashboardShell role="buyer" email={user?.email} onLogout={logout} aside={aside}>
      <DeskHeader
        title="Deal finder desk"
        subtitle="Live seller links, risk flags, and a clear buy or skip — built for bulk sourcing too."
      />
      {loading && (
        <SteppedLoading
          steps={[
            isBulk ? 'Finding wholesale & local sellers…' : 'Checking live local prices…',
            'Weighing risk vs value…',
            isBulk ? 'Gathering seller links…' : 'Picking buy or skip…',
          ]}
        />
      )}
      {error && <p className="dash-error">{error}</p>}
      {!loading && !result && !error && (
        <AgentsEmpty
          headline="Multiple agents, one clear deal"
          body="Tell us what you need and how many. Agents pull live seller links, weigh risk, and call buy or skip."
        />
      )}

      {result && !loading && (
        <div className="dash-results">
          {result.risk_score && <RiskAlertBanner risk={result.risk_score} />}

          <div className="ux-hero">
            <span
              className={`ux-hero__wash${verdictTag === 'BUY' ? '' : ' ux-hero__wash--coral'}`}
              aria-hidden
            />
            <span
              className={`dash-verdict-pill ${
                verdictTag === 'BUY' ? 'dash-verdict-pill--buy' : 'dash-verdict-pill--pass'
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
            <div className="ux-hero__ctas">
              {winnerLink ? (
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

          <MarketStatus
            severity={listingCount >= 3 ? 'good' : listingCount > 0 ? 'thin' : 'empty'}
            message={
              listingCount >= 3
                ? `${listingCount} live listings · ${linkCount} seller link${linkCount === 1 ? '' : 's'}`
                : listingCount > 0
                  ? `Thin live data (${listingCount} listing${listingCount === 1 ? '' : 's'}) — verify in person`
                  : result.market_warning ||
                    'We couldn’t load live prices right now, so we won’t invent a deal.'
            }
          />

          <ResultTabs
            defaultTab={linkCount > 0 ? 'sellers' : 'risk'}
            tabs={[
              {
                id: 'sellers',
                label: `Sellers${linkCount ? ` (${linkCount})` : ''}`,
                content: (
                  <div className="ux-panel seller-links-panel">
                    <SellerLinksTable
                      rows={linkedListings.length ? linkedListings : listingRows}
                      emptyMessage="No seller links in this run. Try a clearer product name or turn on bulk mode."
                      onCopyAll={linkCount > 0 ? copyAllLinks : undefined}
                      copyLabel={copiedLinks ? 'Copied' : 'Copy all links'}
                      hint="Open any seller page directly. For bulk, ask about MOQ, stock, and unit price."
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
                label: verdictTag === 'BUY' ? 'Negotiate' : 'Checklist',
                content: (
                  <div className="ux-panel">
                    {!resultWasBulk ? (
                      <ActionItems
                        alternatives={alternatives}
                        location={location}
                        itemName={itemName}
                      />
                    ) : null}
                    {verdictTag === 'BUY' &&
                    result.negotiation_script &&
                    result.negotiation_script.length > 0 ? (
                      <NegotiationScript questions={result.negotiation_script} />
                    ) : null}
                    {verdictTag === 'PASS' &&
                    result.buy_checklist &&
                    result.buy_checklist.length > 0 ? (
                      <BuyChecklist items={result.buy_checklist} />
                    ) : null}
                    {resultWasBulk &&
                    !(
                      (verdictTag === 'BUY' &&
                        result.negotiation_script &&
                        result.negotiation_script.length > 0) ||
                      (verdictTag === 'PASS' &&
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
                          ['--agent' as string]: ['#5BA3D9', '#7BB8E5', '#C4A574', '#8B949E'][i % 4],
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
            primaryLabel="Open best seller"
            onCopy={linkCount > 0 ? copyAllLinks : undefined}
            copyLabel={copiedLinks ? 'Copied' : 'Copy seller links'}
          />
        </div>
      )}
    </DashboardShell>
  );
}
