/**
 * RegionProfile loader — shared JSON under shared/region_profiles/.
 * Pakistan (pk / region_pk_v1) is the golden regression fixture.
 * Shopping for pk stays unsupported.
 * Unsupported countries throw — no silent UK/PK fallback.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROFILES_DIR =
  process.env.REGION_PROFILES_DIR ||
  path.resolve(__dirname, "../shared/region_profiles");

export const TRADE_ZONES = Object.freeze(["UK", "EU", "US", "PK", "EFTA-CH", "EFTA-NO"]);
export const SUPPORTED_PROFILE_IDS = Object.freeze(["pk", "uk"]);

const CODE_ALIASES = {
  pk: "pk",
  pakistan: "pk",
  uk: "uk",
  gb: "uk",
  us: "us",
  usa: "us",
  in: "in",
  india: "in",
  eu: "eu",
  de: "eu",
  fr: "eu",
  "efta-ch": "efta-ch",
  ch: "efta-ch",
  "efta-no": "efta-no",
  no: "efta-no",
};

const cache = new Map();

export class RegionNotSupportedError extends Error {
  constructor(profileId) {
    const id = String(profileId || "unknown").toLowerCase();
    super(
      `Region not supported: '${id}'. Supported regions: ${SUPPORTED_PROFILE_IDS.join(", ")}.`,
    );
    this.name = "RegionNotSupportedError";
    this.profileId = id;
    this.code = "region_not_supported";
  }
}

export function profilesDir() {
  return PROFILES_DIR;
}

export function profileAvailable(profileId) {
  const pid = CODE_ALIASES[String(profileId || "").toLowerCase()] || String(profileId || "").toLowerCase();
  return fs.existsSync(path.join(PROFILES_DIR, `${pid}.json`));
}

export function loadProfile(profileId) {
  const pid = CODE_ALIASES[String(profileId || "").toLowerCase()] || String(profileId || "").toLowerCase();
  if (cache.has(pid)) return cache.get(pid);
  const file = path.join(PROFILES_DIR, `${pid}.json`);
  if (!fs.existsSync(file)) {
    throw new RegionNotSupportedError(pid);
  }
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  if (data.trade_zone && !TRADE_ZONES.includes(data.trade_zone)) {
    throw new Error(`Invalid trade_zone ${data.trade_zone}`);
  }
  cache.set(pid, data);
  return data;
}

export function resolveProfileId({ location, countryCode, currency } = {}) {
  const code = String(countryCode || "").trim().toLowerCase();
  if (code) return CODE_ALIASES[code] || code;
  const loc = String(location || "");
  if (/\b(pakistan|lahore|karachi|islamabad|rawalpindi|faisalabad|multan|peshawar)\b/i.test(loc)) {
    return "pk";
  }
  if (/\b(united kingdom|england|scotland|wales|london|manchester|edinburgh|birmingham|glasgow|uk)\b/i.test(loc)) {
    return "uk";
  }
  if (/\b(united states|usa|new york|california|texas)\b/i.test(loc)) return "us";
  if (/\b(india|mumbai|delhi|bangalore)\b/i.test(loc)) return "in";
  const cur = String(currency || "").toUpperCase();
  if (cur === "PKR") return "pk";
  if (cur === "GBP") return "uk";
  if (cur === "USD") return "us";
  const env = String(process.env.DEFAULT_REGION || process.env.DEFAULT_COUNTRY_CODE || "uk").toLowerCase();
  return CODE_ALIASES[env] || env || "uk";
}

export function getProfile(opts = {}) {
  const id = opts.profileId || resolveProfileId(opts);
  return loadProfile(id);
}

export function localHostRegex(profile) {
  const parts = (profile?.local_host_patterns || []).filter(Boolean);
  if (!parts.length) return /a^/;
  return new RegExp(parts.map((p) => `(?:${p})`).join("|"), "i");
}

export function isLocalHost(urlOrHost, profile) {
  return localHostRegex(profile).test(String(urlOrHost || ""));
}

/** Golden PK parity — throw if frozen rates drift. */
export function assertPkGoldenParity() {
  const pk = loadProfile("pk");
  if (pk.version !== "region_pk_v1") throw new Error("pk version drift");
  if (pk.trade_zone !== "PK") throw new Error("pk trade_zone drift");
  if (pk.currency !== "PKR") throw new Error("pk currency drift");
  if (pk.serp?.shopping_gl_supported !== false) throw new Error("pk shopping must stay off");
  if (pk.serp?.preferred_engine !== "google") throw new Error("pk engine drift");
  if (Math.abs(Number(pk.fx_to_usd_fallback) - 1 / 278) > 1e-12) throw new Error("pk FX drift");
  if (Number(pk.sales_tax?.rate) !== 0.18) throw new Error("pk sales_tax drift");
  if (Number(pk.duty?.fallback?.rate_mid) !== 0.25) throw new Error("pk duty drift");
  if (Number(pk.shipping_flat_local?.amount) !== 8500) throw new Error("pk flat ship drift");
  if (Number(pk.min_plausible_price_retail) !== 1000) throw new Error("pk retail floor drift");
  if (Number(pk.min_plausible_price_bulk) !== 150) throw new Error("pk bulk floor drift");
  return pk;
}
