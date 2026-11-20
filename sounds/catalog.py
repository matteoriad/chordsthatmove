#!/usr/bin/env python3
"""Sound catalogue: candidate sounds for the reels and the jam app, to audition and pick from.

  python3 sounds/catalog.py OUTDIR

Renders every candidate over the same loop (Am – F – C – G, 76 bpm, the reels' voicing and glide)
to OUTDIR/<id>.mp3 plus OUTDIR/catalog.json. Four slots for held sounds (pad, organ, dreamy, ambient)
and one for textures/arpeggios. A picked candidate becomes a reel sound profile (songreel.py) and,
through sounds/reel_packs.py, a sample pack for the app.
"""
import json, os, subprocess, sys
import numpy as np
from scipy import signal
from scipy.io import wavfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import songreel as sr, voicing  # noqa: E402

SR = sr.SR
BPM, BARS = 76, ["Am", "F", "C", "G"]
TAIL = 3.0


# ------------------------------------------------------------------ the loop --
def make_song():
    spec = voicing.build({"title": "catalog", "artist": "", "key": "A minor", "bpm": BPM,
                          "chords": [{"name": n, "beats": 4, "text": ""} for n in BARS]})
    sr.LEAD_IN, sr.TAIL, sr.GLIDE = 0.0, TAIL, 0.4
    return sr.Song(spec)


SONG = N = T = END = STARTS = since = clen = ENV = None


def use(song, n=None):
    """Point every generator below at a song (the catalogue loop, or a reel from songreel.synth)."""
    global SONG, N, T, END, STARTS, since, clen, ENV
    SONG = song
    N = n or int(song.total * SR)
    T = np.arange(N) / SR
    END = song.end
    STARTS = np.array(song.starts)
    since = np.zeros(N); clen = np.zeros(N)
    for i, st in enumerate(STARTS):
        en = STARTS[i + 1] if i + 1 < len(STARTS) else END
        m = T >= st; since[m] = T[m] - st; clen[m] = en - st
    ENV = np.clip((T - STARTS[0]) / 0.05, 0, 1) * np.where(T < END, 1.0, np.exp(-(T - END) / 0.5))


def midi_curve(v): return SONG.voice_curve(v, T)
def hz(m): return 440 * 2 ** ((m - 69) / 12)
def phase(f): return np.cumsum(f) / SR   # in cycles
def saw(p): return 2 * (p % 1) - 1
def sq(p, w=0.5): return np.where(p % 1 < w, 1.0, -1.0)
def tri(p): return 2 * np.abs(saw(p)) - 1
def sine(p): return np.sin(2 * np.pi * p)
def lp(x, fc, o=2): return signal.sosfilt(signal.butter(o, min(fc, SR / 2.2), "low", fs=SR, output="sos"), x)
def hp(x, fc, o=2): return signal.sosfilt(signal.butter(o, fc, "high", fs=SR, output="sos"), x)
def bp(x, lo, hi): return signal.sosfilt(signal.butter(2, [lo, hi], "band", fs=SR, output="sos"), x)
def rms(x): return np.sqrt(np.mean(x ** 2)) + 1e-9


def chord_env(attack, release=0.6, sustain=1.0):
    """Per-chord swell that never drops to silence between chords (held sounds re-voice, not re-strike)."""
    a = np.clip(since / max(attack, 1e-3), 0, 1)
    return (0.55 + 0.45 * a * a * (3 - 2 * a)) * sustain


def sweep(dark, bright, x, rise=0.45, ease_back=0.25):
    """Low-pass that opens over each chord (crossfade of a dark and a bright copy)."""
    r = np.clip(since / np.maximum(clen * rise, 0.3), 0, 1); r = r * r * (3 - 2 * r)
    k = np.clip(0.4 + 0.6 * r - ease_back * np.clip((since / np.maximum(clen, 0.3) - rise) / (1 - rise), 0, 1), 0, 1)
    return lp(x, dark) * (1 - k) + lp(x, bright) * k


def chorus(x, depth=0.003, rate=0.35, base=0.012, side=1):
    d = base + depth * np.sin(2 * np.pi * rate * T + (0 if side > 0 else np.pi / 2))
    return 0.6 * x + 0.5 * np.interp(T - d, T, x, left=0)


def vib(m, rate=5.0, cents=8): return m + cents / 100 * np.sin(2 * np.pi * rate * T)


