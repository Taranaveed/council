type Alternative = {
  vendor?: string;
  price?: string;
  note?: string;
};

type PlotPoint = {
  id: string;
  label: string;
  /** 0 = cheap, 1 = expensive */
  cost: number;
  /** 0 = safe, 1 = risky */
  risk: number;
  color: string;
  subtitle?: string;
};

function parsePrice(raw?: string): number | null {
  if (!raw) return null;
  const n = Number(String(raw).replace(/[^0-9.]/g, ''));
  return Number.isFinite(n) && n > 0 ? n : null;
}

function blob(a: Alternative): string {
  return [a.vendor, a.note, a.price].filter(Boolean).join(' ').toLowerCase();
}

function buildPoints(
  alternatives: Alternative[],
  riskScore?: number | null,
): PlotPoint[] {
  const authorizedAlts = alternatives.filter((a) =>
    /authori[sz]ed|official|mall|retailer|dealer|verified/.test(blob(a)),
  );
  const refurbishedAlts = alternatives.filter((a) =>
    /refurb|used|pre-?owned|open.?box|second.?hand|unverified/.test(blob(a)),
  );

  const authPrice = authorizedAlts.map((a) => parsePrice(a.price)).find((p) => p != null);
  const refurbPrice = refurbishedAlts.map((a) => parsePrice(a.price)).find((p) => p != null);

  let authCost = 0.78;
  let refurbCost = 0.32;
  if (authPrice != null && refurbPrice != null && authPrice !== refurbPrice) {
    const lo = Math.min(authPrice, refurbPrice);
    const hi = Math.max(authPrice, refurbPrice);
    authCost = (authPrice - lo) / (hi - lo);
    refurbCost = (refurbPrice - lo) / (hi - lo);
    authCost = Math.min(0.92, Math.max(0.55, authCost));
    refurbCost = Math.min(0.45, Math.max(0.08, refurbCost));
  }

  const riskBoost = typeof riskScore === 'number' ? riskScore / 3 : 0.5;

  return [
    {
      id: 'authorized',
      label: 'Safer pick',
      cost: authCost,
      risk: 0.18 + riskBoost * 0.08,
      color: '#5ba3d9',
      subtitle:
        authPrice != null
          ? `Higher cost · lower risk${authorizedAlts[0]?.vendor ? ` · ${authorizedAlts[0].vendor}` : ''}`
          : 'Higher cost · lower risk',
    },
    {
      id: 'refurbished',
      label: 'Cheaper pick',
      cost: refurbCost,
      risk: 0.62 + riskBoost * 0.25,
      color: '#e07060',
      subtitle:
        refurbPrice != null
          ? `Lower cost · higher risk${refurbishedAlts[0]?.vendor ? ` · ${refurbishedAlts[0].vendor}` : ''}`
          : 'Lower cost · higher risk',
    },
  ];
}

type Props = {
  alternatives?: Alternative[];
  riskScore?: number | null;
  verdict?: string;
};

