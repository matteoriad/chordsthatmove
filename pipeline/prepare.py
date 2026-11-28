#!/usr/bin/env python3
"""Chrome-posting mode (.github/PAUSED exists): render the next episodes on GitHub and
publish them as assets of the GitHub release "ready", so the Chrome scheduled tasks only
have to download and upload them.

For each episode it keeps (the next READY_COUNT unposted ones, plus posted ones still
waiting for YouTube/TikTok, up to 4 days old) the release holds:
  <slug>.mp4            the reel
  <slug>_cover.png      the reel cover
  <slug>_caption.txt    Instagram caption (= YouTube description / TikTok caption)
  <slug>_yt_title.txt   YouTube title
and ready.json lists them all. Download without a token (public repo):
  https://github.com/matteoriad/chordsthatmove/releases/download/ready/<file>

An episode is only re-rendered when its queue file changed (sha1 stored in ready.json).
Assets of episodes that are no longer needed are deleted.
Needs GH_TOKEN (contents: write) and GITHUB_REPOSITORY.
"""
import datetime, hashlib, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brandreel  # noqa: E402
import platforms  # noqa: E402
import post  # noqa: E402

TAG = "ready"
READY_COUNT = int(os.environ.get("READY_COUNT", "4"))   # 4 slots a day: a day of buffer
KEEP_POSTED = datetime.timedelta(days=4)


def log(*a): print(*a, flush=True)


def gh(*args, check=True):
    r = subprocess.run(["gh", *args, "-R", os.environ["GITHUB_REPOSITORY"]], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args)}: {r.stderr.strip()}")
    return r


def sha(path): return hashlib.sha1(open(path, "rb").read()).hexdigest()


def wanted(state, q):
    done = {s["episode"]: s for s in state}
    now = datetime.datetime.now(datetime.timezone.utc)
    keep = []
    for ep, slug, spec in q:   # posted, but YouTube/TikTok still need the file
        s = done.get(ep)
        if not s: continue
        missing = not (s.get("youtube") or {}).get("id") or not (s.get("tiktok") or {}).get("publish_id")
        try: recent = now - datetime.datetime.fromisoformat(s["posted_at"]) < KEEP_POSTED
        except Exception: recent = False
        if missing and recent: keep.append((ep, slug, spec))
    keep += [x for x in q if x[0] not in done][:READY_COUNT]
    return keep


def main():
    state = post.load_state()
    q = post.queue()
    want = wanted(state, q)
    log("wanted:", ", ".join(f"ep{ep}" for ep, _, _ in want) or "nothing")

    if gh("release", "view", TAG, check=False).returncode:
        gh("release", "create", TAG, "--prerelease", "--title", "Ready to post (rendered by GitHub)",
           "--notes", "Rendered reels for the Chrome posting tasks. Managed by pipeline/prepare.py; don't edit by hand.")
    rel = json.loads(gh("release", "view", TAG, "--json", "assets").stdout)
    assets = {a["name"] for a in rel["assets"]}
    manifest = {}
    if "ready.json" in assets:
        with tempfile.TemporaryDirectory() as d:
            gh("release", "download", TAG, "-p", "ready.json", "-D", d, "--clobber")
            manifest = {e["slug"]: e for e in json.load(open(os.path.join(d, "ready.json"))).get("episodes", [])}

    out = os.path.join(ROOT, "out", "ready"); os.makedirs(out, exist_ok=True)
    new_manifest = []
    for ep, slug, spec in want:
        qpath = os.path.join(ROOT, "songs", "queue", f"{slug}.json")
        h = sha(qpath)
        files = [f"{slug}.mp4", f"{slug}_cover.png", f"{slug}_caption.txt", f"{slug}_yt_title.txt"]
        old = manifest.get(slug)
        if old and old.get("sha1") == h and all(f in assets for f in files):
            log(f"ep{ep} {slug}: already ready")
            new_manifest.append(old); continue
        log(f"ep{ep} {slug}: rendering")
        video = os.path.join(out, files[0])
        brandreel.render(spec, video)
        _, cover = brandreel.Reel(spec).cover()
        cover.save(os.path.join(out, files[1]))
        text = post.caption(spec)
        open(os.path.join(out, files[2]), "w").write(text)
        open(os.path.join(out, files[3]), "w").write(platforms.youtube_meta(spec, text)["snippet"]["title"])
        gh("release", "upload", TAG, *[os.path.join(out, f) for f in files], "--clobber")
        new_manifest.append({"episode": ep, "slug": slug, "title": spec["title"], "sha1": h, "files": files,
                             "rendered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")})

    mpath = os.path.join(out, "ready.json")
    json.dump({"updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "base_url": f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/releases/download/{TAG}/",
               "episodes": new_manifest}, open(mpath, "w"), indent=1, ensure_ascii=False)
    gh("release", "upload", TAG, mpath, "--clobber")

    keep = {"ready.json"} | {f for e in new_manifest for f in e["files"]}
    for name in sorted(assets - keep):
        log("removing old asset", name)
        gh("release", "delete-asset", TAG, name, "--yes", check=False)
    log(f"ready: {', '.join('ep%d' % e['episode'] for e in new_manifest)}")


if __name__ == "__main__":
    main()
