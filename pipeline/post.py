#!/usr/bin/env python3
"""Daily job: render the next queued episode and publish it to Instagram as a Reel.

Steps: pick next song → render reel + covers → push the cover (public URL for
Instagram) → create Reel container with resumable video upload → wait until
Instagram has processed it → publish → record it in posted.json → refresh the
access token → cross-post to YouTube Shorts / TikTok (pipeline/crosspost.py).

Env:
  IG_USER_ID, IG_ACCESS_TOKEN   Instagram account ID + token (required unless DRY_RUN)
  IG_LOGIN                      "facebook" (default: Facebook-login setup, Page token, no expiry)
                                or "instagram" (Instagram-login setup, 60-day token, auto-refresh)
  GH_ADMIN_TOKEN                optional PAT that may update repo secrets (auto token refresh)
  DRY_RUN=true                  render only; no git push, no Instagram calls
  EPISODE=N                     force a specific episode
  IG_API_VERSION                default v22.0
"""
import glob, json, os, re, subprocess, sys, time, datetime
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import brandreel  # noqa: E402

LOGIN = os.environ.get("IG_LOGIN", "facebook").strip().lower() or "facebook"
HOST = "graph.instagram.com" if LOGIN == "instagram" else "graph.facebook.com"
API = f"https://{HOST}/" + os.environ.get("IG_API_VERSION", "v22.0")
RUPLOAD = "https://rupload.facebook.com/ig-api-upload/" + os.environ.get("IG_API_VERSION", "v22.0")
STATE = os.path.join(ROOT, "posted.json")
DRY = os.environ.get("DRY_RUN", "false").lower() == "true"


def log(*a): print(*a, flush=True)
def git(*args): return subprocess.run(["git", "-C", ROOT, *args], check=True, capture_output=True, text=True).stdout.strip()


def commit_push(path, msg):
    """Commit and push one file; a no-op if it is unchanged (e.g. on a rerun)."""
    git("add", path)
    if subprocess.run(["git", "-C", ROOT, "diff", "--cached", "--quiet"]).returncode == 0:
        log(f"{path} unchanged, nothing to commit"); return
    git("commit", "-m", msg); git("push")


def load_state():
    return json.load(open(STATE)) if os.path.exists(STATE) else []


def queue():
    items = []
    for p in sorted(glob.glob(os.path.join(ROOT, "songs/queue/*.json"))):
        spec = json.load(open(p))
        items.append((spec["episode"], os.path.basename(p)[:-5], spec))
    return sorted(items)


def plain(text): return text.replace("*", "")


def caption(spec):
    chords = [c["name"] for c in spec["chords"]]
    romans = [c.get("roman", "") for c in spec["chords"]]
    tag = spec.get("hashtag") or re.sub(r"[^a-z0-9]", "", spec["title"].lower())
    return (f"{plain(spec['hook'])}\n\n"
            f"{spec['artist']} — {spec['title']} · {spec['key']}\n"
            f"{' → '.join(chords)}\n({' – '.join(romans)})\n\n"
            f"{plain(spec.get('question') or 'Which song should I break down next? Comment it 👇')}\n\n"
            f"New song broken down every 4 hours. Follow {spec.get('handle', '@chordsthatmove')} 🎹\n\n"
            f"#musictheory #chordprogression #{tag} #songwriting #harmony #pianochords #guitarchords #producer")


def ig(method, url, **kw):
    r = requests.request(method, url, timeout=120, **kw)
    try: data = r.json()
    except ValueError: data = {"raw": r.text}
    if r.status_code >= 400 or "error" in data:
        raise SystemExit(f"Instagram API error {r.status_code} on {url.split('?')[0]}: {data}")
    return data


