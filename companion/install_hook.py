#!/usr/bin/env python3
"""Install or remove the global Codex Usage Display lifecycle hooks."""

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict


SCRIPT_NAME = "codex_display_event.py"
EVENTS = ("UserPromptSubmit", "Stop")


def hook_group(script_path: Path) -> Dict[str, Any]:
    command = f'/usr/bin/python3 "{script_path}"'
    return {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 2,
            }
        ]
    }


def belongs_to_display(group: Any) -> bool:
    if not isinstance(group, dict):
        return False
    handlers = group.get("hooks")
    if not isinstance(handlers, list):
        return False
    return any(
        isinstance(handler, dict)
        and SCRIPT_NAME in str(handler.get("command", ""))
        for handler in handlers
    )


def updated_config(
    config: Dict[str, Any], script_path: Path, uninstall: bool
) -> Dict[str, Any]:
    result = dict(config)
    existing_hooks = result.get("hooks") or {}
    if not isinstance(existing_hooks, dict):
        raise ValueError("hooks must be a JSON object")
    hooks = dict(existing_hooks)
    for event in EVENTS:
        groups = hooks.get(event) or []
        if not isinstance(groups, list):
            raise ValueError(f"hooks.{event} must be a list")
        groups = [group for group in groups if not belongs_to_display(group)]
        if not uninstall:
            groups.append(hook_group(script_path))
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    result["hooks"] = hooks
    if not uninstall and "description" not in result:
        result["description"] = "User-level Codex lifecycle hooks."
    return result


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("global hooks.json must contain a JSON object")
    return value


def write_config(path: Path, config: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix="hooks.", suffix=".json", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install Codex Usage Display global hooks"
    )
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    repository = Path(__file__).resolve().parents[1]
    script_path = repository / ".codex" / "hooks" / SCRIPT_NAME
    config_path = Path.home() / ".codex" / "hooks.json"
    config = updated_config(
        load_config(config_path),
        script_path.resolve(),
        args.uninstall,
    )
    write_config(config_path, config)
    action = "Removed" if args.uninstall else "Installed"
    print(f"{action} Codex Usage Display hooks in {config_path}")


if __name__ == "__main__":
    main()
