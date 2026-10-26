/** Shared API helpers for Council */
import { getApiBase } from './apiBase';

export type User = {
  id: number;
  email: string;
  role: 'business' | 'buyer' | null;
};

export type AuthResponse = {
  access_token: string;
  token_type: string;
  user: User;
};

export type GeoInfo = {
  ip?: string | null;
  city?: string | null;
  region?: string | null;
  country?: string | null;
  country_code?: string | null;
  location_label: string;
  nearest_api_region: string;
  source: string;
};

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('sf_token');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as { detail?: unknown }));
    const detail = body.detail;
    let message = `Request failed (${res.status})`;
    if (typeof detail === 'string') {
      message = /groq|model_not_found|invalid_request|rate_limit/i.test(detail)
        ? 'The agents could not finish this run. Wait a moment and try again.'
        : detail;
    }
    else if (Array.isArray(detail)) {
      message = detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ');
    }
    throw new Error(message);
  }
  return res.json();
}

function networkErrorMessage(err: unknown): Error {
  const raw = err instanceof Error ? err.message : String(err ?? '');
  const name = err instanceof Error ? err.name : '';
  if (name === 'AbortError' || /aborted|abort/i.test(raw)) {
    return new Error('Request was interrupted (server reloading or timeout). Wait a second and retry.');
  }
  if (/failed to fetch|networkerror|load failed|network request failed/i.test(raw)) {
    const base = getApiBase();
    const local = /localhost|127\.0\.0\.1/.test(base);
    return new Error(
      local
        ? `Can’t reach the API at ${base}. Confirm the backend is running on port 8001, open http://localhost:5173, then retry.`
        : 'Can’t reach the server. On free hosting it may be waking up — wait ~30s, open the site again, then retry.',
    );
  }
  return err instanceof Error ? err : new Error(raw || 'Request failed');
}

/** Ping the API so a sleeping free-tier Render service wakes before auth. */
export async function wakeApi(timeoutMs = 90000): Promise<boolean> {
  const base = getApiBase();
  const local = /localhost|127\.0\.0\.1/.test(base);
  const budget = local ? Math.min(timeoutMs, 4000) : timeoutMs;
  const started = Date.now();
  let delay = local ? 400 : 1500;
  while (Date.now() - started < budget) {
    try {
      const ctrl = new AbortController();
      const timer = window.setTimeout(() => ctrl.abort(), local ? 2500 : 20000);
      const res = await fetch(`${base}/health`, { signal: ctrl.signal, cache: 'no-store' });
      window.clearTimeout(timer);
      if (res.ok) return true;
    } catch {
      // keep retrying while the free tier boots
    }
    await new Promise((r) => setTimeout(r, delay));
    delay = Math.min(delay + (local ? 400 : 1000), local ? 800 : 4000);
  }
  return false;
}

/** Wake market-service via the API proxy (same host → no CORS issues on mobile). */
export async function wakeMarket(timeoutMs = 90000): Promise<boolean> {
  const base = getApiBase();
  const local = /localhost|127\.0\.0\.1/.test(base);
  const budget = local ? Math.min(timeoutMs, 8000) : timeoutMs;
  const started = Date.now();
  let delay = local ? 400 : 1500;
  while (Date.now() - started < budget) {
    try {
      const ctrl = new AbortController();
      const timer = window.setTimeout(() => ctrl.abort(), local ? 5000 : 25000);
      const res = await fetch(`${base}/api/market/ping`, {
        signal: ctrl.signal,
        cache: 'no-store',
      });
      window.clearTimeout(timer);
      if (res.ok) {
        const data = (await res.json().catch(() => ({}))) as { status?: string };
        if (data.status === 'ok') return true;
      }
    } catch {
      // keep retrying
    }
    await new Promise((r) => setTimeout(r, delay));
    delay = Math.min(delay + (local ? 400 : 1000), local ? 1000 : 4000);
  }
  return false;
}

export async function resolveGeoFromIp(): Promise<GeoInfo> {
  const res = await fetch(`${getApiBase()}/api/geo/ip`);
  return handle(res);
}

export async function register(email: string, password: string): Promise<AuthResponse> {
  try {
    await wakeApi(45000);
    const res = await fetch(`${getApiBase()}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    return await handle(res);
  } catch (err) {
    throw networkErrorMessage(err);
  }
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  try {
    await wakeApi(45000);
    const res = await fetch(`${getApiBase()}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    return await handle(res);
  } catch (err) {
    throw networkErrorMessage(err);
  }
}

export async function fetchMe(): Promise<User> {
  const res = await fetch(`${getApiBase()}/auth/me`, { headers: authHeaders() });
  return handle(res);
}

export async function setRole(role: 'business' | 'buyer'): Promise<User> {
  const res = await fetch(`${getApiBase()}/auth/role`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ role }),
  });
  return handle(res);
}

export type RiskFlag = {
  code?: string;
  message?: string;
  cite?: string;
  link?: string;
  listing_title?: string;
  /** Backend severity: high | medium | low | info */
  severity?: string;
};