def publish_reel(video, cover_url, text, user, token):
    c = ig("POST", f"{API}/{user}/media", data={
        "media_type": "REELS", "upload_type": "resumable", "caption": text,
        "cover_url": cover_url, "share_to_feed": "true", "access_token": token})
    cid = c["id"]; log("container", cid)
    size = os.path.getsize(video)
    with open(video, "rb") as f:
        ig("POST", c.get("uri") or f"{RUPLOAD}/{cid}", data=f.read(), headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)})
    log("uploaded", size, "bytes")
    for _ in range(60):                       # up to ~10 minutes of processing
        st = ig("GET", f"{API}/{cid}", params={"fields": "status_code,status", "access_token": token})
        log("status", st.get("status_code"), st.get("status", ""))
        if st.get("status_code") == "FINISHED": break
        if st.get("status_code") in ("ERROR", "EXPIRED"): raise SystemExit(f"processing failed: {st}")
        time.sleep(10)
    else:
        raise SystemExit("timed out waiting for Instagram to process the video")
    pub = ig("POST", f"{API}/{user}/media_publish", data={"creation_id": cid, "access_token": token})
    mid = pub["id"]
    info = ig("GET", f"{API}/{mid}", params={"fields": "permalink", "access_token": token})
    return mid, info.get("permalink")


def refresh_token(token):
    try:
        r = requests.get("https://graph.instagram.com/refresh_access_token",
                         params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=60).json()
    except Exception as e:
        log("token refresh failed:", e); return
    new, days = r.get("access_token"), int(r.get("expires_in", 0)) // 86400
    if not new: log("token refresh skipped:", r); return
    log(f"token valid for another {days} days")
    if new != token and os.environ.get("GH_ADMIN_TOKEN"):
        subprocess.run(["gh", "secret", "set", "IG_ACCESS_TOKEN", "--body", new,
                        "--repo", os.environ["GITHUB_REPOSITORY"]],
                       env={**os.environ, "GH_TOKEN": os.environ["GH_ADMIN_TOKEN"]}, check=True)
        log("stored refreshed token in repo secret")


def main():
    state = load_state()
    done = {s["episode"] for s in state}
    q = queue()
    want = os.environ.get("EPISODE")
    pending = [x for x in q if (int(want) == x[0] if want else x[0] not in done)]
    if not pending:
        raise SystemExit("Queue is empty: add songs to songs/queue/ (see README).")
    ep, slug, spec = pending[0]
    log(f"Episode {ep}: {spec['artist']} — {spec['title']}")

    out = os.path.join(ROOT, "out"); os.makedirs(out, exist_ok=True)
    video = os.path.join(out, f"{slug}.mp4")
    brandreel.render(spec, video)
    reel_r = brandreel.Reel(spec)
    grid, reel_cover = reel_r.cover()
    grid.save(os.path.join(out, f"{slug}_grid.png"))
    cover_rel = f"covers/{slug}.png"
    reel_cover.save(os.path.join(ROOT, cover_rel))
    text = caption(spec)
    open(os.path.join(out, f"{slug}_caption.txt"), "w").write(text)
    log("---- caption ----\n" + text + "\n-----------------")

    if DRY:
        log("DRY_RUN: rendered only, nothing posted."); return

    user, token = os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    commit_push(cover_rel, f"cover: episode {ep}")
    cover_url = f"https://raw.githubusercontent.com/{repo}/{git('rev-parse', 'HEAD')}/{cover_rel}"
    time.sleep(5)
    mid, link = publish_reel(video, cover_url, text, user, token)
    log("published", mid, link)
    state.append({"episode": ep, "slug": slug, "title": spec["title"], "media_id": mid, "permalink": link,
                  "posted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")})
    json.dump(state, open(STATE, "w"), indent=1)
    commit_push("posted.json", f"posted episode {ep}: {spec['title']}")
    import crosspost   # YouTube Shorts + TikTok (skipped if their secrets aren't set)
    if crosspost.catch_up(state, rendered={slug: video}):
        json.dump(state, open(STATE, "w"), indent=1)
        commit_push("posted.json", f"cross-posted episode {ep}: {spec['title']}")
    left = len([x for x in q if x[0] not in done and x[0] != ep])
    log(f"{left} episodes left in the queue")
    if LOGIN == "instagram": refresh_token(token)   # Facebook-login Page tokens don't expire


if __name__ == "__main__":
    main()
