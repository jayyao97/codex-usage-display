import asyncio
import json
import unittest

from companion.codex_display.app_server import AppServerClient, AppServerError
from companion.codex_display.main import SnapshotCache, reconcile_active_loop
from companion.codex_display.metrics import collect_snapshot


class FakeClient:
    def __init__(self):
        self.threads = [{"status": {"type": "active"}}]

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
            return {"data": self.threads}
        raise AssertionError(method)


class AppServerAdapterTests(unittest.TestCase):
    def test_collects_all_three_sources(self):
        client = FakeClient()
        snapshot = asyncio.run(collect_snapshot(client))
        self.assertEqual(snapshot.remaining_percent, 90)
        self.assertEqual(snapshot.active_threads, 1)
        self.assertEqual(client.thread_params["sortKey"], "recency_at")
        self.assertTrue(client.thread_params["useStateDbOnly"])


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_hook_change_reconciles_cached_active_count(self):
        client = FakeClient()
        cache = SnapshotCache(client, refresh_seconds=60)
        await cache.refresh()
        self.assertEqual(json.loads(await cache.encoded())["a"], 1)

        client.threads = []
        await cache.activity_changed()

        self.assertEqual(json.loads(await cache.encoded())["a"], 0)
        self.assertTrue(cache.status_changed.is_set())

    async def test_wait_for_exit_reports_unexpected_app_server_exit(self):
        client = AppServerClient("/usr/bin/false")
        client._reader_task = asyncio.create_task(asyncio.sleep(0))

        with self.assertRaises(AppServerError):
            await client.wait_for_exit()

    async def test_active_reconcile_pauses_while_disconnected(self):
        class Cache:
            def __init__(self):
                self.calls = 0

            async def reconcile_active(self):
                self.calls += 1

        cache = Cache()
        connected = asyncio.Event()
        task = asyncio.create_task(
            reconcile_active_loop(cache, 0.01, connected)
        )
        try:
            await asyncio.sleep(0.035)
            self.assertEqual(cache.calls, 0)

            connected.set()
            await asyncio.sleep(0.025)
            self.assertGreater(cache.calls, 0)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task


if __name__ == "__main__":
    unittest.main()
