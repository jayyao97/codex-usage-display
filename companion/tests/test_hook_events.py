import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from companion.codex_display.hook_events import HookActivityTracker


def boundary(event_type, turn_id):
    return (
        json.dumps(
            {
                "type": "event_msg",
                "payload": {"type": event_type, "turn_id": turn_id},
            }
        )
        + "\n"
    )


class HookActivityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False
        )
        self.rollout_path = handle.name
        handle.close()
        self.addCleanup(lambda: os.unlink(self.rollout_path))
        self.changed = AsyncMock()
        self.tracker = HookActivityTracker(self.changed)

    async def test_stop_waits_for_matching_task_complete(self):
        self._append(boundary("task_started", "turn-1"))
        await self.tracker.process_event(self._event("UserPromptSubmit"))
        await self.tracker.reconcile()
        self.assertEqual(self.tracker.extra_count(set()), 1)

        await self.tracker.process_event(self._event("Stop"))
        await self.tracker.reconcile()
        self.assertEqual(self.tracker.extra_count(set()), 1)

        self._append(boundary("task_complete", "another-turn"))
        await self.tracker.reconcile()
        self.assertEqual(self.tracker.extra_count(set()), 1)

        self._append(boundary("task_complete", "turn-1"))
        await self.tracker.reconcile()
        self.assertEqual(self.tracker.extra_count(set()), 0)

    async def test_unconfirmed_submit_expires(self):
        tracker = HookActivityTracker(
            self.changed,
            start_timeout_seconds=2,
        )
        await tracker.process_event(self._event("UserPromptSubmit", at=10))
        self.assertEqual(tracker.extra_count(set()), 1)

        await tracker.reconcile(now=12)
        self.assertEqual(tracker.extra_count(set()), 0)

    async def test_base_rollout_is_not_double_counted(self):
        await self.tracker.process_event(self._event("UserPromptSubmit"))
        base_paths = {os.path.realpath(self.rollout_path)}
        self.assertEqual(self.tracker.extra_count(base_paths), 0)

    async def test_rotation_keeps_unread_tail_and_creates_fresh_queue(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        events_path = Path(directory.name) / "hook-events.jsonl"
        events_path.write_text("old\n", encoding="utf-8")
        tracker = HookActivityTracker(
            self.changed,
            events_path=events_path,
            max_event_bytes=1,
        )
        handle = events_path.open("r", encoding="utf-8")
        handle.seek(0, os.SEEK_END)
        with events_path.open("a", encoding="utf-8") as writer:
            writer.write("late\n")

        new_handle, late_lines = tracker._rotate_if_needed(handle)
        self.addCleanup(new_handle.close)

        self.assertEqual(late_lines, ["late\n"])
        self.assertEqual(events_path.read_text(encoding="utf-8"), "")
        self.assertEqual(
            Path(str(events_path) + ".1").read_text(encoding="utf-8"),
            "old\nlate\n",
        )

    def _event(self, name, at=100):
        return {
            "event": name,
            "session_id": "session-1",
            "turn_id": "turn-1",
            "transcript_path": self.rollout_path,
            "at": at,
        }

    def _append(self, text):
        with Path(self.rollout_path).open("a", encoding="utf-8") as handle:
            handle.write(text)


if __name__ == "__main__":
    unittest.main()
