import { Link } from 'react-router-dom';
import type { ReactNode } from 'react';
import '../styles/bright-dash.css';
import { friendlyExpertName } from '../lib/friendlyLabels';
import { DebateProse, ExpandableDebate } from '../lib/debateProse';
import { AgentTheater } from './ux/AgentTheater';

type Props = {
  role: 'business' | 'buyer';
  email?: string | null;
  onLogout: () => void;
  aside: ReactNode;
  children: ReactNode;
};

function BentoMark() {
  return (
    <span className="dash-proto__bento" aria-hidden>
      <i />
      <i />
      <i />
      <i />
    </span>
  );
}

export function DashboardShell({ role, email, onLogout, aside, children }: Props) {
  const toolsLabel = role === 'business' ? 'Seller council' : 'Buyer council';

  return (
    <div className={`dash-proto dash-proto--${role}`}>
      <div className="dash-proto__mesh" aria-hidden />

      <header className="dash-proto__header">
        <div className="dash-proto__brand">
          <BentoMark />
          <span className="dash-proto__brand-name">{toolsLabel}</span>
        </div>
        <nav className="dash-proto__nav">
          {email ? <span className="dash-proto__email">{email}</span> : null}
          <Link to="/role">Change path</Link>
          <button type="button" onClick={onLogout}>
            Sign out
          </button>
        </nav>
      </header>

      <div className="dash-proto__body">
        <aside className="dash-proto__aside">{aside}</aside>
        <main className="dash-proto__main">{children}</main>
      </div>
    </div>
  );
}

/** Editorial desk title — serif headline + quiet subtitle (Seller launch desk pattern). */
export function DeskHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <header className="dash-desk">
      <h1 className="dash-desk__title">{title}</h1>
      <p className="dash-desk__sub">{subtitle}</p>
    </header>
  );
}

export function DashLoading({ label }: { label: string }) {
  return <AgentTheater steps={[label]} compact intervalMs={12000} />;
}

export function DashEmpty({ title, body }: { title: string; body: string }) {
  return (
    <div className="dash-empty dash-empty--quiet">
      <h2 className="dash-empty__title">{title}</h2>
      <p>{body}</p>
    </div>
  );
}

const COUNCIL_AVATARS = [
  { color: '#3d6f99', label: 'Agent 1' },
  { color: '#b8734f', label: 'Agent 2' },
  { color: '#8a5068', label: 'Agent 3' },
];

function RobotFace() {
  return (
    <span className="agents-empty__robot" aria-hidden>
      <span className="agents-empty__eye agents-empty__eye--l" />
      <span className="agents-empty__eye agents-empty__eye--r" />
      <span className="agents-empty__mouth" />
    </span>
  );
}

/** Centered empty state — stacked agent avatars + short council pitch. */
export function AgentsEmpty({
  headline = 'Multiple agents, one council',
  body = 'Fill the brief on the left, then run the pack.',
  cta,
}: {
  headline?: string;
  body?: string;
  cta?: string;
}) {
  return (
    <div className="agents-empty agents-empty--quiet">
      <div className="agents-empty__stack" aria-hidden>
        {COUNCIL_AVATARS.map((a) => (
          <span
            key={a.label}
            className="agents-empty__avatar"
            style={{ background: a.color }}
            title={a.label}
          >
            <RobotFace />
          </span>
        ))}
      </div>
      <h2 className="agents-empty__headline">{headline}</h2>
      <p className="agents-empty__body">{body}</p>
      {cta ? <p className="agents-empty__cta">{cta}</p> : null}
    </div>
  );
}

const EXPERT_COLORS = ['#5BA3D9', '#7BB8E5', '#C4A574', '#8B949E', '#3D7FAD'];

export function TranscriptBlock({
  transcript,
  collapsedByDefault = false,
  title = 'Full discussion',
  asPanel = false,
}: {
  transcript: Record<string, string>;
  collapsedByDefault?: boolean;
  title?: string;
  asPanel?: boolean;
}) {
  if (!transcript) return null;
  const entries = Object.entries(transcript);
  if (!entries.length) return null;

  const body = (
    <div
      className="ux-transcript"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '0.65rem',
        marginTop: asPanel ? 0 : '0.75rem',
      }}
    >
      {entries.map(([name, text], i) => (
        <div
          key={name}
          className="dash-agent"
          style={{
            ['--agent' as string]: EXPERT_COLORS[i % EXPERT_COLORS.length],
            animationDelay: `${i * 0.07}s`,
          }}
        >
          <p className="dash-agent__name">{friendlyExpertName(name)}</p>
          {asPanel ? (
            <DebateProse text={String(text || '')} className="dash-agent__text ux-transcript__full" />
          ) : (
            <ExpandableDebate text={String(text || '')} lines={8} className="dash-agent__text" />
          )}
        </div>
      ))}
    </div>
  );

  if (asPanel) {
    return (
      <div className="ux-panel">
        {title ? (
          <h3 className="dash-section-title" style={{ marginTop: 0 }}>
            {title}
          </h3>
        ) : null}
        {body}
      </div>
    );
  }

  return (
    <details className="ux-details" open={!collapsedByDefault}>
      <summary className="dash-section-title ux-details__summary">{title}</summary>
      {body}
    </details>
  );
}
