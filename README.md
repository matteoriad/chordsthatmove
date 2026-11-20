# chords that move: daily reel pipeline

Twice a day (09:30 and 21:30 Berlin time), GitHub Actions picks the next song in `songs/queue/`,
renders the reel (voice lines + synth audio) and its cover, and publishes it to
Instagram as a Reel, then to YouTube Shorts and TikTok. Nothing runs on your laptop.

```
songs/sketches/   chord symbols + hooks + captions (what you or Claude write)
songs/queue/      full specs with voicings (built from sketches by voicing.py)
brandreel.py      video + cover renderer ("chords that move" brand)
songreel.py       timing + synth audio
pipeline/post.py  render → upload → publish → record in posted.json
pipeline/crosspost.py + platforms.py   YouTube Shorts + TikTok (backfills and retries)
pipeline/connect.py                    one-time sign-in for YouTube/TikTok tokens
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
   "User or Page" → **Get User Access Token**. Tick `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`,
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
- From then on it posts by itself twice a day (09:30 and 21:30 Berlin). If a run fails, GitHub emails you.

## YouTube Shorts and TikTok

After every Instagram post the same video goes to YouTube Shorts and TikTok. Each platform is
switched on by its secrets; without them it is skipped. Every run also uploads any posted episode
that isn't on a platform yet, oldest first (up to 6 per platform per run), so old episodes get
backfilled and failed uploads retried. A YouTube/TikTok failure never blocks the Instagram post.
`posted.json` records the YouTube ID and TikTok publish ID per episode.

To backfill right away: Actions → **Daily reel** → Run workflow → untick **dry run**, tick
**crosspost only**.

### YouTube (one-time, ~10 min)
1. In YouTube, create the channel (e.g. "chords that move") on the Google account you'll use.
2. console.cloud.google.com → new project → APIs & Services → Library → enable **YouTube Data API v3**.
3. Google Auth Platform / OAuth consent screen: **External**, fill in the app name and your email,
   add the scope `.../auth/youtube.upload`. Then **Publish app** so its status is **In production**.
   Skip this and the token stops working after 7 days. Google will show an "unverified app"
   warning when you sign in; that's fine for your own channel.
4. Credentials → Create credentials → **OAuth client ID** → type **Desktop app**. Copy the ID and secret.
5. On your laptop: `pip install requests && python3 pipeline/connect.py youtube CLIENT_ID CLIENT_SECRET`
   and sign in, picking the chords that move channel.
6. Repo secrets: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
   Optional repo variable `YT_PRIVACY` (`public` default, or `unlisted`/`private` to test first).

### TikTok (one-time, plus TikTok's app review)
1. Make @chordsthatmove on TikTok.
2. developers.tiktok.com → Manage apps → **Connect an app**. Add the products **Login Kit** and
   **Content Posting API**. In Login Kit set the Redirect URI to
   `https://github.com/matteoriad/chordsthatmove`. Add the scope `video.upload`.
3. Submit the app for review (icon, description, terms + privacy URLs; the repo URL works for
   a personal tool). While waiting you can test in **Sandbox** by adding @chordsthatmove as a target user.
4. On your laptop: `python3 pipeline/connect.py tiktok CLIENT_KEY CLIENT_SECRET`, log in as
   @chordsthatmove, then paste the GitHub address the browser lands on back into the terminal.
5. Repo secrets: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`.
   Also add `GH_ADMIN_TOKEN` (a fine-grained PAT on this repo with *Secrets: read and write*) so
   the pipeline can save TikTok's refresh token when it rotates.

**Inbox mode (default):** each video lands in the TikTok app as a draft notification and you tap
Post (a chance to add a trending sound). No TikTok audit needed. **Direct mode:** set the repo variable
`TIKTOK_MODE=direct`, add the `video.publish` scope and Direct Post in the app, and redo step 4 with
`TIKTOK_MODE=direct python3 pipeline/connect.py tiktok ...`. Until TikTok audits the app, direct
posts are private-only; after the audit they go public by themselves.

## Adding songs
Write a sketch in `songs/sketches/` (copy an existing one), then build the queue file:

```
python3 -c "import json,voicing,sys; p=sys.argv[1]; json.dump(voicing.build(json.load(open(p))), open(p.replace('sketches','queue'),'w'), ensure_ascii=False, indent=1)" songs/sketches/ep15-your-song.json
```

Preview without posting: `python3 brandreel.py render songs/queue/ep15-your-song.json test.mp4`
and `python3 brandreel.py cover songs/queue/ep15-your-song.json test`.
When fewer than 20 episodes are left (about two weeks), the run opens a "Queue is running low" issue, which GitHub emails you. When the queue runs out, the job fails and GitHub emails you.

Optional sketch fields: `"question"` is a comment prompt added to the Instagram caption (default: asks which song to break down next); `"hashtag"` overrides the song hashtag (default: the title, lowercased).

## "Jam over this" reels
A progression to play along with, no song. Write a short file in `songs/jams/` (title, key, scale,
scale notes, bpm, hook, chords as `[name, roman, bars]`), then:

```
python3 songs/make_jam.py songs/jams/rainy-night.json 71
```

It writes `songs/sketches/ep71-jam-rainy-night.json` (the loop for about 25–35 s, the safe notes under each
chord, a "your turn" line at the end); build the queue file as usual. The outro points to
chordsthatmove.com/jam, and the caption carries a link that opens the tool with this exact
progression, key and tempo.

## Your own sounds (sample packs)
Record a sound (Moog, GarageBand …) as one file per note, named after the note: `C3.wav`, `D#3.wav`,
`F#3.wav`, `A3.wav` … (every 3 semitones from C2 to C5 is enough, ~4 s each, dry). Then:

