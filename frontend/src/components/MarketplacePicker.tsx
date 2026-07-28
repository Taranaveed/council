import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/apiBase';

export type MarketplaceProfile = {
  slug: string;
  name: string;
  currency?: string | null;
  safety_guidelines: string;
  regulatory_notes: string;
  hint: string;
  sort_order: number;
};

type LocationContext = {
  currency?: string;
  trade_zone?: string;
  regulatory_focus?: string;
};

type Props = {
  location: string;
  countryCode?: string | null;
  value: string;
  onChange: (slug: string, profile?: MarketplaceProfile) => void;
  onContextChange?: (ctx: LocationContext | null) => void;
};

export function MarketplacePicker({
  location,
  countryCode,
  value,
  onChange,
  onContextChange,
}: Props) {
  const [options, setOptions] = useState<MarketplaceProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [context, setContext] = useState<LocationContext | null>(null);

  useEffect(() => {
    const trimmed = location.trim();
    if (trimmed.length < 2) {
      setOptions([]);
      setContext(null);
      onContextChange?.(null);
      return;
    }

    const token = localStorage.getItem('sf_token');
    if (!token) return;

    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({ location: trimmed });
        if (countryCode) params.set('country_code', countryCode.toUpperCase());

        const res = await fetch(`${getApiBase()}/api/marketplaces/by-location?${params}`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        if (!res.ok) {
          throw new Error(
            res.status === 401
              ? 'Your session ended — sign out and sign in again'
              : 'Couldn’t load shopping sites for this city',
          );
        }
        const data = await res.json();
        const list: MarketplaceProfile[] = data.marketplaces || [];
        setOptions(list);
        setContext(data.location_context || null);
        onContextChange?.(data.location_context || null);

        if (list.length && !list.some((m) => m.slug === value)) {
          onChange(list[0].slug, list[0]);
        }
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        setError(err instanceof Error ? err.message : 'Couldn’t load shopping sites');
        setOptions([]);
      } finally {
        setLoading(false);
      }
    }, 400);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location, countryCode]);

  const selected = options.find((o) => o.slug === value);

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-semibold text-[#3d4f6f]">Where to shop</p>
        {loading && <span className="text-[10px] text-[#3d4f6f]/70">Updating for your city…</span>}
      </div>

      {context?.trade_zone && (
        <p className="text-[11px] text-[#3d4f6f] mb-2 font-medium">
          Area: <span className="text-[#0b1b3a]">{context.trade_zone}</span>
          {context.currency ? (
            <>
              {' '}
              · Currency: <span className="text-[#0b1b3a]">{context.currency}</span>
            </>
          ) : null}
          {countryCode ? (
            <>
              {' '}
              · Country: <span className="text-[#0b1b3a]">{countryCode.toUpperCase()}</span>
            </>
          ) : null}
        </p>
      )}

      {error && <p className="text-xs text-[#ff5a5f] font-semibold mb-2">{error}</p>}

      {!loading && options.length === 0 && location.trim().length >= 2 && (
        <p className="text-xs text-[#3d4f6f] mb-2">Type a clearer city name to see shopping sites.</p>
      )}

      <div className="space-y-2">
        {options.map((opt) => {
          const isSelected = value === opt.slug;
          return (
            <button
              key={opt.slug}
              type="button"
              onClick={() => onChange(opt.slug, opt)}
              className={`w-full text-left border px-3 py-2.5 transition ${
                isSelected
                  ? 'border-[#5BA3D9]/50 bg-[#5BA3D9]/12 shadow-none'
                  : 'border-[rgba(11,27,58,0.1)] bg-white/60 hover:border-[rgba(11,27,58,0.22)]'
              }`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-[#0b1b3a]">{opt.name}</span>
                {opt.currency ? (
                  <span className="text-[10px] font-semibold text-[#3d4f6f] border border-[rgba(11,27,58,0.12)] px-1.5 py-0.5">
                    {opt.currency}
                  </span>
                ) : null}
              </span>
              <span className="block text-[11px] text-[#3d4f6f] mt-0.5 font-medium">{opt.hint}</span>
            </button>
          );
        })}
      </div>

      {selected?.safety_guidelines && (
        <p className="mt-2 text-[11px] text-[#9a5b00] leading-relaxed font-medium">
          {selected.safety_guidelines}
        </p>
      )}
    </div>
  );
}
