# chords that move: daily reel pipeline

Every day at ~18:00 Berlin time, GitHub Actions picks the next song in `songs/queue/`,
renders the reel (voice lines + synth audio) and its cover, and publishes it to
Instagram as a Reel. Nothing runs on your laptop.

```
songs/sketches/   chord symbols + hooks + captions (what you or Claude write)
songs/queue/      full specs with voicings (built from sketches by voicing.py)
brandreel.py      video + cover renderer ("chords that move" brand)
songreel.py       timing + synth audio
pipeline/post.py  render → upload → publish → record in posted.json
.github/workflows/daily-reel.yml   the daily schedule
```

## One-time setup

### 1. Instagram account
In the Instagram app: Settings → Account type and tools → **Switch to professional account**
→ Creator (or Business). Posting through the API only works for professional accounts.

### 2. Meta developer app (gives the access token)
1. Go to developers.facebook.com → **My Apps → Create app**.
2. Use case: **"Manage messaging & content on Instagram"** (Instagram API with Instagram login).
3. In the app: **Instagram → API setup with Instagram login → Add account**, then log in as `@chordsthatmove`.
4. Click **Generate token** next to the account. Copy:
   - the **access token** (long-lived, 60 days)
   - the **Instagram user ID** shown next to the account
5. The app can stay in development mode: it only posts to an account that has a role on the app.

### 3. GitHub repository
1. Create a **public** repo (e.g. `chordsthatmove`). It has to be public so Instagram can fetch
   the cover image from it.
2. Push this folder to it.
3. Repo → Settings → Secrets and variables → Actions → **New repository secret**:
   - `IG_USER_ID`: the Instagram user ID
   - `IG_ACCESS_TOKEN`: the access token
   - `GH_ADMIN_TOKEN` (optional, recommended): a fine-grained GitHub token for this repo with
     **Secrets: read and write**. With it the job refreshes the Instagram token by itself.
     Without it, generate a new token in Meta every ~50 days and update the secret.

### 4. Test, then go live
- Actions → **Daily reel** → Run workflow with **dry run** ticked → download the `reel` artifact and check it.
- Run it again with dry run unticked to post episode 1 right away.
- From then on it posts by itself every day. If a run fails, GitHub emails you.

## Adding songs
Write a sketch in `songs/sketches/` (copy an existing one), then build the queue file:

```
python3 -c "import json,voicing,sys; p=sys.argv[1]; json.dump(voicing.build(json.load(open(p))), open(p.replace('sketches','queue'),'w'), ensure_ascii=False, indent=1)" songs/sketches/ep15-your-song.json
```

Preview without posting: `python3 brandreel.py render songs/queue/ep15-your-song.json test.mp4`
and `python3 brandreel.py cover songs/queue/ep15-your-song.json test`.
When the queue runs out, the job fails and GitHub emails you.
