import unittest

from companion.codex_display.actions import perform_action


class ActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_calls_refresh_callback(self):
        calls = []

        async def refresh():
            calls.append(True)

        ok, message = await perform_action("refresh", refresh)
        self.assertTrue(ok)
        self.assertEqual(message, "UPDATED")
        self.assertEqual(calls, [True])

    async def test_rejects_unknown_action(self):
        async def refresh():
            raise AssertionError("must not refresh")

        ok, message = await perform_action("unknown", refresh)
        self.assertFalse(ok)
        self.assertEqual(message, "NOT ALLOWED")


if __name__ == "__main__":
    unittest.main()
