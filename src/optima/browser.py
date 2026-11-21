"""The agent-facing browser: reading, acting, safety rules and human hand-off."""
from __future__ import annotations

import datetime as _dt
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from . import config
from .engines import Engine, EngineError, make_engine
from .i18n import t
from .notify import notify

# Words that reveal what a button does, in the six supported languages.
_CATEGORIES: List[Tuple[str, re.Pattern]] = [
    ("purchase", re.compile(r"\b(buy|pay|purchase|checkout|place (your )?order|order now|subscribe|acquista|paga|compra|ordina|"
                            r"abbonati|comprar|pagar|suscribirse|acheter|payer|commander|s'abonner|kaufen|bezahlen|"
                            r"zahlungspflichtig|bestellen|abonnieren|assinar|finalizar compra)\b", re.I)),
    ("delete", re.compile(r"\b(delete|remove|erase|cancel (my )?(account|subscription)|elimina|cancella|rimuovi|borrar|eliminar|"
                          r"supprimer|effacer|löschen|entfernen|excluir|apagar)\b", re.I)),
    ("send", re.compile(r"\b(send|post|publish|tweet|reply|share|invia|pubblica|rispondi|condividi|enviar|publicar|responder|"
                        r"envoyer|publier|répondre|partager|senden|veröffentlichen|antworten|teilen|compartilhar)\b", re.I)),
]


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class ActionRefused(Exception):
    pass


