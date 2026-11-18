"""search_premium_domains: params sent to name.ai, result mapping, limits, errors.

Run: python -m unittest discover -s tests
"""

import unittest
from unittest.mock import AsyncMock, patch

from nameai_mcp import limits, server
from mcp.server.mcpserver.exceptions import ToolError

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
    def setUp(self):
        limits.reset()

    async def call(self, response=ITEMS, **kwargs):
        with patch.object(server, "get_json", AsyncMock(return_value=response)) as get_json:
            result = await server.search_premium_domains(**kwargs)
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

    async def test_api_error_becomes_readable_tool_error(self):
        with patch.object(server, "get_json", AsyncMock(side_effect=NameAIAPIError(429, "Rate limit exceeded"))):
            with self.assertRaisesRegex(ToolError, "busy"):
                await server.search_premium_domains(keyword="pay")

    async def test_tool_is_registered_read_only_with_card_and_schema(self):
        tools = {t.name: t for t in await server.mcp.list_tools()}
        tool = tools["search_premium_domains"]
        self.assertTrue(tool.annotations.read_only_hint)
        self.assertEqual(tool.title, "Search premium domains for sale")
        self.assertEqual(tool.meta["ui"]["resourceUri"], "ui://nameai/market-results.html")
        self.assertIn("results", tool.output_schema["properties"])

    async def test_same_query_is_served_from_cache(self):
        get_json = AsyncMock(return_value=ITEMS)
        with patch.object(server, "get_json", get_json):
            await server.search_premium_domains(keyword="pay")
            await server.search_premium_domains(keyword="pay")
        self.assertEqual(get_json.await_count, 1)

    async def test_session_limit_refuses_without_calling_name_ai(self):
        class Ctx:
            headers = {"Mcp-Session-Id": "abc"}  # mixed case, as Claude sends it
        get_json = AsyncMock(return_value=ITEMS)
        with patch.object(server, "get_json", get_json):
            for i in range(limits.PER_SESSION_PER_MIN):
                await server.search_premium_domains(keyword=f"k{i}", ctx=Ctx())
            with self.assertRaisesRegex(ToolError, "Too many"):
                await server.search_premium_domains(keyword="one-more", ctx=Ctx())
        self.assertEqual(get_json.await_count, limits.PER_SESSION_PER_MIN)


class LimitsTest(unittest.TestCase):
    def setUp(self):
        limits.reset()

    def test_global_cap_and_new_minute(self):
        for _ in range(limits.GLOBAL_PER_MIN):
            self.assertTrue(limits.allow(None, now=60.0))
        self.assertFalse(limits.allow(None, now=60.0))
        self.assertTrue(limits.allow(None, now=120.0))

    def test_cache_expires(self):
        limits.cache_put("k", 1, now=0.0)
        self.assertEqual(limits.cache_get("k", now=10.0), 1)
        self.assertIsNone(limits.cache_get("k", now=limits.CACHE_TTL_SEC + 1.0))


if __name__ == "__main__":
    unittest.main()


class DirectoryRequirementsTest(unittest.IsolatedAsyncioTestCase):
    async def test_every_tool_has_title_and_read_only_hint(self):
        for t in await server.mcp.list_tools():
            self.assertTrue(t.title, t.name)
            self.assertTrue(t.annotations and t.annotations.read_only_hint, t.name)
            self.assertLessEqual(len(t.name), 64)

    async def test_name_ai_errors_reach_the_model(self):
        with patch.object(server, "post_json", AsyncMock(side_effect=NameAIAPIError(429, "WHOIS limit reached for today"))):
            with self.assertRaisesRegex(ToolError, "WHOIS limit reached for today"):
                await server.mcp.call_tool("whois_lookup", {"domain": "example.com"})
