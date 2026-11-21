"""Tell the human they are needed: desktop notification, plus optional phone push (ntfy)."""
from __future__ import annotations

import subprocess
import sys
import urllib.request
from typing import Any, Dict


def _desktop(title: str, body: str) -> None:
    try:
        if sys.platform == "darwin":
            def q(s: str) -> str:
                return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
            subprocess.run(["osascript", "-e", f"display notification {q(body)} with title {q(title)} sound name \"Glass\""],
                           timeout=5, capture_output=True)
        elif sys.platform.startswith("win"):
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
                "$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                "$t = $x.GetElementsByTagName('text'); $t.Item(0).AppendChild($x.CreateTextNode($env:OPT_T)) > $null;"
                "$t.Item(1).AppendChild($x.CreateTextNode($env:OPT_B)) > $null;"
                "$n = [Windows.UI.Notifications.ToastNotification]::new($x);"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
                "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($n)"
            )
            import os
            env = dict(os.environ, OPT_T=title, OPT_B=body)
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, timeout=10, capture_output=True)
        else:
            subprocess.run(["notify-send", "-a", "Optima", title, body], timeout=5, capture_output=True)
    except Exception:
        pass  # notifications are best effort


def _ntfy(cfg: Dict[str, Any], title: str, body: str) -> None:
    topic = (cfg.get("ntfy_topic") or "").strip()
    if not topic:
        return
    url = cfg.get("ntfy_server", "https://ntfy.sh").rstrip("/") + "/" + topic
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST",
                                 headers={"Title": title.encode("utf-8").decode("latin-1", "ignore"),
                                          "Priority": "high", "Tags": "robot"})
    try:
        urllib.request.urlopen(req, timeout=8).close()
    except Exception:
        pass


def notify(cfg: Dict[str, Any], title: str, body: str) -> None:
    if cfg.get("notify_desktop", True):
        _desktop(title, body)
    _ntfy(cfg, title, body)