/** Risk (Y) vs Cost (X) — Night Forge dark plot. */
export function RiskCostChart({ alternatives = [], riskScore, verdict }: Props) {
  const points = buildPoints(alternatives, riskScore);
  const w = 340;
  const h = 236;
  const pad = { top: 30, right: 22, bottom: 42, left: 46 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const toX = (cost: number) => pad.left + cost * plotW;
  const toY = (risk: number) => pad.top + (1 - risk) * plotH;

  const isPass = String(verdict || '').toUpperCase() === 'PASS';

  return (
    <div className="risk-plot">
      <div className="risk-plot__head">
        <div>
          <p className="risk-plot__kicker">Risk vs price</p>
          <h3 className="risk-plot__title">Safer vs cheaper</h3>
          <p className="risk-plot__sub">
            Trade risk for price — and see why skip can win.
          </p>
        </div>
        {isPass ? <span className="risk-plot__badge">Why skip</span> : null}
      </div>

      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="risk-plot__svg"
        role="img"
        aria-label="Risk versus cost chart"
      >
        <defs>
          <radialGradient id="riskPlotAvoid" cx="20%" cy="20%" r="70%">
            <stop offset="0%" stopColor="#e07060" stopOpacity="0.22" />
            <stop offset="100%" stopColor="#e07060" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="riskPlotSafe" cx="85%" cy="85%" r="55%">
            <stop offset="0%" stopColor="#5ba3d9" stopOpacity="0.14" />
            <stop offset="100%" stopColor="#5ba3d9" stopOpacity="0" />
          </radialGradient>
        </defs>

        <rect
          x={pad.left}
          y={pad.top}
          width={plotW}
          height={plotH}
          rx={8}
          fill="#0e1218"
          stroke="rgba(255,255,255,0.1)"
          strokeWidth={1}
        />
        <rect
          x={pad.left}
          y={pad.top}
          width={plotW}
          height={plotH}
          rx={8}
          fill="url(#riskPlotAvoid)"
        />
        <rect
          x={pad.left}
          y={pad.top}
          width={plotW}
          height={plotH}
          rx={8}
          fill="url(#riskPlotSafe)"
        />

        <text
          x={pad.left + 10}
          y={pad.top + 18}
          fill="#e07060"
          fontSize={9}
          fontWeight={600}
          fontFamily="IBM Plex Mono, ui-monospace, monospace"
          letterSpacing="0.04em"
        >
          AVOID
        </text>

        <text
          x={pad.left + plotW / 2}
          y={h - 12}
          textAnchor="middle"
          fill="#8b949e"
          fontSize={10}
          fontFamily="IBM Plex Sans, system-ui, sans-serif"
        >
          Cost →
        </text>
        <text
          x={14}
          y={pad.top + plotH / 2}
          textAnchor="middle"
          fill="#8b949e"
          fontSize={10}
          fontFamily="IBM Plex Sans, system-ui, sans-serif"
          transform={`rotate(-90 14 ${pad.top + plotH / 2})`}
        >
          Risk →
        </text>
        <text x={pad.left} y={pad.top - 10} fill="#8b949e" fontSize={9}>
          High risk
        </text>
        <text x={pad.left} y={h - pad.bottom + 16} fill="#8b949e" fontSize={9}>
          Low cost
        </text>
        <text
          x={w - pad.right}
          y={h - pad.bottom + 16}
          textAnchor="end"
          fill="#8b949e"
          fontSize={9}
        >
          High cost
        </text>

        {[0.25, 0.5, 0.75].map((t) => (
          <g key={t}>
            <line
              x1={pad.left}
              x2={pad.left + plotW}
              y1={toY(t)}
              y2={toY(t)}
              stroke="rgba(255,255,255,0.06)"
              strokeDasharray="4 4"
            />
            <line
              x1={toX(t)}
              x2={toX(t)}
              y1={pad.top}
              y2={pad.top + plotH}
              stroke="rgba(255,255,255,0.06)"
              strokeDasharray="4 4"
            />
          </g>
        ))}

        {points.map((p) => {
          const cx = toX(p.cost);
          const cy = toY(p.risk);
          return (
            <g key={p.id}>
              <circle cx={cx} cy={cy} r={16} fill={p.color} opacity={0.16} />
              <circle
                cx={cx}
                cy={cy}
                r={7}
                fill={p.color}
                stroke="#0e1218"
                strokeWidth={2}
              />
              <text
                x={cx}
                y={cy - 18}
                textAnchor="middle"
                fill="#e9edf2"
                fontSize={10}
                fontWeight={600}
                fontFamily="IBM Plex Sans, system-ui, sans-serif"
              >
                {p.label}
              </text>
            </g>
          );
        })}
      </svg>

      <ul className="risk-plot__legend">
        {points.map((p) => (
          <li key={p.id}>
            <span className="risk-plot__dot" style={{ background: p.color }} />
            <span className="risk-plot__legend-label">{p.label}</span>
            <span className="risk-plot__legend-sub">{p.subtitle}</span>
          </li>
        ))}
      </ul>

      {isPass ? (
        <p className="risk-plot__note">
          Cheaper options often carry more risk. Safer ones cost more. A{' '}
          <strong>Skip</strong> means neither feels safe enough for your budget right now.
        </p>
      ) : null}
    </div>
  );
}
