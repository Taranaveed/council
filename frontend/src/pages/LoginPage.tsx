import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './LoginPage.css';

export function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = mode === 'login' ? await login(email, password) : await register(email, password);
      navigate(user.role ? (user.role === 'business' ? '/business' : '/buyer') : '/role');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-proto">
      <div className="login-proto__mesh" aria-hidden />
      <div className="login-proto__orbs" aria-hidden>
        <span className="login-proto__orb login-proto__orb--a" />
        <span className="login-proto__orb login-proto__orb--b" />
        <span className="login-proto__orb login-proto__orb--c" />
        <span className="login-proto__orb login-proto__orb--d" />
      </div>

      <main className="login-proto__main">
        <header className="login-proto__brand-block">
          <p className="login-proto__live">
            <span className="login-proto__live-dot" />
            Ready when you are
          </p>
          <h1 className="login-proto__brand">
            <span>Council</span>
          </h1>
          <p className="login-proto__tagline">
            Multiple agents. One clear call — on price, buyers, or the deal in front of you.
          </p>
        </header>

        <div className="login-proto__form-wrap">
          <span className="login-proto__form-glow login-proto__form-glow--a" aria-hidden />
          <span className="login-proto__form-glow login-proto__form-glow--b" aria-hidden />

          <div className="login-proto__tabs" role="tablist" aria-label="Auth mode">
            <span
              className={`login-proto__tab-ink${mode === 'register' ? ' login-proto__tab-ink--register' : ''}`}
              aria-hidden
            />
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'login'}
              className={`login-proto__tab${mode === 'login' ? ' login-proto__tab--active' : ''}`}
              onClick={() => {
                setMode('login');
                setError(null);
              }}
            >
              Sign in
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'register'}
              className={`login-proto__tab${mode === 'register' ? ' login-proto__tab--active' : ''}`}
              onClick={() => {
                setMode('register');
                setError(null);
              }}
            >
              Register
            </button>
          </div>

          <form onSubmit={onSubmit}>
            <label className="login-proto__field">
              Email
              <input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
              />
            </label>
            <label className="login-proto__field">
              Password
              <input
                type="password"
                required
                minLength={6}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 6 characters"
              />
            </label>

            {error ? <p className="login-proto__error">{error}</p> : null}

            <button type="submit" disabled={busy} className="login-proto__submit">
              <span className="login-proto__submit-shine" aria-hidden />
              <span className="login-proto__submit-label">
                {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
                {!busy ? (
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
                    <path
                      d="M3 8h10M9 4l4 4-4 4"
                      stroke="currentColor"
                      strokeWidth="1.75"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                ) : null}
              </span>
            </button>
          </form>

          <div className="login-proto__agents" aria-hidden>
            <span className="login-proto__dot" />
            <span className="login-proto__dot" />
            <span className="login-proto__dot" />
            <span className="login-proto__dot" />
          </div>
        </div>
      </main>
    </div>
  );
}
