#!/usr/bin/env python3
"""Sample packs: your own recorded sounds (Moog, GarageBand…) for the reels and the jam app.

A pack is a folder sounds/<id>/ with one WAV per recorded note plus pack.json:

  {"id": "moog-pad", "label": "Moog pad", "role": "pad",      # pad | keys | pluck | arp
   "attack": 0.03, "release": 0.9, "gain_db": 0, "loop": true,
   "notes": {"C3": "C3.wav", "D#3": "D#3.wav", ...}}

Make one from a folder of recordings named after their note (C3.wav, D#3.wav, F#3.wav, A3.wav …):

  python3 sounds/samples.py make ~/Desktop/moog-pad moog-pad "Moog pad" pad

It trims the silence in front, normalises, writes 44.1 kHz mono WAVs (reels) and MP3s (app, needs
ffmpeg) into sounds/<id>/, and writes pack.json. The renderer uses a pack when an episode has
"sound": "<id>", or for every episode when sounds/default.json says {"pad": "<id>"}.

Recording tips: one note every 3 semitones (C, D#, F#, A) from C2 to C5 is enough; hold each
note ~4 s and let it ring out; same velocity, no effects (the reel adds reverb and echo).
"""
import json, os, re, shutil, subprocess, sys
import numpy as np
from scipy.io import wavfile
from scipy import signal

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 44100
PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi(name):
    m = re.fullmatch(r"([A-G])([#b]?)(-?\d)", name)
    if not m: raise ValueError(f"not a note name: {name}")
    return PC[m[1]] + {"#": 1, "b": -1, "": 0}[m[2]] + 12 * (int(m[3]) + 1)


def read_wav(path):
    sr, raw = wavfile.read(path)
    x = raw.astype(np.float64)
    if x.ndim > 1: x = x.mean(axis=1)
    if np.issubdtype(raw.dtype, np.integer): x /= np.iinfo(raw.dtype).max
    if sr != SR: x = signal.resample_poly(x, SR, sr)
    return x


# ------------------------------------------------------------------ pack loading --
_cache = {}


def load(pack_id):
    """{"meta": pack.json, "samples": [(midi, array)] sorted by pitch}, or None if there's no such pack."""
    if not pack_id: return None
    if pack_id in _cache: return _cache[pack_id]
    d = os.path.join(HERE, pack_id)
    if not os.path.exists(os.path.join(d, "pack.json")): return None
    meta = json.load(open(os.path.join(d, "pack.json")))
    samples = sorted((midi(n), read_wav(os.path.join(d, f))) for n, f in meta["notes"].items())
    _cache[pack_id] = {"meta": meta, "samples": samples}
    return _cache[pack_id]


def default(role):
    p = os.path.join(HERE, "default.json")
    return json.load(open(p)).get(role) if os.path.exists(p) else None


def note(pack, m, dur, vel=1.0):
    """One note of `dur` seconds plus the release tail, pitched from the nearest recorded sample."""
    meta = pack["meta"]
    root, x = min(pack["samples"], key=lambda s: (abs(s[0] - m), s[0]))
    ratio = 2 ** ((m - root) / 12)
    rel = float(meta.get("release", 0.8)); att = float(meta.get("attack", 0.01))
    need = int((dur + rel) * SR)
    # read the sample faster/slower to change pitch
    pos = np.arange(need) * ratio
    if meta.get("loop") and pos[-1] >= len(x) - 1:
        # hold: loop the second half of the sample with a short crossfade
        a, b = len(x) // 2, len(x) - 1
        xf = min(2048, (b - a) // 4)
        body = x[a:b].copy()
        body[:xf] = body[:xf] * np.linspace(0, 1, xf) + x[b - xf:b] * np.linspace(1, 0, xf)
        x = np.concatenate([x[:b - xf]] + [body[xf:]] * int(np.ceil(pos[-1] / max(1, len(body) - xf)) + 1))
    y = np.interp(pos, np.arange(len(x)), x, right=0.0)
    t = np.arange(need) / SR
    env = np.minimum(1, t / max(att, 1e-3)) * np.where(t < dur, 1.0, np.exp(-(t - dur) / max(rel / 4, 1e-3)))
    return y * env * vel * 10 ** (float(meta.get("gain_db", 0)) / 20)


def layer(song, pack, n, voices, glide_lead=0.09):
    """Each voice holds its note while it doesn't move and restarts when it does (a little before the
    chord line, like the drawn glide)."""
    out = np.zeros(n)
    for v in voices:
        i = 0
        while i < len(song.starts):
            j = i
            while j + 1 < len(song.starts) and song.pitch[j + 1, v] == song.pitch[i, v]: j += 1
            start = max(0.0, song.starts[i] - (glide_lead if i else 0))
            end = song.starts[j + 1] - glide_lead if j + 1 < len(song.starts) else song.end
            y = note(pack, int(song.pitch[i, v]), max(0.05, end - start))
            i0 = int(start * SR)
            out[i0:i0 + len(y)] += y[:max(0, n - i0)]
            i = j + 1
    return out


def arp(song, pack, n):
    out = np.zeros(n)
    for s, v, m, vel in song.arp:
        y = note(pack, int(m), song.beat / 4, vel)
        i0 = int(s * SR)
        out[i0:i0 + len(y)] += y[:max(0, n - i0)]
    return out


# ------------------------------------------------------------------ making a pack --
def make(src, pack_id, label, role):
    out = os.path.join(HERE, pack_id); os.makedirs(out, exist_ok=True)
    notes = {}
    for f in sorted(os.listdir(src)):
        stem, ext = os.path.splitext(f)
        if ext.lower() not in (".wav", ".aif", ".aiff", ".m4a", ".mp3"): continue
        name = stem.strip().replace("♯", "#").replace("♭", "b")
        try: midi(name)
        except ValueError: print("skipped (name it after its note, e.g. C3.wav):", f); continue
        path = os.path.join(src, f)
        if ext.lower() != ".wav":   # let ffmpeg decode anything else
            tmp = os.path.join(out, "_tmp.wav")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", path, tmp], check=True); path = tmp
        x = read_wav(path)
        on = np.argmax(np.abs(x) > 0.02 * np.max(np.abs(x)))   # trim silence in front
        x = x[max(0, on - 64):]
        x = x / (np.max(np.abs(x)) + 1e-9) * 0.9
        wavfile.write(os.path.join(out, f"{name}.wav"), SR, (x * 32767).astype(np.int16))
        if shutil.which("ffmpeg"):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", os.path.join(out, f"{name}.wav"),
                            "-b:a", "128k", os.path.join(out, f"{name}.mp3")], check=True)
        notes[name] = f"{name}.wav"
    if os.path.exists(os.path.join(out, "_tmp.wav")): os.remove(os.path.join(out, "_tmp.wav"))
    if not notes: raise SystemExit("no recordings found")
    meta = {"id": pack_id, "label": label, "role": role, "attack": 0.02 if role == "pad" else 0.003,
            "release": 0.9 if role == "pad" else 0.4, "gain_db": 0, "loop": role == "pad",
            "notes": dict(sorted(notes.items(), key=lambda kv: midi(kv[0])))}
    json.dump(meta, open(os.path.join(out, "pack.json"), "w"), indent=1)
    print(f"sounds/{pack_id}: {len(notes)} notes ({', '.join(meta['notes'])})")


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "make":
        make(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else sys.argv[3],
             sys.argv[5] if len(sys.argv) > 5 else "pad")
    else:
        print(__doc__)