def voices(fn, detunes=(0,), spread=0.0):
    """Sum fn(phase, midi, v) over the three upper voices and detunes; returns (L, R)."""
    L, R = np.zeros(N), np.zeros(N)
    rng = np.random.default_rng(3)
    for v in range(1, SONG.nv):
        m = midi_curve(v)
        for j, d in enumerate(detunes):
            p = phase(hz(m + d / 100)) + rng.random()
            y = fn(p, m, v)
            pan = 0.5 + spread * ((j / max(1, len(detunes) - 1)) - 0.5) if len(detunes) > 1 else 0.5
            L += y * (1 - pan); R += y * pan
    return L, R


# ------------------------------------------------------------------ candidates --
def pad_lush():
    tt, env = T, ENV
    return sr.lush_pad(SONG, tt, env)

def pad_analog():
    L, R = voices(lambda p, m, v: saw(p) + 0.6 * sine(p / 2), (-6, 6), 0.6)
    e = chord_env(0.5) * ENV
    return [lp(x, 1300) * e for x in (L, R)]

def pad_choir():
    L, R = voices(lambda p, m, v: saw(p), (-9, 0, 9), 0.7)
    f = lambda x: bp(x, 600, 950) + 0.8 * bp(x, 1050, 1350) + 0.3 * bp(x, 2400, 2900)   # "aah" formants
    e = chord_env(0.7) * ENV
    return [chorus(f(x), side=s) * e for x, s in ((L, 1), (R, -1))]

def pad_supersaw():
    L, R = voices(lambda p, m, v: saw(p), (-21, -13, -6, 0, 6, 13, 21), 0.9)
    e = chord_env(0.25) * ENV
    return [sweep(1800, 6500, x) * e for x in (L, R)]

def pad_juno():
    L, R = voices(lambda p, m, v: sq(p, 0.5 + 0.18 * np.sin(2 * np.pi * 0.6 * T)), (-5, 5), 0.6)
    e = chord_env(0.35) * ENV
    return [chorus(lp(x, 2200), side=s) * e for x, s in ((L, 1), (R, -1))]


DRAW = (1, 3, 2, 4, 6, 8, 10, 12, 16)   # drawbar harmonics of the 16' pitch


def organ(reg, rotary=0.8, drive=0.0, click=0.3, attack=0.01, vibr=0.0):
    amps = [int(c) / 8 for c in reg]
    def fn(p, m, v):
        p0 = p / 2   # 16' = an octave below
        return sum(a * sine(p0 * h) for a, h in zip(amps, DRAW) if a)
    L, R = voices(fn, (0,))
    x = L + R
    if vibr: x = 0.7 * x + 0.3 * np.interp(T - 0.002 * (1 + np.sin(2 * np.pi * 6.5 * T)), T, x, left=0)
    if drive: x = np.tanh(drive * x / (np.max(np.abs(x)) + 1e-9)) * np.max(np.abs(x)) / np.tanh(drive)
    noise = np.random.default_rng(1).standard_normal(N)
    clk = hp(noise, 2500) * np.exp(-since / 0.012) * click * rms(x) * 3
    e = np.clip(since / max(attack, 1e-3), 0, 1) if attack > 0.05 else 1.0
    x = lp(x * e + clk, 5000) * ENV
    rot = np.sin(2 * np.pi * rotary * T)
    return [x * (1 + 0.25 * rot), x * (1 - 0.25 * rot)]

def org_jazz(): return organ("888000000", rotary=0.9, click=0.5)
def org_gospel(): return organ("888888888", rotary=6.2, drive=1.8, click=0.4)
def org_flute(): return organ("008000000", rotary=0.6, click=0.0, vibr=1)
def org_church(): return organ("008808008", rotary=0.0, click=0.0, attack=0.35)
def org_rock(): return organ("888000008", rotary=6.0, drive=3.0, click=0.6)

def dream_pad():
    L, R = voices(lambda p, m, v: saw(p) + 0.5 * sine(2 * p), (-10, 10), 0.8)
    lfo = 0.5 + 0.5 * np.sin(2 * np.pi * 0.15 * T)
    e = chord_env(0.9) * ENV
    out = []
    for x, s in ((L, 1), (R, -1)):
        y = lp(x, 900) * (1 - lfo) + lp(x, 3000) * lfo
        out.append(chorus(y, depth=0.004, rate=0.25, side=s) * e)
    return out

def dream_glass():
    def fn(p, m, v):
        return sine(p + 0.35 * np.sin(2 * np.pi * 3 * p) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.2 * T)))
    L, R = voices(fn, (-4, 4), 0.8)
    e = chord_env(0.6) * ENV
    return [chorus(x, side=s) * e for x, s in ((L, 1), (R, -1))]

