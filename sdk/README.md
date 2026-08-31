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

Every method works without authentication. To see marketplace prices on
`searchDomain`, authenticate per [name.ai/auth.md](https://name.ai/auth.md)
and pass `{ accessToken }`.

- OpenAPI spec: https://name.ai/openapi.json
- MCP server (same tools for agents): `https://nameai-mcp.h.namekart.com/mcp`
- Rate limits and quotas: https://name.ai/pricing.md
