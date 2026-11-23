#!/usr/bin/env python3
"""Song chord reel: one continuous line per voice, gliding between chords,
plus a distorted 16th-note arpeggio, an opening hook and theory captions.

Usage:
  python3 songreel.py stills SONG.json OUTDIR t1 t2 ...
  python3 songreel.py render SONG.json OUT.mp4

SONG.json:
  {"title": "Creep", "artist": "Radiohead", "key": "G major", "bpm": 92,
   "hook": "The *one chord* that makes Creep sound so sad", "hook_beats": 4,
   "chords": [{"name": "G", "roman": "I", "text": "Home: *G major*.", "beats": 8,
               "notes": ["G2", "B3", "D4", "G4"]}, ...]}
Every chord lists the same number of notes, lowest (bass) first: note i of
each chord is one continuous line. *stars* mark highlighted words.
"""
import json, os, re, subprocess, sys
import numpy as np
import cairo
from PIL import Image, ImageDraw, ImageFont
from scipy import signal
from scipy.io import wavfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds"))
import samples  # noqa: E402  (your recorded sound packs)

W, H, FPS, SR = 1080, 1920, 30, 44100
LEAD_IN, TAIL = 0.4, 2.8
GLIDE = 0.24                      # seconds, centred on each chord change
PX_PER_SEC = 150
PLAYHEAD_X = 330
ROLL_TOP, ROLL_BOT = 800, 1480
TITLE_Y, CHORD_Y, STRIP_Y, CAPTION_Y, HOOK_Y = 150, 300, 450, 552, 390

BG_TOP, BG_BOT = (16, 15, 22), (7, 7, 10)
VOICE_COLORS = [(255, 190, 105), (255, 128, 170), (178, 156, 255), (120, 214, 255),
                (150, 240, 190), (255, 240, 200)]
ACCENT = (255, 128, 170)
FONT_DIR = "/usr/share/fonts/opentype/inter/"

PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi(name):
    m = re.fullmatch(r"([A-G])([#b]?)(-?\d)", name)
    letter, acc, octv = m.groups()
    return PC[letter] + {"#": 1, "b": -1, "": 0}[acc] + 12 * (int(octv) + 1)


def pretty(name):
    return name.replace("b", "♭").replace("#", "♯") if len(name) > 1 else name


def pretty_chord(name):
    return re.sub(r"(^[A-G]|/[A-G])([#b])", lambda m: m.group(1) + ("♭" if m.group(2) == "b" else "♯"), name)


class Song:
    def __init__(self, spec):
        self.spec = spec
        self.beat = 60 / spec["bpm"]
        self.starts, t = [], LEAD_IN
        for c in spec["chords"]:
            self.starts.append(t)
            t += c["beats"] * self.beat
        self.end = t
        self.total = t + TAIL
        self.hook_end = LEAD_IN + spec.get("hook_beats", 4) * self.beat if spec.get("hook") else 0
        self.nv = len(spec["chords"][0]["notes"])
        assert all(len(c["notes"]) == self.nv for c in spec["chords"]), "same note count per chord"
        self.pitch = np.array([[midi(n) for n in c["notes"]] for c in spec["chords"]], float)
        self.arp = self.arp_events()

    def chord_at(self, t):
        i = 0
        for k, s in enumerate(self.starts):
            if t >= s: i = k
        return i

    def voice_curve(self, v, ts):
        """Pitch of voice v at times ts (smoothstep glides)."""
        p = np.full_like(ts, self.pitch[0, v])
        for i in range(1, len(self.starts)):
            x = np.clip((ts - self.starts[i] + GLIDE / 2) / GLIDE, 0, 1)
            p += (self.pitch[i, v] - self.pitch[i - 1, v]) * x * x * (3 - 2 * x)
        return p

    def arp_events(self):
        """16th-note arpeggio: (time, voice, midi, accent). Bass an octave up, then up and down the chord."""
        up = list(range(1, self.nv))
        pattern = [(0, 12)] + [(v, 0) for v in up] + [(1, 12)] + [(v, 0) for v in reversed(up)]
        step, ev, k = self.beat / 4, [], 0
        rng = np.random.default_rng(sum(map(ord, self.spec["title"])))
        while LEAD_IN + k * step < self.end - 1e-6:
            t = LEAD_IN + k * step
            v, octv = pattern[k % len(pattern)]
            ci = self.chord_at(t)
            # soft by default, with the odd random louder note
            vel = 1.0 if rng.random() < 0.14 else rng.uniform(0.35, 0.55)
            ev.append((t, v, self.pitch[ci, v] + octv, vel))
            k += 1
        return ev


