# nameai-sdk

Official JavaScript SDK for the [Name.ai](https://name.ai/developers) public
API: domain search/availability, WHOIS, TLD pricing and registry
requirements, and marketplace listings. Zero dependencies, Node ≥ 18.

```bash
npm install nameai-sdk
```

```js
import NameAI from 'nameai-sdk';

const nameai = new NameAI();
const { results } = await nameai.searchDomain('acme.ai');
const { priceCents } = await nameai.tldPrice('ai', 'register');
```

## Paging

Follow the cursor rather than incrementing an offset — a cursor names the row
you stopped at, so a listing sold or added while you page cannot shift the
window under you:

```js
for await (const listing of nameai.listAllListings({ tld: 'ai', sort: 'price_asc' })) {
  console.log(listing.domain);
}
```

## Batching

Several lookups in one round trip. Each operation still costs the rate limit
what the individual call would have, and one failure does not fail the rest:

```js
const { results } = await nameai.batch([
  { id: 'a', op: 'search_domain', params: { q: 'acme.ai' } },
  { id: 'b', op: 'tld_registration_price', params: { tld: 'ai', op: 'register' } },
  { id: 'c', op: 'whois_lookup', params: { domain: 'example.com' } },
]);
```

## Errors and auth

A non-2xx throws an `Error` carrying the API's typed `status`, `code` and
`retryAfter`, so you can branch on the code instead of parsing a message.

Every method works without authentication. To see marketplace prices on
`searchDomain`, authenticate per [name.ai/auth.md](https://name.ai/auth.md)
and pass `{ accessToken }`.

- API docs: https://name.ai/developers/api
- OpenAPI spec: https://name.ai/openapi.json
- Python SDK, same surface: `pip install nameai`
- MCP server (same tools for agents): `https://mcp.name.ai/mcp`
- Rate limits and quotas: https://name.ai/pricing.md
