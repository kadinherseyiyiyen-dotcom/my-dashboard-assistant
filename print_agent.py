"""
Print Agent (Windows/Linux)
--------------------------
Runs on the shop PC (the one that has the kitchen printer connected).

Flow:
  - Polls Render for pending print jobs (/api/print-jobs)
  - Claims a job, prints it locally, then marks it done.

Env vars:
  PRINT_SERVER_URL   (required) e.g. https://my-dashboard-assistant.onrender.com
  PRINT_AGENT_TOKEN  (required) must match server PRINT_AGENT_TOKEN
  PRINT_TARGET       (optional) default: kitchen
  PRINT_MODE         (optional) printer|console (default: printer)
  PRINTER_NAME       (optional) Windows printer name for kitchen
  POLL_SECONDS       (optional) default: 2
"""

import json
import os
import time
import uuid
import urllib.request


def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


SERVER = _env("PRINT_SERVER_URL")
TOKEN = _env("PRINT_AGENT_TOKEN", "2024Family")
TARGET = _env("PRINT_TARGET", "kitchen")
MODE = _env("PRINT_MODE", "printer")
PRINTER_NAME = _env("PRINTER_NAME")
POLL_SECONDS = float(_env("POLL_SECONDS", "2") or 2)

AGENT_ID = _env("PRINT_AGENT_ID") or f"agent-{uuid.uuid4().hex[:8]}"


def _request(path, method="GET", body=None, timeout=15):
    if not SERVER or not TOKEN:
        raise RuntimeError("PRINT_SERVER_URL and PRINT_AGENT_TOKEN are required")
    url = SERVER.rstrip("/") + path
    data = None
    headers = {
        "X-Agent-Token": TOKEN,
        "X-Agent-Id": AGENT_ID,
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return resp.status, raw


def _print_text(text, cut=True, charcode="CP857"):
    if MODE == "console":
        print("\n--- PRINT JOB ---")
        print(text)
        print("--- END ---\n")
        return

    if not PRINTER_NAME:
        raise RuntimeError("PRINTER_NAME is required in PRINT_MODE=printer")

    # python-escpos Win32Raw requires: pip install python-escpos
    from escpos.printer import Win32Raw

    p = Win32Raw(PRINTER_NAME)
    try:
        p.charcode(charcode)
    except Exception:
        try:
            p.charcode("CP1254")
        except Exception:
            pass
    p.text(text + "\n")
    if cut:
        try:
            p.cut()
        except Exception:
            pass


def loop():
    print(f"[print-agent] id={AGENT_ID} target={TARGET} mode={MODE}", flush=True)
    while True:
        try:
            status, raw = _request(f"/api/print-jobs?status=pending&target={TARGET}&limit=5")
            payload = json.loads(raw) if raw else {}
            jobs = payload.get("jobs") or []
            if not jobs:
                time.sleep(POLL_SECONDS)
                continue
            for job in jobs:
                job_id = job.get("id")
                if not job_id:
                    continue
                # claim
                try:
                    _request(f"/api/print-jobs/{job_id}/claim", method="POST", body={"agent_id": AGENT_ID})
                except Exception:
                    continue

                try:
                    p = job.get("payload") or {}
                    _print_text(
                        p.get("text") or "",
                        cut=bool(p.get("cut", True)),
                        charcode=p.get("charcode") or "CP857",
                    )
                    _request(f"/api/print-jobs/{job_id}/done", method="POST", body={"ok": True})
                except Exception as exc:
                    try:
                        _request(f"/api/print-jobs/{job_id}/error", method="POST", body={"error": repr(exc)})
                    except Exception:
                        pass
        except Exception as exc:
            print(f"[print-agent] error: {exc!r}", flush=True)
            time.sleep(max(POLL_SECONDS, 3))


if __name__ == "__main__":
    loop()
