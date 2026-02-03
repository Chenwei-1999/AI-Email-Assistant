import json
import re
from pathlib import Path
from typing import Any, Dict


def redact_sensitive(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"(?i)(verification code|security code|one-time code|验证码)[^\n]*", "[REDACTED_LINE]", text)
    text = re.sub(r"\b\d{6}\b", "[REDACTED_CODE]", text)
    return text


def trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def write_state(state_path: Path, state: Dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def read_state(state_path: Path) -> Dict[str, Any]:
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def completion_window_to_seconds(window: str) -> int:
    if window.endswith("h"):
        return int(window[:-1]) * 3600
    if window.endswith("m"):
        return int(window[:-1]) * 60
    return 24 * 3600
