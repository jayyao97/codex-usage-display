#!/usr/bin/env python3
"""Install or remove the macOS LaunchAgent for the BLE companion."""

import argparse
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict


LABEL = "com.jayyao.codex-usage-display"


def build_plist(repository: Path, home: Path) -> Dict[str, Any]:
    python = repository / "companion" / ".venv" / "bin" / "python"
    logs = home / "Library" / "Logs" / "CodexUsageDisplay"
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(python),
            "-m",
            "companion.codex_display",
        ],
        "WorkingDirectory": str(repository),
        "EnvironmentVariables": {
            "PYTHONPATH": str(repository),
            "CODEX_DISPLAY_LOG": str(logs / "companion.log"),
        },
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }


def prepare_environment(repository: Path) -> None:
    companion = repository / "companion"
    python = companion / ".venv" / "bin" / "python"
    if not python.exists():
        subprocess.run(
            [sys.executable, "-m", "venv", str(companion / ".venv")],
            check=True,
        )
    result = subprocess.run(
        [str(python), "-c", "import bleak"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "-r",
                str(companion / "requirements.txt"),
            ],
            check=True,
        )


def write_plist(path: Path, config: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=LABEL + ".",
        suffix=".plist",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            plistlib.dump(config, handle, sort_keys=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def launchctl(*args: str, check: bool = True) -> None:
    subprocess.run(
        ["launchctl", *args],
        check=check,
        stdout=None if check else subprocess.DEVNULL,
        stderr=None if check else subprocess.DEVNULL,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install Codex Usage Display as a macOS LaunchAgent"
    )
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    repository = Path(__file__).resolve().parents[1]
    home = Path.home()
    plist_path = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LABEL}"

    launchctl("bootout", service, check=False)
    if args.uninstall:
        plist_path.unlink(missing_ok=True)
        print(f"Removed {LABEL}")
        return

    prepare_environment(repository)
    (home / "Library" / "Logs" / "CodexUsageDisplay").mkdir(
        parents=True,
        exist_ok=True,
    )
    write_plist(plist_path, build_plist(repository, home))
    launchctl("bootstrap", domain, str(plist_path))
    launchctl("kickstart", "-k", service)
    print(f"Installed and started {LABEL}")


if __name__ == "__main__":
    main()
