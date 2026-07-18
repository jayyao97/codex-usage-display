import json
import os
import tempfile
import unittest
from datetime import date

from companion.codex_display.metrics import (
    build_snapshot,
    rollout_is_active,
    rollout_turn_state,
)


def event(event_type):
    return json.dumps(
        {"type": "event_msg", "payload": {"type": event_type}}
    ).encode("utf-8")


def turn_event(event_type, turn_id):
    return json.dumps(
        {
            "type": "event_msg",
            "payload": {"type": event_type, "turn_id": turn_id},
        }
    ).encode("utf-8")


class MetricsTests(unittest.TestCase):
    def test_builds_snapshot_from_current_codex_shapes(self):
        now = 1_800_000_000
        limits = {
            "rateLimits": {
                "primary": {
                    "usedPercent": 31,
                    "windowDurationMins": 10080,
                    "resetsAt": now + 7200,
                }
            },
            "rateLimitResetCredits": {
                "availableCount": 2,
                "credits": [
                    {
                        "status": "available",
                        "expiresAt": now + 3600,
                    },
                    {
                        "status": "available",
                        "expiresAt": now + 86400,
                    },
                ],
            },
        }
        usage = {
            "dailyUsageBuckets": [
                {"startDate": "2027-01-10", "tokens": 100},
                {"startDate": "2027-01-09", "tokens": 90},
                {"startDate": "2027-01-04", "tokens": 40},
                {"startDate": "2027-01-03", "tokens": 999},
            ]
        }
        snapshot = build_snapshot(
            limits,
            usage,
            [{"status": {"type": "active"}}],
            now=now,
            local_date=date(2027, 1, 10),
            utc_offset_minutes=480,
        )

        self.assertEqual(snapshot.remaining_percent, 69)
        self.assertEqual(snapshot.limit_window_minutes, 10080)
        self.assertEqual(snapshot.quota_reset_seconds, 7200)
        self.assertEqual(snapshot.tokens_today, 100)
        self.assertEqual(snapshot.tokens_7d, 230)
        self.assertEqual(snapshot.reset_credits, 2)
        self.assertEqual(snapshot.next_credit_expiry_seconds, 3600)
        self.assertEqual(snapshot.active_threads, 1)

    def test_prefers_codex_bucket_in_multi_limit_response(self):
        snapshot = build_snapshot(
            {
                "rateLimits": {"primary": {"usedPercent": 99}},
                "rateLimitsByLimitId": {
                    "codex": {
                        "primary": {
                            "usedPercent": 4,
                            "windowDurationMins": 10080,
                        }
                    },
                    "other": {"primary": {"usedPercent": 80}},
                },
            },
            {},
            [],
            now=1,
            local_date=date(2027, 1, 10),
            utc_offset_minutes=0,
        )
        self.assertEqual(snapshot.remaining_percent, 96)

    def test_rollout_started_without_completion_is_active(self):
        path = self._write_rollout(["task_complete", "task_started"])
        self.assertTrue(rollout_is_active(path))

    def test_rollout_completion_is_not_active(self):
        path = self._write_rollout(["task_started", "task_complete"])
        self.assertFalse(rollout_is_active(path))

    def test_rollout_ignores_trailing_non_event_records(self):
        handle = tempfile.NamedTemporaryFile(delete=False)
        self.addCleanup(lambda: os.unlink(handle.name))
        handle.write(event("task_started") + b"\n")
        handle.write(b'{"type":"response_item","payload":{"type":"reasoning"}}\n')
        handle.write(b"not-json\n")
        handle.close()
        self.assertTrue(rollout_is_active(handle.name))

    def test_old_incomplete_rollout_is_not_counted_forever(self):
        path = self._write_rollout(["task_started"])
        os.utime(path, (1, 1))
        self.assertFalse(rollout_is_active(path))

    def test_rollout_turn_state_matches_exact_turn(self):
        handle = tempfile.NamedTemporaryFile(delete=False)
        self.addCleanup(lambda: os.unlink(handle.name))
        handle.write(turn_event("task_complete", "older") + b"\n")
        handle.write(turn_event("task_started", "current") + b"\n")
        handle.close()

        self.assertIs(rollout_turn_state(handle.name, "older"), False)
        self.assertIs(rollout_turn_state(handle.name, "current"), True)
        self.assertIsNone(rollout_turn_state(handle.name, "missing"))

    def _write_rollout(self, events):
        handle = tempfile.NamedTemporaryFile(delete=False)
        self.addCleanup(lambda: os.unlink(handle.name))
        for item in events:
            handle.write(event(item) + b"\n")
        handle.close()
        return handle.name


if __name__ == "__main__":
    unittest.main()