class Browser:
    def __init__(self) -> None:
        self.cfg = config.load()
        self.engine: Optional[Engine] = None
        self._last_action = 0.0

    # ---------- lifecycle ----------

    @property
    def lang(self) -> str:
        return self.cfg.get("language") or "en"

    def ensure(self) -> Engine:
        if self.engine is None or not self.engine.alive():
            if self.engine is not None:
                try:
                    self.engine.stop()
                except Exception:
                    pass
            self.engine = make_engine(self.cfg)
            self.engine.start()
        return self.engine

    def close(self) -> None:
        if self.engine is not None:
            try:
                self.engine.stop()
            finally:
                self.engine = None

    # ---------- helpers ----------

    def _pace(self) -> None:
        gap = self.cfg.get("min_action_interval_ms", 400) / 1000.0
        wait = self._last_action + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last_action = time.time()

    def _log(self, tool: str, args: Dict[str, Any], result: str) -> None:
        try:
            config.LOG_DIR.mkdir(parents=True, exist_ok=True)
            f = config.LOG_DIR / (_dt.date.today().isoformat() + ".jsonl")
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": _now(), "tool": tool, "args": args, "result": result[:300]},
                                    ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _after_load(self) -> List[str]:
        """Runs after every page change: cookie banner, human check, JS dialogs."""
        e = self.ensure()
        notes: List[str] = []
        if self.cfg.get("dismiss_cookie_banners", True):
            try:
                r = e.ab("dismissCookies")
                if r and r.get("clicked"):
                    notes.append(f'Cookie banner dismissed with "{r["clicked"]}" (privacy-preserving choice).')
                    e.wait_idle(5)
            except Exception:
                pass
        try:
            challenge = e.ab("detectChallenge")
        except Exception:
            challenge = None
        if challenge:
            if self.cfg.get("auto_handoff", True):
                notes.append(self._handoff(challenge=challenge))
            else:
                notes.append(f"This page shows a human check ({challenge}). Call browser_ask_human so the user can complete it.")
        for d in e.dialogs():
            notes.append("Page dialog: " + d)
        return notes

    def _handoff(self, reason: str = "", challenge: Optional[str] = None) -> str:
        e = self.ensure()
        site = ""
        try:
            site = urlparse(json.loads(e.eval("(function(){return JSON.stringify(location.href)})()"))).netloc
        except Exception:
            pass
        if challenge:
            banner = t(self.lang, "handoff_challenge")
            body = t(self.lang, "notify_challenge", site=site or "?")
        else:
            banner = t(self.lang, "handoff_generic", reason=reason)
            body = t(self.lang, "notify_generic", reason=reason)
        notify(self.cfg, t(self.lang, "notify_title"), body)
        e.handoff_begin(banner, t(self.lang, "done_button"))
        timeout = float(self.cfg.get("handoff_timeout_seconds", 300))
        start = time.time()
        clear_streak = 0
        outcome = "timeout"
        try:
            while time.time() - start < timeout:
                time.sleep(1.0)
                if e.handoff_done():
                    outcome = "done"
                    break
                if challenge:
                    try:
                        still = e.ab("detectChallenge")
                    except Exception:
                        still = challenge
                    clear_streak = clear_streak + 1 if not still else 0
                    if clear_streak >= 2:
                        outcome = "cleared"
                        break
        finally:
            try:
                e.handoff_end()
            except EngineError:
                pass
        waited = int(time.time() - start)
        if outcome == "timeout":
            return f"Asked the user for help ({challenge or reason}) but they did not respond within {int(timeout)}s. Tell the user what you need and stop, or try again later."
        if challenge:
            return f"The user completed the human check ({challenge}) in {waited}s. Continuing."
        return f"The user finished ({waited}s): {reason}"

    def _snapshot(self, max_chars: Optional[int] = None) -> Dict[str, Any]:
        e = self.ensure()
        return e.ab("snapshot", int(max_chars or self.cfg.get("max_read_chars", 12000)))

    def _render(self, notes: List[str], max_chars: Optional[int] = None) -> str:
        snap = self._snapshot(max_chars)
        head = [f"URL: {snap.get('url', '')}", f"Title: {snap.get('title', '')}", f"Scroll: {snap.get('scroll', '')}"]
        if snap.get("challenge"):
            head.append(f"Human check still on page: {snap['challenge']}")
        out = "\n".join(head)
        if notes:
            out += "\n" + "\n".join("Note: " + n for n in notes)
        out += "\n\n" + (snap.get("text") or "(empty page)")
        if snap.get("truncated"):
            out += "\n\n[truncated: call browser_scroll then browser_read for more, or browser_read with a larger max_chars]"
        return out

    def _classify(self, info: Dict[str, Any], submitting: bool) -> List[str]:
        text = " ".join([info.get("text", ""), info.get("name", ""), info.get("form_action", "")])
        cats = [name for name, rx in _CATEGORIES if rx.search(text)]
        is_submit = submitting or info.get("type") == "submit" or (
            info.get("tag") == "button" and info.get("type") in ("", "submit") and info.get("in_form"))
        if is_submit:
            cats.append("submit")
        return cats

    def _check_policy(self, element_id: str, confirmed: bool, submitting: bool = False, typing: bool = False) -> None:
        e = self.ensure()
        info = e.ab("info", element_id)
        if not info:
            raise ActionRefused(f"No element with id {element_id}. Call browser_read to get fresh ids.")
        pol = self.cfg.get("policies", {})
        if typing and pol.get("human_only_fields", True):
            ac = info.get("autocomplete", "")
            if info.get("type") == "password" or ac.startswith("cc-") or "current-password" in ac or "new-password" in ac \
                    or re.search(r"card|cvv|cvc|iban", info.get("name", ""), re.I):
                raise ActionRefused("This is a password or payment field. Those are always entered by the human: "
                                    "call browser_ask_human and ask the user to fill it in.")
        cats = self._classify(info, submitting)
        blocked = [c for c in cats if c in pol.get("block", [])]
        if blocked:
            raise ActionRefused(f"Blocked by the user's rules: this looks like a {blocked[0]} action "
                                f"({info.get('text') or info.get('tag')}). Do not try another way.")
        need = [c for c in cats if c in pol.get("confirm_before", [])]
        if need and not confirmed:
            raise ActionRefused(f"This looks like a {need[0]} action (\"{info.get('text') or info.get('tag')}\"). "
                                "Ask the user to confirm in the chat, then call again with confirmed=true.")

    # ---------- tools ----------

    def open(self, url: str) -> str:
        if not re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I):
            url = "https://" + url
        self._pace()
        e = self.ensure()
        info = e.navigate(url)
        notes = []
        if info.get("error"):
            notes.append("Load error: " + str(info["error"]))
        if info.get("timed_out"):
            notes.append("The page was still loading after 30s; content may be partial.")
        notes += self._after_load()
        return self._render(notes)

    def read(self, max_chars: Optional[int] = None) -> str:
        self.ensure()
        return self._render([], max_chars)

    def click(self, element_id: str, confirmed: bool = False) -> str:
        self._check_policy(element_id, confirmed)
        self._pace()
        e = self.ensure()
        r = e.click(element_id)
        if not r.get("ok"):
            raise ActionRefused(r.get("error", "click failed"))
        e.wait_idle(15)
        return self._render(self._after_load())

    def type(self, element_id: str, text: str, submit: bool = False, confirmed: bool = False) -> str:
        self._check_policy(element_id, confirmed, submitting=submit, typing=True)
        self._pace()
        e = self.ensure()
        r = e.type(element_id, text, submit)
        if not r.get("ok"):
            raise ActionRefused(r.get("error", "typing failed"))
        notes: List[str] = []
        if submit:
            e.wait_idle(15)
            notes = self._after_load()
        return self._render(notes)

    def select(self, element_id: str, value: str) -> str:
        self._pace()
        r = self.ensure().ab("select", element_id, value)
        if not r.get("ok"):
            raise ActionRefused(r.get("error", "select failed"))
        return self._render([f"Selected \"{r.get('selected')}\"."])

    def scroll(self, direction: str = "down") -> str:
        self.ensure().ab("scroll", direction)
        time.sleep(0.4)
        return self._render([])

    def navigate_history(self, action: str) -> str:
        self._pace()
        e = self.ensure()
        e.history(action)
        return self._render(self._after_load())

    def screenshot(self) -> bytes:
        return self.ensure().screenshot()

    def ask_human(self, reason: str) -> str:
        return self._handoff(reason=reason) + "\n\n" + self._render([])

    def wait(self, seconds: float) -> str:
        time.sleep(max(0.0, min(float(seconds), 30.0)))
        return self._render(self._after_load())

    def recent_actions(self, limit: int = 20) -> str:
        f = config.LOG_DIR / (_dt.date.today().isoformat() + ".jsonl")
        if not f.exists():
            return "No actions logged today."
        lines = f.read_text("utf-8").splitlines()[-int(limit):]
        out = []
        for ln in lines:
            try:
                d = json.loads(ln)
                out.append(f"{d['ts']}  {d['tool']}  {json.dumps(d['args'], ensure_ascii=False)}")
            except (ValueError, KeyError):
                continue
        return "\n".join(out) or "No actions logged today."
