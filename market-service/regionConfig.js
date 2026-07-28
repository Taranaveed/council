/**
 * Regional defaults for global launches.
 * Override via env — never hardcode a single country for production.
 *
 * DEFAULT_REGION: logical region label (us | eu | uk | asia | pk | ...)
 * DEFAULT_COUNTRY_CODE: country code used for locale (us, uk, pk, fr, de, ...)
 * DEFAULT_LANGUAGE: SerpApi `hl` (en, fr, ...)
 * DEFAULT_LOCATION: fallback search location when body.location is empty
 *
 * Note: Google Shopping (`engine=google_shopping`) only supports a subset of
 * countries. Pakistan (`pk`) and several others are NOT supported — those
 * searches fall back to regular Google Search (`engine=google`).
 * See: https://serpapi.com/google-shopping-countries
 */
const DEFAULT_REGION = (process.env.DEFAULT_REGION || "us").toLowerCase();
const DEFAULT_COUNTRY_CODE = (process.env.DEFAULT_COUNTRY_CODE || "us").toLowerCase();
const DEFAULT_LANGUAGE = process.env.DEFAULT_LANGUAGE || "en";
const DEFAULT_LOCATION = process.env.DEFAULT_LOCATION || "United States";

/** Map free-text location → country code */
const LOCATION_TO_GL = [
  { match: /\b(pakistan|lahore|karachi|islamabad|rawalpindi|faisalabad|multan|peshawar)\b/i, gl: "pk" },
  { match: /\b(united kingdom|england|scotland|wales|london|manchester|edinburgh|uk)\b/i, gl: "uk" },
  { match: /\b(united states|usa|new york|california|texas|chicago|seattle|los angeles)\b/i, gl: "us" },
  { match: /\b(france|paris|lyon|marseille)\b/i, gl: "fr" },
  { match: /\b(germany|berlin|munich|hamburg)\b/i, gl: "de" },
  { match: /\b(canada|toronto|vancouver)\b/i, gl: "ca" },
  { match: /\b(india|mumbai|delhi|bangalore)\b/i, gl: "in" },
  { match: /\b(uae|dubai|abu dhabi)\b/i, gl: "ae" },
  { match: /\b(singapore)\b/i, gl: "sg" },
  { match: /\b(netherlands|amsterdam)\b/i, gl: "nl" },
  { match: /\b(spain|madrid|barcelona)\b/i, gl: "es" },
  { match: /\b(italy|rome|milan)\b/i, gl: "it" },
  { match: /\b(ireland|dublin)\b/i, gl: "ie" },
];

const REGION_TO_GL = {
  us: "us",
  eu: "de",
  uk: "uk",
  asia: "sg",
  pk: "pk",
  pakistan: "pk",
};

/** Canonical SerpApi `location` strings (must match their locations list). */
const CITY_TO_SERP_LOCATION = [
  { match: /\blahore\b/i, location: "Lahore,Punjab,Pakistan", gl: "pk" },
  { match: /\bkarachi\b/i, location: "Karachi,Sindh,Pakistan", gl: "pk" },
  { match: /\bislamabad\b/i, location: "Islamabad,Islamabad Capital Territory,Pakistan", gl: "pk" },
  { match: /\brawalpindi\b/i, location: "Rawalpindi,Punjab,Pakistan", gl: "pk" },
  { match: /\bfaisalabad\b/i, location: "Faisalabad,Punjab,Pakistan", gl: "pk" },
  { match: /\bmultan\b/i, location: "Multan,Punjab,Pakistan", gl: "pk" },
  { match: /\bpeshawar\b/i, location: "Peshawar,Khyber Pakhtunkhwa,Pakistan", gl: "pk" },
  { match: /\bmumbai\b/i, location: "Mumbai,Maharashtra,India", gl: "in" },
  { match: /\bdelhi\b/i, location: "Delhi,India", gl: "in" },
  { match: /\bbangalore\b|\bbengaluru\b/i, location: "Bengaluru,Karnataka,India", gl: "in" },
  { match: /\blondon\b/i, location: "London,England,United Kingdom", gl: "uk" },
  { match: /\bmanchester\b/i, location: "Manchester,England,United Kingdom", gl: "uk" },
  { match: /\bnew york\b/i, location: "New York,New York,United States", gl: "us" },
  { match: /\blos angeles\b/i, location: "Los Angeles,California,United States", gl: "us" },
  { match: /\bchicago\b/i, location: "Chicago,Illinois,United States", gl: "us" },
  { match: /\bparis\b/i, location: "Paris,Ile-de-France,France", gl: "fr" },
  { match: /\bberlin\b/i, location: "Berlin,Germany", gl: "de" },
  { match: /\btoronto\b/i, location: "Toronto,Ontario,Canada", gl: "ca" },
  { match: /\bdubai\b/i, location: "Dubai,United Arab Emirates", gl: "ae" },
  { match: /\bsingapore\b/i, location: "Singapore", gl: "sg" },
];

