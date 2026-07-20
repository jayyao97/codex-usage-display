import asyncio
import fcntl
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Dict, IO, List, Optional, Set, Tuple

from .metrics import rollout_turn_state


DEFAULT_EVENTS_PATH = (
    Path.home()
    / "Library"
    / "Caches"
    / "CodexUsageDisplay"
    / "hook-events.jsonl"
)


@dataclass
class PendingTurn:
    turn_id: str
    transcript_path: Optional[str]
    phase: str
    created_at: float
    counted: bool


class HookActivityTracker:
    def __init__(
        self,
        on_change: Callable[[], Awaitable[None]],
        events_path: Path = DEFAULT_EVENTS_PATH,
        start_timeout_seconds: float = 10,
        stale_seconds: float = 30 * 60,
        max_event_bytes: int = 1024 * 1024,
        poll_seconds: float = 1,
    ) -> None:
        self._on_change = on_change
        self._events_path = events_path
        self._start_timeout_seconds = start_timeout_seconds
        self._stale_seconds = stale_seconds
        self._max_event_bytes = max_event_bytes
        self._poll_seconds = poll_seconds
        self._lock_path = events_path.with_name("hook-events.lock")
        self._archive_path = events_path.with_name(events_path.name + ".1")
        self._turns: Dict[Tuple[str, str], PendingTurn] = {}

    def extra_count(self, base_active_paths: Set[str]) -> int:
        identities = set()
        for key, turn in self._turns.items():
            if not turn.counted:
                continue
            if turn.transcript_path:
                path = os.path.realpath(turn.transcript_path)
                if path in base_active_paths:
                    continue
                identities.add(("path", path))
            else:
                identities.add(("session", key[0]))
        return len(identities)

    async def process_event(self, event: Dict[str, object]) -> None:
        event_name = event.get("event")
        session_id = event.get("session_id")
        turn_id = event.get("turn_id")
        if (
            event_name not in {"UserPromptSubmit", "Stop"}
            or not isinstance(session_id, str)
            or not isinstance(turn_id, str)
        ):
            return

        key = (session_id, turn_id)
        now = float(event.get("at") or time.time())
        transcript_path = event.get("transcript_path")
        path = transcript_path if isinstance(transcript_path, str) else None

        if event_name == "UserPromptSubmit":
            self._turns[key] = PendingTurn(
                turn_id=turn_id,
                transcript_path=path,
                phase="pending_start" if path is not None else "active",
                created_at=now,
                counted=True,
            )
        else:
            existing = self._turns.get(key)
            resolved_path = path or (
                existing.transcript_path if existing is not None else None
            )
            if resolved_path is None:
                self._turns.pop(key, None)
            else:
                self._turns[key] = PendingTurn(
                    turn_id=turn_id,
                    transcript_path=resolved_path,
                    phase="pending_stop",
                    created_at=(
                        existing.created_at if existing is not None else now
                    ),
                    counted=(
                        existing.counted if existing is not None else False
                    ),
                )
        await self._on_change()

    async def reconcile(self, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        changed = False
        for key, turn in list(self._turns.items()):
            state = (
                rollout_turn_state(turn.transcript_path, turn.turn_id)
                if turn.transcript_path
                else None
            )
            age = now - turn.created_at

            if state is False:
                del self._turns[key]
                changed = True
            elif state is True:
                if not turn.counted or turn.phase == "pending_start":
                    turn.counted = True
                    turn.phase = (
                        "pending_stop"
                        if turn.phase == "pending_stop"
                        else "active"
                    )
                    changed = True
            elif (
                turn.phase == "pending_start"
                and age >= self._start_timeout_seconds
            ):
                del self._turns[key]
                changed = True
            elif age >= self._stale_seconds:
                del self._turns[key]
                changed = True

        if changed:
            await self._on_change()

    def _rotate_if_needed(
        self, handle: IO[str]
    ) -> Tuple[IO[str], List[str]]:
        if os.fstat(handle.fileno()).st_size < self._max_event_bytes:
            return handle, []

        lock_descriptor = os.open(
            self._lock_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            late_lines = handle.readlines()
            handle.close()
            os.replace(self._events_path, self._archive_path)
            descriptor = os.open(
                self._events_path,
                os.O_CREAT | os.O_TRUNC | os.O_WRONLY,
                0o600,
            )
            os.close(descriptor)
            new_handle = self._events_path.open("r", encoding="utf-8")
        finally:
            os.close(lock_descriptor)
        return new_handle, late_lines

    async def run_forever(self) -> None:
        self._events_path.parent.mkdir(parents=True, exist_ok=True)
        self._events_path.touch(mode=0o600, exist_ok=True)
        os.chmod(self._events_path, 0o600)
        handle = self._events_path.open("r", encoding="utf-8")
        try:
            # Startup truth comes from rollout reconciliation, not stale hooks.
            handle.seek(0, os.SEEK_END)
            while True:
                position = handle.tell()
                line = handle.readline()
                if line:
                    if not line.endswith("\n"):
                        handle.seek(position)
                        await asyncio.sleep(min(0.05, self._poll_seconds))
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    await self.process_event(event)
                else:
                    handle, late_lines = self._rotate_if_needed(handle)
                    for late_line in late_lines:
                        if not late_line.endswith("\n"):
                            continue
                        try:
                            event = json.loads(late_line)
                        except json.JSONDecodeError:
                            continue
                        await self.process_event(event)
                    await self.reconcile()
                    await asyncio.sleep(self._poll_seconds)
        finally:
            handle.close()
