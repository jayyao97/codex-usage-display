import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


@dataclass(frozen=True)
class Snapshot:
    generated_at: int
    utc_offset_minutes: int
    remaining_percent: int
    limit_window_minutes: int
    quota_reset_seconds: int
    tokens_today: int
    tokens_today_estimated: bool
    tokens_7d: int
    reset_credits: int
    next_credit_expiry_seconds: int
    active_threads: int


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def _seconds_until(timestamp: Optional[int], now: int) -> int:
    if timestamp is None:
        return 0
    return max(0, int(timestamp) - now)


def build_snapshot(
    rate_limit_result: Dict[str, Any],
    usage_result: Dict[str, Any],
    threads: Iterable[Dict[str, Any]],
    now: Optional[int] = None,
    local_date: Optional[date] = None,
    utc_offset_minutes: Optional[int] = None,
) -> Snapshot:
    now = int(time.time()) if now is None else now
    # Codex dailyUsageBuckets use UTC calendar dates, independent of the
    # computer's local timezone.
    local_date = (
        datetime.now(timezone.utc).date() if local_date is None else local_date
    )
    if utc_offset_minutes is None:
        local_seconds = (
            datetime_offset_seconds(now)
        )
        utc_offset_minutes = int(local_seconds // 60)

    limits_by_id = rate_limit_result.get("rateLimitsByLimitId") or {}
    limits = limits_by_id.get("codex") or rate_limit_result.get("rateLimits") or {}
    window = limits.get("primary") or {}
    used_percent = _clamp(int(window.get("usedPercent", 100)), 0, 100)
    remaining_percent = 100 - used_percent
    limit_window_minutes = max(0, int(window.get("windowDurationMins") or 0))
    quota_reset_seconds = _seconds_until(window.get("resetsAt"), now)

    buckets = {
        item.get("startDate"): max(0, int(item.get("tokens", 0)))
        for item in usage_result.get("dailyUsageBuckets") or []
        if item.get("startDate")
    }
    today_key = local_date.isoformat()
    tokens_today_estimated = today_key not in buckets
    tokens_today = buckets.get(today_key, 0)
    tokens_7d = sum(
        buckets.get((local_date - timedelta(days=offset)).isoformat(), 0)
        for offset in range(7)
    )

    credit_summary = rate_limit_result.get("rateLimitResetCredits") or {}
    reset_credits = max(0, int(credit_summary.get("availableCount", 0)))
    expiries = [
        int(credit["expiresAt"])
        for credit in credit_summary.get("credits") or []
        if credit.get("status") == "available"
        and credit.get("expiresAt") is not None
        and int(credit["expiresAt"]) > now
    ]
    next_expiry_seconds = _seconds_until(min(expiries) if expiries else None, now)

    active_threads = sum(1 for thread in threads if thread_is_active(thread))

    return Snapshot(
        generated_at=now,
        utc_offset_minutes=utc_offset_minutes,
        remaining_percent=remaining_percent,
        limit_window_minutes=limit_window_minutes,
        quota_reset_seconds=quota_reset_seconds,
        tokens_today=tokens_today,
        tokens_today_estimated=tokens_today_estimated,
        tokens_7d=tokens_7d,
        reset_credits=reset_credits,
        next_credit_expiry_seconds=next_expiry_seconds,
        active_threads=active_threads,
    )


def datetime_offset_seconds(now: Optional[int] = None) -> int:
    now = int(time.time()) if now is None else now
    local = time.localtime(now)
    if local.tm_isdst > 0 and time.daylight:
        return -time.altzone
    return -time.timezone


def thread_is_active(thread: Dict[str, Any]) -> bool:
    path = thread.get("path")
    if path and os.path.isfile(path):
        return rollout_is_active(path)

    status = thread.get("status") or {}
    return status.get("type") == "active"


def rollout_is_active(
    path: str, tail_bytes: int = 1024 * 1024, stale_seconds: int = 30 * 60
) -> bool:
    try:
        size = os.path.getsize(path)
        if time.time() - os.path.getmtime(path) > stale_seconds:
            return False
        with open(path, "rb") as handle:
            if size > tail_bytes:
                handle.seek(size - tail_bytes)
                handle.readline()
            lines = handle.readlines()
    except OSError:
        return False

    for raw_line in reversed(lines):
        try:
            record = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if record.get("type") != "event_msg":
            continue
        event_type = (record.get("payload") or {}).get("type")
        if event_type == "task_complete":
            return False
        if event_type == "task_started":
            return True
    return False


def rollout_turn_state(
    path: str, turn_id: str, tail_bytes: int = 1024 * 1024
) -> Optional[bool]:
    """Return True/False for this exact turn, or None if no boundary exists."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            if size > tail_bytes:
                handle.seek(size - tail_bytes)
                handle.readline()
            lines = handle.readlines()
    except OSError:
        return None

    for raw_line in reversed(lines):
        try:
            record = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if record.get("type") != "event_msg":
            continue
        payload = record.get("payload") or {}
        if payload.get("turn_id") != turn_id:
            continue
        if payload.get("type") == "task_complete":
            return False
        if payload.get("type") == "task_started":
            return True
    return None


def active_thread_state(
    threads: Iterable[Dict[str, Any]]
) -> Tuple[int, Set[str]]:
    count = 0
    paths: Set[str] = set()
    for thread in threads:
        if not thread_is_active(thread):
            continue
        count += 1
        path = thread.get("path")
        if path:
            paths.add(os.path.realpath(path))
    return count, paths


async def collect_snapshot(client: Any) -> Snapshot:
    snapshot, _ = await collect_snapshot_state(client)
    return snapshot


async def collect_snapshot_state(client: Any) -> Tuple[Snapshot, Set[str]]:
    rate_limits, usage, thread_result = await gather_metrics(client)
    threads = thread_result.get("data") or []
    snapshot = build_snapshot(rate_limits, usage, threads)
    _, active_paths = active_thread_state(threads)
    return snapshot, active_paths


async def collect_active_thread_state(
    client: Any, limit: int = 100
) -> Tuple[int, Set[str]]:
    result = await client.request(
        "thread/list",
        {
            "limit": limit,
            "sortKey": "recency_at",
            "sortDirection": "desc",
            "useStateDbOnly": True,
        },
    )
    return active_thread_state(result.get("data") or [])


async def gather_metrics(client: Any) -> List[Dict[str, Any]]:
    import asyncio

    results = await asyncio.gather(
        client.request("account/rateLimits/read"),
        client.request("account/usage/read"),
        client.request(
            "thread/list",
            {
                "limit": 100,
                "sortKey": "recency_at",
                "sortDirection": "desc",
                "useStateDbOnly": True,
            },
        ),
    )
    return list(results)
