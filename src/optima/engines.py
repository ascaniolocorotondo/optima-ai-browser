"""Browser engines. Both expose the same small interface used by browser.py.

- WebKitEngine: macOS. Drives the native Optima.app (system WebKit) over stdin/stdout.
- PlaywrightEngine: Windows, Linux (and macOS if you prefer). Uses Chrome/Edge when
  installed, otherwise Playwright's Chromium.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import brand, config

_PAGE_SCRIPT = (config.PACKAGE_DIR / "page_script.js").read_text("utf-8")


class EngineError(RuntimeError):
    pass


def call_js(fn: str, *args: Any) -> str:
    """Builds an expression that injects the page script once and calls window.__ab.<fn>."""
    a = ", ".join(json.dumps(x) for x in args)
    return "(function(){" + _PAGE_SCRIPT + ";return JSON.stringify(window.__ab." + fn + "(" + a + "));})()"


class Engine:
    native_handoff = False

    def start(self) -> None: ...
    def alive(self) -> bool: return False
    def stop(self) -> None: ...
    def navigate(self, url: str, timeout: float = 30) -> Dict[str, Any]: raise NotImplementedError
    def set_content(self, html: str) -> None: raise NotImplementedError
    def eval(self, js: str) -> Any: raise NotImplementedError
    def wait_idle(self, timeout: float = 15) -> Dict[str, Any]: raise NotImplementedError
    def history(self, action: str) -> Dict[str, Any]: raise NotImplementedError
    def screenshot(self) -> bytes: raise NotImplementedError
    def focus(self) -> None: ...
    def dialogs(self) -> List[str]: return []

    # High-level helpers shared by engines (overridable for real input events).
    def ab(self, fn: str, *args: Any) -> Any:
        raw = self.eval(call_js(fn, *args))
        return json.loads(raw) if isinstance(raw, str) else raw

    def click(self, element_id: str) -> Dict[str, Any]:
        return self.ab("click", element_id)

    def type(self, element_id: str, text: str, submit: bool) -> Dict[str, Any]:
        return self.ab("type", element_id, text, submit)

    # Hand-off to the human.
    def handoff_begin(self, message: str, button: str) -> None:
        self.focus()
        self.ab("overlay", message, button)
        self._overlay = (message, button)

    def handoff_done(self) -> bool:
        try:
            done = self.eval("(function(){return window.__abHumanDone?'1':'0';})()") == "1"
            if not done:
                self.ab("overlay", *self._overlay)  # re-add after a navigation
            return done
        except Exception:
            return False

    def handoff_end(self) -> None:
        try:
            self.ab("removeOverlay")
            self.eval("(function(){window.__abHumanDone=false;return '';})()")
        except Exception:
            pass


class WebKitEngine(Engine):
    native_handoff = True

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.proc: Optional[subprocess.Popen] = None
        self.lines: "queue.Queue[str]" = queue.Queue()
        self.next_id = 1

    def start(self) -> None:
        app = config.webkit_app_path()
        binary = app / "Contents" / "MacOS" / "OptimaEngine"
        if not binary.exists():
            raise EngineError(f"macOS engine not built. Run: sh engines/macos/build.sh  (looked in {app})")
        suffix = "Version/18.0 Safari/605.1.15"
        if self.cfg.get("identify_as_agent", True):
            from . import __version__
            suffix += " " + brand.ua_suffix(__version__)
        self.proc = subprocess.Popen(
            [str(binary), "--ua-suffix", suffix, "--title", brand.FULL_NAME],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=None if os.environ.get("OPTIMA_DEBUG") else subprocess.DEVNULL,
            text=True, bufsize=1, encoding="utf-8",
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                msg = json.loads(self.lines.get(timeout=0.5))
                if msg.get("event") == "ready":
                    return
            except queue.Empty:
                if self.proc.poll() is not None:
                    break
            except ValueError:
                continue
        raise EngineError("macOS engine did not start")

    def _reader(self, proc: subprocess.Popen) -> None:
        assert proc.stdout
        for line in proc.stdout:
            self.lines.put(line)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.alive():
            try:
                self._call("quit", timeout=3)
            except Exception:
                pass
            try:
                self.proc.wait(3)  # type: ignore[union-attr]
            except Exception:
                self.proc.kill()  # type: ignore[union-attr]

    def _call(self, cmd: str, timeout: float = 45, **args: Any) -> Any:
        if not self.alive():
            raise EngineError("browser window was closed")
        mid = self.next_id
        self.next_id += 1
        assert self.proc and self.proc.stdin
        # The engine's own wait ends a little before ours, so it can still answer.
        args = dict(args, timeout=max(1.0, timeout - 3))
        self.proc.stdin.write(json.dumps({"id": mid, "cmd": cmd, "args": args}) + "\n")
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self.lines.get(timeout=0.25)
            except queue.Empty:
                if not self.alive():
                    raise EngineError("browser window was closed")
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") != mid:
                continue
            if not msg.get("ok"):
                raise EngineError(msg.get("error", "engine error"))
            return msg.get("result")
        raise EngineError(f"engine timed out on {cmd}")

    def navigate(self, url: str, timeout: float = 30) -> Dict[str, Any]:
        return self._call("navigate", timeout=timeout + 5, url=url)

    def set_content(self, html: str) -> None:
        self._call("set_content", html=html, timeout=10)

    def eval(self, js: str) -> Any:
        return self._call("eval", js=js)

    def wait_idle(self, timeout: float = 15) -> Dict[str, Any]:
        return self._call("wait_idle", timeout=timeout + 3)

    def history(self, action: str) -> Dict[str, Any]:
        return self._call(action, timeout=20)

    def screenshot(self) -> bytes:
        return base64.b64decode(self._call("screenshot"))

    def focus(self) -> None:
        self._call("focus")

    def dialogs(self) -> List[str]:
        return self._call("dialogs") or []

    def handoff_begin(self, message: str, button: str) -> None:
        self._call("handoff_begin", message=message, button=button)

    def handoff_done(self) -> bool:
        return bool((self._call("handoff_status") or {}).get("done"))

    def handoff_end(self) -> None:
        self._call("handoff_end")


class PlaywrightEngine(Engine):
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.pw = None
        self.ctx = None
        self.page = None
        self._dialogs: List[str] = []

    def start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise EngineError("Playwright is not installed. Run the install script for your system.") from e
        self.pw = sync_playwright().start()
        config.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        wanted = self.cfg.get("playwright_channel", "auto")
        channels = ["chrome", "msedge", None] if wanted == "auto" else [None if wanted == "chromium" else wanted]
        last: Optional[Exception] = None
        for ch in channels:
            try:
                kw: Dict[str, Any] = dict(headless=bool(self.cfg.get("headless")), no_viewport=True,
                                          args=["--disable-features=Translate"])
                if ch:
                    kw["channel"] = ch
                self.ctx = self.pw.chromium.launch_persistent_context(str(config.PROFILE_DIR), **kw)
                break
            except Exception as e:  # browser channel not installed: try the next one
                last = e
        if self.ctx is None:
            raise EngineError(f"could not launch a browser: {last}")
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.ctx.on("page", self._on_page)
        self._watch(self.page)
        if self.cfg.get("identify_as_agent", True):
            from . import __version__
            ua = self.page.evaluate("navigator.userAgent")
            self.ctx.set_extra_http_headers({"User-Agent": ua + " " + brand.ua_suffix(__version__)})

    def _on_page(self, page: Any) -> None:
        # Single-tab model: a new tab becomes the current page.
        self.page = page
        self._watch(page)

    def _watch(self, page: Any) -> None:
        def on_dialog(d: Any) -> None:
            if d.type == "alert":
                self._dialogs.append("alert: " + d.message)
                d.accept()
            else:
                self._dialogs.append(f"{d.type} (answered cancel): {d.message}")
                d.dismiss()
        page.on("dialog", on_dialog)
        page.on("close", lambda *_: self._page_closed(page))

    def _page_closed(self, page: Any) -> None:
        if self.page is page and self.ctx is not None:
            pages = [p for p in self.ctx.pages if not p.is_closed()]
            self.page = pages[-1] if pages else None

    def alive(self) -> bool:
        try:
            return self.ctx is not None and self.page is not None and not self.page.is_closed()
        except Exception:
            return False

    def stop(self) -> None:
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self.pw:
                self.pw.stop()
            self.ctx = self.pw = self.page = None

    def navigate(self, url: str, timeout: float = 30) -> Dict[str, Any]:
        info: Dict[str, Any] = {"timed_out": False}
        try:
            self.page.goto(url, wait_until="load", timeout=timeout * 1000)
        except Exception as e:
            if "Timeout" in type(e).__name__ or "Timeout" in str(e):
                info["timed_out"] = True
            else:
                info["error"] = str(e).splitlines()[0]
        info.update(url=self.page.url, title=self.page.title())
        return info

    def set_content(self, html: str) -> None:
        self.page.set_content(html)

    def eval(self, js: str) -> Any:
        return self.page.evaluate(js)

    def wait_idle(self, timeout: float = 15) -> Dict[str, Any]:
        time.sleep(0.35)
        timed_out = False
        try:
            self.page.wait_for_load_state("load", timeout=timeout * 1000)
        except Exception:
            timed_out = True
        return {"url": self.page.url, "title": self.page.title(), "timed_out": timed_out}

    def history(self, action: str) -> Dict[str, Any]:
        fn = {"back": self.page.go_back, "forward": self.page.go_forward, "reload": self.page.reload}[action]
        try:
            fn(timeout=20000)
        except Exception:
            pass
        return {"url": self.page.url, "title": self.page.title()}

    def screenshot(self) -> bytes:
        return self.page.screenshot(type="png")

    def focus(self) -> None:
        try:
            self.page.bring_to_front()
        except Exception:
            pass

    def dialogs(self) -> List[str]:
        d, self._dialogs = self._dialogs, []
        return d

    # Real mouse and keyboard events where Playwright can provide them.
    def click(self, element_id: str) -> Dict[str, Any]:
        sel = f'[data-ab-id="{element_id}"]'
        try:
            self.page.click(sel, timeout=5000)
            return {"ok": True}
        except Exception:
            return self.ab("click", element_id)

    def type(self, element_id: str, text: str, submit: bool) -> Dict[str, Any]:
        sel = f'[data-ab-id="{element_id}"]'
        try:
            self.page.fill(sel, text, timeout=5000)
            if submit:
                self.page.press(sel, "Enter")
            return {"ok": True}
        except Exception:
            return self.ab("type", element_id, text, submit)


def make_engine(cfg: Dict[str, Any]) -> Engine:
    kind = config.resolve_engine(cfg)
    return WebKitEngine(cfg) if kind == "webkit" else PlaywrightEngine(cfg)
