export type MarketSeverity = 'good' | 'thin' | 'empty' | 'info';

type Props = {
  severity: MarketSeverity;
  message: string;
};

export function marketSeverityFromCounts(
  localCount: number | null | undefined,
  foreignCount: number | null | undefined,
  emptyNote?: string | null,
  warning?: string | null,
): { severity: MarketSeverity; message: string } {
  const local = localCount ?? 0;
  const foreign = foreignCount ?? 0;
  if (local >= 5) {
    return {
      severity: 'good',
      message: `Based on ${local} local live price${local === 1 ? '' : 's'}`,
    };
  }
  if (local >= 1) {
    return {
      severity: 'thin',
      message: `Few local comps (${local}) — treat the suggested price as directional`,
    };
  }
  if (foreign > 0) {
    return {
      severity: 'thin',
      message: 'Only foreign-currency listings — use your local band as the anchor',
    };
  }
  if (emptyNote) {
    return { severity: 'empty', message: emptyNote };
  }
  if (warning) {
    return { severity: 'empty', message: warning };
  }
  return {
    severity: 'empty',
    message: 'No live prices — using your band and product details',
  };
}

export function MarketStatus({ severity, message }: Props) {
  if (!message) return null;
  return (
    <p className={`ux-status ux-status--${severity}`} role="status">
      {message}
    </p>
  );
}
