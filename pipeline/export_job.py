#!/usr/bin/env python3
"""Steps of .github/workflows/export-reel.yml (a reel export requested by the web app).

  python3 pipeline/export_job.py prepare   read inputs from the event file → work/jam.json
  python3 pipeline/export_job.py start     tell the app we're rendering, get upload links
  python3 pipeline/export_job.py upload    upload work/out/reel.mp4 and cover.png
  python3 pipeline/export_job.py done      tell the app the export is ready
  python3 pipeline/export_job.py failed    tell the app it failed (doesn't count against quota)

This repo is public, so its Actions logs are public: the jam and the upload links never go into
environment variables or logs (inputs are read from $GITHUB_EVENT_PATH, links are masked).
Standard library only, so it runs before `pip install`.
Env: EXPORT_APP_URL (repo variable), EXPORT_WEBHOOK_SECRET (repo secret).
"""
import json
import os
import re
import sys
import urllib.request

WORK = "work"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_JAM_BYTES = 60_000


def export_id():
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        value = (json.load(f).get("inputs") or {}).get("export_id", "")
    if not UUID.match(value):
        sys.exit("export_id must be a UUID")
    return value


def webhook(payload):
    url = os.environ["EXPORT_APP_URL"].rstrip("/") + "/api/exports/webhook"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ["EXPORT_WEBHOOK_SECRET"],
            "User-Agent": "chordsthatmove-export",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read() or b"{}")


def prepare():
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        jam = (json.load(f).get("inputs") or {}).get("jam", "")
    export_id()  # validates
    if not jam or len(jam.encode()) > MAX_JAM_BYTES:
        sys.exit("jam input is missing or too large")
    json.loads(jam)  # must be JSON; jamreel.py validates the content
    os.makedirs(WORK, exist_ok=True)
    with open(os.path.join(WORK, "jam.json"), "w", encoding="utf-8") as f:
        f.write(jam)
    print("jam received:", len(jam), "bytes")


def start():
    res = webhook({"export_id": export_id(), "status": "rendering"})
    upload = res.get("upload") or {}
    for key in ("video", "cover"):
        if not isinstance(upload.get(key), str) or not upload[key].startswith("https://"):
            sys.exit("the app didn't return upload links")
        print(f"::add-mask::{upload[key]}")  # keep signed links out of the public log
    with open(os.path.join(WORK, "upload.json"), "w", encoding="utf-8") as f:
        json.dump(upload, f)
    print("upload links received")


def put(url, path, content_type):
    with open(path, "rb") as f:
        req = urllib.request.Request(url, data=f.read(), method="PUT", headers={"Content-Type": content_type, "x-upsert": "true"})
    with urllib.request.urlopen(req, timeout=120) as res:
        if res.status >= 300:
            sys.exit(f"upload failed: HTTP {res.status}")


def upload():
    with open(os.path.join(WORK, "upload.json"), encoding="utf-8") as f:
        links = json.load(f)
    put(links["video"], os.path.join(WORK, "out", "reel.mp4"), "video/mp4")
    put(links["cover"], os.path.join(WORK, "out", "cover.png"), "image/png")
    print("uploaded reel.mp4 and cover.png")


def done():
    webhook({"export_id": export_id(), "status": "done"})
    print("export marked done")


def failed():
    run = f"{os.environ.get('GITHUB_SERVER_URL', '')}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    try:
        webhook({"export_id": export_id(), "status": "failed", "error": f"render failed ({run})"})
        print("export marked failed")
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 - best effort: the app also times stale exports out
        print("could not reach the app:", e)


if __name__ == "__main__":
    steps = {"prepare": prepare, "start": start, "upload": upload, "done": done, "failed": failed}
    if len(sys.argv) != 2 or sys.argv[1] not in steps:
        sys.exit(__doc__)
    steps[sys.argv[1]]()
