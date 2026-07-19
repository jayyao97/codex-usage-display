import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DEFAULT_USAGE_STATE_PATH = (
    Path.home()
    / "Library"
    / "Caches"
    / "CodexUsageDisplay"
    / "local-usage.json"
)


def read_local_tokens(
    path: Path = DEFAULT_USAGE_STATE_PATH,
    utc_date: Optional[str] = None,
) -> Optional[int]:
    utc_date = (
        datetime.now(timezone.utc).date().isoformat()
        if utc_date is None
        else utc_date
    )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("utc_date") != utc_date:
            return None
        return max(0, int(value.get("tokens", 0)))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
