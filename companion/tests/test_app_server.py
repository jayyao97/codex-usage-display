import asyncio
import unittest

from companion.codex_display.metrics import collect_snapshot


class FakeClient:
    async def request(self, method, params=None):
        if method == "account/rateLimits/read":
            return {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 10,
                        "windowDurationMins": 10080,
                    }
                }
            }
        if method == "account/usage/read":
            return {"dailyUsageBuckets": []}
        if method == "thread/list":
            self.thread_params = params
            return {"data": [{"status": {"type": "active"}}]}
        raise AssertionError(method)


class AppServerAdapterTests(unittest.TestCase):
    def test_collects_all_three_sources(self):
        client = FakeClient()
        snapshot = asyncio.run(collect_snapshot(client))
        self.assertEqual(snapshot.remaining_percent, 90)
        self.assertEqual(snapshot.active_threads, 1)
        self.assertEqual(client.thread_params["sortKey"], "recency_at")
        self.assertTrue(client.thread_params["useStateDbOnly"])


if __name__ == "__main__":
    unittest.main()
