/** Client-side mirror of backend vague-query detection for UX before submit. */

const VAGUE = new Set([
  'mist', 'mists', 'spray', 'perfume', 'cream', 'oil', 'soap', 'bag', 'shirt',
  'shoes', 'phone', 'cover', 'case', 'mug', 'bottle', 'watch', 'light', 'lamp',
  'chair', 'table', 'toy', 'kit', 'gift', 'set', 'pack', 'product', 'item',
]);

const SUGGEST: Record<string, string> = {
  mist: 'body mist 100ml wholesale',
  mists: 'body mist 100ml wholesale',
  spray: 'body spray fragrance wholesale',
  perfume: 'perfume body mist wholesale',
  cover: 'phone cover wholesale',
  case: 'phone case wholesale',
  mug: 'ceramic mug wholesale',
  handsfree: 'handsfree earphones wholesale',
  handfree: 'handsfree earphones wholesale',
};

const AUDIO_PRODUCT =
  /\b(earbuds?|earphones?|headphones?|headset|wired|wireless|bluetooth|tws)\b/i;

const ADAPTER_AMBIGUOUS: Record<string, { suggestion: string; options: string[] }> = {
  'mobile adapters': {
    suggestion: 'USB wall charger adapter wholesale',
    options: [
      'USB wall charger adapter wholesale',
      'OTG USB-C adapter wholesale',
      '3.5mm headphone jack adapter wholesale',
      'SIM card adapter wholesale',
    ],
  },
  'mobile adapter': {
    suggestion: 'USB wall charger adapter wholesale',
    options: [
      'USB wall charger adapter wholesale',
      'OTG USB-C adapter wholesale',
      '3.5mm headphone jack adapter wholesale',
      'SIM card adapter wholesale',
    ],
  },
  'usb wall mobile adapters': {
    suggestion: 'USB wall charger adapter wholesale',
    options: [
      'USB wall charger adapter wholesale',
      'OTG USB-C adapter wholesale',
      'USB-C car charger wholesale',
    ],
  },
  adapters: {
    suggestion: 'USB wall charger adapter wholesale',
    options: [
      'USB wall charger adapter wholesale',
      'OTG USB-C adapter wholesale',
      'travel plug adapter wholesale',
    ],
  },
};

function normKey(s: string): string {
  return s.trim().toLowerCase().replace(/\s+/g, ' ');
}

export function clientQueryHint(
  itemName: string,
): { vague: boolean; suggestion: string; options?: string[] } | null {
  const raw = itemName.trim();
  const normalized = raw
    .replace(/\bhand[\s-]*frees?\b/gi, 'handsfree')
    .replace(/\bhands[\s-]*frees?\b/gi, 'handsfree')
    .replace(/\bhandsfrees?\b/gi, 'handsfree');
  const keyFull = normKey(normalized);
  const ambiguous = ADAPTER_AMBIGUOUS[keyFull];
  if (ambiguous) {
    return { vague: true, suggestion: ambiguous.suggestion, options: ambiguous.options };
  }
  if (/^(mobile|phone)\s+adapters?$/.test(keyFull)) {
    return {
      vague: true,
      suggestion: 'USB wall charger adapter wholesale',
      options: ADAPTER_AMBIGUOUS['mobile adapters'].options,
    };
  }
  // "usb wall mobile adapters" / similar phone-heavy adapter queries
  if (
    /\bmobile\b/.test(keyFull) &&
    /\badapters?\b/.test(keyFull) &&
    !/\b(charger|otg|wall\s*charger|type-?c|lightning|sim)\b/.test(keyFull)
  ) {
    return {
      vague: true,
      suggestion: 'USB wall charger adapter wholesale',
      options: ADAPTER_AMBIGUOUS['usb wall mobile adapters'].options,
    };
  }

  const tokens = normalized.split(/\s+/).filter(Boolean);
  if (!tokens.length) return null;
  const key = tokens[0].toLowerCase().replace(/[^a-z]/g, '');

  if (/\bhandsfree\b/i.test(normalized) && AUDIO_PRODUCT.test(normalized) && tokens.length >= 2) {
    return null;
  }

  let suggestion: string | null = null;
  if (tokens.length === 1 && (VAGUE.has(key) || key.length <= 4 || key === 'handsfree')) {
    suggestion = SUGGEST[key] || `${raw} wholesale pack size`;
  } else if (/\bhandsfree\b/i.test(normalized) && !AUDIO_PRODUCT.test(normalized)) {
    suggestion = 'handsfree earphones wholesale';
  } else if (tokens.length === 2 && /\bbody mists?\b/i.test(raw)) {
    suggestion = 'body mist 100ml floral wholesale';
  }

  if (!suggestion) return null;
  if (normKey(suggestion) === normKey(raw) || normKey(suggestion) === normKey(normalized)) {
    return null;
  }
  return { vague: true, suggestion };
}
