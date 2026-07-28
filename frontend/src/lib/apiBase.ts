/**
 * Resolve API base URL for nearest region (CDN / multi-region edge).
 * In production, put Cloudflare (or similar) in front and set regional origins:
 *   VITE_API_URL_US, VITE_API_URL_EU, VITE_API_URL_ASIA
 * Locally falls back to VITE_API_URL / localhost.
 */

const REGION_ENV: Record<string, string | undefined> = {
  us: import.meta.env.VITE_API_URL_US,
  eu: import.meta.env.VITE_API_URL_EU,
  asia: import.meta.env.VITE_API_URL_ASIA,
};

function cleanBase(url: unknown): string {
  return String(url ?? '')
    .trim()
    .replace(/\/+$/, '');
}

const DEFAULT_API = cleanBase(import.meta.env.VITE_API_URL) || 'http://localhost:8000';

let cachedBase: string | null = null;
let cachedRegion: string | null = null;

export function getApiBase(): string {
  return cachedBase || DEFAULT_API;
}

export function getApiRegion(): string | null {
  return cachedRegion;
}

export function setApiRegion(region: string | null | undefined) {
  const key = (region || '').toLowerCase();
  cachedRegion = key || null;
  const regional = key ? cleanBase(REGION_ENV[key]) : '';
  cachedBase = regional || DEFAULT_API;
  return cachedBase;
}

export function resetApiBase() {
  cachedBase = null;
  cachedRegion = null;
}