def dream_rhodes():
    bell = np.exp(-since / 0.3); strike = 0.3 + 0.7 * np.exp(-since / 1.8)
    L, R = voices(lambda p, m, v: np.sin(2 * np.pi * p + 0.9 * bell * np.sin(4 * np.pi * p)), (-3, 3), 0.6)
    trem = 1 + 0.3 * np.sin(2 * np.pi * 4.2 * T)
    return [chorus(L * strike * trem, side=1) * ENV, chorus(R * strike * (2 - trem), side=-1) * ENV]

def dream_vapor():
    wow = 12 * np.sin(2 * np.pi * 0.45 * T) + 4 * np.sin(2 * np.pi * 1.3 * T)   # tape wobble, cents
    def fn(p, m, v): return tri(p) + 0.4 * sine(p * 2)
    L, R = np.zeros(N), np.zeros(N)
    for v in range(1, SONG.nv):
        for d, side in ((-7, 0), (7, 1)):
            y = fn(phase(hz(midi_curve(v) + (d + wow) / 100)), None, v)
            (L if side == 0 else R)[:] += y
    e = chord_env(0.8) * ENV
    return [lp(x, 2400) * e for x in (L, R)]

def dream_lofi():
    L, R = voices(lambda p, m, v: sq(p) * 0.6 + saw(p) * 0.4, (-8, 8), 0.6)
    hiss = lp(np.random.default_rng(4).standard_normal(N), 4000) * 0.004
    e = chord_env(0.4) * ENV
    out = []
    for x in (L, R):
        y = lp(x, 1500) * e
        y = np.round(y / (np.max(np.abs(y)) + 1e-9) * 96) / 96 * np.max(np.abs(y))   # gentle bit-crush
        out.append(lp(y, 3200) + hiss * rms(y) * 20)
    return out

def amb_cloud():
    L, R = voices(lambda p, m, v: sine(p) + 0.4 * tri(p) + 0.25 * sine(2 * p), (-5, 5), 0.9)
    e = chord_env(1.6) * ENV
    return [x * e for x in (L, R)]

def amb_swell():
    sw = np.clip(since / np.maximum(clen * 0.8, 0.5), 0, 1) ** 2   # every chord swells up like a reversed note
    L, R = voices(lambda p, m, v: saw(p), (-8, 0, 8), 0.8)
    return [lp(x, 1600) * (0.15 + 0.85 * sw) * ENV for x in (L, R)]

def amb_air():
    rng = np.random.default_rng(6)
    L, R = np.zeros(N), np.zeros(N)
    for v in range(1, SONG.nv):
        f = hz(midi_curve(v))
        for out in (L, R):
            noise = rng.standard_normal(N)
            # resonant filter following the voice: noise ring-modulated around its pitch
            out += lp(noise, 300) * np.sin(2 * np.pi * phase(f)) * 3 + 0.25 * sine(phase(f))
    e = chord_env(1.2) * ENV
    return [x * e for x in (L, R)]

def amb_space():
    L, R = voices(lambda p, m, v: sine(p / 2) + 0.3 * sine(p * 2) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.1 * T + v)), (-3, 3), 1.0)
    e = chord_env(2.0) * ENV
    return [x * e for x in (L, R)]

def amb_grains():
    rng = np.random.default_rng(8)
    L, R = np.zeros(N), np.zeros(N)
    g = int(0.18 * SR); w = np.hanning(g)
    for _ in range(int(END * 30)):
        t0 = rng.uniform(0, END); i0 = int(t0 * SR); v = rng.integers(1, SONG.nv)
        m = SONG.voice_curve(v, np.array([t0]))[0] + rng.choice([0, 0, 12, -12])
        tt = np.arange(g) / SR
        y = np.sin(2 * np.pi * hz(m + rng.normal(0, 0.08)) * tt) * w * rng.uniform(0.4, 1)
        tgt = L if rng.random() < 0.5 else R
        tgt[i0:i0 + g] += y[:max(0, N - i0)]
    return [x * ENV for x in (L, R)]


