export interface NameAIOptions {
  baseUrl?: string;
  accessToken?: string;
  fetch?: typeof fetch;
}
export interface SearchResultRow {
  domain: string;
  state: string;
  state_label: string;
  available: boolean | null;
  price: number | { bin: number | null; floor: number | null; currency?: string } | null;
  listing: object | null;
  whois_summary?: object;
  [key: string]: unknown;
}
export interface ApiError extends Error {
  status?: number;
  code?: string | null;
  retryAfter?: number | null;
}
export declare class NameAI {
  constructor(options?: NameAIOptions);
  baseUrl: string;
  accessToken: string | null;
  searchDomain(domain: string): Promise<{ query: string; results: SearchResultRow[] }>;
  whoisLookup(domain: string, options?: { idempotencyKey?: string }): Promise<object>;
  tldPrice(tld: string, operation?: 'register' | 'renew' | 'transfer' | 'restore'): Promise<{ tld: string; op: string; priceCents: number | null }>;
  tldRequirements(tld: string): Promise<object>;
  marketListings(params?: { limit?: number; offset?: number; q?: string; tld?: string; max?: number; sort?: 'newest' | 'price_asc' | 'price_desc' }): Promise<{ items: object[]; page: { limit: number; offset: number; total: number } }>;
}
export default NameAI;