# ------------------------------------------------------------------ audio --
def svf_pluck(x, fc_env, damp=0.22):
    """Chamberlin state-variable low-pass with a per-sample cutoff."""
    F = 2 * np.sin(np.pi * np.minimum(fc_env, SR / 7) / SR)
    low = band = 0.0
    out = np.empty_like(x)
    for i in range(len(x)):
        low += F[i] * band
        high = x[i] - low - damp * band
        band += F[i] * high
        out[i] = low
    return out


def arp_layer(song, n):
    out = np.zeros(n)
    dur = 0.30
    t = np.arange(int(dur * SR)) / SR
    for s, v, m, vel in song.arp:
        f = 440 * 2 ** ((m - 69) / 12)
        ph = (f * t) % 1
        osc = 0.6 * (2 * ph - 1) + 0.5 * np.where(ph < 0.35, 1.0, -1.0)
        fc = 420 + (1500 + 2300 * vel) * np.exp(-t / 0.07)
        y = svf_pluck(osc, fc)
        y = np.tanh((3.2 if STYLE == "classic" else 1.7) * y)   # grit (lush: rounder, more like a synth pluck)
        amp = (1 - np.exp(-t / 0.002)) * np.exp(-t / 0.11) * vel
        i0 = int(s * SR)
        seg = y * amp
        out[i0:i0 + len(seg)] += seg[:max(0, n - i0)]
    return signal.sosfilt(signal.butter(2, 160, "high", fs=SR, output="sos"), out)


def delayed(x, sec):
    k = int(sec * SR)
    return np.concatenate([np.zeros(k), x[:-k]])


def rms(x): return np.sqrt(np.mean(x ** 2)) + 1e-9


def log_sound(role, pack): print(f"{role} sound: {pack['meta'].get('label', pack['meta']['id'])}", flush=True)


STYLE = os.environ.get("REEL_SOUND") or "lush"   # "lush" (2026-11-20) or "classic" (the original pad)


# Sound profiles (2026-11-20): not every reel should sound the same. Chosen per song by profile_for().
PROFILES = {
    "lush":  dict(arp=0.32, pad=1.0),    # wide detuned pad + soft arpeggio (the default)
    "warm":  dict(arp=0.0, pad=1.0),     # darker pad, no arpeggio: slow, sad songs
    "pluck": dict(arp=0.62, pad=0.75),   # lighter pad, the arpeggio in front: fast songs
    "keys":  dict(arp=0.18, pad=1.0),    # electric-piano tone, re-struck each chord: jazz and soul
    "organ": dict(arp=0.0, pad=1.0),     # drawbar organ with a rotary wobble
}
JAZZY = ("7", "maj7", "m7", "6", "m6", "7sus4", "add9")


SLOW_SAD = ["pad-analog", "amb-grains", "dream-pad", "pad-lush"]
FAST = ["pad-supersaw", "dream-lofi", "pad-lush", "dream-vapor"]
DEFAULT_ROT = ["pad-lush", "pad-analog", "pad-supersaw", "dream-pad", "dream-vapor", "dream-lofi", "org-church"]


