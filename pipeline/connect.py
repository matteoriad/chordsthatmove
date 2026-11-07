#!/usr/bin/env python3
"""One-time: get the refresh tokens the pipeline needs. Run on your laptop.

  python3 pipeline/connect.py youtube  CLIENT_ID CLIENT_SECRET
  python3 pipeline/connect.py tiktok   CLIENT_KEY CLIENT_SECRET [REDIRECT_URI]
  (prefix with TIKTOK_MODE=direct once TikTok has approved video.publish)

Each prints the refresh token to paste into the repo secrets (see README).
Only needs `requests`.
"""
import http.server, os, secrets, sys, threading, urllib.parse, webbrowser
import requests

TT_REDIRECT = "https://github.com/matteoriad/chordsthatmove"   # must match the TikTok app's Redirect URI


def youtube(cid, secret):
    """Google 'Desktop app' OAuth client; loopback redirect on a free local port."""
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            got.update(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
            self.send_response(200); self.end_headers()
            self.wfile.write(b"Done - you can close this tab and go back to the terminal.")
        def log_message(self, *a): pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_port}"
    state = secrets.token_urlsafe(16)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "state": state,
        "scope": "https://www.googleapis.com/auth/youtube.upload",
        "access_type": "offline", "prompt": "consent"})
    print("Opening the browser. Sign in with the account that owns the chords that move channel.\n", url)
    webbrowser.open(url)
    t = threading.Thread(target=srv.handle_request); t.start(); t.join()
    if got.get("state", [""])[0] != state or "code" not in got:
        sys.exit(f"Sign-in did not complete: {got}")
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": cid, "client_secret": secret, "code": got["code"][0],
        "redirect_uri": redirect, "grant_type": "authorization_code"}).json()
    if "refresh_token" not in r: sys.exit(f"No refresh token: {r}")
    print("\nYT_REFRESH_TOKEN =\n" + r["refresh_token"])


def tiktok(key, secret, redirect=TT_REDIRECT):
    """TikTok Login Kit (web). TikTok only accepts https redirects, so the browser lands
    on the redirect page and you paste its full address back here."""
    state = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": key, "response_type": "code", "redirect_uri": redirect, "state": state,
        "scope": "user.info.basic,video.upload" + (
            ",video.publish" if os.environ.get("TIKTOK_MODE") == "direct" else "")})
    print("Opening the browser. Log in as @chordsthatmove and allow access.\n", url)
    webbrowser.open(url)
    back = input("\nAfter allowing, paste the full address from the browser bar here:\n> ").strip()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(back).query)
    if q.get("state", [""])[0] != state or "code" not in q:
        sys.exit(f"That address has no matching code: {q}")
    r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", headers={
        "Content-Type": "application/x-www-form-urlencoded"}, data={
        "client_key": key, "client_secret": secret, "code": q["code"][0],
        "grant_type": "authorization_code", "redirect_uri": redirect}).json()
    if "refresh_token" not in r: sys.exit(f"No refresh token: {r}")
    print(f"\nGranted scopes: {r.get('scope')}")
    print("TIKTOK_REFRESH_TOKEN =\n" + r["refresh_token"])


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] not in ("youtube", "tiktok"):
        sys.exit(__doc__)
    {"youtube": youtube, "tiktok": tiktok}[sys.argv[1]](*sys.argv[2:])
