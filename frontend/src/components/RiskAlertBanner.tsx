import { useState } from 'react';
import { AlertTriangle, ChevronDown, ChevronRight, ClipboardList } from 'lucide-react';
import type { RiskFlag, RiskScore } from '../lib/api';

/** Codes that are common on wholesale snippets — checklist items, not alarms. */
const ROUTINE_CODES = new Set([
  'moq_not_verified',
  'warranty_not_verified',
  'could_not_fetch',
]);

/** Codes that represent real risk the buyer should not miss. */
const SERIOUS_CODES = new Set([
  'price_outlier',
  'price_not_verified',
  'unverified_supplier',
  'not_product_page',
  'retail_ask_bulk_quote',
  'retail_not_wholesale',
  'spec_missing',
  'wrong_category',
  'implausible_gold_price',
  'implausible_metal',
  'disputed_fact',
  'unit_price_unreliable',
]);

export type FlagTier = 'routine' | 'serious';

export function flagTier(flag: RiskFlag): FlagTier {
  const code = String(flag.code || '').toLowerCase();
  const sev = String(flag.severity || '').toLowerCase();
  const msg = `${flag.message || ''} ${flag.cite || ''}`.toLowerCase();

  if (SERIOUS_CODES.has(code) || sev === 'high') return 'serious';
  if (ROUTINE_CODES.has(code) || sev === 'info' || sev === 'low') return 'routine';
  if (
    /implausible|outlier|bad scrape|retail\b|not a wholesale|unverified supplier|fraud|storefront/.test(
      msg
    )
  ) {
    return 'serious';
  }
  // Default: medium "not verified" style → routine checklist
  if (/not verified|not confirmed|not found|verify on/.test(msg)) return 'routine';
  return sev === 'medium' ? 'routine' : 'serious';
}

function summaryCopy(total: number, seriousCount: number): { title: string; hint: string } {
  if (total === 0) {
    return {
      title: 'Nothing flagged from listing snippets',
      hint: 'Still open the seller page before you pay.',
    };
  }
  if (seriousCount > 0) {
    return {
      title:
        seriousCount === 1
          ? `1 high-priority issue · ${total} thing${total === 1 ? '' : 's'} to check`
          : `${seriousCount} high-priority issues · ${total} things to check`,
      hint: 'Expand for details before you order.',
    };
  }
  return {
    title: `${total} thing${total === 1 ? '' : 's'} to verify before you order`,
    hint: 'Routine checklist items — common on wholesale snippets.',
  };
}

function FlagRow({ flag, tier }: { flag: RiskFlag; tier: FlagTier }) {
  return (
    <li className={`risk-check__item risk-check__item--${tier}`}>
      <span className="risk-check__badge" aria-hidden>
        {tier === 'serious' ? '!' : '○'}
      </span>
      <div className="risk-check__body">
        <p className="risk-check__msg">{flag.message || flag.code || 'Flag'}</p>
        {flag.cite ? <p className="risk-check__cite">{flag.cite}</p> : null}
        {flag.link ? (
          <a href={flag.link} target="_blank" rel="noreferrer" className="risk-check__link">
            Open listing
          </a>
        ) : null}
      </div>
    </li>
  );
}

export function RiskAlertBanner({ risk }: { risk: RiskScore }) {
  const flags = (Array.isArray(risk.flags) ? risk.flags : []) as RiskFlag[];
  const [open, setOpen] = useState(false);

  const serious = flags.filter((f) => flagTier(f) === 'serious');
  const routine = flags.filter((f) => flagTier(f) === 'routine');
  const seriousCount = serious.length;
  const hasSerious = seriousCount > 0;
  const { title, hint } = summaryCopy(flags.length, seriousCount);

  const shellClass = hasSerious
    ? 'risk-check risk-check--alert'
    : flags.length > 0
      ? 'risk-check risk-check--calm'
      : 'risk-check risk-check--empty';

  return (
    <div
      role={hasSerious ? 'alert' : 'status'}
      className={`${shellClass} animate-[dashEnter_0.45s_ease_both]`}
    >
      <button
        type="button"
        className="risk-check__summary"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={`risk-check__icon-wrap${hasSerious ? ' risk-check__icon-wrap--alert' : ''}`}>
          {hasSerious ? (
            <AlertTriangle className="risk-check__icon" aria-hidden />
          ) : (
            <ClipboardList className="risk-check__icon" aria-hidden />
          )}
        </span>
        <span className="risk-check__summary-text">
          <span className="risk-check__title">{title}</span>
          <span className="risk-check__hint">{hint}</span>
        </span>
        <span className="risk-check__chevron" aria-hidden>
          {open ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
        </span>
      </button>

      {open ? (
        <div className="risk-check__panel">
          {flags.length === 0 ? (
            <p className="risk-check__empty-note">
              No MOQ / warranty / supplier facts were flagged from title/snippet for these listings.
              Still read the seller page before you pay.
            </p>
          ) : (
            <>
              {serious.length > 0 ? (
                <section className="risk-check__group" aria-label="Priority issues">
                  <h3 className="risk-check__group-title risk-check__group-title--serious">
                    Priority — check these first
                  </h3>
                  <ul className="risk-check__list">
                    {serious.map((f, i) => (
                      <FlagRow key={`s-${f.code}-${i}`} flag={f} tier="serious" />
                    ))}
                  </ul>
                </section>
              ) : null}
              {routine.length > 0 ? (
                <section className="risk-check__group" aria-label="Before you order checklist">
                  <h3 className="risk-check__group-title risk-check__group-title--routine">
                    Before you order — quick checklist
                  </h3>
                  <ul className="risk-check__list">
                    {routine.map((f, i) => (
                      <FlagRow key={`r-${f.code}-${i}`} flag={f} tier="routine" />
                    ))}
                  </ul>
                </section>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