```
python3 sounds/samples.py make ~/Desktop/moog-pad moog-pad "Moog pad" pad
```

That writes `sounds/moog-pad/` (trimmed, normalised WAVs for the reels, MP3s for the app, and
`pack.json`). Use it in one episode with `"sound": "moog-pad"` (pad) or `"arp_sound": "…"` (the
arpeggio), or for every reel with `sounds/default.json`: `{"pad": "moog-pad"}`. The jam app picks
the same packs up with `npm run sounds` (in chordsthatmove_app).

## Sound style
Reels use the "lush" pad (five detuned saws per voice, a filter that swells open on every chord, a
longer reverb, a rounder arpeggio). Set the repo variable / env `REEL_SOUND=classic` to go back to
the original sound. A sample pack (`"sound"`) replaces the pad either way.

## Reel format (loopable, lines first)
Since 20 Nov 2026 the voice lines take the middle of the frame (about 1.7× taller, thicker lines,
bigger dots), with a smaller chord name and captions above. Reels **loop**: no end card, the last
chord leads straight back to the first, the last 0.35 s blends into the opening frame, and the
reverb tail is wrapped onto the start, so Instagram's replay continues without a cut. Guess the
song reveals the answer in the last chord's caption. `REEL_LOOP=0` (or `"loop": false` in a sketch)
brings back the end card. Layout numbers are the constants at the top of `brandreel.py`.

## Themes
Reels rotate through the jam tool's looks: **Night** (the brand look) on every even episode, and on
odd episodes Riso, Chalkboard, Blueprint, Graph paper, Sheet music and Paper in turn. Set
`"theme": "chalk"` (night, riso, chalk, blueprint, graph, score, paper) in a sketch to pick one.
The default pink accent follows the theme; a custom `accent` stays as it is. The colours are in
`brandreel.THEMES` and match the app's `globals.css`.

## Timing (whole bars)
Each chord in a sketch has `"bars"`: how long it lasts in the original song in 4/4 bars
(1, 2, 0.5 = two beats, 0.25 = one beat). A final return-home chord gets `"ending": true`.
`brandreel.expand()` turns this into the played timeline: a whole-bar intro on the first chord
(the hook plays over it), the loop stretched evenly by ×2/×4 when chords would be too short
to read, and a whole-bar ending before the outro. Everything lands on whole bars and keeps
the record's proportions (Clocks: E♭ 2, B♭m 4, Fm 2). Old episodes with `"beats"` still render as before.

## Weekly report
Every Monday morning `.github/workflows/weekly-report.yml` runs `pipeline/insights.py`: all reels of
the last 14 days (at least 48 h old), grouped by format (song breakdown, guess the song, jam over
this, your own videos), slot and look, with views, reach, saves + shares per 1k views, watch time,
the top 5 and your follower change. It arrives as a GitHub issue (emailed) and in `reports/`.

**One-time:** the token needs the `instagram_manage_insights` permission. Redo step 2 of the
Instagram setup (Graph API Explorer → Get User Access Token) with `instagram_manage_insights`
ticked as well, extend it, read the Page token again with `me/accounts`, and replace the
`IG_ACCESS_TOKEN` secret. Then Actions → Weekly report → Run workflow to try it.
Python's `requests` is the only dependency, so the run takes under a minute.

## Pausing
Create `.github/PAUSED` to stop all automatic posting (manual runs from the Actions tab still work);
delete it to resume.
