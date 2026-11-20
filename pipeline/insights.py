#!/usr/bin/env python3
"""Weekly Instagram report: which format, slot and look gets views, saves, shares and follows.

Every reel of the last 14 days that is at least 48 h old is grouped by
  format  song breakdown · guess the song · jam over this · your own video (not in posted.json)
  slot    08:30 · 12:30 · 17:30 · 21:30 · other (Berlin)
  look    Night · other theme (as recorded in posted.json when it was posted)
and the report goes out as a GitHub issue (GitHub emails it) and into reports/YYYY-MM-DD.md.
Followers are tracked in reports/followers.json, so the report shows the change since last week.

Needs the instagram_manage_insights permission on IG_ACCESS_TOKEN (README: Weekly report).

Env: IG_USER_ID, IG_ACCESS_TOKEN, IG_API_VERSION (v22.0), GITHUB_REPOSITORY + GH_TOKEN (issue),
     DRY_RUN=true (print only).
"""
import datetime, json, os, statistics, subprocess, sys
from zoneinfo import ZoneInfo
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
API = "https://graph.facebook.com/" + os.environ.get("IG_API_VERSION", "v22.0")
BER = ZoneInfo("Europe/Berlin")
METRICS = ["views", "reach", "likes", "comments", "shares", "saved", "ig_reels_avg_watch_time", "reels_skip_rate"]
WINDOW, MIN_AGE = datetime.timedelta(days=14), datetime.timedelta(hours=48)
FORMAT_NAMES = {"song": "Song breakdown", "guess": "Guess the song", "jam": "Jam over this", "own": "Your own video"}


def get(path, **params):
    r = requests.get(f"{API}/{path}", params={**params, "access_token": os.environ["IG_ACCESS_TOKEN"]}, timeout=60)
    data = r.json()
    if r.status_code >= 400 or "error" in data:
        raise RuntimeError(data.get("error", {}).get("message", str(data)))
    return data


def recent_media(since):
    out, url, params = [], f"{os.environ['IG_USER_ID']}/media", {"fields": "id,media_product_type,timestamp,permalink,caption", "limit": 50}
    while url:
        page = get(url, **params) if not url.startswith("http") else requests.get(url, timeout=60).json()
        for m in page.get("data", []):
            ts = datetime.datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00"))
            if ts < since: return out
            out.append({**m, "ts": ts})
        url, params = page.get("paging", {}).get("next"), {}
    return out


def insights(media_id):
    """All metrics in one call; if Instagram refuses one (they change often), ask one by one."""
    try:
        data = get(f"{media_id}/insights", metric=",".join(METRICS))["data"]
        return {d["name"]: d["values"][0]["value"] for d in data}
    except RuntimeError:
        vals = {}
        for m in METRICS:
            try: vals[m] = get(f"{media_id}/insights", metric=m)["data"][0]["values"][0]["value"]
            except RuntimeError: pass
        return vals


def classify(media, posted, specs):
    p = posted.get(media["id"])
    if not p: return "own", None
    spec = specs.get(p["slug"], {})
    fmt = "jam" if spec.get("jam") else "guess" if spec.get("guess") else "song"
    return fmt, {**spec, "_theme": p.get("theme", "night"), "_sound": p.get("held", "old pad"),
                 "_texture": p.get("texture", "old pluck")}   # posts before 2026-11-20: Night, old sound


def slot(ts):
    t = ts.astimezone(BER)
    for h, m in ((8, 30), (12, 30), (17, 30), (21, 30)):
        if abs((t.hour * 60 + t.minute) - (h * 60 + m)) <= 45: return f"{h:02d}:{m:02d}"
    return "other"


def summarise(rows, key):
    groups = {}
    for r in rows: groups.setdefault(key(r), []).append(r)
    lines = ["| | Reels | Median views | Avg reach | Saves + shares per 1k views | Avg watch (s) |", "|---|---|---|---|---|---|"]
    for name, rs in sorted(groups.items(), key=lambda kv: -statistics.median(r["views"] for r in kv[1])):
        views = [r["views"] for r in rs]
        keep = sum(r["saved"] + r["shares"] for r in rs) / max(1, sum(views)) * 1000
        watch = [r["watch"] for r in rs if r["watch"]]
        lines.append(f"| {name} | {len(rs)} | {statistics.median(views):,.0f} | {statistics.mean(r['reach'] for r in rs):,.0f} "
                     f"| {keep:.1f} | {statistics.mean(watch) / 1000:.1f} |" if watch else
                     f"| {name} | {len(rs)} | {statistics.median(views):,.0f} | {statistics.mean(r['reach'] for r in rs):,.0f} | {keep:.1f} | – |")
    return "\n".join(lines)