def sound_for(spec):
    """The held sound, texture and breath layer for a reel, from Matteo's picks (sounds/catalog.py).
    Rotates by episode within a mood group so consecutive reels sound different.
    Overrides: spec["sound"] (a catalogue id, e.g. "dream-vapor"), spec["texture"] ("tex-harp" or "none")."""
    import catalog
    ep = int(spec.get("episode") or 0)
    minor = "minor" in spec.get("key", "").lower()
    if spec.get("sound") in catalog.GEN: held = spec["sound"]
    elif minor and spec["bpm"] < 85: held = SLOW_SAD[ep % len(SLOW_SAD)]
    elif spec["bpm"] >= 110: held = FAST[ep % len(FAST)]
    else: held = DEFAULT_ROT[ep % len(DEFAULT_ROT)]
    tex = spec.get("texture")
    if tex not in catalog.TEX and tex != "none":
        tex = "none" if held == "amb-grains" else catalog.PICKED_TEX[(ep // 2) % len(catalog.PICKED_TEX)]
    breath = held in catalog.BREATH_UNDER and (minor or spec["bpm"] < 90)
    return {"held": held, "texture": tex, "breath": breath}


def profile_for(spec):
    """Old profile names, kept for the glide rule: maps the picked sound to a profile."""
    try:
        held = sound_for(spec)["held"]
        return {"amb-grains": "warm", "pad-analog": "warm", "pad-supersaw": "pluck", "dream-lofi": "pluck",
                "org-church": "organ"}.get(held, "lush")
    except Exception:
        pass
    return _profile_for_old(spec)


def _profile_for_old(spec):
    """spec["sound_profile"] if set, else from the chords, key and tempo."""
    if spec.get("sound_profile") in PROFILES: return spec["sound_profile"]
    names = [c["name"].split("/")[0] for c in spec["chords"]]
    quals = [re.sub(r"^[A-G][#b]?", "", n) for n in names]
    jazzy = sum(q in JAZZY for q in quals) / max(1, len(quals))
    minor = "minor" in spec.get("key", "").lower()
    if jazzy >= 0.4: return "keys"
    if spec["bpm"] >= 115: return "pluck"
    if minor and spec["bpm"] < 80: return "warm"
    return ("lush", "lush", "organ")[int(spec.get("episode") or 0) % 3]


def keys_pad(song, tt, env):
    """Electric-piano-like: sine plus a bell-ish 2nd/3rd harmonic that decays, re-struck on every chord."""
    since = np.zeros(len(tt))
    for st in song.starts: since = np.where(tt >= st, tt - st, since)
    strike = np.exp(-since / 1.4) * 0.75 + 0.25
    bell = np.exp(-since / 0.25)
    sides = []
    for spread in (-4, 4):   # a few cents apart left/right
        acc = np.zeros(len(tt))
        for v in range(1, song.nv):
            f = 440 * 2 ** ((song.voice_curve(v, tt) - 69 + spread / 100) / 12)
            ph = 2 * np.pi * np.cumsum(f) / SR
            acc += np.sin(ph + 0.8 * bell * np.sin(2 * ph)) + 0.12 * np.sin(3 * ph) * bell
        sides.append(acc * strike * env)
    return sides


def organ_pad(song, tt, env):
    """Drawbar organ (harmonics 1 2 3 4 6 8) with a rotary-style wobble that moves left and right."""
    bars = ((1, 1.0), (2, 0.7), (3, 0.5), (4, 0.35), (6, 0.2), (8, 0.15))
    acc = np.zeros(len(tt))
    for v in range(1, song.nv):
        ph = 2 * np.pi * np.cumsum(440 * 2 ** ((song.voice_curve(v, tt) - 69) / 12)) / SR
        acc += sum(a * np.sin(k * ph) for k, a in bars)
    rot = np.sin(2 * np.pi * 5.6 * tt)
    acc = signal.sosfilt(signal.butter(2, 3500, "low", fs=SR, output="sos"), acc * env)
    return [acc * (1 + 0.18 * rot), acc * (1 - 0.18 * rot)]


def glide_for(spec, profile):
    """Seconds each voice takes to slide to its next note: longer chords and calmer songs glide slower.
    spec["glide"] overrides."""
    if spec.get("glide"): return float(spec["glide"])
    beat = 60 / spec["bpm"]
    lens = sorted(c.get("beats", 4) * beat for c in spec["chords"])
    med = lens[len(lens) // 2]
    g = float(np.clip(0.1 + 0.12 * med, 0.18, 0.55))
    return round(g * {"warm": 1.3, "pluck": 0.75, "keys": 0.9}.get(profile, 1.0), 3)


def lush_pad(song, tt, env, bright=3200, base=0.3):
    """Five detuned saws per voice, spread left/right, through a filter that swells open on every
    chord (a dark and a bright copy crossfaded, so it stays cheap). Returns (left, right)."""
    rng = np.random.default_rng(7)
    sides = []
    for detunes in ((-14, -6, 0, 5, 12), (-11, -3, 0, 7, 15)):   # different per side = width
        acc = np.zeros(len(tt))
        for v in range(1, song.nv):
            f = 440 * 2 ** ((song.voice_curve(v, tt) - 69) / 12)
            cyc = np.cumsum(f) / SR
            acc += sum(2 * ((cyc * 2 ** (d / 1200) + rng.random()) % 1) - 1 for d in detunes) / len(detunes)
            acc += 0.35 * np.sin(2 * np.pi * (cyc * 0.5 + rng.random()))   # soft sub-octave body
        sides.append(acc * env)
    dark = [signal.sosfilt(signal.butter(2, 650, "low", fs=SR, output="sos"), x) for x in sides]
    bright = [signal.sosfilt(signal.butter(2, bright, "low", fs=SR, output="sos"), x) for x in sides]
    # swell: opens over ~0.6 of a chord, eases back; a slow 0.13 Hz drift keeps long chords alive
    open_ = np.zeros(len(tt))
    for i, st in enumerate(song.starts):
        en = song.starts[i + 1] if i + 1 < len(song.starts) else song.end
        m = (tt >= st) & (tt < en + 0.5)
        # smooth: from half open, rise over the first 45% of the chord, then ease back only slightly
        # (the old swell peaked early and dropped off, which sounded loud-then-quiet)
        x = np.clip((tt[m] - st) / max(0.4, en - st), 0, 1)
        rise = np.clip(x / 0.45, 0, 1); rise = rise * rise * (3 - 2 * rise)
        open_[m] = np.maximum(open_[m], 0.55 + 0.45 * rise - 0.25 * np.clip((x - 0.45) / 0.55, 0, 1))
    k = base + 0.6 * open_ + 0.1 * np.sin(2 * np.pi * 0.13 * tt)
    return [0.16 * (d * (1 - k) + b * k) for d, b in zip(dark, bright)]


def synth(song, path):
    n = int(song.total * SR)
    pad, bass = np.zeros(n), np.zeros(n)
    rng = np.random.default_rng(1)
    rel = 1.0
    tt = np.arange(n) / SR
    s0, e0 = song.starts[0], song.end
    env = np.clip((tt - s0) / 0.12, 0, 1) * np.where(tt < e0, 1.0, np.exp(-(tt - e0) / (rel / 4)))
    for v in range(song.nv):
        f = 440 * 2 ** ((song.voice_curve(v, tt) - 69) / 12)
        cyc = np.cumsum(f) / SR
        if v == 0:
            w = np.sin(2 * np.pi * cyc) + 0.3 * (2 * (cyc % 1) - 1)
            bass += 0.7 * w * env   # +3 dB since 2026-11-23 (Matteo: bass louder)
        else:
            w = sum(2 * ((cyc * 2 ** (d / 1200) + rng.random()) % 1) - 1 for d in (-8, 0, 7))
            pad += 0.12 * w * env
    # pad ducks on every beat so the arp punches through
    ph = ((tt - LEAD_IN) / song.beat) % 1
    pad *= 1 - 0.15 * np.exp(-ph * 5) * (tt > LEAD_IN)
    # your own recorded sound replaces the saw pad (sounds/samples.py; "sound" in the episode)
    pad_pack = samples.load(song.spec.get("sound") or samples.default("pad"))
    if pad_pack:
        pad = 0.5 * samples.layer(song, pad_pack, n, range(1, song.nv)) * env
        log_sound("pad", pad_pack)
    pad = signal.sosfilt(signal.butter(3, 1800, "low", fs=SR, output="sos"), pad)
    pads = [pad, pad]
    profile = profile_for(song.spec) if STYLE == "lush" else "classic"
    picked = sound_for(song.spec) if STYLE == "lush" and not pad_pack else None
    tex_ch = None
    if picked:
        import catalog
        catalog.use(song, n)
        L_, R_ = catalog.GEN[picked["held"]]()
        if picked["breath"]:   # "Breath" only as a quiet layer on top
            bL, bR = catalog.amb_air()
            g = 0.16 * rms(L_) / rms(bL)
            L_, R_ = L_ + g * bL, R_ + g * bR
        if picked["texture"] != "none":
            tex_ch = catalog.texture(*catalog.TEX[picked["texture"]])
        print(f"sound: {picked['held']}{' + breath' if picked['breath'] else ''} · texture: {picked['texture']}", flush=True)
    if STYLE == "lush" and not pad_pack:
        mid, side = 0.5 * (L_ + R_), 0.5 * (L_ - R_)   # natural width: still safe on mono phone speakers
        duck = 1 - 0.05 * np.exp(-ph * 5) * (tt > LEAD_IN)   # a much lighter pump than the classic pad
        gain = rms(pad) / rms(mid) * PROFILES[profile]["pad"]   # same loudness as the classic pad
        pads = [(mid + side) * duck * gain, (mid - side) * duck * gain]
        pad = mid * duck * gain
    bass = signal.sosfilt(signal.butter(3, 360, "low", fs=SR, output="sos"), bass)
    bass *= 1 - 0.12 * np.exp(-ph * 5) * (tt > LEAD_IN)
    arp_pack = samples.load(song.spec.get("arp_sound") or samples.default("arp"))
    arp = samples.arp(song, arp_pack, n) if arp_pack else arp_layer(song, n)
    if arp_pack: log_sound("arp", arp_pack)
    arp *= (PROFILES[profile]["arp"] if profile in PROFILES else 0.32) * rms(pad) / rms(arp)   # level per profile
    # ping-pong echoes at a dotted eighth
    d8 = 0.75 * song.beat
    arpL = arp + 0.30 * delayed(arp, 2 * d8)
    arpR = arp + 0.38 * delayed(arp, d8) + 0.16 * delayed(arp, 3 * d8)
    if picked:   # the picked texture (its own echoes), mixed subtly under the chords
        if tex_ch is None:
            arp, arpL, arpR = arp * 0, arpL * 0, arpR * 0
        else:
            g = 0.2 * rms(pad) / rms(tex_ch[0])
            arpL, arpR = tex_ch[0] * g, tex_ch[1] * g
            arp = 0.5 * (arpL + arpR)
    lush = STYLE == "lush"
    irn = int((4.0 if lush else 2.8) * SR)
    decay = np.exp(-np.arange(irn) / SR / (1.25 if lush else 0.75))
    chans = []
    for seed, a_ch, p_ch in ((2, arpL, pads[0]), (3, arpR, pads[1])):
        ir = np.random.default_rng(seed).standard_normal(irn) * decay
        ir = signal.sosfilt(signal.butter(2, 3200 if not lush else 2600, "low", fs=SR, output="sos"), ir)
        send = p_ch + (0.45 if lush else 0.3) * arp
        wet = signal.fftconvolve(send, ir)[:n]
        chans.append(p_ch + bass + a_ch + (0.95 if lush else 0.8) * wet / np.max(np.abs(wet)) * np.max(np.abs(p_ch)))
    st = np.stack(chans, axis=1)
    st = np.tanh(1.1 * st / np.max(np.abs(st)))
    st *= 0.89 / np.max(np.abs(st))
    fade = int(1.0 * SR)
    st[-fade:] *= np.linspace(1, 0, fade)[:, None]
    wavfile.write(path, SR, (st * 32767).astype(np.int16))


# ---------------------------------------------------------------- visuals --
def mix(c, a, bg=(12, 12, 17)):
    return tuple(int(c[i] * a + bg[i] * (1 - a)) for i in range(3))


ACC_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_acc_cache = {}
_measure = ImageDraw.Draw(Image.new("L", (1, 1)))


def rich(d, xy, text, font, fill, anchor="lm"):
    """Draw text whose ♯/♭ come from a fallback font; anchors 'lm' or 'mm'. Returns width."""
    size = font.size
    if size not in _acc_cache: _acc_cache[size] = ImageFont.truetype(ACC_FONT, size)
    af = _acc_cache[size]
    runs = re.findall(r"[♯♭]|[^♯♭]+", text)
    widths = [_measure.textlength(r, font=af if r in "♯♭" else font) + (size * 0.04 if r in "♯♭" else 0)
              for r in runs]
    if d is None: return sum(widths)
    x, y = xy
    if anchor == "mm": x -= sum(widths) / 2
    bb = font.getbbox("H")
    base = y + (bb[3] - bb[1]) / 2
    for r, w in zip(runs, widths):
        if r in "♯♭":
            d.text((x + size * 0.02, base - size * 0.02), r, font=af, fill=fill, anchor="ls")
        else:
            d.text((x, base), r, font=font, fill=fill, anchor="ls")
        x += w
    return sum(widths)


def layout(tokens, max_w):
    """tokens: [(word, font, color)] -> lines of tokens, greedy wrap."""
    lines, cur, cw = [], [], 0
    for tok in tokens:
        w = rich(None, None, tok[0], tok[1], None)
        sp = 0 if (len(tok) > 3 and tok[3]) else _measure.textlength(" ", font=tok[1])
        if cur and cw + sp + w > max_w:
            lines.append(cur); cur, cw = [], 0
        cw += (sp if cur else 0) + w
        cur.append(tok[:3] + (w, sp))
    if cur: lines.append(cur)
    return lines


def draw_lines(d, lines, cx, y0, lh):
    for li, line in enumerate(lines):
        total = sum(t[3] for t in line) + sum(t[4] for t in line[1:])
        x = cx - total / 2
        for j, (word, font, color, w, sp) in enumerate(line):
            if j: x += sp
            rich(d, (x, y0 + li * lh), word, font, color)
            x += w


def marked_tokens(text, font, font_hi, color, color_hi):
    toks, hi = [], False
    prev = ""
    for part in re.split(r"(\*)", text):
        if part == "*": hi = not hi; continue
        # glue only when there is no space on either side, e.g. "*D♯*," keeps the comma attached
        glue = bool(part) and bool(prev) and not part[0].isspace() and not prev[-1].isspace() and bool(toks)
        if part: prev = part
        for j, w in enumerate(part.split()):
            toks.append((w, font_hi if hi else font, color_hi if hi else color, glue and j == 0))
    return toks


class Renderer:
    def __init__(self, song):
        self.song = song
        allp = song.pitch.flatten()
        self.lo, self.hi = allp.min() - 2.5, allp.max() + 2.5
        F = lambda name, size: ImageFont.truetype(FONT_DIR + name, size)
        self.f_title = F("Inter-Medium.otf", 32)
        self.f_chord = F("InterDisplay-SemiBold.otf", 190)
        self.f_strip = F("Inter-Medium.otf", 40)
        self.f_marker = F("Inter-Medium.otf", 32)
        self.f_note = F("Inter-SemiBold.otf", 30)
        self.f_note_dim = F("Inter-Medium.otf", 26)
        self.f_cap = F("Inter-Medium.otf", 36)
        self.f_cap_hi = F("Inter-SemiBold.otf", 36)
        self.f_hook = F("InterDisplay-SemiBold.otf", 84)
        self.colors = [VOICE_COLORS[i % len(VOICE_COLORS)] for i in range(song.nv)]
        self.hits = [np.array([e[0] for e in song.arp if e[1] == v]) for v in range(song.nv)]
        self.vels = [np.array([e[3] for e in song.arp if e[1] == v]) for v in range(song.nv)]
        bg = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
        cr = cairo.Context(bg)
        g = cairo.LinearGradient(0, 0, 0, H)
        g.add_color_stop_rgb(0, *[c / 255 for c in BG_TOP])
        g.add_color_stop_rgb(1, *[c / 255 for c in BG_BOT])
        cr.set_source(g); cr.paint()
        cr.set_line_width(1)
        for m in range(int(np.ceil(self.lo)), int(self.hi) + 1):
            y = self.y(m) + 0.5
            cr.set_source_rgba(1, 1, 1, 0.075 if m % 12 == 0 else 0.03)
            cr.move_to(0, y); cr.line_to(W, y); cr.stroke()
        self.bg = bg

    def y(self, p): return ROLL_BOT - (p - self.lo) / (self.hi - self.lo) * (ROLL_BOT - ROLL_TOP)
    def x(self, ts, now): return PLAYHEAD_X + (ts - now) * PX_PER_SEC

    def flash(self, v, now):
        h = self.hits[v]
        k = np.searchsorted(h, now, side="right") - 1
        return float(self.vels[v][k] * np.exp(-(now - h[k]) / 0.11)) if k >= 0 else 0.0

    def frame(self, now):
        s, sp = self.song, self.song.spec
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
        cr = cairo.Context(surf)
        cr.set_source_surface(self.bg); cr.paint()
        t_left, t_right = now - PLAYHEAD_X / PX_PER_SEC, now + (W - PLAYHEAD_X) / PX_PER_SEC
        bar = 4 * s.beat
        k = np.ceil((t_left - LEAD_IN) / bar)
        cr.set_line_width(1)
        while LEAD_IN + k * bar < min(t_right, s.end):
            bx = round(self.x(LEAD_IN + k * bar, now)) + 0.5
            if k >= 0:
                cr.set_source_rgba(1, 1, 1, 0.035)
                cr.move_to(bx, ROLL_TOP - 10); cr.line_to(bx, ROLL_BOT + 10); cr.stroke()
            k += 1
        markers = []
        for i, st in enumerate(s.starts):
            mx = self.x(st, now)
            if -50 < mx < W + 10:
                a = 0.28 if st > now else 0.28 * max(0, 1 - (now - st) / 1.8)
                cr.set_source_rgba(1, 1, 1, a)
                cr.move_to(round(mx) + 0.5, ROLL_TOP - 30); cr.line_to(round(mx) + 0.5, ROLL_BOT + 30); cr.stroke()
                markers.append((mx, i, a))
        ts = np.linspace(max(t_left, 0), min(t_right, s.end), 400)
        heads = []
        for v in range(s.nv):
            col = [c / 255 for c in self.colors[v]]
            ys = self.y(s.voice_curve(v, ts))
            xs = self.x(ts, now)
            past = ts <= now
            for mask, alpha, lw in ((~past, 0.32, 3), (past, 0.95, 4)):
                idx = np.where(mask)[0]
                if len(idx) < 2: continue
                if mask is past and idx[-1] + 1 < len(ts): idx = np.append(idx, idx[-1] + 1)
                if alpha > 0.5:
                    cr.set_source_rgba(*col, 0.12); cr.set_line_width(14)
                    cr.move_to(xs[idx[0]], ys[idx[0]])
                    for j in idx[1:]: cr.line_to(xs[j], ys[j])
                    cr.stroke()
                cr.set_source_rgba(*col, alpha); cr.set_line_width(lw)
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.move_to(xs[idx[0]], ys[idx[0]])
                for j in idx[1:]: cr.line_to(xs[j], ys[j])
                cr.stroke()
            if LEAD_IN - 0.4 <= now <= s.end:
                hy = float(self.y(s.voice_curve(v, np.array([now]))[0]))
                heads.append((v, hy))
        cr.set_source_rgba(1, 1, 1, 0.55); cr.set_line_width(2)
        cr.move_to(PLAYHEAD_X, ROLL_TOP - 30); cr.line_to(PLAYHEAD_X, ROLL_BOT + 30); cr.stroke()
        for v, hy in heads:
            col = [c / 255 for c in self.colors[v]]
            fl = self.flash(v, now)          # arp hit on this voice
            r = 44 * (1 + 0.55 * fl)
            g = cairo.RadialGradient(PLAYHEAD_X, hy, 0, PLAYHEAD_X, hy, r)
            g.add_color_stop_rgba(0, *col, 0.6 + 0.4 * fl); g.add_color_stop_rgba(1, *col, 0)
            cr.set_source(g); cr.arc(PLAYHEAD_X, hy, r, 0, 6.2832); cr.fill()
            cr.set_source_rgb(1, 1, 1); cr.arc(PLAYHEAD_X, hy, 8 + 4 * fl, 0, 6.2832); cr.fill()

        # ---- text (PIL) ----
        buf = np.frombuffer(surf.get_data(), np.uint8).reshape(H, surf.get_stride() // 4, 4)[:, :W]
        img = Image.fromarray(buf[:, :, [2, 1, 0]].copy())
        d = ImageDraw.Draw(img)
        d.text((W / 2, TITLE_Y), f"{sp['artist'].upper()}  —  {sp['title'].upper()}", font=self.f_title,
               fill=(150, 150, 165), anchor="mm")
        ui = 1.0 if not s.hook_end else float(np.clip((now - s.hook_end) / 0.35, 0, 1))
        if s.hook_end and now < s.hook_end + 0.05:
            ha = float(np.clip((s.hook_end - now) / 0.3, 0, 1)) * min(1, (now + 0.2) / 0.2)
            toks = marked_tokens(sp["hook"], self.f_hook, self.f_hook, mix((255, 255, 255), ha), mix(ACCENT, ha))
            lines = layout(toks, 940)
            lh = 100
            draw_lines(d, lines, W / 2, HOOK_Y - (len(lines) - 1) * lh / 2, lh)
        ci = s.chord_at(now)
        ch = sp["chords"][ci]
        if ui > 0:
            since = now - max(s.starts[ci], s.hook_end)
            a = ui * min(1, 0.35 + max(0, since) / 0.18 * 0.65)
            rich(d, (W / 2, CHORD_Y), pretty_chord(ch["name"]), self.f_chord, mix((255, 255, 255), a), "mm")
            names = []
            for c in sp["chords"]:
                if c["name"] not in names: names.append(c["name"])
            ws = [rich(None, None, pretty_chord(n_), self.f_strip, None) for n_ in names]
            gap = 46
            x0 = W / 2 - (sum(ws) + gap * (len(ws) - 1)) / 2
            for n_, w_ in zip(names, ws):
                on = n_ == ch["name"]
                rich(d, (x0, STRIP_Y), pretty_chord(n_), self.f_strip,
                     mix((245, 245, 250) if on else (88, 88, 104), ui))
                if on: d.rounded_rectangle([x0, STRIP_Y + 33, x0 + w_, STRIP_Y + 37], radius=2,
                                           fill=mix((245, 245, 250), ui))
                x0 += w_ + gap
            if ch.get("text"):
                ca = ui * float(np.clip(since / 0.35, 0, 1))
                toks = []
                if ch.get("roman"): toks.append((ch["roman"] + "  ·", self.f_cap_hi, mix(ACCENT, ca)))
                toks += marked_tokens(ch["text"], self.f_cap, self.f_cap_hi,
                                      mix((175, 175, 192), ca), mix((255, 255, 255), ca))
                draw_lines(d, layout(toks, 940), W / 2, CAPTION_Y, 50)
        for mx, i, a in markers:
            rich(d, (mx + 12, ROLL_TOP - 52), pretty_chord(sp["chords"][i]["name"]), self.f_marker,
                 mix((255, 255, 255), min(1, a * 2.4)))
            if s.starts[i] > now and mx + 40 < W - 40:
                for v in range(s.nv):
                    ly = self.y(s.pitch[i, v]) - 22
                    rich(d, (mx + 24, ly), pretty(sp["chords"][i]["notes"][v]), self.f_note_dim,
                         mix(self.colors[v], 0.55))
        for v, hy in heads:
            rich(d, (PLAYHEAD_X + 26, hy - 24), pretty(ch["notes"][v]), self.f_note, self.colors[v])
        return img


def stills(spec, outdir, times):
    r = Renderer(Song(spec))
    os.makedirs(outdir, exist_ok=True)
    for t in map(float, times):
        p = os.path.join(outdir, f"frame_{t:05.2f}.jpg")
        r.frame(t).save(p, quality=90); print(p)


def render(spec, out):
    song = Song(spec)
    base = os.path.splitext(out)[0]
    wav, silent, tmp = base + ".wav", base + ".video.tmp.mp4", base + ".tmp.mp4"
    synth(song, wav)
    r = Renderer(song)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                           "-crf", "19", "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
    for i in range(int(song.total * FPS)):
        ff.stdin.write(r.frame(i / FPS).tobytes())
    ff.stdin.close()
    if ff.wait() != 0: sys.exit("video encode failed")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", wav, "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", tmp],
                   check=True)
    os.replace(tmp, out); os.remove(silent); os.remove(wav)
    print(out)


if __name__ == "__main__":
    cmd, spec = sys.argv[1], json.load(open(sys.argv[2]))
    if cmd == "stills": stills(spec, sys.argv[3], sys.argv[4:])
    elif cmd == "render": render(spec, sys.argv[3])
