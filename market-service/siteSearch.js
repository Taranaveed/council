/**
 * Location-aware marketplace site: queries to find same-product seller pages.
 */

const ELECTRONICS_RE =
  /\b(earbuds?|earphones?|headphones?|phone|iphone|samsung|laptop|tablet|watch|smartwatch|charger|powerbank|camera|keyboard|mouse|monitor|tv|router|console|speaker)\b/i;

const FASHION_RE =
  /\b(pashmina|shawl|scarf|stole|dupatta|jacket|coat|bag|backpack|wallet|belt|purse|handbag|dress|kurta|saree|sweater|hoodie|leather|cashmere|silk|wool|handmade)\b/i;

const SITES_BY_GL = {
  pk: {
    fashion: [
      { host: "daraz.pk", vendor: "Daraz" },
      { host: "olx.com.pk", vendor: "OLX" },
      { host: "homeshopping.pk", vendor: "HomeShopping" },
      { host: "shophive.com", vendor: "Shophive" },
    ],
    electronics: [
      { host: "priceoye.pk", vendor: "Priceoye" },
      { host: "daraz.pk", vendor: "Daraz" },
      { host: "telemart.pk", vendor: "Telemart" },
      { host: "shophive.com", vendor: "Shophive" },
      { host: "homeshopping.pk", vendor: "HomeShopping" },
      { host: "olx.com.pk", vendor: "OLX" },
    ],
    default: [
      { host: "daraz.pk", vendor: "Daraz" },
      { host: "olx.com.pk", vendor: "OLX" },
      { host: "homeshopping.pk", vendor: "HomeShopping" },
      { host: "priceoye.pk", vendor: "Priceoye" },
      { host: "telemart.pk", vendor: "Telemart" },
      { host: "shophive.com", vendor: "Shophive" },
    ],
  },
  in: [
    { host: "amazon.in", vendor: "Amazon.in" },
    { host: "flipkart.com", vendor: "Flipkart" },
    { host: "indiamart.com", vendor: "IndiaMART" },
  ],
  us: [
    { host: "amazon.com", vendor: "Amazon" },
    { host: "bestbuy.com", vendor: "Best Buy" },
    { host: "walmart.com", vendor: "Walmart" },
    { host: "ebay.com", vendor: "eBay" },
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
  if (ELECTRONICS_RE.test(q)) return "electronics";
  if (FASHION_RE.test(q)) return "fashion";
  return "default";
}

export function marketplaceSitesForGl(gl, productName = "") {
  const key = String(gl || "").toLowerCase();
  const entry = SITES_BY_GL[key] || SITES_BY_GL.default;
  if (Array.isArray(entry)) return entry;
  const cat = categoryForQuery(productName);
  return entry[cat] || entry.default || SITES_BY_GL.default;
}

export function siteSearchQueries(productName, gl, maxSites = 3) {
  const q = String(productName || "").trim();
  if (!q) return [];
  const code = String(gl || "").toLowerCase();
  // Pull more local shop sites when Google Shopping is weak for this country
  const sites = Math.max(maxSites, code === "pk" ? 5 : maxSites);
  return marketplaceSitesForGl(gl, q)
    .slice(0, sites)
    .map((site) => ({
      ...site,
      query: `${q} site:${site.host}`,
    }));
}
