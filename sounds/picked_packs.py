#!/usr/bin/env python3
"""Render Matteo's picked sounds (sounds/catalog.py) note by note into sample packs for the jam app,
so the studio plays the same engine as the reels:  python3 sounds/picked_packs.py
Held sounds: 13 notes (C2..C5, every minor third) of 8 s, with the quiet "Breath" layer baked in where
the reels layer it (catalog.BREATH_UNDER). Textures: 13 short notes (C3..C6). Loudness is levelled
across packs through `gain_db` in pack.json. Then run `npm run sounds` in chordsthatmove_app."""
import json, os, sys, tempfile
import numpy as np
from scipy.io import wavfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import songreel as sr, samples, catalog as C

LABELS = {"pad-lush": "Lush strings", "pad-analog": "Analog warm", "pad-supersaw": "Bright supersaw",
          "org-church": "Church organ", "dream-pad": "Dream pad", "dream-vapor": "Vapor tape",
          "dream-lofi": "Lo-fi synth", "amb-grains": "Granular haze"}
TEX_LABELS = {"tex-marimba": "Marimba", "tex-harp": "Harp", "tex-softkeys": "Soft keys", "tex-synth": "Synth pluck"}
HELD_NOTES = [f"{n}{o}" for o in range(2, 6) for n in ("C", "D#", "F#", "A")][:13]    # C2 .. C5
TEX_NOTES = [f"{n}{o}" for o in range(3, 7) for n in ("C", "D#", "F#", "A")][:13]     # C3 .. C6
DUR = 8.0
TARGET_RMS = 0.176   # of the held packs' loudest 2 s: level with each other and with Reel pad (-15 dBFS incl. its gain)


class OneNote:
    """The bits of songreel.Song the catalogue generators use, for one held note."""
    nv = 2; beat = 0.5; arp = []
    def __init__(self, midi, dur):
        self.m, self.end, self.total, self.starts = midi, dur, dur + 1.5, [0.0]
    def voice_curve(self, v, ts): return np.full(len(ts), float(self.m))


def rms(x): return float(np.sqrt(np.mean(x ** 2)) + 1e-12)


def held(cid, midi):
    C.use(OneNote(midi, DUR))
    L, R = C.GEN[cid]()
    if cid in C.BREATH_UNDER:
        aL, aR = C.amb_air()
        g = 0.16 * rms(L) / rms(aL)          # as in songreel.synth
        L, R = L + g * aL, R + g * aR
    x = 0.5 * (L + R)
    t = np.arange(len(x)) / sr.SR
    x = x * np.where(t < DUR, 1.0, np.exp(-(t - DUR) / 0.35))   # release tail
    return x


def tex(cid, midi):
    kind, _ = C.TEX[cid]
    return C.tex_note(kind, C.hz(midi), 1.2, 0.8)


def build(cid, label, role, notes, fn):
    tmp = tempfile.mkdtemp()
    for n in notes:
        x = fn(cid, samples.midi(n))
        x = x / (np.max(np.abs(x)) + 1e-9) * 0.9
        wavfile.write(os.path.join(tmp, f"{n}.wav"), sr.SR, (x * 32767).astype(np.int16))
    samples.make(tmp, cid, label, role)
    # level: measure the middle note's loudest 2 s (held) or its first 0.5 s (textures)
    mid = samples.read_wav(os.path.join(HERE, cid, "C3.wav" if "C3" in notes else notes[0] + ".wav"))
    win = int((2.0 if role == "pad" else 0.5) * sr.SR)
    best = max(rms(mid[i:i + win]) for i in range(0, max(1, len(mid) - win), win // 4)) if len(mid) > win else rms(mid)
    meta_path = os.path.join(HERE, cid, "pack.json"); meta = json.load(open(meta_path))
    target = TARGET_RMS if role == "pad" else 0.11
    meta["gain_db"] = round(float(np.clip(20 * np.log10(target / best), -18, 6)), 1)
    json.dump(meta, open(meta_path, "w"), indent=1)
    print(f"  {cid}: rms {best:.3f} → gain_db {meta['gain_db']}")


if __name__ == "__main__":
    for cid in C.PICKED_HELD:
        build(cid, LABELS[cid], "pad", HELD_NOTES, held)
    C.use(OneNote(60, 2.0))
    for cid in C.PICKED_TEX:
        build(cid, TEX_LABELS[cid], "arp", TEX_NOTES, tex)
