import argparse
import asyncio
import logging
from dataclasses import replace
from typing import Optional, Set

from .app_server import AppServerClient
from .ble import BleCompanion
from .hook_events import HookActivityTracker
from .local_usage import read_local_tokens
from .metrics import (
    Snapshot,
    collect_active_thread_state,
    collect_snapshot_state,
)
from .protocol import encode_snapshot


class SnapshotCache:
    def __init__(self, client: AppServerClient, refresh_seconds: float) -> None:
        self._client = client
        self._refresh_seconds = refresh_seconds
        self._snapshot: Optional[Snapshot] = None
        self._updated_at = 0.0
        self._sequence = 0
        self._lock = asyncio.Lock()
        self._active_paths: Set[str] = set()
        self._activity: Optional[HookActivityTracker] = None
        self.status_changed = asyncio.Event()

    def attach_activity(self, activity: HookActivityTracker) -> None:
        self._activity = activity

    def _active_count(self) -> int:
        assert self._snapshot is not None
        extra = (
            self._activity.extra_count(self._active_paths)
            if self._activity is not None
            else 0
        )
        return self._snapshot.active_threads + extra

    def _current_snapshot(self) -> Snapshot:
        assert self._snapshot is not None
        snapshot = self._snapshot
        if snapshot.tokens_today_estimated:
            local_tokens = read_local_tokens()
            if local_tokens is not None:
                snapshot = replace(snapshot, tokens_today=local_tokens)
        return replace(snapshot, active_threads=self._active_count())

    async def encoded(self) -> bytes:
        loop = asyncio.get_running_loop()
        if (
            self._snapshot is None
            or loop.time() - self._updated_at >= self._refresh_seconds
        ):
            await self.refresh()
        assert self._snapshot is not None
        snapshot = self._current_snapshot()
        return encode_snapshot(snapshot, self._sequence)

    async def refresh(self) -> None:
        async with self._lock:
            self._snapshot, self._active_paths = await collect_snapshot_state(
                self._client
            )
            self._updated_at = asyncio.get_running_loop().time()
            self._sequence += 1
            current = self._current_snapshot()
            logging.info(
                "数据已更新：剩余 %d%%，today %s%d，7d %d，reset %d，running %d",
                current.remaining_percent,
                "~" if current.tokens_today_estimated else "",
                current.tokens_today,
                current.tokens_7d,
                current.reset_credits,
                current.active_threads,
            )

    async def activity_changed(self) -> None:
        async with self._lock:
            self._sequence += 1
            self.status_changed.set()

    async def reconcile_active(self) -> None:
        count, paths = await collect_active_thread_state(self._client)
        async with self._lock:
            if self._snapshot is None:
                return
            before = self._active_count()
            self._snapshot = replace(self._snapshot, active_threads=count)
            self._active_paths = paths
            if self._active_count() != before:
                self._sequence += 1
                self.status_changed.set()


async def reconcile_active_loop(
    cache: SnapshotCache, seconds: float
) -> None:
    while True:
        await asyncio.sleep(seconds)
        try:
            await cache.reconcile_active()
        except Exception as error:
            logging.warning("RUN 定期校准失败：%s", error)


async def run(args: argparse.Namespace) -> None:
    client = AppServerClient(args.codex_bin)
    await client.start()
    try:
        cache = SnapshotCache(client, args.refresh_seconds)
        if args.once:
            print((await cache.encoded()).decode("utf-8"))
            return

        activity = HookActivityTracker(cache.activity_changed)
        cache.attach_activity(activity)
        companion = BleCompanion(
            cache.encoded,
            cache.refresh,
            device_name=args.device,
            heartbeat_seconds=args.heartbeat_seconds,
            status_changed=cache.status_changed,
        )
        hook_task = asyncio.create_task(activity.run_forever())
        reconcile_task = asyncio.create_task(
            reconcile_active_loop(cache, args.run_reconcile_seconds)
        )
        try:
            await companion.run_forever()
        finally:
            hook_task.cancel()
            reconcile_task.cancel()
    finally:
        await client.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Codex Usage Display macOS BLE Companion"
    )
    parser.add_argument("--device", default="Codex Display")
    parser.add_argument("--codex-bin")
    parser.add_argument("--refresh-seconds", type=float, default=60)
    parser.add_argument("--heartbeat-seconds", type=float, default=15)
    parser.add_argument("--run-reconcile-seconds", type=float, default=30)
    parser.add_argument(
        "--once",
        action="store_true",
        help="读取一次真实 Codex 数据并打印，不连接 BLE",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
