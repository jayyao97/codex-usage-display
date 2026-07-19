import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from companion.codex_display.local_usage import read_local_tokens


HOOK_PATH = (
    Path(__file__).resolve().parents[2]
    / ".codex"
    / "hooks"
    / "codex_display_event.py"
)


def token_record(day, tokens):
    return json.dumps(
        {
            "timestamp": f"{day}T01:02:03.000Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"last_token_usage": {"total_tokens": tokens}},
            },
        }
    )


class LocalUsageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)

        spec = importlib.util.spec_from_file_location("display_hook", HOOK_PATH)
        self.hook = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(self.hook)

        self.hook.STATE_DIR = root
        self.hook.EVENTS_PATH = root / "hook-events.jsonl"
        self.hook.USAGE_STATE_PATH = root / "local-usage.json"
        self.hook.LOCK_PATH = root / "hook-events.lock"
        self.hook.SESSIONS_PATH = root / "sessions"
        self.hook._today = lambda: "2027-01-10"

    def test_incrementally_counts_each_token_record_once(self):
        first = Path(self.directory.name) / "first.jsonl"
        first.write_text(
            token_record("2027-01-09", 999)
            + "\n"
            + token_record("2027-01-10", 100)
            + "\n",
            encoding="utf-8",
        )

        self.hook._update_usage(str(first))
        self.hook._update_usage(str(first))
        with first.open("a", encoding="utf-8") as handle:
            handle.write(token_record("2027-01-10", 50) + "\n")
        self.hook._update_usage(str(first))

        tokens = read_local_tokens(
            self.hook.USAGE_STATE_PATH,
            utc_date="2027-01-10",
        )
        self.assertEqual(tokens, 150)

    def test_accumulates_multiple_transcripts(self):
        for name, tokens in (("one.jsonl", 100), ("two.jsonl", 25)):
            path = Path(self.directory.name) / name
            path.write_text(
                token_record("2027-01-10", tokens) + "\n",
                encoding="utf-8",
            )
            self.hook._update_usage(str(path))

        tokens = read_local_tokens(
            self.hook.USAGE_STATE_PATH,
            utc_date="2027-01-10",
        )
        self.assertEqual(tokens, 125)

    def test_only_stop_event_updates_usage(self):
        path = Path(self.directory.name) / "rollout.jsonl"
        path.write_text(
            token_record("2027-01-10", 100) + "\n",
            encoding="utf-8",
        )
        event = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "transcript_path": str(path),
            "cwd": self.directory.name,
        }

        for name in ("UserPromptSubmit", "Stop"):
            event["hook_event_name"] = name
            with mock.patch.object(
                self.hook.sys,
                "stdin",
                io.StringIO(json.dumps(event)),
            ), contextlib.redirect_stdout(io.StringIO()):
                self.hook.main()
            if name == "UserPromptSubmit":
                self.assertFalse(self.hook.USAGE_STATE_PATH.exists())

        self.assertEqual(
            read_local_tokens(
                self.hook.USAGE_STATE_PATH,
                utc_date="2027-01-10",
            ),
            100,
        )

    def test_official_reader_rejects_another_utc_day(self):
        self.hook.USAGE_STATE_PATH.write_text(
            '{"utc_date":"2027-01-09","tokens":42}',
            encoding="utf-8",
        )
        self.assertIsNone(
            read_local_tokens(
                self.hook.USAGE_STATE_PATH,
                utc_date="2027-01-10",
            )
        )

    def test_preserves_partial_tail_until_newline_arrives(self):
        path = Path(self.directory.name) / "partial.jsonl"
        path.write_text(
            token_record("2027-01-10", 100)
            + "\n"
            + token_record("2027-01-10", 50),
            encoding="utf-8",
        )

        self.hook._update_usage(str(path))
        self.assertEqual(
            read_local_tokens(
                self.hook.USAGE_STATE_PATH,
                utc_date="2027-01-10",
            ),
            100,
        )

        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n")
        self.hook._update_usage(str(path))
        self.assertEqual(
            read_local_tokens(
                self.hook.USAGE_STATE_PATH,
                utc_date="2027-01-10",
            ),
            150,
        )

    def test_resets_tokens_at_utc_day_boundary(self):
        path = Path(self.directory.name) / "rollout.jsonl"
        path.write_text(
            token_record("2027-01-10", 100) + "\n",
            encoding="utf-8",
        )
        self.hook._update_usage(str(path))

        self.hook._today = lambda: "2027-01-11"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(token_record("2027-01-11", 25) + "\n")
        self.hook._update_usage(str(path))

        self.assertEqual(
            read_local_tokens(
                self.hook.USAGE_STATE_PATH,
                utc_date="2027-01-11",
            ),
            25,
        )

    def test_bootstrap_rebuilds_current_utc_day(self):
        sessions = self.hook.SESSIONS_PATH / "2027" / "01" / "10"
        sessions.mkdir(parents=True)
        first = sessions / "rollout-one.jsonl"
        second = sessions / "rollout-two.jsonl"
        first.write_text(
            token_record("2027-01-09", 999)
            + "\n"
            + token_record("2027-01-10", 100)
            + "\n",
            encoding="utf-8",
        )
        second.write_text(
            token_record("2027-01-10", 25) + "\n",
            encoding="utf-8",
        )
        modified = datetime(
            2027, 1, 10, 1, tzinfo=timezone.utc
        ).timestamp()
        os.utime(first, (modified, modified))
        os.utime(second, (modified, modified))

        with contextlib.redirect_stdout(io.StringIO()):
            self.hook.bootstrap_usage()

        self.assertEqual(
            read_local_tokens(
                self.hook.USAGE_STATE_PATH,
                utc_date="2027-01-10",
            ),
            125,
        )


if __name__ == "__main__":
    unittest.main()
