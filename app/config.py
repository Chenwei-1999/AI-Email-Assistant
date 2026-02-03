import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

DEFAULT_CONFIG: Dict[str, Any] = {
    "openai": {
        "api_base": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "completion_window": "24h",
        "timeout_sec": 60,
    },
    "gmail": {
        "profile_dir": ".gmail_profile",
        "headless": False,
        "cdp_url": "http://127.0.0.1:18800",
        "login_timeout_sec": 600,
        "max_unread": 20,
        "search_query": "is:unread in:inbox",
        "self_email": "",
        "summary_subject": "Daily email summary",
        "reply_signature": "",
    },
    "rules": {
        "max_body_chars": 4000,
    },
    "state_dir": ".state",
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return deep_merge(DEFAULT_CONFIG, raw)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(key)
    if val:
        return val
    return default
