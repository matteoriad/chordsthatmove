#!/usr/bin/env python3
"""Render the reels' own synths (songreel.py) note by note into sample packs, so the jam app plays
exactly the sounds of the reels:  python3 sounds/reel_packs.py
Writes sounds/reel-pad, reel-keys and reel-organ (WAV for the reels, MP3 for the app); then run
`npm run sounds` in chordsthatmove_app."""
import os, sys, tempfile
import numpy as np
from scipy.io import wavfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import songreel as sr, samples

NOTES = [f"{n}{o}" for o in range(2, 6) for n in ("C", "D#", "F#", "A")][:13]   # C2 … C5
DUR = 4.0   # per pack below: held sounds get 8 s so long chords in the app don't fade


class OneNote:
    """The bits of songreel.Song the pad functions use, for a single held note."""
    def __init__(self, midi, dur):
        self.nv, self.starts, self.end, self.m = 2, [0.0], dur, midi
    def voice_curve(self, v, ts): return np.full(len(ts), float(self.m))


def render(kind, midi):
    dur = 4.0 if kind == "keys" else 8.0
    song = OneNote(midi, dur); tt = np.arange(int((dur + 1.5) * sr.SR)) / sr.SR
    env = np.clip(tt / 0.02, 0, 1) * np.where(tt < dur, 1.0, np.exp(-(tt - dur) / 0.35))
    L, R = {"pad": lambda: sr.lush_pad(song, tt, env), "keys": lambda: sr.keys_pad(song, tt, env),
            "organ": lambda: sr.organ_pad(song, tt, env)}[kind]()
    x = 0.5 * (L + R)
    return x / (np.max(np.abs(x)) + 1e-9) * 0.9


if __name__ == "__main__":
    for kind, label, role in (("pad", "Reel pad", "pad"), ("keys", "Reel keys", "keys"), ("organ", "Reel organ", "pad")):
        tmp = tempfile.mkdtemp()
        for n in NOTES:
            wavfile.write(os.path.join(tmp, f"{n}.wav"), sr.SR, (render(kind, samples.midi(n)) * 32767).astype(np.int16))
        samples.make(tmp, f"reel-{kind}", label, role)
