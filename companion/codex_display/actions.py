import asyncio
import platform
from typing import Awaitable, Callable, Tuple


async def _run(*args: str) -> Tuple[bool, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode == 0:
        return True, ""
    return False, stderr.decode("utf-8", errors="replace").strip()


async def perform_action(
    action: str, refresh: Callable[[], Awaitable[None]]
) -> Tuple[bool, str]:
    if action not in {"refresh", "focus_codex", "new_task"}:
        return False, "NOT ALLOWED"

    if action == "refresh":
        await refresh()
        return True, "UPDATED"

    if platform.system() != "Darwin":
        return False, "MACOS ONLY"

    if action == "focus_codex":
        ok, _ = await _run("open", "-a", "ChatGPT")
        return (True, "FOCUSED") if ok else (False, "APP NOT FOUND")

    if action == "new_task":
        script = (
            'tell application "ChatGPT" to activate\n'
            "delay 0.3\n"
            'tell application "System Events" to keystroke "n" using command down'
        )
        ok, error = await _run("osascript", "-e", script)
        if ok:
            return True, "NEW TASK"
        if "not allowed" in error.lower() or "不允许" in error:
            return False, "ALLOW ACCESSIBILITY"
        return False, "ACTION FAILED"

    raise AssertionError("allowlisted action was not handled")
