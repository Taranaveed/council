/**
 * Extract warranty text, policy links, price confirmation, and variants from product HTML.
 */

const POLICY_HREF_RE =
  /href=["']([^"']*(?:refund|return|warranty|shipping|privacy|terms|policy)[^"']*)["']/gi;

const WARRANTY_BLOB_RE =
  /(?:warranty|guarantee|return\s+policy|refund\s+policy|money[- ]back)[^.<]{0,200}[.<]/gi;

const VARIANT_OPTION_RE =
  /<(?:option|span|button|label)[^>]*(?:variant|option|swatch|size|color|colour)[^>]*>\s*([^<]{1,60})\s*</gi;

const JSON_VARIANT_RE =
  /"title"\s*:\s*"([^"]{1,80})"\s*,\s*"price"\s*:\s*"?([\d.]+)"?/gi;

function cleanText(raw) {
  return String(raw || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function absolutize(href, baseUrl) {
  const h = String(href || "").trim();
  if (!h || h.startsWith("#") || h.startsWith("javascript:")) return null;
  try {
    return new URL(h, baseUrl).href;
  } catch {
    return null;
  }
}

/**
 * @returns {{
 *   warranty_text: string|null,
 *   policy_links: Array<{label:string,url:string}>,
 *   variants: Array<{label:string,price?:string}>,
 *   page_price_raw: string|null,
 * }}
 */
export function extractPageFacts(html, { url = "", pagePrice = null } = {}) {
  const src = String(html || "");
  if (!src) {
    return {
      warranty_text: null,
      policy_links: [],
      variants: [],
      page_price_raw: pagePrice || null,
    };
  }

  // Policy footer / nav links
  const policy_links = [];
  const seenHref = new Set();
  for (const m of src.matchAll(POLICY_HREF_RE)) {
    const abs = absolutize(m[1], url);
    if (!abs || seenHref.has(abs)) continue;
    seenHref.add(abs);
    const path = abs.toLowerCase();
    let label = "policy";
    if (/refund|return/.test(path)) label = "refund_or_return";
    else if (/warrant/.test(path)) label = "warranty";
    else if (/ship/.test(path)) label = "shipping";
    else if (/privacy/.test(path)) label = "privacy";
    else if (/terms/.test(path)) label = "terms";
    policy_links.push({ label, url: abs });
    if (policy_links.length >= 8) break;
  }

  // Warranty / return prose near keywords
  let warranty_text = null;
  const hits = [...src.matchAll(WARRANTY_BLOB_RE)].map((m) => cleanText(m[0]));
  const meaningful = hits.filter((t) => t.length >= 20 && t.length <= 280);
  if (meaningful.length) {
    warranty_text = meaningful[0];
  } else if (policy_links.some((p) => /refund|return|warranty/.test(p.label))) {
    warranty_text = `Policy link found: ${policy_links.find((p) => /refund|return|warranty/.test(p.label)).url}`;
  }

  // Variants from Shopify-ish JSON + option labels
  const variants = [];
  const seenVar = new Set();
  for (const m of src.matchAll(JSON_VARIANT_RE)) {
    const label = cleanText(m[1]);
    if (!label || seenVar.has(label.toLowerCase())) continue;
    seenVar.add(label.toLowerCase());
    variants.push({ label, price: m[2] ? String(m[2]) : undefined });
    if (variants.length >= 12) break;
  }
  if (variants.length < 4) {
    for (const m of src.matchAll(VARIANT_OPTION_RE)) {
      const label = cleanText(m[1]);
      if (!label || label.length < 2 || seenVar.has(label.toLowerCase())) continue;
      if (/select|choose|option/i.test(label)) continue;
      seenVar.add(label.toLowerCase());
      variants.push({ label });
      if (variants.length >= 12) break;
    }
  }

  return {
    warranty_text,
    policy_links,
    variants,
    page_price_raw: pagePrice || null,
  };
}

/**
 * Merge page facts onto a listing row.
 */
export function applyPageFacts(listing, facts, { html = "" } = {}) {
  const row = { ...(listing || {}) };
  if (!facts) return row;
  row.page_facts_fetched = true;
  if (facts.warranty_text) {
    row.warranty = facts.warranty_text;
    row.warranty_source = "page";
  } else if (html) {
    row.warranty = null;
    row.warranty_source = "page_checked_absent";
  }
  if (Array.isArray(facts.policy_links) && facts.policy_links.length) {
    row.policy_links = facts.policy_links;
    row.policy_links_source = "page";
  } else if (html) {
    row.policy_links = [];
    row.policy_links_source = "page_checked_absent";
  }
  if (Array.isArray(facts.variants) && facts.variants.length) {
    row.variants = facts.variants;
    row.variants_source = "page";
  }
  if (facts.page_price_raw && (!row.price || /^(see listing)/i.test(String(row.price)))) {
    row.price = facts.page_price_raw;
    row.price_source = "page";
  }
  return row;
}
