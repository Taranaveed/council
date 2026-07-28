/**
 * Local / regional synonym expansion so searches match how people actually shop.
 */

const SYNONYM_GROUPS = [
  {
    trigger: /\bpashmina\b/i,
    extras: ["kashmiri shawl", "soft shawl", "pashmina shawl"],
  },
  {
    trigger: /\b(shawl|stole)\b/i,
    extras: ["pashmina", "kashmiri shawl"],
    requireAlso: /\b(handmade|kashmir|cashmere|wool|silk)\b/i,
  },
  {
    trigger: /\bcashmere\b/i,
    extras: ["cashmere shawl", "soft wool shawl"],
  },
  {
    // Only expand bare leather goods — not phone covers (that pulls craft leather junk)
    trigger: /\bleather\b/i,
    extras: ["genuine leather"],
    skipIf: /\b(cover|covers|case|cases|phone|mobile|jacket|bag|wallet)\b/i,
  },
  {
    trigger: /\b(cover|covers)\b/i,
    extras: ["leather phone cover", "phone cover"],
    requireAlso: /\bleather\b/i,
  },
  {
    trigger: /\b(case|cases)\b/i,
    extras: ["leather phone case", "phone case"],
    requireAlso: /\bleather\b/i,
  },
  {
    trigger: /\bearbuds?\b/i,
    extras: ["wireless earbuds", "tws earbuds"],
  },
  {
    trigger: /\b(iphone|samsung)\b/i,
    extras: [],
  },
];

/**
 * Return extra search phrases derived from the product name (not including the base itself).
 */
export function expandSearchSynonyms(productName, { max = 2 } = {}) {
  const raw = String(productName || "").trim();
  if (!raw) return [];
  const lower = raw.toLowerCase();
  const out = [];
  const seen = new Set([lower]);

  for (const group of SYNONYM_GROUPS) {
    if (!group.trigger.test(raw)) continue;
    if (group.requireAlso && !group.requireAlso.test(raw)) continue;
    if (group.skipIf && group.skipIf.test(raw)) continue;
    for (const extra of group.extras || []) {
      const phrase = String(extra).trim();
      if (!phrase) continue;
      const key = phrase.toLowerCase();
      if (seen.has(key)) continue;
      // Skip if already fully contained in the original query
      if (lower.includes(key)) continue;
      seen.add(key);
      out.push(phrase);
      if (out.length >= max) return out;
    }
  }
  return out;
}
