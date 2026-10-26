import { useEffect, useState } from 'react';

type Props = {
  steps: string[];
  intervalMs?: number;
  compact?: boolean;
};

const WAIT_HINTS = [
  'Pulling live supplier pages…',
  'Checking prices and MOQs…',
  'Agents are weighing the options…',
  'Almost there — grounding the verdict…',
];

/** Progress checklist with professional loading motion. */
export function AgentTheater({ steps, intervalMs = 6500, compact = false }: Props) {
  const [index, setIndex] = useState(0);
  const [hintIndex, setHintIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [tick, setTick] = useState(0);
  const list = steps.length ? steps : ['Working…'];

  useEffect(() => {
    setIndex(0);
    setElapsed(0);
    setHintIndex(0);
    if (list.length <= 1) return;
    const id = window.setInterval(() => {
      setIndex((i) => (i < list.length - 1 ? i + 1 : i));
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [list.length, intervalMs, steps.join('|')]);

  useEffect(() => {
    const id = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      setHintIndex((h) => (h + 1) % WAIT_HINTS.length);
      setTick((t) => t + 1);
    }, 3200);
    return () => window.clearInterval(id);
  }, []);

  const base = list.length <= 1 ? 0.28 : (index + 0.35) / list.length;
  // Soft creep within the current step so the bar never feels frozen
  const creep = Math.min(0.12, (elapsed % 8) / 70);
  const progress = Math.min(0.94, base + creep);
  const mm = String(Math.floor(elapsed / 60)).padStart(1, '0');
  const ss = String(elapsed % 60).padStart(2, '0');

  return (
    <div
      className={`ai-load${compact ? ' ai-load--compact' : ''}`}
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="ai-load__copy">
        <div className="ai-load__top">
          <p className="ai-load__kicker">
            <span className="ai-load__live" aria-hidden />
            Working
            <span className="ai-load__dots" aria-hidden>
              <i />
              <i />
              <i />
            </span>
          </p>
          <p className="ai-load__timer" aria-label={`Elapsed ${mm}:${ss}`}>
            {mm}:{ss}
          </p>
        </div>

        <p key={`active-${index}`} className="ai-load__active">
          {list[index]}
        </p>

        <div className="ai-load__bar" aria-hidden>
          <span
            className="ai-load__bar-fill"
            style={{ transform: `scaleX(${Math.min(1, progress)})` }}
          />
          <span className="ai-load__bar-shine" />
        </div>

        {!compact ? (
          <>
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
                    {i < index ? (
                      <svg viewBox="0 0 16 16" width="10" height="10" fill="none">
                        <path
                          d="M3.5 8.5 6.5 11.5 12.5 4.5"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    ) : i === index ? (
                      <span className="ai-load__spinner" />
                    ) : (
                      <span className="ai-load__idle" />
                    )}
                  </span>
                  <span className="ai-load__step-label">{label}</span>
                </li>
              ))}
            </ol>
            <p key={`hint-${tick}`} className="ai-load__hint">
              {WAIT_HINTS[hintIndex]}
            </p>
          </>
        ) : null}
      </div>
    </div>
  );
}
