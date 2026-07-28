import type { RiskScore } from '../lib/api';

const LEVEL: Record<string, { label: string; tone: string }> = {
  low: { label: 'Low risk', tone: 'ok' },
  medium: { label: 'Medium risk', tone: 'warn' },
  high: { label: 'High risk', tone: 'bad' },
};

export function RiskScoreMeter({ risk }: { risk: RiskScore }) {
  const max = risk.max_score || 3;
  const score = Math.min(Math.max(risk.score ?? 0, 0), max);
  const level = LEVEL[risk.level] || LEVEL.medium;
  const pct = max > 0 ? (score / max) * 100 : 0;

  return (
    <div className={`risk-meter risk-meter--${level.tone}`}>
      <div className="risk-meter__head">
        <div>
          <p className="risk-meter__kicker">How risky?</p>
          <p className="risk-meter__score">
            {score}
            <span> / {max}</span>
          </p>
        </div>
        <span className="risk-meter__badge">{level.label}</span>
      </div>

      <div className="risk-meter__track" aria-hidden>
        <div className="risk-meter__fill" style={{ width: `${pct}%` }} />
      </div>

      <p className="risk-meter__sub">Based on warnings about customs, warranty, and shipping.</p>

      {risk.triggers?.length > 0 ? (
        <div className="risk-meter__tags">
          {risk.triggers.map((t) => (
            <span key={t}>{t}</span>
          ))}
        </div>
      ) : (
        <p className="risk-meter__clear">No big flags on customs, warranty, or shipping.</p>
      )}
    </div>
  );
}
