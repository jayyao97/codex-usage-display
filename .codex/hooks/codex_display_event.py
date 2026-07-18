#!/usr/bin/python3
"""Forward a small Codex lifecycle event to the local display companion."""

import json
import os
import sys
import time
import fcntl
from pathlib import Path


EVENTS_PATH = (
    Path.home()
    / "Library"
    / "Caches"
    / "CodexUsageDisplay"
    / "hook-events.jsonl"
)
LOCK_PATH = EVENTS_PATH.with_name("hook-events.lock")
ALLOWED_EVENTS = {"UserPromptSubmit", "Stop"}


def main() -> int:
    try:
        hook_input = json.load(sys.stdin)
        event_name = hook_input.get("hook_event_name")
        if event_name not in ALLOWED_EVENTS:
            return 0

        event = {
            "event": event_name,
            "session_id": hook_input.get("session_id"),
            "turn_id": hook_input.get("turn_id"),
            "transcript_path": hook_input.get("transcript_path"),
            "cwd": hook_input.get("cwd"),
            "at": time.time(),
        }
        if not event["session_id"] or not event["turn_id"]:
            return 0

        EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        encoded = (
            json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        lock_descriptor = os.open(
            LOCK_PATH,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            descriptor = os.open(
                EVENTS_PATH,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                remaining = memoryview(encoded)
                while remaining:
                    written = os.write(descriptor, remaining)
                    remaining = remaining[written:]
            finally:
                os.close(descriptor)
        finally:
            os.close(lock_descriptor)
    except (OSError, ValueError, TypeError):
        # RUN telemetry must never block or fail a Codex turn.
        pass

    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
