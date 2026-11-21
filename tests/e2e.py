"""End-to-end test: drives the real MCP server and browser against a local test site.

    python tests/e2e.py                    # default engine for this OS
    python tests/e2e.py --engine playwright --headless
"""
import argparse
import functools
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ap = argparse.ArgumentParser()
ap.add_argument("--engine", default="auto")
ap.add_argument("--headless", action="store_true")
opts = ap.parse_args()

# Local test site on a free port.
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "tests" / "site"))
httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_address[1]}"

home = tempfile.mkdtemp(prefix="optima-test-")
Path(home, "config.json").write_text(json.dumps({
    "language": "it", "engine": opts.engine, "headless": opts.headless,
    "handoff_timeout_seconds": 15, "notify_desktop": False, "min_action_interval_ms": 0,
}))
env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), OPTIMA_HOME=home)
proc = subprocess.Popen([sys.executable, "-m", "optima", "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        text=True, encoding="utf-8", env=env)
n = 0


def rpc(method, params=None):
    global n
    n += 1
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n, "method": method, "params": params or {}}) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def tool(name, **args):
    r = rpc("tools/call", {"name": name, "arguments": args})["result"]
    c = r["content"][0]
    return bool(r.get("isError")), c.get("text") or c.get("data", "")


failures = []


def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)
        print("     " + detail[:800].replace("\n", "\n     "))


try:
    info = rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]
    check("initialize", info["serverInfo"]["name"] == "optima", str(info))
    check("tools/list", len(rpc("tools/list")["result"]["tools"]) == 11)

    err, out = tool("browser_open", url=base + "/")
    check("open page", not err and "Negozio" in out, out)
    if os.environ.get("OPTIMA_DEBUG"):
        print("DEBUG open result:\n" + out[:900])
    check("cookie banner declined", "Rifiuta tutto" in out and "Cookie rifiutati" in out, out)

    err, out = tool("browser_type", id="2", text="x")
    check("refuse typing into a button", err and "not a text field" in out, out)

    err, out = tool("browser_type", id="1", text="scarpe", submit=True)
    if "Risultati per: scarpe" not in out:  # diagnostics for slow engines
        print("DEBUG first result:\n" + out[:600])
        _, out = tool("browser_wait", seconds=2)
        print("DEBUG after 2s:\n" + out[:600])
    check("type + submit search", not err and "Risultati per: scarpe" in out, out)

    err, out = tool("browser_type", id="4", text="secret")
    check("password field left to the human", err and "password" in out.lower(), out)

    err, out = tool("browser_click", id="5")
    check("purchase needs confirmation", err and "purchase" in out, out)

    err, out = tool("browser_click", id="5", confirmed=True)
    check("confirmed purchase click + dialog reported", not err and "comprato" in out, out)

    err, out = tool("browser_click", id="6")
    check("human check detected and waited out", not err and "completed the human check" in out
          and "area protetta" in out.lower(), out)

    err, out = tool("browser_navigate", action="back")
    check("back", not err and "Negozio" in out, out)

    err, data = tool("browser_screenshot")
    check("screenshot", not err and len(data) > 1000, str(data)[:200])

    err, out = tool("browser_recent_actions")
    check("audit log", not err and "browser_open" in out, out)
finally:
    try:
        proc.stdin.close()
        proc.wait(20)
    except Exception:
        proc.kill()
    httpd.shutdown()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
