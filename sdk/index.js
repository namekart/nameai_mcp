/**
 * Official Name.ai SDK — a thin, zero-dependency client for the public API.
 * Docs: https://name.ai/developers · Spec: https://name.ai/openapi.json
 * Auth is optional (https://name.ai/auth.md): pass { accessToken } to see
 * marketplace prices on domain search.
 */
const DEFAULT_BASE_URL = 'https://name.ai';

export class NameAI {
  /** @param {{ baseUrl?: string, accessToken?: string, fetch?: typeof fetch }} [options] */
  constructor(options = {}) {
    this.baseUrl = (options.baseUrl || DEFAULT_BASE_URL).replace(/\/+$/, '');
    this.accessToken = options.accessToken || null;
    this._fetch = options.fetch || globalThis.fetch;
    if (!this._fetch) throw new Error('global fetch not available — Node 18+ required, or pass options.fetch');
  }

  _headers(extra = {}) {
    const h = { accept: 'application/json', 'user-agent': 'nameai-sdk/1.0.0 (+https://name.ai/developers)', ...extra };
    if (this.accessToken) h.authorization = `Bearer ${this.accessToken}`;
    return h;
  }

  async _json(res) {
    if (!res.ok) {
      let detail = null;
      try { detail = await res.json(); } catch { /* non-JSON error body */ }
      const message = detail?.error?.message || detail?.error || `Name.ai API returned HTTP ${res.status}`;
      const err = new Error(message);
      err.status = res.status;
      err.code = detail?.error?.code || null;
      err.retryAfter = res.headers.get('retry-after') ? Number(res.headers.get('retry-after')) : null;
      throw err;
    }
    return res.json();
  }

  /**
   * Check a domain's availability plus its alternate-TLD siblings.
   * Streams NDJSON server-side; resolves with every result row.
   * @param {string} domain e.g. "acme.ai"
   * @returns {Promise<{query: string, results: Array<object>}>}
   */
  async searchDomain(domain) {
    const res = await this._fetch(`${this.baseUrl}/api/domain/search`, {
      method: 'POST',
      headers: this._headers({ 'content-type': 'application/json' }),
      body: JSON.stringify({ q: domain }),
    });
    if (!res.ok) return this._json(res);
    const text = await res.text();
    const results = [];
    for (const line of text.split('\n')) {
      if (!line.trim()) continue;
      let event;
      try { event = JSON.parse(line); } catch { continue; }
      if (event.kind === 'row') { delete event.kind; results.push(event); }
    }
    return { query: domain, results };
  }

  /**
   * WHOIS/RDAP lookup (10/day per IP for anonymous callers).
   * @param {string} domain
   * @param {{ idempotencyKey?: string }} [options] replay-safe retries
   */
  async whoisLookup(domain, options = {}) {
    const headers = this._headers({ 'content-type': 'application/json' });
    if (options.idempotencyKey) headers['idempotency-key'] = options.idempotencyKey;
    const res = await this._fetch(`${this.baseUrl}/api/tools/whois`, {
      method: 'POST', headers, body: JSON.stringify({ domain }),
    });
    return this._json(res);
  }

  /**
   * Price (USD cents) for register|renew|transfer|restore on a TLD.
   * @param {string} tld e.g. "ai"
   * @param {"register"|"renew"|"transfer"|"restore"} [operation]
   */
  async tldPrice(tld, operation = 'register') {
    const res = await this._fetch(
      `${this.baseUrl}/api/pricing/tld?tld=${encodeURIComponent(tld)}&op=${encodeURIComponent(operation)}`,
      { headers: this._headers() },
    );
    return this._json(res);
  }

  /** Registry requirements (terms, org/nameserver rules) for a TLD. */
  async tldRequirements(tld) {
    const res = await this._fetch(`${this.baseUrl}/api/tlds/${encodeURIComponent(tld)}/metadata`, {
      headers: this._headers(),
    });
    return this._json(res);
  }

  /**
   * Marketplace listings (offset pagination). Prices require auth
   * (scope pricing:read) — masked to null otherwise.
   * @param {{ limit?: number, offset?: number, q?: string, tld?: string, max?: number, sort?: "newest"|"price_asc"|"price_desc" }} [params]
   */
  async marketListings(params = {}) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v != null) qs.set(k, String(v));
    const res = await this._fetch(`${this.baseUrl}/api/market/listings?${qs}`, { headers: this._headers() });
    return this._json(res);
  }
}

export default NameAI;
