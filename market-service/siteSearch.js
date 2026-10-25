/**
 * Location-aware marketplace site: queries to find same-product seller pages.
 */

import { pickSuppliersForGl } from "./wholesaleSuppliers.js";

const ELECTRONICS_RE =
  /\b(earbuds?|earphones?|headphones?|phone|iphone|samsung|laptop|tablet|watch|smartwatch|charger|powerbank|camera|keyboard|mouse|monitor|tv|router|console|speaker|cover|covers|case|cases)\b/i;

const FASHION_RE =
  /\b(pashmina|shawl|scarf|stole|dupatta|jacket|coat|bag|backpack|wallet|belt|purse|handbag|dress|kurta|saree|sweater|hoodie|leather|cashmere|silk|wool|handmade)\b/i;

const JEWELRY_RE =
  /\b(rings?|jewellery|jewelry|necklace|bracelet|earring|earrings|pendant|silver|gold|zircon)\b/i;

const SITES_BY_GL = {
  pk: {
    jewelry: [
      { host: "daraz.pk", vendor: "Daraz" },
      { host: "tjwholesale.pk", vendor: "TJ Wholesale" },
      { host: "abwholesale.pk", vendor: "AB Wholesale" },
      { host: "imwholesale.pk", vendor: "IM Wholesale" },
      { host: "meerzah.pk", vendor: "Meerzah" },
      { host: "laam.com", vendor: "LAAM" },
      { host: "olx.com.pk", vendor: "OLX" },
    ],
    fashion: [
      { host: "daraz.pk", vendor: "Daraz" },
      { host: "olx.com.pk", vendor: "OLX" },
      { host: "laam.com", vendor: "LAAM" },
      { host: "homeshopping.pk", vendor: "HomeShopping" },
      { host: "shophive.com", vendor: "Shophive" },
      { host: "mega.pk", vendor: "Mega.pk" },
    ],
    electronics: [
      { host: "priceoye.pk", vendor: "Priceoye" },
      { host: "daraz.pk", vendor: "Daraz" },
      { host: "telemart.pk", vendor: "Telemart" },
      { host: "shophive.com", vendor: "Shophive" },
      { host: "homeshopping.pk", vendor: "HomeShopping" },
      { host: "olx.com.pk", vendor: "OLX" },
      { host: "symbios.pk", vendor: "Symbios" },
    ],
    default: [
      { host: "daraz.pk", vendor: "Daraz" },
      { host: "olx.com.pk", vendor: "OLX" },
      { host: "homeshopping.pk", vendor: "HomeShopping" },
      { host: "priceoye.pk", vendor: "Priceoye" },
      { host: "telemart.pk", vendor: "Telemart" },
      { host: "shophive.com", vendor: "Shophive" },
      { host: "mega.pk", vendor: "Mega.pk" },
    ],
  },
  in: [
    { host: "amazon.in", vendor: "Amazon.in" },
    { host: "flipkart.com", vendor: "Flipkart" },
    { host: "indiamart.com", vendor: "IndiaMART" },
    { host: "meesho.com", vendor: "Meesho" },
  ],
  us: [
    { host: "amazon.com", vendor: "Amazon" },
    { host: "bestbuy.com", vendor: "Best Buy" },
    { host: "walmart.com", vendor: "Walmart" },
    { host: "ebay.com", vendor: "eBay" },
    { host: "target.com", vendor: "Target" },
    { host: "costco.com", vendor: "Costco" },
  ],
  uk: [
    { host: "amazon.co.uk", vendor: "Amazon UK" },
    { host: "ebay.co.uk", vendor: "eBay UK" },
    { host: "argos.co.uk", vendor: "Argos" },
  ],
  gb: [
    { host: "amazon.co.uk", vendor: "Amazon UK" },
    { host: "ebay.co.uk", vendor: "eBay UK" },
    { host: "argos.co.uk", vendor: "Argos" },
  ],
  ae: [
    { host: "amazon.ae", vendor: "Amazon.ae" },
    { host: "noon.com", vendor: "Noon" },
  ],
  ca: [
    { host: "amazon.ca", vendor: "Amazon.ca" },
    { host: "bestbuy.ca", vendor: "Best Buy CA" },
  ],
  default: [
    { host: "amazon.com", vendor: "Amazon" },
    { host: "ebay.com", vendor: "eBay" },
  ],
};

function categoryForQuery(productName) {
  const q = String(productName || "");
  if (JEWELRY_RE.test(q)) return "jewelry";
  if (ELECTRONICS_RE.test(q)) return "electronics";
  if (FASHION_RE.test(q)) return "fashion";
  return "default";
}

export function marketplaceSitesForGl(gl, productName = "", { bulkMode = false } = {}) {
  const key = String(gl || "").toLowerCase();
  const entry = SITES_BY_GL[key] || SITES_BY_GL.default;
  let sites = Array.isArray(entry) ? [...entry] : [...(entry[categoryForQuery(productName)] || entry.default || SITES_BY_GL.default)];
  if (bulkMode) {
    // Local shops only — global wholesale hosts are covered by fetchWholesaleSupplierListings
    // (avoid double SerpApi site:alibaba / indiamart / made-in-china passes).
    const wholesale = pickSuppliersForGl(key, { max: 5 }).map((s) => s.host);
    const wholesaleHosts = new Set(wholesale);
    sites = sites.filter((s) => !wholesaleHosts.has(s.host));
  }
  return sites;
}

export function siteSearchQueries(productName, gl, maxSites = 3, { bulkMode = false } = {}) {
  const q = String(productName || "").trim();
  if (!q) return [];
  const code = String(gl || "").toLowerCase();
  // Bulk: still probe several local shops — wholesale factories alone are not enough
  const floor = bulkMode ? (code === "pk" ? 4 : 3) : code === "pk" ? 5 : 3;
  const sites = Math.max(maxSites, floor);
  return marketplaceSitesForGl(gl, q, { bulkMode })
    .slice(0, sites)
    .map((site) => ({
      ...site,
      query: `${q} site:${site.host}`,
    }));
}
