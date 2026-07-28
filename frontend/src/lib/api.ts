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
    if (typeof detail === 'string') message = detail;
    else if (Array.isArray(detail)) {
      message = detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ');
    }
    throw new Error(message);
  }
  return res.json();
}

function networkErrorMessage(err: unknown): Error {
  const raw = err instanceof Error ? err.message : String(err ?? '');
  if (/failed to fetch|networkerror|load failed|network request failed/i.test(raw)) {
    return new Error(
      'Can’t reach the server. On free hosting it may be waking up — wait ~30s, open the site again, then retry.',
    );
  }
  return err instanceof Error ? err : new Error(raw || 'Request failed');
}

/** Ping the API so a sleeping free-tier Render service wakes before auth. */
export async function wakeApi(timeoutMs = 90000): Promise<boolean> {
  const base = getApiBase();
  const started = Date.now();
  let delay = 1500;
  while (Date.now() - started < timeoutMs) {
    try {
      const ctrl = new AbortController();
      const timer = window.setTimeout(() => ctrl.abort(), 20000);
      const res = await fetch(`${base}/health`, { signal: ctrl.signal, cache: 'no-store' });
      window.clearTimeout(timer);
      if (res.ok) return true;
    } catch {
      // keep retrying while the free tier boots
    }
    await new Promise((r) => setTimeout(r, delay));
    delay = Math.min(delay + 1000, 4000);
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

export type RiskScore = {
  score: number;
  max_score: number;
  level: 'low' | 'medium' | 'high' | string;
  triggers: string[];
  echoed_by_others?: string[];
  source_agent?: string;
};

export type ModeResult = {
  transcript: Record<string, string>;
  verdict: Record<string, unknown>;
  market_listings?: Array<Record<string, unknown>>;
  market_warning?: string | null;
  raw_verdict?: string | null;
  risk_score?: RiskScore | null;
  negotiation_script?: string[];
  buy_checklist?: string[];
  price_explanation?: Record<string, unknown> | null;
  action_pack?: Record<string, unknown> | null;
  channel_creatives?: Array<Record<string, unknown>>;
  empty_state_note?: string | null;
};

export type LaunchPackVariant = {
  label: string;
  product_name: string;
  price_verdict: Record<string, unknown>;
  audience_verdict: Record<string, unknown>;
  price_transcript: Record<string, string>;
  audience_transcript: Record<string, string>;
  price_explanation: Record<string, unknown>;
  action_pack: Record<string, unknown>;
  channel_creatives: Array<Record<string, unknown>>;
  export_text: string;
  empty_state_note?: string | null;
  market_listings?: Array<Record<string, unknown>>;
  market_warning?: string | null;
};

export type LaunchPackResult = {
  primary: LaunchPackVariant;
  variant_b?: LaunchPackVariant | null;
  comparison_note?: string | null;
  market_listings?: Array<Record<string, unknown>>;
  market_warning?: string | null;
};

export type SellerEconomics = {
  cost_of_goods?: string;
  target_margin_pct?: string;
  condition?: string;
  category?: string;
  competitor_links?: string;
};

export async function runPriceBargaining(
  body: {
    product_specs: string;
    price_range_min: string;
    price_range_max: string;
    currency?: string;
    location?: string;
    product_name?: string;
    problem_solved?: string;
  } & SellerEconomics,
): Promise<ModeResult> {
  const res = await fetch(`${getApiBase()}/api/modes/price-bargaining`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  return handle(res);
}

export async function runAudienceDiscovery(
  body: {
    product_name: string;
    problem_solved: string;
    location?: string;
    currency?: string;
    price_range_min?: string;
    price_range_max?: string;
    product_specs?: string;
  } & SellerEconomics,
): Promise<ModeResult> {
  const res = await fetch(`${getApiBase()}/api/modes/audience-discovery`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  return handle(res);
}

export async function runLaunchPack(
  body: {
    product_name: string;
    product_specs: string;
    problem_solved: string;
    price_range_min: string;
    price_range_max: string;
    currency?: string;
    location?: string;
    variant_b_name?: string;
    variant_b_specs?: string;
  } & SellerEconomics,
): Promise<LaunchPackResult> {
  const res = await fetch(`${getApiBase()}/api/modes/launch-pack`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  return handle(res);
}

export async function runDealFinder(body: {
  item_name: string;
  location: string;
  max_budget?: string;
  marketplace?: string;
  quantity?: number;
  buying_mode?: 'retail' | 'bulk';
}): Promise<ModeResult> {
  const res = await fetch(`${getApiBase()}/api/modes/deal-finder`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  return handle(res);
}