const GL_TO_COUNTRY_LOCATION = {
  pk: "Pakistan",
  in: "India",
  us: "United States",
  uk: "United Kingdom",
  gb: "United Kingdom",
  ca: "Canada",
  fr: "France",
  de: "Germany",
  ae: "United Arab Emirates",
  sg: "Singapore",
  au: "Australia",
  nl: "Netherlands",
  es: "Spain",
  it: "Italy",
  ie: "Ireland",
};

/**
 * SerpApi only accepts known location names — not free text like
 * "Lahore, karachi, PAkistan". Normalize to one canonical place.
 */
export function normalizeSerpLocation(rawLocation, gl) {
  const text = String(rawLocation || "").trim();
  const code = String(gl || "").toLowerCase();

  if (text) {
    for (const row of CITY_TO_SERP_LOCATION) {
      if (row.match.test(text)) {
        return { location: row.location, gl: row.gl || code };
      }
    }

    for (const [g, name] of Object.entries(GL_TO_COUNTRY_LOCATION)) {
      if (new RegExp(`\\b${name.replace(/\s+/g, "\\s+")}\\b`, "i").test(text)) {
        return { location: name, gl: g };
      }
    }
  }

  const fallback = GL_TO_COUNTRY_LOCATION[code] || DEFAULT_LOCATION;
  return { location: fallback, gl: code || DEFAULT_COUNTRY_CODE };
}

export function isUnsupportedLocationError(detail) {
  return /unsupported\s+.+location\s*-\s*location/i.test(String(detail || ""));
}

/**
 * Google Shopping `gl` allowlist (SerpApi / Google Shopping countries).
 * Anything outside this set must use engine=google instead.
 */
export const GOOGLE_SHOPPING_GL = new Set([
  "ai", "ar", "aw", "au", "at", "be", "bm", "br", "io", "ca", "ky", "cl", "cx",
  "cc", "co", "cz", "dk", "fk", "fi", "fr", "gf", "pf", "tf", "de", "gr", "gp",
  "hm", "hk", "hu", "in", "id", "ie", "il", "it", "jp", "kr", "my", "mq", "yt",
  "mx", "ms", "nl", "nc", "nz", "nf", "no", "ph", "pl", "pt", "re", "ro", "ru",
  "pm", "sa", "sg", "sk", "za", "gs", "es", "se", "ch", "tw", "th", "tk", "tr",
  "tc", "ua", "ae", "uk", "gb", "us", "vn", "vg", "wf",
]);

export function isShoppingGlSupported(gl) {
  return GOOGLE_SHOPPING_GL.has(String(gl || "").toLowerCase());
}

export function resolveSearchLocale({ location, countryCode } = {}) {
  const loc = (location || "").trim();
  let gl = (countryCode || "").trim().toLowerCase();

  if (!gl && loc) {
    for (const row of LOCATION_TO_GL) {
      if (row.match.test(loc)) {
        gl = row.gl;
        break;
      }
    }
  }

  if (!gl) {
    gl = REGION_TO_GL[DEFAULT_REGION] || DEFAULT_COUNTRY_CODE;
  }

  const normalized = normalizeSerpLocation(loc || DEFAULT_LOCATION, gl);
  gl = normalized.gl || gl;
  const shoppingSupported = isShoppingGlSupported(gl);

  return {
    // Human label from the user (for query text / UI)
    locationLabel: loc || normalized.location,
    // SerpApi-safe location string
    location: normalized.location,
    gl,
    hl: DEFAULT_LANGUAGE,
    defaultRegion: DEFAULT_REGION,
    shoppingSupported,
    engine: shoppingSupported ? "google_shopping" : "google",
  };
}

export function getRegionConfig() {
  return {
    DEFAULT_REGION,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_LANGUAGE,
    DEFAULT_LOCATION,
  };
}