export type RiskScore = {
  score: number;
  max_score: number;
  level: 'low' | 'medium' | 'high' | 'info' | string;
  triggers: string[];
  echoed_by_others?: string[];
  source_agent?: string;
  flags?: RiskFlag[];
  header?: string;
};

export type SupplierCompareRow = {
  rank?: number;
  vendor?: string;
  title?: string;
  link?: string;
  unit_price?: string;
  currency?: string;
  moq?: number | string | null;
  origin?: string;
  risk_score?: number;
  risk_reasons?: string[];
  landed_mid?: string | null;
  best_pick?: boolean;
};

export type CreditStatus = {
  plan?: string;
  used_this_month?: number;
  limit?: number;
  remaining?: number;
  exhausted?: boolean;
};

export type ModeResult = {
  transcript: Record<string, string>;
  verdict: Record<string, unknown>;
  market_listings?: Array<Record<string, unknown>>;
  market_warning?: string | null;
  raw_verdict?: string | null;
  risk_score?: RiskScore | null;
  negotiation_script?: string[];
  negotiation_message?: string | null;
  buy_checklist?: string[];
  price_explanation?: Record<string, unknown> | null;
  action_pack?: Record<string, unknown> | null;
  channel_creatives?: Array<Record<string, unknown>>;
  empty_state_note?: string | null;
  brief_id?: number | null;
  compare_to_prior?: CompareToPrior | null;
  supplier_table?: SupplierCompareRow[];
  export_text?: string | null;
  credits?: CreditStatus | null;
  query_meta?: {
    vague?: boolean;
    hard_vague?: boolean;
    suggestion?: string;
    auto_narrowed?: boolean;
    used_query?: string;
    original?: string;
    reason?: string;
    relevance?: {
      relevant_priced_count?: number;
      dropped_count?: number;
      drop_reasons?: Record<string, number>;
      no_good_matches?: boolean;
      listing_counts?: { found?: number; relevant?: number; priced?: number };
    };
    supplier_table?: SupplierCompareRow[];
    negotiation_message?: string;
    serp_source_status?: Array<{
      label?: string;
      status?: string;
      ok?: boolean;
      error?: string | null;
    }>;
  } | null;
};

export type CompareToPrior = {
  prior_brief_id?: number;
  prior_created_at?: string;
  prior_verdict?: string;
  prior_winner_vendor?: string;
  prior_winner_price?: string;
  prior_landed_mid?: string;
  prior_item_name?: string;
  current_verdict?: string;
  current_winner_price?: string;
  current_landed_mid?: string;
  verdict_flipped?: boolean;
  same_supplier?: boolean;
  match_basis?: string;
};

export type BriefSummary = {
  id: number;
  run_id?: string | null;
  item_name: string;
  location?: string | null;
  currency?: string | null;
  quantity?: number | null;
  buying_mode?: string | null;
  verdict_tag?: string | null;
  winner_title?: string | null;
  winner_vendor?: string | null;
  winner_price?: string | null;
  winner_link?: string | null;
  supplier_host?: string | null;
  landed_mid?: string | null;
  summary?: string | null;
  fake_cheap?: boolean;
  created_at?: string | null;
  supplier_fake_cheap_count?: number;
};

export type BriefDetail = BriefSummary & {
  payload?: Record<string, unknown>;
  compare_to_prior?: CompareToPrior | null;
};

export async function listBriefs(limit = 30): Promise<{
  briefs: BriefSummary[];
  supplier_flags: Record<string, number>;
}> {
  const res = await fetch(`${getApiBase()}/api/briefs?limit=${limit}`, {
    headers: authHeaders(),
  });
  return handle(res);
}

export async function getBrief(id: number): Promise<BriefDetail> {
  const res = await fetch(`${getApiBase()}/api/briefs/${id}`, {
    headers: authHeaders(),
  });
  return handle(res);
}

export async function setBriefFakeCheap(
  id: number,
  fakeCheap = true,
): Promise<BriefDetail> {
  const res = await fetch(`${getApiBase()}/api/briefs/${id}/fake-cheap`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ fake_cheap: fakeCheap }),
  });
  return handle(res);
}

export async function shareBrief(id: number): Promise<{ token: string; url: string }> {
  const res = await fetch(`${getApiBase()}/api/briefs/${id}/share`, {
    method: 'POST',
    headers: authHeaders(),
  });
  return handle(res);
}

export async function exportBrief(id: number): Promise<{
  text: string;
  share_url?: string | null;
  supplier_table?: SupplierCompareRow[];
  negotiation_message?: string | null;
}> {
  const res = await fetch(`${getApiBase()}/api/briefs/${id}/export`, {
    headers: authHeaders(),
  });
  return handle(res);
}

export async function markBriefOrdered(
  id: number,
  days = 30,
): Promise<BriefDetail> {
  const res = await fetch(`${getApiBase()}/api/briefs/${id}/ordered`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ days }),
  });
  return handle(res);
}

