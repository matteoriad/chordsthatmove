#!/usr/bin/env python3
"""Render a jam from the web app (chords that move – jam) as a reel, with the brand renderer.

Usage:
  python3 jamreel.py JAM.json OUTDIR
    → OUTDIR/reel.mp4, OUTDIR/cover.png (4:5 grid cover), OUTDIR/cover_reel.png (9:16)

JAM.json has the same shape as songs/queue/*.json: title, key, bpm, chords (name, beats,
notes bass-first, optional roman/tag/text/focus), optional hook. "artist" is not needed: the jam's
title replaces "ARTIST — TITLE", and the outro is a small "made with chords that move" card.

The input comes from users of the web app, so everything is validated and capped here as well.
Used by .github/workflows/export-reel.yml; never by the daily posting pipeline.
"""
import json
import os
import re
import sys

import numpy as np
import cairo
from PIL import ImageDraw

import brandreel as br

MAX_SECONDS = 60          # music length (the outro comes on top)
MAX_CHORDS = 32
NOTE = re.compile(r"^[A-G][#b]?-?\d$")                                   # what songreel.midi() accepts
CHORD = re.compile(r"^[A-G][#b]?(|m|7|m7|maj7|6|m6|sus2|sus4|7sus4|add9|dim|5)(/[A-G][#b]?)?$")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class JamError(ValueError):
    pass


def _text(v, limit, default=""):
    if v is None:
        return default
    if not isinstance(v, str):
        raise JamError("text fields must be strings")
    v = re.sub(r"[\x00-\x1f\x7f]", " ", v).strip()
    return v[:limit]


def validate(raw):
    """A safe brandreel spec from untrusted jam JSON (raises JamError)."""
    if not isinstance(raw, dict):
        raise JamError("jam must be an object")
    title = _text(raw.get("title"), 80) or "Untitled jam"
    key = _text(raw.get("key"), 24)
    bpm = raw.get("bpm")
    if not isinstance(bpm, (int, float)) or not 40 <= bpm <= 220:
        raise JamError("bpm must be between 40 and 220")
    chords = raw.get("chords")
    if not isinstance(chords, list) or not 1 <= len(chords) <= MAX_CHORDS:
        raise JamError(f"1 to {MAX_CHORDS} chords")
    out = []
    for i, c in enumerate(chords):
        if not isinstance(c, dict):
            raise JamError(f"chord {i + 1}: must be an object")
        name = c.get("name")
        if not isinstance(name, str) or not CHORD.match(name):
            raise JamError(f"chord {i + 1}: unsupported name {name!r}")
        notes = c.get("notes")
        if not isinstance(notes, list) or len(notes) != 4 or not all(isinstance(n, str) and NOTE.match(n) for n in notes):
            raise JamError(f"chord {i + 1}: notes must be 4 note names, bass first")
        beats = c.get("beats")
        if not isinstance(beats, (int, float)) or not 0.5 <= beats <= 64:
            raise JamError(f"chord {i + 1}: beats must be between 0.5 and 64")
        focus = c.get("focus")
        out.append({
            "name": name, "notes": notes, "beats": float(beats),
            "roman": _text(c.get("roman"), 10), "tag": _text(c.get("tag"), 24), "text": _text(c.get("text"), 140),
            **({"focus": focus} if isinstance(focus, int) and 0 <= focus < 4 else {}),
        })
    seconds = sum(c["beats"] for c in out) * 60 / bpm
    if seconds > MAX_SECONDS:
        raise JamError(f"the jam is {seconds:.0f} s long; reels are at most {MAX_SECONDS} s")
    accent = raw.get("accent") if isinstance(raw.get("accent"), str) and HEX.match(raw["accent"]) else "#FF7AA8"
    hook = _text(raw.get("hook"), 60)
    return {
        "title": title, "artist": "", "key": key, "bpm": float(bpm),
        "accent": accent, "handle": _text(raw.get("handle"), 40, "@chordsthatmove"),
        "site": _text(raw.get("site"), 60), "chords": out,
        **({"hook": hook, "hook_beats": 4} if hook else {}),
        "cover_text": "Made with *chords that move*",
    }


def _short(s, n):
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


class JamReel(br.Reel):
    """The episode look, with the jam's title in place of song and artist."""

    def label(self):
        return _short(self.spec["title"].upper(), 30)

    def cover_kicker(self):
        return f"JAM · {self.spec['key'].upper()}" if self.spec.get("key") else "JAM"

    def outro(self, now):
        """Small end card: four voice lines settling, then "made with chords that move"."""
        sp = self.spec
        k = br.ease((now - self.outro_start) / 0.6)
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, br.W, br.H)
        cr = cairo.Context(surf)
        cr.set_source_rgb(*br.rgb1(br.INK)); cr.paint()
        # the logo, drawn large and revealed left to right
        cr.save(); cr.rectangle(0, 0, br.L + 400 * k, br.H); cr.clip()
        br.logo(cr, br.L, 700, 220, 8)
        cr.restore()
        img = br.to_pil(surf); d = ImageDraw.Draw(img)
        a = br.ease((now - self.outro_start - 0.25) / 0.5)
        col = lambda c: br.mixc(c, a)
        br.tx.draw(d, br.L, br.tx.base(1000, br.MONO, 26), "MADE WITH", br.MONO, 26, col(br.MUTED), 0.12)
        b = br.tx.base(1040, br.SEMI, 76, 1.0)
        x = br.tx.draw(d, br.L, b, "chords that ", br.SEMI, 76, col(br.PAPER), -0.045)
        br.tx.draw(d, x, b, "move", br.SEMI, 76, col(self.accent), -0.045)
        y = 1160
        if sp.get("site"):
            br.tx.draw(d, br.L, br.tx.base(y, br.MONO, 28), sp["site"], br.MONO, 28, col(br.SOFT))
            y += 52
        br.tx.draw(d, br.L, br.tx.base(y, br.MONO, 26), sp.get("handle", "@chordsthatmove"), br.MONO, 26, col(br.MUTED))
        return img


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 64
    try:
        with open(argv[1], encoding="utf-8") as f:
            spec = validate(json.load(f))
    except (JamError, json.JSONDecodeError) as e:
        print(f"invalid jam: {e}", file=sys.stderr)
        return 2
    outdir = argv[2]
    os.makedirs(outdir, exist_ok=True)
    video = os.path.join(outdir, "reel.mp4")
    br.render(spec, video, reel_cls=JamReel)
    grid, reel = JamReel(spec).cover()
    grid.save(os.path.join(outdir, "cover.png"))
    reel.save(os.path.join(outdir, "cover_reel.png"))
    seconds = sum(c["beats"] for c in spec["chords"]) * 60 / spec["bpm"]
    print(json.dumps({"video": video, "cover": os.path.join(outdir, "cover.png"), "seconds": round(seconds, 1)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
