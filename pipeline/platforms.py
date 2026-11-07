"""Uploads to YouTube Shorts and TikTok. Plain `requests`, no SDKs.

Each platform is switched on by its secrets; with them missing it is skipped.

YouTube   YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
          YT_PRIVACY      public (default) | unlisted | private
TikTok    TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN
          TIKTOK_MODE     inbox (default): video lands in the TikTok app's inbox as a draft
                                           and you tap Post (no app audit needed)
                          direct: posts by itself (needs video.publish; until TikTok audits
                                  the app, direct posts are private-only)
          TIKTOK_PRIVACY  for direct mode: PUBLIC_TO_EVERYONE (default) | SELF_ONLY | ...
"""
import os, re, subprocess, time
import requests


def log(*a): print(*a, flush=True)


def _env(*names):
    vals = [os.environ.get(n, "").strip() for n in names]
    return vals if all(vals) else None


def _store_secret(name, value):
    """Save a rotated token back into the repo secrets (needs GH_ADMIN_TOKEN)."""
    if not (os.environ.get("GH_ADMIN_TOKEN") and os.environ.get("GITHUB_REPOSITORY")):
        log(f"WARNING: {name} rotated but GH_ADMIN_TOKEN is not set; update the secret by hand.")
        return
    subprocess.run(["gh", "secret", "set", name, "--body", value, "--repo", os.environ["GITHUB_REPOSITORY"]],
                   env={**os.environ, "GH_TOKEN": os.environ["GH_ADMIN_TOKEN"]}, check=True)
    log(f"stored rotated {name} in repo secrets")


def _check(r, what):
    try: data = r.json()
    except ValueError: data = {"raw": r.text[:500]}
    if r.status_code >= 400:
        raise RuntimeError(f"{what}: HTTP {r.status_code} {data}")
    return data


# ---------------------------------------------------------------- YouTube

def youtube_enabled(): return _env("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") is not None


def youtube_meta(spec, caption):
    title = re.sub(r"\s+", " ", spec["hook"].replace("*", "")).strip()
    tail = " #Shorts"
    if len(title) + len(tail) > 100: title = title[:100 - len(tail) - 1].rstrip() + "…"
    tags = ["music theory", "chord progression", spec["title"], spec["artist"], "songwriting",
            "harmony", "piano chords", "guitar chords"]
    return {"snippet": {"title": title + tail, "description": caption, "tags": tags, "categoryId": "10"},
            "status": {"privacyStatus": os.environ.get("YT_PRIVACY", "").strip() or "public",
                       "selfDeclaredMadeForKids": False}}


def youtube_upload(video, spec, caption):
    cid, secret, refresh = _env("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
    tok = _check(requests.post("https://oauth2.googleapis.com/token", timeout=60, data={
        "client_id": cid, "client_secret": secret, "refresh_token": refresh,
        "grant_type": "refresh_token"}), "YouTube token refresh")["access_token"]
    size = os.path.getsize(video)
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        json=youtube_meta(spec, caption), timeout=60, headers={
            "Authorization": f"Bearer {tok}", "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(size)})
    _check(init, "YouTube upload init")
    with open(video, "rb") as f:
        data = _check(requests.put(init.headers["Location"], data=f, timeout=600, headers={
            "Authorization": f"Bearer {tok}", "Content-Type": "video/mp4",
            "Content-Length": str(size)}), "YouTube upload")
    vid = data["id"]
    return {"id": vid, "url": f"https://www.youtube.com/shorts/{vid}"}


# ---------------------------------------------------------------- TikTok

TT = "https://open.tiktokapis.com/v2"


def tiktok_enabled(): return _env("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN") is not None


_tt_token = None


def _tiktok_token():
    """Access tokens last 24 h, so get a fresh one per run from the refresh token."""
    global _tt_token
    if _tt_token: return _tt_token
    key, secret, refresh = _env("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN")
    d = _check(requests.post(f"{TT}/oauth/token/", timeout=60, headers={
        "Content-Type": "application/x-www-form-urlencoded"}, data={
        "client_key": key, "client_secret": secret, "grant_type": "refresh_token",
        "refresh_token": refresh}), "TikTok token refresh")
    if "access_token" not in d: raise RuntimeError(f"TikTok token refresh: {d}")
    if d.get("refresh_token") and d["refresh_token"] != refresh:
        os.environ["TIKTOK_REFRESH_TOKEN"] = d["refresh_token"]
        _store_secret("TIKTOK_REFRESH_TOKEN", d["refresh_token"])
    _tt_token = d["access_token"]
    return _tt_token


def _tt(path, token, body):
    d = _check(requests.post(f"{TT}{path}", json=body, timeout=60, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}), f"TikTok {path}")
    err = d.get("error", {})
    if err.get("code") not in (None, "ok"): raise RuntimeError(f"TikTok {path}: {err}")
    return d.get("data", {})


def _chunks(size):
    """TikTok wants chunks of 5–64 MB (the last may be bigger); under 64 MB send one chunk."""
    if size <= 64_000_000: return size, 1
    chunk = 10_000_000
    return chunk, size // chunk


def tiktok_post(video, spec, caption):
    token = _tiktok_token()
    mode = os.environ.get("TIKTOK_MODE", "inbox").strip().lower() or "inbox"
    size = os.path.getsize(video)
    chunk, count = _chunks(size)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}
    if mode == "direct":
        info = _tt("/post/publish/creator_info/query/", token, {})
        options = info.get("privacy_level_options", [])
        want = os.environ.get("TIKTOK_PRIVACY", "").strip() or "PUBLIC_TO_EVERYONE"
        privacy = want if want in options else ("SELF_ONLY" if "SELF_ONLY" in options else options[0])
        if privacy != want: log(f"TikTok: {want} not allowed for this app yet, posting as {privacy}")
        init = _tt("/post/publish/video/init/", token, {"source_info": source, "post_info": {
            "title": caption[:2200], "privacy_level": privacy, "disable_duet": False,
            "disable_comment": False, "disable_stitch": False}})
    else:
        init = _tt("/post/publish/inbox/video/init/", token, {"source_info": source})
    pid, url = init["publish_id"], init["upload_url"]
    with open(video, "rb") as f:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            f.seek(start)
            r = requests.put(url, data=f.read(end - start + 1), timeout=600, headers={
                "Content-Type": "video/mp4", "Content-Range": f"bytes {start}-{end}/{size}"})
            if r.status_code not in (200, 201, 206): raise RuntimeError(f"TikTok upload: HTTP {r.status_code} {r.text[:300]}")
    status = "?"
    for _ in range(60):
        st = _tt("/post/publish/status/fetch/", token, {"publish_id": pid})
        status = st.get("status", "?")
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"): break
        if status == "FAILED": raise RuntimeError(f"TikTok processing failed: {st}")
        time.sleep(10)
    log(f"TikTok status: {status}")
    return {"publish_id": pid, "mode": mode, "status": status}


PLATFORMS = {"youtube": (youtube_enabled, youtube_upload), "tiktok": (tiktok_enabled, tiktok_post)}