export async function fetchSharedBrief(token: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${getApiBase()}/api/briefs/shared/${encodeURIComponent(token)}`);
  return handle(res);
}

export async function getCredits(): Promise<CreditStatus> {
  const res = await fetch(`${getApiBase()}/api/workspace/credits`, {
    headers: authHeaders(),
  });
  return handle(res);
}

export async function listReminders(): Promise<{
  reminders: Array<Record<string, unknown>>;
}> {
  const res = await fetch(`${getApiBase()}/api/workspace/reminders`, {
    headers: authHeaders(),
  });
  return handle(res);
}

export type WatchItem = {
  id: number;
  item_name: string;
  location?: string | null;
  currency?: string | null;
  quantity?: number | null;
  max_unit_price?: number | null;
  max_landed?: number | null;
  tracked_url?: string | null;
  listing_title?: string | null;
  listing_vendor?: string | null;
  native_currency?: string | null;
  saved_price?: string | null;
  saved_price_source?: string | null;
  last_price_source?: string | null;
  last_checked_at?: string | null;
  last_best_price?: string | null;
  last_best_link?: string | null;
  last_alert?: string | null;
};

export async function listWatchlist(): Promise<{ items: WatchItem[] }> {
  const res = await fetch(`${getApiBase()}/api/workspace/watchlist`, {
    headers: authHeaders(),
  });
  return handle(res);
}

export async function addWatchlistItem(body: {
  item_name: string;
  tracked_url: string;
  listing_title?: string;
  listing_vendor?: string;
  native_currency: string;
  saved_price: string;
  saved_price_source?: string;
  location?: string;
  currency?: string;
  quantity?: number;
  max_unit_price?: number;
}): Promise<WatchItem> {
  const res = await fetch(`${getApiBase()}/api/workspace/watchlist`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  return handle(res);
}

export async function removeWatchlistItem(id: number): Promise<void> {
  const res = await fetch(`${getApiBase()}/api/workspace/watchlist/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  await handle(res);
}

export async function checkWatchlistItem(id: number): Promise<WatchItem> {
  const res = await fetch(`${getApiBase()}/api/workspace/watchlist/${id}/check`, {
    method: 'POST',
    headers: authHeaders(),
  });
  return handle(res);
}

export type AppNotification = {
  id: number;
  kind: string;
  title: string;
  body: string;
  href?: string | null;
  unread?: boolean;
  created_at?: string | null;
  meta?: Record<string, unknown>;
};

export async function listNotifications(opts?: {
  unreadOnly?: boolean;
  limit?: number;
}): Promise<{ items: AppNotification[]; unread: number }> {
  const q = new URLSearchParams();
  if (opts?.unreadOnly) q.set('unread_only', 'true');
  if (opts?.limit) q.set('limit', String(opts.limit));
  const qs = q.toString();
  const res = await fetch(
    `${getApiBase()}/api/workspace/notifications${qs ? `?${qs}` : ''}`,
    { headers: authHeaders() },
  );
  return handle(res);
}

export async function markNotificationRead(id: number): Promise<AppNotification> {
  const res = await fetch(`${getApiBase()}/api/workspace/notifications/${id}/read`, {
    method: 'POST',
    headers: authHeaders(),
  });
  return handle(res);
}

export async function markAllNotificationsRead(): Promise<{ ok: boolean; marked: number }> {
  const res = await fetch(`${getApiBase()}/api/workspace/notifications/read-all`, {
    method: 'POST',
    headers: authHeaders(),
  });
  return handle(res);
}

export async function dismissReminder(briefId: number): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiBase()}/api/workspace/reminders/${briefId}/dismiss`, {
    method: 'POST',
    headers: authHeaders(),
  });
  return handle(res);
}

export async function runWorkspaceAlerts(force = false): Promise<{
  watches_checked: number;
  alerts_fired: number;
  unread: number;
  notifications: AppNotification[];
  reminders: Array<Record<string, unknown>>;
  email_enabled?: boolean;
}> {
  const q = force ? '?force=true' : '';
  const res = await fetch(`${getApiBase()}/api/workspace/alerts/run${q}`, {
    method: 'POST',
    headers: authHeaders(),
  });
  return handle(res);
}

export async function runDealFinder(body: {
  item_name: string;
  location: string;
  max_budget?: string;
  currency?: string;
  marketplace?: string;
  quantity?: number;
  buying_mode?: 'retail' | 'bulk';
}): Promise<ModeResult> {
  try {
    // Local backends are already up — don't burn 45–90s on wake loops.
    const local = /localhost|127\.0\.0\.1/.test(getApiBase());
    await wakeApi(local ? 3000 : 45000);
    await wakeMarket(local ? 3000 : 90000);
    const res = await fetch(`${getApiBase()}/api/modes/deal-finder`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(body),
    });
    return await handle(res);
  } catch (err) {
    throw networkErrorMessage(err);
  }
}