# ------------------------------------------------------------------ textures --
def tex_note(kind, f, dur, vel):
    n = int(dur * SR); t = np.arange(n) / SR
    if kind == "pluck":   # the reels' current one
        ph = (f * t) % 1
        osc = 0.6 * (2 * ph - 1) + 0.5 * np.where(ph < 0.35, 1.0, -1.0)
        y = np.tanh(1.7 * sr.svf_pluck(osc, 420 + (1500 + 2300 * vel) * np.exp(-t / 0.07)))
        return y * (1 - np.exp(-t / 0.002)) * np.exp(-t / 0.11)
    if kind == "bell":
        return np.sin(2 * np.pi * f * t + 2.2 * np.exp(-t / 0.25) * np.sin(2 * np.pi * 3.5 * f * t)) * np.exp(-t / 0.6)
    if kind == "marimba":
        return (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 4 * f * t) * np.exp(-t / 0.03)) * np.exp(-t / 0.25)
    if kind == "harp":
        return sum(np.sin(2 * np.pi * k * f * t) / k * np.exp(-t * (2 + 3 * k)) for k in range(1, 9)) * (1 - np.exp(-t / 0.002))
    if kind == "softkeys":
        return np.sin(2 * np.pi * f * t + 0.6 * np.exp(-t / 0.2) * np.sin(4 * np.pi * f * t)) * np.exp(-t / 0.45)
    if kind == "synthpluck":
        x = 2 * ((f * t) % 1) - 1
        return lp(x, 900) * np.exp(-t / 0.18) + (lp(x, 5000) - lp(x, 900)) * np.exp(-t / 0.04)
    if kind == "musicbox":
        return (np.sin(2 * np.pi * 2 * f * t) + 0.25 * np.sin(2 * np.pi * 5.4 * f * t) * np.exp(-t / 0.08)) * np.exp(-t / 0.5)
    if kind == "kalimba":
        return (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * 5.9 * f * t) * np.exp(-t / 0.02)) * np.exp(-t / 0.35) * (1 - np.exp(-t / 0.003))
    raise ValueError(kind)


def texture(kind, octave=0):
    L, R = np.zeros(N), np.zeros(N)
    for i, (s, v, m, vel) in enumerate(SONG.arp):
        y = tex_note(kind, hz(m + 12 * octave), 1.2 if kind in ("bell", "musicbox", "softkeys") else 0.6, vel) * vel
        i0 = int(s * SR); seg = y[:max(0, N - i0)]
        pan = 0.35 + 0.3 * ((i * 3) % 4) / 3
        L[i0:i0 + len(seg)] += seg * (1 - pan); R[i0:i0 + len(seg)] += seg * pan
    d8 = int(0.75 * SONG.beat * SR)   # dotted-eighth ping-pong, as in the reels
    L = L + 0.32 * np.concatenate([np.zeros(2 * d8), L[:-2 * d8]])
    R = R + 0.36 * np.concatenate([np.zeros(d8), R[:-d8]])
    return [L * ENV, R * ENV]


HELD = [
    ("pad",     "pad-lush",     "Lush strings",    "Today's reel pad: five detuned saws, swells open on each chord.", pad_lush),
    ("pad",     "pad-analog",   "Analog warm",     "Two saws and a sub, dark and round. Calm, vintage.", pad_analog),
    ("pad",     "pad-choir",    "Choir aah",       "Saws through vowel formants: a soft human 'aah'.", pad_choir),
    ("pad",     "pad-supersaw", "Bright supersaw", "Seven wide saws, opens bright: big and emotional.", pad_supersaw),
    ("pad",     "pad-juno",     "Juno pulse",      "Pulse-width squares with chorus: 80s synth-pop warmth.", pad_juno),
    ("organ",   "org-jazz",     "Jazz organ",      "Drawbars 888000000, slow rotary, key click.", org_jazz),
    ("organ",   "org-gospel",   "Gospel organ",    "All drawbars out, fast rotary, a little drive.", org_gospel),
    ("organ",   "org-flute",    "Soft flute organ","Only the 8' bar with vibrato: gentle and hollow.", org_flute),
    ("organ",   "org-church",   "Church organ",    "Principal stops, slow attack, no rotary.", org_church),
    ("organ",   "org-rock",     "Rock organ",      "888000008 with overdrive and fast rotary.", org_rock),
    ("dreamy",  "dream-pad",    "Dream pad",       "Wide saws, the filter breathes slowly, chorus.", dream_pad),
    ("dreamy",  "dream-glass",  "Glass pad",       "Shimmering FM sine, like light through glass.", dream_glass),
    ("dreamy",  "dream-rhodes", "Dreamy Rhodes",   "Electric piano with tremolo and chorus.", dream_rhodes),
    ("dreamy",  "dream-vapor",  "Vapor tape",      "Soft triangles with tape wobble: vaporwave.", dream_vapor),
    ("dreamy",  "dream-lofi",   "Lo-fi synth",     "Squares through a dull filter, light crush and hiss.", dream_lofi),
    ("ambient", "amb-cloud",    "Cloud",           "Very slow swell of soft sines: weightless.", amb_cloud),
    ("ambient", "amb-swell",    "Reverse swell",   "Every chord swells up like a reversed note.", amb_swell),
    ("ambient", "amb-air",      "Breath",          "Filtered noise that follows the voices: airy, breathy.", amb_air),
    ("ambient", "amb-space",    "Deep space",      "Low drones with a slow shimmer an octave up.", amb_space),
    ("ambient", "amb-grains",   "Granular haze",   "Tiny grains of the chord scattered in space.", amb_grains),
]
TEXTURES = [
    ("tex-pluck",     "Reel pluck",     "Today's reel arpeggio: a soft plucked synth.", "pluck", 0),
    ("tex-bell",      "Glass bell",     "FM bells, bright and sparkly.", "bell", 1),
    ("tex-marimba",   "Marimba",        "Woody mallets, warm attack.", "marimba", 0),
    ("tex-harp",      "Harp",           "Plucked strings that ring.", "harp", 0),
    ("tex-softkeys",  "Soft keys",      "Gentle electric-piano notes.", "softkeys", 0),
    ("tex-synth",     "Synth pluck",    "Bright filtered saw pluck: modern pop.", "synthpluck", 0),
    ("tex-musicbox",  "Music box",      "Tiny high tines, nostalgic.", "musicbox", 0),
    ("tex-kalimba",   "Kalimba",        "Thumb piano: round and playful.", "kalimba", 0),
]


