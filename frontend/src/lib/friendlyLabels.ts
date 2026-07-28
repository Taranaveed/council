/** Plain-language labels for internal role / expert keys shown in the UI. */
const LABELS: Record<string, string> = {
  premium_maximizer: 'Higher price view',
  volume_discounter: 'Lower price view',
  market_skeptic: 'Cautious market view',
  market_benchmark: 'Market average view',
  demographic_scout: 'Who buys this',
  psychographic_analyst: 'Why they buy',
  utility_specialist: 'What problem it solves',
  thrift_advocate: 'Best deal view',
  risk_analyst: 'Safety & risk view',
  contextual_persona: 'Practical fit view',
};

export function friendlyExpertName(key: string): string {
  const normalized = key.trim().toLowerCase();
  if (LABELS[normalized]) return LABELS[normalized];
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function friendlyVerdict(raw: unknown): string {
  const v = String(raw || '').toUpperCase();
  if (v === 'BUY') return 'Buy';
  if (v === 'PASS') return 'Skip';
  return String(raw || '—');
}
