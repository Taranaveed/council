import { useEffect, useState } from 'react';

type Props = {
  steps: string[];
  intervalMs?: number;
  compact?: boolean;
};

/**
 * Loading inspired by afro-m’s AI product loading (Dribbble #6298759):
 * soft core + concentric rings + orbiting nodes — restyled Graphite + Moss.
 */
export function AgentTheater({ steps, intervalMs = 8500, compact = false }: Props) {
  const [index, setIndex] = useState(0);
  const list = steps.length ? steps : ['Working…'];

  useEffect(() => {
    setIndex(0);
    if (list.length <= 1) return;
    const id = window.setInterval(() => {
      setIndex((i) => (i < list.length - 1 ? i + 1 : i));
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [list.length, intervalMs, steps.join('|')]);

  const progress = list.length <= 1 ? 0.42 : (index + 0.55) / list.length;

  return (
    <div
      className={`ai-load${compact ? ' ai-load--compact' : ''}`}
      role="status"
      aria-live="polite"
    >
      <div className="ai-load__visual" aria-hidden>
        <div className="ai-load__glow" />
        <div className="ai-load__ring ai-load__ring--outer" />
        <div className="ai-load__ring ai-load__ring--mid" />
        <div className="ai-load__ring ai-load__ring--inner" />
        <div className="ai-load__core">
          <span className="ai-load__core-shine" />
        </div>
        <div className="ai-load__orbit ai-load__orbit--a">
          <span className="ai-load__node" />
        </div>
        <div className="ai-load__orbit ai-load__orbit--b">
          <span className="ai-load__node ai-load__node--sm" />
        </div>
        <div className="ai-load__orbit ai-load__orbit--c">
          <span className="ai-load__node" />
        </div>
        <div className="ai-load__sparks">
          <i />
          <i />
          <i />
          <i />
          <i />
          <i />
        </div>
      </div>

      <div className="ai-load__copy">
        <p className="ai-load__kicker">Agents thinking</p>
        <p className="ai-load__active">{list[index]}</p>
        <div className="ai-load__bar" aria-hidden>
          <span style={{ transform: `scaleX(${Math.min(1, progress)})` }} />
        </div>
        {!compact ? (
          <ol className="ai-load__steps">
            {list.map((label, i) => (
              <li
                key={label}
                className={
                  i < index
                    ? 'ai-load__step ai-load__step--done'
                    : i === index
                      ? 'ai-load__step ai-load__step--active'
                      : 'ai-load__step'
                }
              >
                <span className="ai-load__mark" aria-hidden>
                  {i < index ? '✓' : ''}
                </span>
                {label}
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </div>
  );
}
