import { useState, type ReactNode } from 'react';
import { ExpandableText } from './ux/ExpandableText';
import { MarketStatus, marketSeverityFromCounts } from './ux/MarketStatus';
import { ResultTabs } from './ux/ResultTabs';
import { StickyExportBar } from './ux/StickyExportBar';

type ActionPack = {
  list_price?: string | null;
  promo_floor?: string | null;
  messaging_angles?: string[];
  first_actions?: string[];
  dont_claim?: string[];
  top_channel?: string | null;
};

type Creative = {
  channel?: string;
  hooks?: string[];
  offer?: string;
};

type Explanation = {
  why?: string;
  vs_your_band?: string;
  median_local?: string | null;
  local_listing_count?: number;
  foreign_listing_count?: number;
  list_price_suggestion?: string | null;
  promo_floor?: string | null;
  cost_floor?: string | null;
  your_band?: string | null;
  data_quality?: string;
};

type Props = {
  actionPack?: ActionPack | null;
  explanation?: Explanation | null;
  creatives?: Creative[];
  emptyNote?: string | null;
  marketWarning?: string | null;
  exportText?: string;
  comparisonNote?: string | null;
  confidencePct?: number | null;
  confidenceHint?: string;
  /** Extra tab panels from parent (Buyers, Prices, Discussion) */
  extraTabs?: Array<{ id: string; label: string; content: ReactNode }>;
  showStickyBar?: boolean;
};

export function SellerLaunchSections({
  actionPack,
  explanation,
  creatives = [],
  emptyNote,
  marketWarning,
  exportText = '',
  comparisonNote,
  confidencePct,
  confidenceHint,
  extraTabs = [],
  showStickyBar = true,
}: Props) {
  const [copied, setCopied] = useState(false);

  const copyExport = async () => {
    if (!exportText) return;
    try {
      await navigator.clipboard.writeText(exportText);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  };

  const downloadTxt = () => {
    if (!exportText) return;
    const blob = new Blob([exportText], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'launch-pack.txt';
    a.click();
    URL.revokeObjectURL(url);
  };

  const listPrice = actionPack?.list_price || explanation?.list_price_suggestion || '—';
  const promoFloor = actionPack?.promo_floor || explanation?.promo_floor || null;
  const channel = actionPack?.top_channel || '—';

  const status = marketSeverityFromCounts(
    explanation?.local_listing_count,
    explanation?.foreign_listing_count,
    emptyNote,
    marketWarning,
  );

  const doNext = (
    <div className="ux-panel">
      {(actionPack?.first_actions || []).length > 0 ? (
        <ul className="seller-pack__list">
          {actionPack!.first_actions!.map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ul>
      ) : (
        <p className="dash-meta">No next steps yet.</p>
      )}
      {(actionPack?.messaging_angles || []).length > 0 ? (
        <>
          <p className="dash-meta" style={{ marginTop: '0.85rem' }}>
            Messaging angles
          </p>
          <ul className="seller-pack__list">
            {actionPack!.messaging_angles!.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </>
      ) : null}
      {(actionPack?.dont_claim || []).length > 0 ? (
        <>
          <p className="dash-meta" style={{ marginTop: '0.85rem' }}>
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
  );

  const whyPanel = explanation ? (
    <div className="ux-panel">
      <ExpandableText lines={3}>{explanation.why || '—'}</ExpandableText>
      {explanation.vs_your_band ? <p className="dash-meta">{explanation.vs_your_band}</p> : null}
      <p className="dash-meta">
        Local comps: {explanation.local_listing_count ?? 0}
        {explanation.median_local ? ` · median ${explanation.median_local}` : ''}
        {(explanation.foreign_listing_count ?? 0) > 0
          ? ` · foreign refs ${explanation.foreign_listing_count}`
          : ''}
      </p>
      {explanation.your_band ? <p className="dash-meta">Your band: {explanation.your_band}</p> : null}
      {explanation.cost_floor ? (
        <p className="dash-meta">Cost / margin floor: {explanation.cost_floor}</p>
      ) : null}
    </div>
  ) : null;

  const hooksPanel =
    creatives.length > 0 ? (
      <ul className="dash-channel-plan__list">
        {creatives.map((c, i) => (
          <li key={i} className="dash-channel-plan__item">
            <p className="dash-channel-plan__name">{c.channel || 'Channel'}</p>
            {(c.hooks || []).map((h, j) => (
              <p key={j} className="dash-channel-plan__why">
                “{h}”
              </p>
            ))}
            {c.offer ? <p className="dash-channel-plan__action">Offer: {c.offer}</p> : null}
          </li>
        ))}
      </ul>
    ) : null;

  const tabs = [
    { id: 'next', label: 'Do next', content: doNext },
    ...(whyPanel ? [{ id: 'why', label: 'Why this price', content: whyPanel }] : []),
    ...(hooksPanel ? [{ id: 'hooks', label: 'Hooks', content: hooksPanel }] : []),
    ...extraTabs,
  ];

  return (
    <div className="seller-pack">
      {comparisonNote ? <p className="dash-meta seller-pack__compare">{comparisonNote}</p> : null}

      <div className="ux-hero">
        <span className="ux-hero__wash" aria-hidden />
        <p className="ux-hero__kicker">Your launch answer</p>
        <div className="ux-hero__grid">
          <div>
            <p className="ux-hero__label">List near</p>
            <p className="ux-hero__price">{listPrice}</p>
          </div>
          {promoFloor ? (
            <div>
              <p className="ux-hero__label">Promo floor</p>
              <p className="ux-hero__price ux-hero__price--sm">{promoFloor}</p>
            </div>
          ) : null}
          <div>
            <p className="ux-hero__label">Best channel</p>
            <p className="ux-hero__price ux-hero__price--sm">{channel}</p>
          </div>
        </div>
        {(confidencePct != null || confidenceHint) && (
          <p className="ux-hero__confidence">
            How sure: {confidencePct != null ? `${confidencePct}%` : '—'}
            {confidenceHint ? ` · ${confidenceHint}` : ''}
          </p>
        )}
        {exportText ? (
          <div className="ux-hero__ctas seller-pack__export">
            <button type="button" className="dash-submit seller-pack__btn" onClick={copyExport}>
              {copied ? 'Copied' : 'Copy WhatsApp text'}
            </button>
            <button type="button" className="dash-submit seller-pack__btn" onClick={downloadTxt}>
              Download .txt
            </button>
          </div>
        ) : null}
      </div>

      <MarketStatus severity={status.severity} message={status.message} />

      <ResultTabs tabs={tabs} defaultTab="next" />

      {showStickyBar && exportText ? (
        <StickyExportBar onCopy={copyExport} onDownload={downloadTxt} />
      ) : null}
    </div>
  );
}
