#!/usr/bin/env python3
"""Decide whether this workflow run should post.

Scheduled runs fire at :41 in three consecutive UTC hours (GitHub drops runs at
the top of the hour under load, and cron is UTC only). The first run that lands
in Berlin's 9 o'clock hour waits until 10:00 Berlin and posts; later runs are
backups that post only if nothing was posted in the last 6 hours.
"Post now" pushes (the daily Claude task) follow the same rules: skip if already
posted, wait until 10:00 if early. Manual runs from the Actions tab always go.
"""
import datetime, json, os, subprocess, time
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BER = ZoneInfo("Europe/Berlin")


def out(go, why):
    print(why)
    with open(os.environ["GITHUB_OUTPUT"], "a") as f: f.write(f"go={'true' if go else 'false'}\n")


def latest_posted():
    """posted.json as it is on GitHub right now (a queued run may have been
    checked out before another run posted)."""
    try:
        subprocess.run(["git", "-C", ROOT, "fetch", "-q", "origin", "main"], check=True, timeout=60)
        return json.loads(subprocess.run(["git", "-C", ROOT, "show", "origin/main:posted.json"], check=True,
                                         capture_output=True, text=True).stdout)
    except Exception as e:
        print("could not read latest posted.json, using local copy:", e)
        p = os.path.join(ROOT, "posted.json")
        return json.load(open(p)) if os.path.exists(p) else []


def main():
    event = os.environ.get("EVENT")
    if event == "workflow_dispatch":
        return out(True, "Manual run: going ahead.")
    now = datetime.datetime.now(BER)
    posted = latest_posted()
    last = max((datetime.datetime.fromisoformat(p["posted_at"]) for p in posted), default=None)
    if last and now - last < datetime.timedelta(hours=6):
        return out(False, f"Already posted at {last.astimezone(BER):%H:%M} Berlin: skipping.")
    if now.hour == 9:
        target = now.replace(hour=10, minute=0, second=0, microsecond=0)
        wait = (target - now).total_seconds()
        print(f"{now:%H:%M} Berlin: waiting {wait / 60:.0f} min until 10:00.")
        time.sleep(max(0, wait))
        return out(True, "10:00 Berlin: posting.")
    if event == "push":   # post-now (e.g. from the daily Claude task): post now, or at 10:00 if early
        return out(True, "Post-now trigger: posting.")
    if now.hour in (10, 11, 12):
        return out(True, f"{now:%H:%M} Berlin: earlier run was missed, posting now as backup.")
    return out(False, f"{now:%H:%M} Berlin is outside the posting window: skipping.")


if __name__ == "__main__":
    main()
