import { useState, type ReactNode } from 'react';

export type ResultTab = {
  id: string;
  label: string;
  content: ReactNode;
};

type Props = {
  tabs: ResultTab[];
  defaultTab?: string;
  className?: string;
};

export function ResultTabs({ tabs, defaultTab, className = '' }: Props) {
  const usable = tabs.filter((t) => t.content != null && t.content !== false);
  const initial =
    (defaultTab && usable.some((t) => t.id === defaultTab) && defaultTab) ||
    usable[0]?.id ||
    '';
  const [active, setActive] = useState(initial);

  if (!usable.length) return null;

  const current = usable.find((t) => t.id === active) || usable[0];

  return (
    <div className={`ux-tabs ${className}`.trim()}>
      <div className="ux-tabs__list" role="tablist" aria-label="Result details">
        {usable.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={t.id === current.id}
            className={`ux-tabs__btn${t.id === current.id ? ' ux-tabs__btn--active' : ''}`}
            onClick={() => setActive(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="ux-tabs__panel" role="tabpanel">
        {current.content}
      </div>
    </div>
  );
}
