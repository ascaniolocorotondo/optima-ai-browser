"""Command line: python -m optima <command>

  setup     first run: language, skill, connect assistants (add --cli for terminal only)
  mcp       run the MCP server (what assistants start)
  open URL  open the browser yourself, e.g. to log in to your sites
  doctor    check the installation
"""
from __future__ import annotations

import json
import sys
import time

from . import __version__, brand, config


def doctor() -> None:
    cfg = config.load()
    engine = config.resolve_engine(cfg)
    print(f"{brand.FULL_NAME} {__version__}")
    print(f"  python:   {sys.executable} ({sys.version.split()[0]})")
    print(f"  config:   {config.CONFIG_FILE} ({'found' if config.CONFIG_FILE.exists() else 'missing: run setup'})")
    print(f"  language: {cfg.get('language') or '(not chosen yet)'}")
    print(f"  engine:   {engine}")
    if engine == "webkit":
        app = config.webkit_app_path()
        print(f"  app:      {app} ({'ok' if app.exists() else 'missing: run engines/macos/build.sh'})")
    else:
        try:
            import playwright  # noqa: F401
            print("  playwright: ok")
        except ImportError:
            print("  playwright: missing (pip install playwright)")
    from .setup import desktop_config_path, find_claude_cli
    print(f"  claude cli: {find_claude_cli() or 'not found'}")
    p = desktop_config_path()
    registered = False
    if p.exists():
        try:
            registered = brand.SLUG in json.loads(p.read_text("utf-8")).get("mcpServers", {})
        except ValueError:
            pass
    print(f"  claude desktop: {'registered' if registered else 'not registered'}")


def open_url(url: str) -> None:
    from .browser import Browser
    b = Browser()
    print(b.open(url).split("\n\n", 1)[0])
    print("Close the window when you are done.")
    try:
        while b.engine and b.engine.alive():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    b.close()


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "help"
    if cmd == "mcp":
        from .mcp_server import main as run
        run()
    elif cmd == "setup":
        from .setup import main as run_setup
        run_setup(args[1:])
    elif cmd == "open" and len(args) > 1:
        open_url(args[1])
    elif cmd == "doctor":
        doctor()
    elif cmd in ("-v", "--version", "version"):
        print(__version__)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
