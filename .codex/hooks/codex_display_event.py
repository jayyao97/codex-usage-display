#!/usr/bin/python3
"""Forward a small Codex lifecycle event to the local display companion."""

import json
import os
import sys
import time
import fcntl
import tempfile
from datetime import datetime, timezone
from pathlib import Path


STATE_DIR = (
    Path.home()
    / "Library"
    / "Caches"
    / "CodexUsageDisplay"
)
EVENTS_PATH = STATE_DIR / "hook-events.jsonl"
USAGE_STATE_PATH = STATE_DIR / "local-usage.json"
LOCK_PATH = EVENTS_PATH.with_name("hook-events.lock")
SESSIONS_PATH = Path.home() / ".codex" / "sessions"
ALLOWED_EVENTS = {"UserPromptSubmit", "Stop"}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _recent_offsets(offsets: object) -> dict[str, int]:
    if not isinstance(offsets, dict):
        return {}
    cutoff = time.time() - 2 * 86400
    result = {}
    for path, offset in offsets.items():
        try:
            if os.path.getmtime(path) >= cutoff:
                result[str(path)] = max(0, int(offset))
        except (OSError, TypeError, ValueError):
            continue
    return result


def _load_usage_state(today: str) -> dict[str, object]:
    try:
        value = json.loads(USAGE_STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError
    except (OSError, ValueError, TypeError):
        value = {}

    same_day = value.get("utc_date") == today
    return {
        "utc_date": today,
        "tokens": max(0, int(value.get("tokens", 0))) if same_day else 0,
        "offsets": (
            value.get("offsets", {})
            if same_day
            else _recent_offsets(value.get("offsets"))
        ),
    }


def _write_usage_state(state: dict[str, object]) -> None:
    USAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix="local-usage.", suffix=".json", dir=USAGE_STATE_PATH.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, separators=(",", ":"), ensure_ascii=False)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, USAGE_STATE_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_token_delta(path: str, offset: int, today: str) -> tuple[int, int]:
    try:
        size = os.path.getsize(path)
        offset = offset if offset <= size else 0
        with open(path, "rb") as handle:
            handle.seek(offset)
            data = handle.read()
    except OSError:
        return 0, offset

    last_newline = data.rfind(b"\n")
    if last_newline < 0:
        return 0, offset

    consumed = last_newline + 1
    tokens = 0
    for raw_line in data[:consumed].splitlines():
        try:
            record = json.loads(raw_line)
            payload = record.get("payload") or {}
            if (
                record.get("type") != "event_msg"
                or payload.get("type") != "token_count"
                or not str(record.get("timestamp", "")).startswith(today)
            ):
                continue
            usage = (payload.get("info") or {}).get("last_token_usage") or {}
            tokens += max(0, int(usage.get("total_tokens", 0)))
        except (ValueError, TypeError, AttributeError):
            continue
    return tokens, offset + consumed


def _update_usage(transcript_path: object) -> None:
    today = _today()
    state = _load_usage_state(today)
    offsets = state["offsets"]
    if not isinstance(offsets, dict):
        offsets = {}
        state["offsets"] = offsets

    if isinstance(transcript_path, str) and transcript_path:
        path = os.path.realpath(transcript_path)
        delta, offset = _read_token_delta(
            path,
            max(0, int(offsets.get(path, 0))),
            today,
        )
        state["tokens"] = max(0, int(state["tokens"])) + delta
        offsets[path] = offset
    _write_usage_state(state)


def _locked_descriptor() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        LOCK_PATH,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    return descriptor


def bootstrap_usage() -> int:
    lock_descriptor = _locked_descriptor()
    try:
        today = _today()
        midnight = datetime.fromisoformat(today).replace(
            tzinfo=timezone.utc
        ).timestamp()
        state: dict[str, object] = {
            "utc_date": today,
            "tokens": 0,
            "offsets": {},
        }
        offsets = state["offsets"]
        assert isinstance(offsets, dict)
        if SESSIONS_PATH.is_dir():
            for path in SESSIONS_PATH.rglob("rollout-*.jsonl"):
                try:
                    if path.stat().st_mtime < midnight:
                        continue
                except OSError:
                    continue
                resolved = os.path.realpath(path)
                delta, offset = _read_token_delta(resolved, 0, today)
                state["tokens"] = int(state["tokens"]) + delta
                offsets[resolved] = offset
        _write_usage_state(state)
        print(json.dumps({"utc_date": today, "tokens": state["tokens"]}))
    finally:
        os.close(lock_descriptor)
    return 0


def main() -> int:
    if sys.argv[1:] == ["--bootstrap"]:
        return bootstrap_usage()

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
            "at": time.time(),
        }
        if not event["session_id"] or not event["turn_id"]:
            return 0

        encoded = (
            json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        lock_descriptor = _locked_descriptor()
        try:
            if event_name == "Stop":
                _update_usage(event["transcript_path"])
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
