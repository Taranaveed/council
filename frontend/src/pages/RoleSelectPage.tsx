import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './RoleSelectPage.css';

const SELLER_POINTS = [
  'Fair list price from live comps',
  'Who buys and where they hang out',
  'Hooks and a short do-next pack',
];

const BUYER_POINTS = [
  'Live seller links you can open',
  'Bulk quantity + wholesale search',
  'Risk flags and buy or skip',
];

function RobotFace() {
  return (
    <span className="role-proto__robot" aria-hidden>
      <span className="role-proto__eye role-proto__eye--l" />
      <span className="role-proto__eye role-proto__eye--r" />
      <span className="role-proto__mouth" />
    </span>
  );
}

function Panel({
  role,
  busy,
  onPick,
  title,
  desc,
  cta,
  points,
  meta,
}: {
  role: 'business' | 'buyer';
  busy: boolean;
  onPick: () => void;
  title: string;
  desc: string;
  cta: string;
  points: string[];
  meta: string;
}) {
  const colors =
    role === 'business'
      ? ['#3d6f99', '#b8734f', '#8a5068']
      : ['#4a7a6a', '#3d6f99', '#c4a574'];

  return (
    <button
      type="button"
      disabled={busy}
      onClick={onPick}
      className={`role-proto__panel role-proto__panel--${role}`}
    >
      <span className="role-proto__accent" aria-hidden />

      <div className="role-proto__panel-top">
        <div className="role-proto__stack" aria-hidden>
          {colors.map((c) => (
            <span key={c} className="role-proto__avatar" style={{ background: c }}>
              <RobotFace />
            </span>
          ))}
        </div>
        <span className="role-proto__meta">{meta}</span>
      </div>

      <h2 className="role-proto__label">{title}</h2>
      <p className="role-proto__desc">{desc}</p>

      <ul className="role-proto__points">
        {points.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>

      <span className="role-proto__cta">
        {cta}
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
          <path
            d="M3 8h10M9 4l4 4-4 4"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    </button>
  );
}

export function RoleSelectPage() {
  const { user, chooseRole, logout } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const pick = async (role: 'business' | 'buyer') => {
    setBusy(true);
    setError(null);
    try {
      await chooseRole(role);
      navigate(role === 'business' ? '/business' : '/buyer');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not set role');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="role-proto">
      <div className="role-proto__mesh" aria-hidden />

      <div className="role-proto__top">
        {user?.email ? <span className="role-proto__email">{user.email}</span> : <span />}
        <button type="button" onClick={logout} className="role-proto__signout">
          Sign out
        </button>
      </div>

      <main className="role-proto__main">
        <header className="role-proto__brand-block">
          <p className="role-proto__live">
            <span className="role-proto__live-dot" />
            Choose your path
          </p>
          <h1 className="role-proto__brand">
            <span>Council</span>
          </h1>
          <p className="role-proto__tagline">
            Pick a lane. Agents debate your brief — you get one clear call.
          </p>
        </header>

        <div className="role-proto__panels">
          <Panel
            role="business"
            busy={busy}
            onPick={() => pick('business')}
            title="I'm selling"
            desc="Turn a product brief into price, buyers, and copy."
            cta="Start selling"
            points={SELLER_POINTS}
            meta="3 agents · launch pack"
          />
          <Panel
            role="buyer"
            busy={busy}
            onPick={() => pick('buyer')}
            title="I'm buying"
            desc="Find seller links for retail or bulk — then buy or skip."
            cta="Start buying"
            points={BUYER_POINTS}
            meta="3 agents · seller links"
          />
        </div>

        <p className="role-proto__proof">Agents debate → one clear call</p>

        {error ? <p className="role-proto__error">{error}</p> : null}
      </main>
    </div>
  );
}
