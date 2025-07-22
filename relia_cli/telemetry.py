"""Relia CLI Telemetry Module

Opt‑in local telemetry: writes anonymized JSON lines to ~/.relia-data/telemetry.log
Configuration toggled via ~/.reliarc or `relia-cli telemetry <enable|disable|status>`.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Paths for telemetry storage and config
data_dir = Path.home() / ".relia-data"
config_path = data_dir / "config.json"
log_path = data_dir / "telemetry.log"

# Default config if none exists
default_config: Dict[str, Any] = {"telemetry_enabled": False}


def _ensure_paths() -> None:
    """Ensure the telemetry directory and files exist."""
    data_dir.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(json.dumps(default_config))
    log_path.touch(exist_ok=True)


def is_enabled() -> bool:
    """Return True if telemetry is currently enabled."""
    _ensure_paths()
    try:
        cfg = json.loads(config_path.read_text())
        return bool(cfg.get("telemetry_enabled", False))
    except Exception:
        return False


def set_enabled(enabled: bool) -> None:
    """Enable or disable telemetry in the config."""
    _ensure_paths()
    config_path.write_text(json.dumps({"telemetry_enabled": bool(enabled)}))


def record(event: str, data: Dict[str, Any] | None = None) -> None:
    """Record an event to the telemetry log if enabled."""
    if not is_enabled():
        return
    entry = {
        "event": event,
        "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
        "data": data or {},
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
