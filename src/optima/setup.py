"""First run: choose the language, install the skill, connect the assistants."""
from __future__ import annotations

import base64
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import brand, config
from .engines import EngineError, make_engine
from .i18n import LANGUAGES, STRINGS, t

SKILL_SRC = config.REPO_DIR / "skill" / brand.SLUG


# ---------- where things live ----------

def find_claude_cli() -> Optional[str]:
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    candidates = [home / ".local" / "bin" / "claude", home / ".claude" / "local" / "claude"]
    if sys.platform == "win32":
        candidates += [home / ".local" / "bin" / "claude.exe", home / "AppData" / "Roaming" / "npm" / "claude.cmd"]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def detect_clients() -> List[Dict[str, Any]]:
    return [
        {"key": "claude_code", "found": bool(find_claude_cli()) or (Path.home() / ".claude").exists()},
        {"key": "claude_desktop", "found": desktop_config_path().parent.exists()},
    ]


def server_command() -> Dict[str, Any]:
    """How assistants start Optima's MCP server."""
    return {
        "command": sys.executable,
        "args": ["-m", brand.SLUG, "mcp"],
        "env": {"PYTHONPATH": str(config.REPO_DIR / "src")},
    }


# ---------- install steps ----------

def install_skill() -> Path:
    dest = Path.home() / ".claude" / "skills" / brand.SLUG
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SKILL_SRC, dest)
    return dest


def skill_zip() -> Path:
    config.HOME.mkdir(parents=True, exist_ok=True)
    out = config.HOME / f"{brand.SLUG}-skill.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in SKILL_SRC.rglob("*"):
            if f.is_file():
                z.write(f, Path(brand.SLUG) / f.relative_to(SKILL_SRC))
    return out


def register_claude_code(lang: str) -> str:
    sc = server_command()
    spec = json.dumps(dict(type="stdio", **sc))
    cli = find_claude_cli()
    manual = f"claude mcp add-json --scope user {brand.SLUG} '{spec}'"
    if not cli:
        return t(lang, "cli_code_manual", cmd=manual)
    subprocess.run([cli, "mcp", "remove", "--scope", "user", brand.SLUG], capture_output=True, timeout=30)
    # add-json avoids the variadic --env option swallowing the server name.
    r = subprocess.run([cli, "mcp", "add-json", "--scope", "user", brand.SLUG, spec],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return t(lang, "cli_code_manual", cmd=manual) + "\n" + (r.stderr or r.stdout).strip()
    return t(lang, "cli_code_ok")


def register_claude_desktop(lang: str) -> List[str]:
    path = desktop_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text("utf-8") or "{}")
        except ValueError:
            data = {}
        shutil.copy2(path, path.with_name(path.name + f".bak-{int(time.time())}"))
    data.setdefault("mcpServers", {})[brand.SLUG] = server_command()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    return [t(lang, "cli_desktop_ok", path=str(path)), t(lang, "cli_desktop_skill", path=str(skill_zip()))]


def apply(lang: str, clients: List[str]) -> List[str]:
    cfg = config.load()
    cfg["language"] = lang
    config.save(cfg)
    results: List[str] = []
    try:
        results.append(t(lang, "cli_skill_ok", path=str(install_skill())))
    except OSError as e:
        results.append(f"Skill: {e}")
    if "claude_code" in clients:
        try:
            results.append(register_claude_code(lang))
        except Exception as e:
            results.append(f"Claude Code: {e}")
    if "claude_desktop" in clients:
        try:
            results.extend(register_claude_desktop(lang))
        except Exception as e:
            results.append(f"Claude Desktop: {e}")
    return results


# ---------- first-run screens ----------

def welcome_html() -> str:
    html = (config.PACKAGE_DIR / "welcome.html").read_text("utf-8")
    icon = config.REPO_DIR / "assets" / "icon-256.png"
    icon_uri = "data:image/png;base64," + base64.b64encode(icon.read_bytes()).decode() if icon.exists() else ""
    return (html.replace("__STRINGS__", json.dumps(STRINGS, ensure_ascii=False))
                .replace("__LANGS__", json.dumps(LANGUAGES, ensure_ascii=False))
                .replace("__CLIENTS__", json.dumps(detect_clients()))
                .replace("__ICON__", icon_uri))


def run_gui() -> bool:
    cfg = config.load()
    engine = make_engine(cfg)
    try:
        engine.start()
    except EngineError as e:
        print(f"Could not open the first-run window ({e}). Falling back to the terminal.")
        return False
    try:
        engine.set_content(welcome_html())
        engine.focus()
        choice = None
        while choice is None:
            time.sleep(0.5)
            if not engine.alive():
                print("Window closed before setup finished. Run setup again any time.")
                return True
            raw = engine.eval("(function(){return JSON.stringify(window.__optimaSetup||null)})()")
            choice = json.loads(raw) if raw else None
        results = apply(choice["lang"], choice.get("clients", []))
        results.append(t(choice["lang"], "cli_done"))
        engine.eval("(function(){return window.__optimaDone(" + json.dumps(results, ensure_ascii=False) + ")})()")
        print("\n".join(results))
        # Leave the window open so the person can log in to their sites; quit when they close it.
        while engine.alive():
            time.sleep(1)
        return True
    finally:
        try:
            engine.stop()
        except Exception:
            pass


def run_cli() -> None:
    codes = list(LANGUAGES)
    for i, c in enumerate(codes, 1):
        print(f"  {i}. {LANGUAGES[c]}")
    lang = "en"
    while True:
        ans = input(" / ".join(STRINGS[c]["cli_language"].strip() for c in ("en", "it")) + " ").strip()
        if ans.isdigit() and 1 <= int(ans) <= len(codes):
            lang = codes[int(ans) - 1]
            break
    print("\n" + t(lang, "welcome_title") + "\n" + t(lang, "welcome_body") + "\n")
    picked = []
    for cl in detect_clients():
        if not cl["found"]:
            continue
        a = input(f"{t(lang, cl['key'])}? {t(lang, 'cli_yes_no')} ").strip().lower()
        if a in ("", "y", "s", "o", "j", "yes", "si", "sì", "oui", "ja", "sim"):
            picked.append(cl["key"])
    for line in apply(lang, picked):
        print(" • " + line)
    print("\n" + t(lang, "cli_done"))


def main(argv: List[str]) -> None:
    if "--cli" in argv or not run_gui():
        run_cli()
