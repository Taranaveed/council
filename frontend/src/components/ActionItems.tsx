import { ExternalLink, ListChecks, MapPin } from 'lucide-react';

type Alternative = {
  vendor?: string;
  price?: string;
  note?: string;
};

type Props = {
  alternatives: Alternative[];
  location: string;
  itemName?: string;
};

/** Build a Google Maps search URL centered on the user's location. */
export function buildMapsSearchUrl(query: string, location: string): string {
  const place = (location || '').trim() || 'nearby';
  const q = `${query.trim()} near ${place}`.replace(/\s+/g, ' ');
  return `https://www.google.com/maps/search/${encodeURIComponent(q)}`;
}

const LINK_PATTERNS: Array<{ match: RegExp; queryFromMatch?: boolean; fallbackQuery: string }> = [
  {
    match: /authorized\s+([a-z0-9][\w.&+\- ]{0,40}?)\s+resellers?/i,
    queryFromMatch: true,
    fallbackQuery: 'Authorized retailer',
  },
  {
    match: /authorized\s+apple\s+resellers?/i,
    fallbackQuery: 'Authorized Apple retailer',
  },
  {
    match: /authorized\s+sony\s+resellers?/i,
    fallbackQuery: 'Authorized Sony retailer',
  },
  {
    match: /local\s+retailers?/i,
    fallbackQuery: 'electronics retailer',
  },
];

function textBlob(alt: Alternative): string {
  return [alt.vendor, alt.note, alt.price].filter(Boolean).join(' ');
}

function extractMapQuery(blob: string, itemName?: string): { label: string; query: string } | null {
  for (const pattern of LINK_PATTERNS) {
    const m = blob.match(pattern.match);
    if (!m) continue;

    if (pattern.queryFromMatch && m[1]) {
      const brand = m[1].trim();
      return {
        label: `Authorized ${brand} resellers`,
        query: `Authorized ${brand} retailer`,
      };
    }

    if (/local\s+retailers?/i.test(blob) && pattern.fallbackQuery === 'electronics retailer') {
      const product = (itemName || 'electronics').trim();
      return {
        label: 'Local retailers',
        query: `${product} store`,
      };
    }

    return {
      label: m[0].replace(/\s+/g, ' ').trim(),
      query: pattern.fallbackQuery,
    };
  }
  return null;
}

export function ActionItems({ alternatives, location, itemName }: Props) {
  const place = location.trim() || 'your area';
  const linkItems: Array<{ label: string; href: string; mapQuery: string }> = [];
  const seen = new Set<string>();

  for (const alt of alternatives) {
    const blob = textBlob(alt);
    const extracted = extractMapQuery(blob, itemName);
    if (!extracted || seen.has(extracted.label.toLowerCase())) continue;
    seen.add(extracted.label.toLowerCase());
    linkItems.push({
      label: extracted.label,
      mapQuery: extracted.query,
      href: buildMapsSearchUrl(extracted.query, place),
    });
  }

  const checklist = alternatives
    .filter((a) => a.vendor || a.note)
    .map((a) => ({
      title: a.vendor || 'Alternative',
      detail: [a.price, a.note].filter(Boolean).join(' · '),
    }));

  if (!linkItems.length && !checklist.length) return null;

  return (
    <div className="bright-panel border border-[rgba(26,29,33,0.1)] bg-white p-5">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <ListChecks className="w-4 h-4 text-[#0f766e]" aria-hidden />
          <h3 className="text-sm font-semibold text-[#1a1d21]">
            Next steps
          </h3>
        </div>
        <span className="text-[11px] text-[#5c6570] font-medium flex items-center gap-1">
          <MapPin className="w-3 h-3" aria-hidden />
          Near {place}
        </span>
      </div>

      <ul className="space-y-2.5">
        {checklist.map((item, i) => (
          <li key={`c-${i}`} className="text-sm text-[#1a1d21] flex gap-2 font-medium">
            <span className="text-[#0f766e]">•</span>
            <span>
              <span className="font-semibold">{item.title}</span>
              {item.detail ? <span className="text-[#5c6570]"> — {item.detail}</span> : null}
            </span>
          </li>
        ))}
      </ul>

      {linkItems.length > 0 && (
        <div className="mt-4 pt-4 border-t border-[rgba(26,29,33,0.1)] space-y-2">
          <p className="text-xs text-[#5c6570] uppercase tracking-wide font-semibold flex items-center gap-1.5">
            <MapPin className="w-3.5 h-3.5" aria-hidden />
            Map search (your location)
          </p>
          {linkItems.map((item) => (
            <a
              key={item.label}
              href={item.href}
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-between gap-3 border border-[rgba(15,118,110,0.25)] bg-[rgba(15,118,110,0.06)] px-3 py-2.5 text-sm text-[#0a5c56] hover:bg-[rgba(15,118,110,0.1)] transition font-medium"
            >
              <span>
                Open map for <strong className="text-[#1a1d21]">{item.label}</strong>
                <span className="block text-[11px] text-[#5c6570] mt-0.5">
                  Google Maps · {item.mapQuery} near {place}
                </span>
              </span>
              <ExternalLink className="w-4 h-4 flex-shrink-0" aria-hidden />
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
