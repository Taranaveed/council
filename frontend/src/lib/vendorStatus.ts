/** Listing host/name match — not seller identity verification. */
export function knownSiteLabel(status?: string | null): string | null {
  const s = String(status || '').trim().toLowerCase();
  if (s === 'known marketplace' || s === 'known_marketplace' || s === 'verified') {
    return 'Known site';
  }
  return null;
}

export const KNOWN_SITE_HINT =
  'This listing is on a known marketplace. It is not a check of the seller’s identity or rating.';
