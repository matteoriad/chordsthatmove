#!/usr/bin/env python3
"""Decide whether this workflow run should post.

Four posts a day: 08:30, 12:30, 17:30 and 21:30 Berlin.
Cron is UTC only and GitHub drops runs at the top of the hour under load, so the
workflow fires at :41 every hour (covers CET and CEST). A run landing in the hour
before a slot waits until the slot and posts; runs in the two hours after a slot
are backups that post only if nothing has gone out for that slot yet (a late
backup post never cancels the next slot).
"Post now" pushes (the Claude scheduled task) follow the same rules: skip if
already posted, wait for the slot if early. Manual runs from the Actions tab
always go.
Slots listed under "own" in schedule.json belong to Matteo's own videos (posted by hand):
the automated reel skips them.
"""
import datetime, json, os, subprocess, time
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BER = ZoneInfo("Europe/Berlin")
SLOTS = ((8, 30), (12, 30), (17, 30), (21, 30))   # posting times (hour, minute), Berlin time
BACKUP = datetime.timedelta(hours=2)   # how long after a slot a missed post may still go out
MIN_GAP = datetime.timedelta(hours=3)   # must stay below the 4 h spacing of the closest slots


def out(go, why):
    print(why)
    with open(os.environ["GITHUB_OUTPUT"], "a") as f: f.write(f"go={'true' if go else 'false'}\n")


def own_slots():
    """Slots reserved for hand-posted videos, as "YYYY-MM-DD HH:MM" Berlin strings."""
    p = os.path.join(ROOT, "schedule.json")
    if not os.path.exists(p): return set()
    return {e["slot"] for e in json.load(open(p)).get("own", [])}


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
    today = now.replace(second=0, microsecond=0)
    for h, m in SLOTS:
        for day in (-1, 0, 1):
            slot_at = today.replace(hour=h, minute=m) + datetime.timedelta(days=day)
            if slot_at - datetime.timedelta(hours=1) <= now < slot_at:
                late = False
            elif slot_at <= now <= slot_at + BACKUP:
                late = True
            else:
                continue
            name = f"{h:02d}:{m:02d}"
            if f"{slot_at:%Y-%m-%d} {name}" in own_slots():
                return out(False, f"The {slot_at:%Y-%m-%d} {name} slot is for your own video (schedule.json): skipping.")
            # One post per slot: skip only if something already went out for THIS slot (from the
            # hour before it on). A late backup post for the previous slot doesn't cancel this one.
            if last and last >= slot_at - datetime.timedelta(hours=1):
                return out(False, f"Already posted at {last.astimezone(BER):%H:%M} Berlin for the {name} slot: skipping.")
            if late:
                return out(True, f"{now:%H:%M} Berlin: the {name} post was missed, posting now as backup.")
            print(f"{now:%H:%M} Berlin: waiting {(slot_at - now).total_seconds() / 60:.0f} min until {name}.")
            time.sleep(max(0, (slot_at - now).total_seconds()))
            return out(True, f"{name} Berlin: posting.")
    if last and now - last < MIN_GAP:
        return out(False, f"Already posted at {last.astimezone(BER):%H:%M} Berlin: skipping.")
    if event == "push":   # post-now outside any window: post right away
        return out(True, "Post-now trigger: posting.")
    return out(False, f"{now:%H:%M} Berlin is outside the posting windows: skipping.")


if __name__ == "__main__":
    main()
