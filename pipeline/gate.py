#!/usr/bin/env python3
"""Decide whether this workflow run should post.

Two posts a day, at 01:00 and 13:00 Berlin (01:00 Berlin is US-evening prime time).
Cron is UTC only and GitHub drops runs at the top of the hour under load, so the
workflow fires at :41 in several UTC hours around each slot (enough to cover both
CET and CEST). A run landing in the hour before a slot waits until the slot and
posts; runs in the two hours after a slot are backups that post only if nothing
went out in the last 6 hours. Everything else skips.
"Post now" pushes (the Claude scheduled task) follow the same rules: skip if
already posted, wait for the slot if early. Manual runs from the Actions tab
always go.
"""
import datetime, json, os, subprocess, time
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BER = ZoneInfo("Europe/Berlin")
SLOTS = (1, 13)          # posting hours, Berlin time
BACKUP_HOURS = 2         # how long after a slot a missed post may still go out
MIN_GAP = datetime.timedelta(hours=6)


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
    if os.path.exists(os.path.join(ROOT, ".github", "PAUSED")):
        return out(False, "Posting is paused (.github/PAUSED exists): skipping.")
    now = datetime.datetime.now(BER)
    posted = latest_posted()
    last = max((datetime.datetime.fromisoformat(p["posted_at"]) for p in posted), default=None)
    if last and now - last < MIN_GAP:
        return out(False, f"Already posted at {last.astimezone(BER):%H:%M} Berlin: skipping.")
    for slot in SLOTS:
        if now.hour == (slot - 1) % 24:
            target = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            print(f"{now:%H:%M} Berlin: waiting {(target - now).total_seconds() / 60:.0f} min until {slot:02d}:00.")
            time.sleep(max(0, (target - now).total_seconds()))
            return out(True, f"{slot:02d}:00 Berlin: posting.")
        if 0 <= (now.hour - slot) % 24 <= BACKUP_HOURS:
            return out(True, f"{now:%H:%M} Berlin: the {slot:02d}:00 post was missed, posting now as backup.")
    if event == "push":   # post-now outside any window: post right away
        return out(True, "Post-now trigger: posting.")
    return out(False, f"{now:%H:%M} Berlin is outside the posting windows: skipping.")


if __name__ == "__main__":
    main()
