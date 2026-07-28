/** localStorage history for seller launch packs / runs */
const KEY = 'sf_seller_runs';
const MAX = 12;

export type SellerRunSnapshot = {
  id: string;
  savedAt: string;
  productName: string;
  location?: string;
  currency?: string;
  mode: 'launch' | 'price' | 'audience';
  listPrice?: string | null;
  topChannel?: string | null;
  exportText: string;
  summary?: string;
};

export function loadSellerRuns(): SellerRunSnapshot[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveSellerRun(run: Omit<SellerRunSnapshot, 'id' | 'savedAt'>): SellerRunSnapshot[] {
  const next: SellerRunSnapshot = {
    ...run,
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    savedAt: new Date().toISOString(),
  };
  const all = [next, ...loadSellerRuns()].slice(0, MAX);
  localStorage.setItem(KEY, JSON.stringify(all));
  return all;
}

export function clearSellerRuns(): void {
  localStorage.removeItem(KEY);
}
