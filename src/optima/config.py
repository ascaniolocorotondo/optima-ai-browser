"""Config and data paths. Everything lives in one folder in the user's home."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from . import brand

HOME = Path(os.environ.get("OPTIMA_HOME", Path.home() / f".{brand.SLUG}"))
CONFIG_FILE = HOME / "config.json"
LOG_DIR = HOME / "logs"
PROFILE_DIR = HOME / "profile"          # Playwright profile (cookies, logins)
PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent.parent  # only meaningful in a source checkout
MACOS_SRC = PACKAGE_DIR / "macos"      # Swift sources of the macOS engine

DEFAULTS: Dict[str, Any] = {
    "language": None,                    # set on first run
    "engine": "auto",                    # auto | webkit (macOS) | playwright
    "playwright_channel": "auto",        # auto | chrome | msedge | chromium
    "headless": False,
    "identify_as_agent": True,           # add an honest AI-agent tag to the user agent
    "dismiss_cookie_banners": True,      # always picks "reject / only necessary"
    "auto_handoff": True,                # call the human when a check page appears
    "handoff_timeout_seconds": 300,
    "min_action_interval_ms": 400,       # gentle pace, no hammering sites
    "notify_desktop": True,
    "ntfy_topic": "",                    # optional: phone push via ntfy.sh
    "ntfy_server": "https://ntfy.sh",
    "policies": {
        # Actions the agent must confirm with the user before doing them.
        "confirm_before": ["purchase", "send", "delete"],
        # Actions that are never allowed.
        "block": [],
        # Password and payment-card fields are always left to the human.
        "human_only_fields": True,
    },
    "max_read_chars": 12000,
}


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text("utf-8"))
        except (OSError, ValueError):
            data = {}
    return _merge(DEFAULTS, data)


def save(cfg: Dict[str, Any]) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")
    tmp.replace(CONFIG_FILE)


def resolve_engine(cfg: Dict[str, Any]) -> str:
    e = cfg.get("engine", "auto")
    if e == "auto":
        return "webkit" if sys.platform == "darwin" else "playwright"
    return e


def webkit_app_path() -> Path:
    """Where the compiled macOS engine lives."""
    installed = HOME / "engine" / "Optima.app"
    if installed.exists():
        return installed
    return MACOS_SRC / "build" / "Optima.app"


def is_source_checkout() -> bool:
    """True when running from a git clone (src/optima), False when installed with pip."""
    return PACKAGE_DIR.parent.name == "src" and (REPO_DIR / "pyproject.toml").exists()


def build_macos_engine() -> Path:
    """Compiles the native macOS engine into ~/.optima/engine (needs the Swift compiler)."""
    import subprocess
    out = HOME / "engine"
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["sh", str(MACOS_SRC / "build.sh"), str(out)], check=True,
                   stdout=subprocess.DEVNULL)
    return out / "Optima.app"
