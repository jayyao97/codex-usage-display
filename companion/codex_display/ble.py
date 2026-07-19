import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from .actions import perform_action
from .constants import (
    COMMAND_UUID,
    DEVICE_NAME,
    RESULT_UUID,
    SERVICE_UUID,
    STATUS_UUID,
)
from .protocol import decode_command, encode_result

logger = logging.getLogger(__name__)

BLE_OPERATION_TIMEOUT_SECONDS = 10
BLE_DISCONNECT_TIMEOUT_SECONDS = 5


class BleCompanion:
    def __init__(
        self,
        get_status: Callable[[], Awaitable[bytes]],
        request_refresh: Callable[[], Awaitable[None]],
        device_name: str = DEVICE_NAME,
        heartbeat_seconds: float = 15,
        status_changed: Optional[asyncio.Event] = None,
    ) -> None:
        self._get_status = get_status
        self._request_refresh = request_refresh
        self._device_name = device_name
        self._heartbeat_seconds = heartbeat_seconds
        self._status_changed = status_changed
        self._commands: asyncio.Queue = asyncio.Queue()
        self._recent_results = {}
        self.connected_event = asyncio.Event()

    async def run_forever(self) -> None:
        from bleak import BleakClient, BleakScanner

        backoff = 1.0
        while True:
            try:
                logger.info("正在搜索 %s…", self._device_name)
                device = await BleakScanner.find_device_by_filter(
                    lambda candidate, advertisement: (
                        (candidate.name or "") == self._device_name
                        or SERVICE_UUID.lower()
                        in [uuid.lower() for uuid in advertisement.service_uuids]
                    ),
                    timeout=10,
                    service_uuids=[SERVICE_UUID],
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.connected_event.clear()
                if "turned off" in str(error).lower():
                    logger.error(
                        "蓝牙不可用或当前启动程序没有权限；请检查“系统设置 → "
                        "隐私与安全性 → 蓝牙”"
                    )
                else:
                    logger.warning("BLE 扫描失败：%s", error)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            if device is None:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue

            disconnected = asyncio.Event()

            def on_disconnect(_: Any) -> None:
                self.connected_event.clear()
                disconnected.set()

            client = BleakClient(
                device, disconnected_callback=on_disconnect
            )
            try:
                await client.connect()
                backoff = 1.0
                logger.info("已连接 %s", device.name or device.address)
                await self._run_connection(client, disconnected)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("BLE 连接中断：%s", error)
            finally:
                self.connected_event.clear()
                await self._disconnect(client)

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _disconnect(self, client: Any) -> None:
        if not client.is_connected:
            return
        try:
            await asyncio.wait_for(
                client.disconnect(),
                timeout=BLE_DISCONNECT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("BLE 断开超时，继续重新扫描")
        except Exception as error:
            logger.warning("BLE 断开失败：%s", error)

    async def _run_connection(
        self, client: Any, disconnected: asyncio.Event
    ) -> None:
        def on_command(_: Any, data: bytearray) -> None:
            self._commands.put_nowait(bytes(data))

        await client.start_notify(COMMAND_UUID, on_command)
        await self._request_refresh()
        await self._send_status(client)
        if disconnected.is_set() or not client.is_connected:
            return
        self.connected_event.set()

        heartbeat = asyncio.create_task(self._heartbeat_loop(client))
        commands = asyncio.create_task(self._command_loop(client))
        wait_disconnect = asyncio.create_task(disconnected.wait())
        tasks = [heartbeat, commands, wait_disconnect]
        try:
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                if task is not wait_disconnect:
                    task.result()
        finally:
            self.connected_event.clear()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _heartbeat_loop(self, client: Any) -> None:
        while client.is_connected:
            if self._status_changed is None:
                await asyncio.sleep(self._heartbeat_seconds)
            else:
                try:
                    await asyncio.wait_for(
                        self._status_changed.wait(),
                        timeout=self._heartbeat_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
                self._status_changed.clear()
            await self._send_status(client)

    async def _send_status(self, client: Any) -> None:
        payload = await self._get_status()
        await self._write_gatt_char(client, STATUS_UUID, payload)

    async def _write_gatt_char(
        self, client: Any, uuid: str, payload: bytes
    ) -> None:
        try:
            await asyncio.wait_for(
                client.write_gatt_char(
                    uuid,
                    payload,
                    response=True,
                ),
                timeout=BLE_OPERATION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as error:
            raise asyncio.TimeoutError("BLE GATT 写入超时") from error

    async def _command_loop(self, client: Any) -> None:
        while client.is_connected:
            raw = await self._commands.get()
            request_id = 0
            try:
                command = decode_command(raw)
                request_id = command["id"]
                cache_key = (command["sid"], request_id)
                if cache_key in self._recent_results:
                    payload = self._recent_results[cache_key]
                    await self._write_gatt_char(
                        client, RESULT_UUID, payload
                    )
                    continue
                ok, message = await perform_action(command["a"], self._request_refresh)
            except ValueError as error:
                ok, message = False, str(error)
            except Exception as error:
                logger.exception("设备动作执行失败：%s", error)
                ok, message = False, "ACTION FAILED"
            payload = encode_result(request_id, ok, message)
            if request_id > 0:
                self._recent_results[cache_key] = payload
                if len(self._recent_results) > 32:
                    oldest = next(iter(self._recent_results))
                    del self._recent_results[oldest]
            await self._write_gatt_char(client, RESULT_UUID, payload)
            if ok:
                await self._send_status(client)
