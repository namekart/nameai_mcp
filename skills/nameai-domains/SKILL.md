---
name: nameai-domains
description: Search domain availability, look up WHOIS, and get TLD registration pricing and requirements on Name.ai — via its MCP server or public REST API, no authentication required.
---

# Name.ai domains skill

Name.ai is an AI-first domain platform. This skill covers checking whether a
domain is available, looking up WHOIS records, and getting registration
pricing and registry requirements for a TLD.

## Preferred: connect to the MCP server

Remote Streamable HTTP MCP server, no install and no API key:

```json
{
  "mcpServers": {
    "name-ai": {
      "type": "http",
      "url": "https://nameai-mcp.h.namekart.com/mcp"
    }
  }
}
```

Tools: `search_domain`, `whois_lookup`, `tld_registration_price`,
`tld_requirements`.

## Alternative: plain REST

The same operations as REST endpoints, documented in the OpenAPI 3.1 spec at
https://name.ai/openapi.json:

- `POST https://name.ai/api/domain/search` — body `{"q": "example.ai"}`,
  streams NDJSON rows (availability, state, price).
- `POST https://name.ai/api/tools/whois` — body `{"domain": "example.com"}`.
  Rate limited to 10/day per IP.
- `GET https://name.ai/api/pricing/tld?tld=ai&op=register` — USD cents.
- `GET https://name.ai/api/tlds/{tld}/metadata` — registry requirements.

## Authentication (optional)

Everything above works anonymously. Marketplace/aftermarket prices on domain
search are masked for anonymous callers; to see them, complete the OAuth 2.1
PKCE flow described at https://name.ai/auth.md and send the access token as
`Authorization: Bearer <token>`.

## Notes

- Prices are USD. `priceCents` fields are integer cents.
- A domain's `state` of `S1` means unregistered (new registration possible);
  aftermarket states carry a `listing` object when visible.
- Do not poll aggressively; cache TLD pricing/requirements, which change
  rarely.
