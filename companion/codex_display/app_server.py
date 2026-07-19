import asyncio
import json
import os
import shutil
from typing import Any, Dict, Optional


class AppServerError(RuntimeError):
    pass


def find_codex_binary() -> str:
    configured = os.environ.get("CODEX_BIN")
    if configured:
        return configured

    found = shutil.which("codex")
    if found:
        return found

    bundled = "/Applications/ChatGPT.app/Contents/Resources/codex"
    if os.path.isfile(bundled):
        return bundled

    raise AppServerError(
        "找不到 Codex CLI；请设置 CODEX_BIN，或安装包含 codex 的 ChatGPT/Codex App"
    )


class AppServerClient:
    def __init__(self, codex_binary: Optional[str] = None) -> None:
        self._codex_binary = codex_binary or find_codex_binary()
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._pending: Dict[int, asyncio.Future] = {}
        self._next_id = 1

    async def start(self) -> None:
        if self._process is not None:
            return

        self._process = await asyncio.create_subprocess_exec(
            self._codex_binary,
            "app-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=2 * 1024 * 1024,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        await self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex_usage_display",
                    "title": "Codex Usage Display",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.notify("initialized", {})

    async def stop(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._reader_task = None

    async def wait_for_exit(self) -> None:
        if self._reader_task is None:
            raise AppServerError("Codex app-server 尚未启动")
        await self._reader_task
        raise AppServerError("Codex app-server 已退出")

    async def request(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[request_id] = future

        message: Dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            message["params"] = params
        await self._send(message)

        try:
            return await asyncio.wait_for(future, timeout=20)
        finally:
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: Dict[str, Any]) -> None:
        await self._send({"method": method, "params": params})

    async def _send(self, message: Dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise AppServerError("Codex app-server 尚未启动")
        payload = json.dumps(message, separators=(",", ":")) + "\n"
        self._process.stdin.write(payload.encode("utf-8"))
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._process is not None
        assert self._process.stdout is not None
        while True:
            line = await self._process.stdout.readline()
            if not line:
                error = AppServerError("Codex app-server 已退出")
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(error)
                return

            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue

            request_id = message.get("id")
            if request_id not in self._pending:
                continue

            future = self._pending[request_id]
            if "error" in message:
                error = message["error"]
                future.set_exception(
                    AppServerError(
                        "{}: {}".format(error.get("code"), error.get("message"))
                    )
                )
            elif not future.done():
                future.set_result(message.get("result", {}))