def reverb(chs, seconds=2.5, wet=0.35):
    irn = int(seconds * 1.6 * SR); dec = np.exp(-np.arange(irn) / SR / (seconds / 3))
    out = []
    for i, x in enumerate(chs):
        ir = lp(np.random.default_rng(10 + i).standard_normal(irn) * dec, 3000)
        w = signal.fftconvolve(x, ir)[:N]
        out.append(x + wet * w / (np.max(np.abs(w)) + 1e-9) * np.max(np.abs(x)))
    return out


def bass_line():
    m = midi_curve(0)
    p = phase(hz(m))
    return lp(np.sin(2 * np.pi * p) + 0.2 * saw(p), 300) * chord_env(0.05) * ENV


def mixdown(chs, wet=0.35, verb=2.5, with_bass=True, bed=None):
    L, R = reverb(chs, verb, wet)
    if bed is not None:
        L, R = L + bed[0], R + bed[1]
    if with_bass:
        b = bass_line(); b *= 0.45 * rms(L) / rms(b); L, R = L + b, R + b
    st = np.stack([L, R], 1)
    st = np.tanh(1.05 * st / np.max(np.abs(st))); st *= 0.89 / np.max(np.abs(st))
    st[-int(0.8 * SR):] *= np.linspace(1, 0, int(0.8 * SR))[:, None]
    return st


WET = {"ambient": (0.65, 5.0), "dreamy": (0.45, 3.5), "organ": (0.25, 2.0), "pad": (0.35, 2.8)}


def write(path, st):
    wav = path[:-4] + ".wav"
    wavfile.write(wav, SR, (st * 32767).astype(np.int16))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", wav, "-b:a", "160k", path], check=True)
    os.remove(wav)


GEN = {cid: fn for _, cid, _, _, fn in HELD}
TEX = {cid: (kind, octv) for cid, _, _, kind, octv in TEXTURES}

# Matteo's picks (20 Nov 2026). The reels rotate through them; the app gets one pack each.
PICKED_HELD = ["pad-lush", "pad-analog", "pad-supersaw", "org-church", "dream-pad", "dream-vapor", "dream-lofi", "amb-grains"]
PICKED_TEX = ["tex-marimba", "tex-harp", "tex-softkeys", "tex-synth"]
BREATH_UNDER = {"pad-lush", "pad-analog", "dream-pad", "amb-grains"}   # "Breath" layered quietly on these only


if __name__ == "__main__":
    use(make_song())
    out = sys.argv[1] if len(sys.argv) > 1 else "catalog"
    os.makedirs(out, exist_ok=True)
    items = []
    for slot, cid, name, desc, fn in HELD:
        wet, verb = WET[slot]
        write(os.path.join(out, cid + ".mp3"), mixdown(fn(), wet, verb))
        items.append({"slot": slot, "id": cid, "name": name, "desc": desc})
        print(cid, flush=True)
    bed = [x * 0.35 for x in pad_lush()]   # textures over a quiet lush pad, as in the reels
    for cid, name, desc, kind, octv in TEXTURES:
        chs = texture(kind, octv)
        g = 0.9 * rms(bed[0]) / rms(chs[0]) * 2.2
        write(os.path.join(out, cid + ".mp3"), mixdown([c * g for c in chs], 0.3, 2.5, bed=[b for b in bed]))
        items.append({"slot": "texture", "id": cid, "name": name, "desc": desc})
        print(cid, flush=True)
    json.dump(items, open(os.path.join(out, "catalog.json"), "w"), indent=1)
