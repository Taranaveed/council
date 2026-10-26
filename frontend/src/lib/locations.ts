/** Structured markets for buyer/seller forms — keeps Serp + agents on known places. */

export type MarketCountry = {
  code: string;
  name: string;
  currency: string;
  cities: string[];
};

export const MARKET_COUNTRIES: MarketCountry[] = [
  {
    code: 'PK',
    name: 'Pakistan',
    currency: 'PKR',
    cities: ['Lahore', 'Karachi', 'Islamabad', 'Rawalpindi', 'Faisalabad', 'Multan', 'Peshawar'],
  },
  {
    code: 'IN',
    name: 'India',
    currency: 'INR',
    cities: ['Mumbai', 'Delhi', 'Bengaluru', 'Hyderabad', 'Chennai', 'Kolkata', 'Pune'],
  },
  {
    code: 'AE',
    name: 'United Arab Emirates',
    currency: 'AED',
    cities: ['Dubai', 'Abu Dhabi', 'Sharjah'],
  },
  {
    code: 'SA',
    name: 'Saudi Arabia',
    currency: 'SAR',
    cities: ['Riyadh', 'Jeddah', 'Dammam'],
  },
  {
    code: 'GB',
    name: 'United Kingdom',
    currency: 'GBP',
    cities: ['London', 'Manchester', 'Birmingham', 'Edinburgh', 'Glasgow'],
  },
  {
    code: 'US',
    name: 'United States',
    currency: 'USD',
    cities: ['New York', 'Los Angeles', 'Chicago', 'Houston', 'Seattle', 'Austin'],
  },
  {
    code: 'CA',
    name: 'Canada',
    currency: 'CAD',
    cities: ['Toronto', 'Vancouver', 'Montreal', 'Calgary'],
  },
  {
    code: 'AU',
    name: 'Australia',
    currency: 'AUD',
    cities: ['Sydney', 'Melbourne', 'Brisbane'],
  },
  {
    code: 'SG',
    name: 'Singapore',
    currency: 'SGD',
    cities: ['Singapore'],
  },
  {
    code: 'DE',
    name: 'Germany',
    currency: 'EUR',
    cities: ['Berlin', 'Munich', 'Hamburg', 'Frankfurt'],
  },
  {
    code: 'FR',
    name: 'France',
    currency: 'EUR',
    cities: ['Paris', 'Lyon', 'Marseille'],
  },
  {
    code: 'NL',
    name: 'Netherlands',
    currency: 'EUR',
    cities: ['Amsterdam', 'Rotterdam'],
  },
  {
    code: 'ES',
    name: 'Spain',
    currency: 'EUR',
    cities: ['Madrid', 'Barcelona'],
  },
  {
    code: 'IT',
    name: 'Italy',
    currency: 'EUR',
    cities: ['Rome', 'Milan'],
  },
  {
    code: 'IE',
    name: 'Ireland',
    currency: 'EUR',
    cities: ['Dublin'],
  },
  {
    code: 'BD',
    name: 'Bangladesh',
    currency: 'BDT',
    cities: ['Dhaka', 'Chittagong'],
  },
  {
    code: 'TR',
    name: 'Turkey',
    currency: 'TRY',
    cities: ['Istanbul', 'Ankara'],
  },
  {
    code: 'EG',
    name: 'Egypt',
    currency: 'EGP',
    cities: ['Cairo', 'Alexandria'],
  },
  {
    code: 'MY',
    name: 'Malaysia',
    currency: 'MYR',
    cities: ['Kuala Lumpur', 'Penang'],
  },
];

export const OTHER_CITY = '__other__';

export function countryByCode(code: string | null | undefined): MarketCountry | undefined {
  const key = String(code || '').trim().toUpperCase();
  if (!key) return undefined;
  return MARKET_COUNTRIES.find((c) => c.code === key);
}

/** Map geo / free-text labels onto a known country + city when possible. */
export function matchMarketFromLabel(
  label: string,
  countryCode?: string | null,
): { countryCode: string; city: string } | null {
  const text = String(label || '').trim();
  const byCode = countryByCode(countryCode);
  if (byCode) {
    const cityHit = byCode.cities.find((c) => new RegExp(`\\b${c.replace(/\s+/g, '\\s+')}\\b`, 'i').test(text));
    return { countryCode: byCode.code, city: cityHit || byCode.cities[0] };
  }
  if (!text) return null;
  for (const country of MARKET_COUNTRIES) {
    if (new RegExp(`\\b${country.name.replace(/\s+/g, '\\s+')}\\b`, 'i').test(text)) {
      const cityHit = country.cities.find((c) =>
        new RegExp(`\\b${c.replace(/\s+/g, '\\s+')}\\b`, 'i').test(text),
      );
      return { countryCode: country.code, city: cityHit || country.cities[0] };
    }
    const cityHit = country.cities.find((c) =>
      new RegExp(`\\b${c.replace(/\s+/g, '\\s+')}\\b`, 'i').test(text),
    );
    if (cityHit) return { countryCode: country.code, city: cityHit };
  }
  return null;
}

/** Canonical location string for agents + Serp ("Lahore, Pakistan"). */
export function formatMarketLocation(countryCode: string, city: string, customCity?: string): string {
  const country = countryByCode(countryCode);
  if (!country) return [city, customCity].filter(Boolean).join(', ').trim();
  const place =
    city === OTHER_CITY
      ? String(customCity || '').trim()
      : String(city || '').trim() || country.cities[0];
  if (!place) return country.name;
  if (place.toLowerCase() === country.name.toLowerCase()) return country.name;
  return `${place}, ${country.name}`;
}
