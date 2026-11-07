#!/usr/bin/env python3
"""Put Instagram episodes on YouTube Shorts and TikTok too.

Goes through posted.json in episode order and uploads every episode that is not
yet on an enabled platform (so it backfills old episodes and retries failed ones).
A platform failing never stops Instagram or the other platform; the next run retries.

Called by post.py after each Instagram post, or on its own (CROSSPOST_ONLY run):
  python pipeline/crosspost.py
Env: CROSSPOST_LIMIT  max uploads per platform per run (default 6)
     DRY_RUN=true     list what would be uploaded, upload nothing
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brandreel  # noqa: E402
import platforms  # noqa: E402

STATE = os.path.join(ROOT, "posted.json")


def log(*a): print(*a, flush=True)


def _spec(slug, episode):
    """The spec as post.py rendered it, including the 'next episode' end card."""
    spec = json.load(open(os.path.join(ROOT, "songs/queue", slug + ".json")))
    import glob
    later = []
    for p in glob.glob(os.path.join(ROOT, "songs/queue/*.json")):
        s = json.load(open(p))
        if s["episode"] > episode: later.append(s)
    if later:
        n = min(later, key=lambda s: s["episode"])
        spec["next"] = f"{n['artist']} — {n['title']}"
    return spec


def catch_up(state, rendered=None, limit=None, dry=False):
    """Upload missing episodes. `rendered` maps slug -> mp4 already on disk.
    Returns True if state changed."""
    import post  # caption()
    rendered = dict(rendered or {})
    limit = int(limit or os.environ.get("CROSSPOST_LIMIT", "6"))
    enabled = [n for n, (on, _) in platforms.PLATFORMS.items() if on()]
    if not enabled:
        log("Cross-posting: no YouTube/TikTok secrets set, skipping."); return False
    changed, done = False, {n: 0 for n in enabled}
    out = os.path.join(ROOT, "out"); os.makedirs(out, exist_ok=True)
    for entry in sorted(state, key=lambda e: e["episode"]):
        todo = [n for n in enabled if not (entry.get(n) or {}).get("id" if n == "youtube" else "publish_id")
                and done[n] < limit]
        if not todo: continue
        log(f"Episode {entry['episode']} ({entry['title']}) → {', '.join(todo)}")
        if dry: continue
        spec = _spec(entry["slug"], entry["episode"])
        video = rendered.get(entry["slug"])
        if not video or not os.path.exists(video):
            video = os.path.join(out, entry["slug"] + ".mp4")
            brandreel.render(spec, video); rendered[entry["slug"]] = video
        text = post.caption(spec)
        for name in todo:
            try:
                res = platforms.PLATFORMS[name][1](video, spec, text)
                entry[name] = res; changed = True; done[name] += 1
                log(f"  {name}: {res}")
            except Exception as e:  # keep going; next run retries
                log(f"  {name} FAILED: {e}")
                entry[name] = {"error": str(e)[:300]}; changed = True
    return changed


def main():
    import post
    dry = os.environ.get("DRY_RUN", "false").lower() == "true"
    state = json.load(open(STATE)) if os.path.exists(STATE) else []
    if catch_up(state, dry=dry) and not dry:
        json.dump(state, open(STATE, "w"), indent=1)
        post.commit_push("posted.json", "cross-posted to YouTube/TikTok")


if __name__ == "__main__":
    main()
