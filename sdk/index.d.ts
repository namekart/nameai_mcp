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
export interface ListingQuery {
  limit?: number;
  q?: string;
  tld?: string;
  max?: number;
  sort?: 'newest' | 'price_asc' | 'price_desc';
}
export interface Page {
  limit: number;
  /** 0 on a page fetched with a cursor — no offset was applied. */
  offset: number;
  total: number;
  has_more: boolean;
  /** Feed back as `cursor`. Null on the last page. */
  next_cursor: string | null;
}
export interface ListingPage {
  items: object[];
  page: Page;
}
export interface BatchOperation {
  id?: string;
  op: 'search_domain' | 'whois_lookup' | 'tld_registration_price' | 'tld_requirements';
  params?: Record<string, unknown>;
}
export interface BatchResponse {
  results: Array<{ id: string; op: string | null; status: number; body: unknown }>;
  count: number;
  /** How many results carry a status >= 400. */
  failed: number;
}
export declare class NameAI {
  constructor(options?: NameAIOptions);
  baseUrl: string;
  accessToken: string | null;
  searchDomain(domain: string): Promise<{ query: string; results: SearchResultRow[] }>;
  whoisLookup(domain: string, options?: { idempotencyKey?: string }): Promise<object>;
  tldPrice(tld: string, operation?: 'register' | 'renew' | 'transfer' | 'restore'): Promise<{ tld: string; op: string; priceCents: number | null }>;
  tldRequirements(tld: string): Promise<object>;
  marketListings(params?: ListingQuery & { offset?: number; cursor?: string }): Promise<ListingPage>;
  listAllListings(params?: ListingQuery): AsyncGenerator<object, void, void>;
  batch(operations: BatchOperation[]): Promise<BatchResponse>;
}
export default NameAI;
