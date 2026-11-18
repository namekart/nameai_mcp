"""search_marketplace: params sent to name.ai, result mapping, limits, errors.

Run: python -m unittest discover -s tests
"""

import unittest
from unittest.mock import AsyncMock, patch

from nameai_mcp import server
from nameai_mcp.nameai_client import NameAIAPIError

ITEMS = {
    "items": [
        {"id": "1", "domain": "quietharbor.ai", "display_name": "QuietHarbor.ai", "price": {"bin": 550000, "floor": None}},
        {"id": "2", "domain": "greco.ai", "display_name": None, "price": {"bin": None, "floor": None}},
        {"id": "3", "domain": "", "price": {"bin": 1}},
    ],
    "page": {"total": 42, "has_more": True},
}


class SearchMarketplaceTest(unittest.IsolatedAsyncioTestCase):
    async def call(self, response=ITEMS, **kwargs):
        with patch.object(server, "get_json", AsyncMock(return_value=response)) as get_json:
            result = await server.search_marketplace(**kwargs)
        return result, get_json

    async def test_maps_rows_and_page(self):
        result, _ = await self.call(keyword="Harbor")
        self.assertEqual(result["total"], 42)
        self.assertTrue(result["has_more"])
        self.assertEqual(len(result["results"]), 2)  # row without a domain dropped
        first, second = result["results"]
        self.assertEqual(first["domain"], "QuietHarbor.ai")
        self.assertEqual(first["price_usd"], 550000)
        self.assertTrue(first["url"].startswith("https://name.ai/quietharbor.ai?"))
        self.assertIsNone(second["price_usd"])  # masked price stays null

    async def test_sends_filters_and_caps_limit(self):
        _, get_json = await self.call(keyword=" Legal ", tld=".AI", min_price=1000, max_price=50000, sort="price_asc", limit=99)
        path, params = get_json.call_args.args[:2]
        self.assertEqual(path, "/api/market/listings")
        self.assertEqual(params, {"limit": 25, "q": "legal", "tld": "ai", "min": 1000, "max": 50000, "sort": "price_asc"})

    async def test_browse_defaults_omit_empty_filters(self):
        _, get_json = await self.call(limit=0)
        params = get_json.call_args.args[1]
        self.assertEqual(params, {"limit": 1, "tld": "ai"})

    async def test_sends_mcp_key_when_configured(self):
        with patch.object(server, "mcp_key_headers", return_value={"x-nameai-mcp-key": "k"}):
            _, get_json = await self.call()
        self.assertEqual(get_json.call_args.kwargs["extra_headers"], {"x-nameai-mcp-key": "k"})

    async def test_api_error_propagates(self):
        with patch.object(server, "get_json", AsyncMock(side_effect=NameAIAPIError(429, "Rate limit exceeded"))):
            with self.assertRaises(NameAIAPIError):
                await server.search_marketplace(keyword="pay")

    async def test_tool_is_registered_read_only(self):
        tools = {t.name: t for t in await server.mcp.list_tools()}
        self.assertIn("search_marketplace", tools)
        self.assertTrue(tools["search_marketplace"].annotations.read_only_hint)


if __name__ == "__main__":
    unittest.main()
