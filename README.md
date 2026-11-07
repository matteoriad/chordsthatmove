# chords that move: daily reel pipeline

Twice a day, at 01:00 and 13:00 Berlin time, GitHub Actions picks the next song in `songs/queue/`,
renders the reel (voice lines + synth audio) and its cover, and publishes it to
Instagram as a Reel. Nothing runs on your laptop.

```
songs/sketches/   chord symbols + hooks + captions (what you or Claude write)
songs/queue/      full specs with voicings (built from sketches by voicing.py)
brandreel.py      video + cover renderer ("chords that move" brand)
songreel.py       timing + synth audio
pipeline/post.py  render → upload → publish → record in posted.json
.github/workflows/daily-reel.yml   the schedule (pipeline/gate.py holds the posting slots)
```

## One-time setup

### 1. Instagram account
In the Instagram app: Settings → Account type and tools → **Switch to professional account**
→ Creator (or Business). Posting through the API only works for professional accounts.

### 2. Meta developer app + token (Facebook-login setup)
1. **Facebook Page:** create a Page (e.g. "chords that move") and link @chordsthatmove to it:
   Page → Settings → Linked accounts → Instagram → Connect.
2. developers.facebook.com → your app → Use cases → Instagram API → **API setup with Facebook login**
   → **Add required content permissions**.
3. Open **Tools → Graph API Explorer**. Pick your app under "Meta App", then
   "User or Page" → **Get User Access Token**. Tick `instagram_basic`, `instagram_content_publish`,
   `pages_show_list`, `pages_read_engagement`, `business_management` → **Generate Access Token**
   and log in, choosing the chordsthatmove Page and Instagram account.
4. Make it long-lived: click the ⓘ next to the token → **Open in Access Token Tool** →
   **Extend Access Token** → copy the new token and paste it back into the Explorer's token field.
5. In the Explorer, run `GET me/accounts?fields=name,access_token,instagram_business_account`.
   For the chordsthatmove Page copy:
   - `instagram_business_account.id`: this is `IG_USER_ID`
   - `access_token`: this Page token never expires; it is `IG_ACCESS_TOKEN`

### 3. GitHub repository
1. Create a **public** repo (e.g. `chordsthatmove`). It has to be public so Instagram can fetch
   the cover image from it.
2. Push this folder to it.
3. Repo → Settings → Secrets and variables → Actions → **New repository secret**:
   - `IG_USER_ID`: the Instagram user ID
   - `IG_ACCESS_TOKEN`: the access token
   (`GH_ADMIN_TOKEN` and the `IG_LOGIN` variable are only needed for the Instagram-login setup,
   whose tokens expire; the Facebook-login Page token above doesn't.)

### 4. Test, then go live
- Actions → **Daily reel** → Run workflow with **dry run** ticked → download the `reel` artifact and check it.
- Run it again with dry run unticked to post episode 1 right away.
- From then on it posts by itself twice a day. If a run fails, GitHub emails you.

## Adding songs
Write a sketch in `songs/sketches/` (copy an existing one), then build the queue file:

```
python3 -c "import json,voicing,sys; p=sys.argv[1]; json.dump(voicing.build(json.load(open(p))), open(p.replace('sketches','queue'),'w'), ensure_ascii=False, indent=1)" songs/sketches/ep15-your-song.json
```

Preview without posting: `python3 brandreel.py render songs/queue/ep15-your-song.json test.mp4`
and `python3 brandreel.py cover songs/queue/ep15-your-song.json test`.
When the queue runs out, the job fails and GitHub emails you.
