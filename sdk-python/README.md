# nameai

Official Python SDK for the [Name.ai](https://name.ai/developers/api) public
API: domain search/availability, WHOIS, TLD pricing and registry requirements,
and marketplace listings. No dependencies — the whole client is `urllib` from
the standard library. Python ≥ 3.9.

```bash
pip install nameai
```

```python
from nameai import NameAI

nameai = NameAI()

nameai.tld_price("ai", "register")          # {'tld': 'ai', 'op': 'register', 'priceCents': 18000}
nameai.search_domain("acme.ai")["results"]  # availability across alternate TLDs
nameai.whois_lookup("example.com")
```

## Paging

Follow the cursor rather than incrementing an offset — a cursor names the row
you stopped at, so a listing sold or added while you page cannot shift the
window under you:

```python
for listing in nameai.list_all_listings(tld="ai", sort="price_asc"):
    print(listing["domain"])
```

## Batching

Several lookups in one round trip. Each operation still costs the rate limit
what the individual call would have, and one failure does not fail the rest:

```python
response = nameai.batch([
    {"id": "a", "op": "search_domain", "params": {"q": "acme.ai"}},
    {"id": "b", "op": "tld_registration_price", "params": {"tld": "ai", "op": "register"}},
    {"id": "c", "op": "whois_lookup", "params": {"domain": "example.com"}},
])
for result in response["results"]:
    print(result["id"], result["status"])
```

## Errors and auth

A non-2xx raises `NameAIError` carrying the API's typed `status`, `code` and
`retry_after`, so you can branch on the code instead of parsing a message.

Every method works unauthenticated. Authentication buys exactly one thing —
real marketplace prices instead of masked ones. Get a token per
[name.ai/auth.md](https://name.ai/auth.md) and pass
`NameAI(access_token=...)`.

- API docs: https://name.ai/developers/api
- OpenAPI spec: https://name.ai/openapi.json
- MCP server (same capabilities, for agents): https://name.ai/developers/mcp