def build_report(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    posted = {p["media_id"]: p for p in json.load(open(os.path.join(ROOT, "posted.json"))) if p.get("media_id")}
    specs = {}
    for p in posted.values():
        f = os.path.join(ROOT, "songs", "queue", p["slug"] + ".json")
        if os.path.exists(f): specs[p["slug"]] = json.load(open(f))
    rows = []
    for m in recent_media(now - WINDOW):
        if m.get("media_product_type") != "REELS" or now - m["ts"] < MIN_AGE: continue
        fmt, spec = classify(m, posted, specs)
        v = insights(m["id"])
        title = (spec or {}).get("title") or (m.get("caption") or "").split("\n")[0][:40] or "(no caption)"
        rows.append({"title": title, "format": FORMAT_NAMES[fmt], "slot": slot(m["ts"]),
                     "look": (spec["_theme"].capitalize() if spec["_theme"] == "night" else "Other theme") if spec else "–",
                     "views": v.get("views", 0), "reach": v.get("reach", 0), "saved": v.get("saved", 0),
                     "shares": v.get("shares", 0), "likes": v.get("likes", 0), "comments": v.get("comments", 0),
                     "watch": v.get("ig_reels_avg_watch_time"), "skip": v.get("reels_skip_rate"),
                     "sound": spec["_sound"] if spec else "–", "texture": spec["_texture"] if spec else "–",
                     "permalink": m.get("permalink", ""), "ts": m["ts"]})
    followers = get(os.environ["IG_USER_ID"], fields="followers_count").get("followers_count")
    hist_path = os.path.join(ROOT, "reports", "followers.json")
    hist = json.load(open(hist_path)) if os.path.exists(hist_path) else []
    prev = hist[-1]["followers"] if hist else None
    hist.append({"date": now.date().isoformat(), "followers": followers})
    day = now.astimezone(BER).date().isoformat()
    lines = [f"# Weekly report {day}", "",
             f"**Followers: {followers:,}**" + (f" ({followers - prev:+,} since {hist[-2]['date']})" if prev is not None else ""),
             f"Reels in the last 14 days (48 h or older): {len(rows)}", ""]
    if rows:
        lines += ["## By format", summarise(rows, lambda r: r["format"]), "",
                  "## By slot (Berlin)", summarise(rows, lambda r: r["slot"]), "",
                  "## By look (automated reels)", summarise([r for r in rows if r["look"] != "–"], lambda r: r["look"]), "",
                  "## By sound (automated reels)", summarise([r for r in rows if r["sound"] != "–"], lambda r: r["sound"]), "",
                  "## By texture (automated reels)", summarise([r for r in rows if r["texture"] != "–"], lambda r: r["texture"]), "",
                  "## Top 5 by views", "| Reel | Format | Views | Saves | Shares | Skip rate |", "|---|---|---|---|---|---|"]
        for r in sorted(rows, key=lambda r: -r["views"])[:5]:
            skip = f"{r['skip']:.0f}%" if isinstance(r["skip"], (int, float)) else "–"
            lines.append(f"| [{r['title']}]({r['permalink']}) | {r['format']} | {r['views']:,} | {r['saved']} | {r['shares']} | {skip} |")
        lines += ["", "*Saves + shares per 1k views* is the best signal of content people value; views alone follow the algorithm's mood."]
    return "\n".join(lines) + "\n", hist, day


def main():
    report, hist, day = build_report()
    print(report)
    if os.environ.get("DRY_RUN", "false").lower() == "true": return
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    open(os.path.join(ROOT, "reports", f"{day}.md"), "w").write(report)
    json.dump(hist, open(os.path.join(ROOT, "reports", "followers.json"), "w"), indent=1)
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo and os.environ.get("GH_TOKEN"):
        subprocess.run(["gh", "issue", "create", "-R", repo, "--title", f"Weekly report {day}", "--body", report], check=True)


if __name__ == "__main__":
    main()
