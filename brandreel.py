#!/usr/bin/env python3
""""chords that move" reel renderer — brand look from the Design canvas.

Frames: hook (title + progression overview) → chord frames (stepper, big chord,
numeral pill, caption, moving-note chip, voice lines) → outro.
Audio and song timing come from songreel.py.

Usage:
  python3 brandreel.py stills SONG.json OUTDIR t1 t2 ...
  python3 brandreel.py render SONG.json OUT.mp4
"""
import json, os, re, subprocess, sys
import numpy as np
import cairo
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
import songreel as sr

sr.LEAD_IN = 0.0       # the song plays from the very first frame
sr.GLIDE = 0.18          # brand rule: soft S-curve over ~180 ms
sr.TAIL = 4.0            # room for the outro (loop mode: the reverb tail, wrapped to the start)
LOOP = (os.environ.get("REEL_LOOP") or "1") != "0"   # loopable reels without the end card (2026-11-20)
# layout (2026-11-20: the voice lines are the focus; text is smaller)
# v3 (same day, second round): text smaller still, lines bigger still
Y_CHORD = 540            # big chord baseline
CHORD_MAX, CHORD_MIN = 110, 84
CAP_Y, CAP_SIZE, CAP_LH = 600, 32, 40
LAB_Y = 690              # chord labels above the lines
UT, UB, BT, BB = 735, 1370, 1415, 1545   # upper-voice lane, bass lane
PH_TOP, PH_BOT = 705, 1575
CHIP_Y = 1610
HOOK_SIZE, HOOK_Y = 64, 480
LW, LW_MOVE, DOT, GLOW = 8, 4, 10, 54       # line width (+ while moving), dot radius, glow radius
LAB_SIZE = 24
LAYOUT = "classic"
LAYOUTS = {   # "lines": no stepper or big chord, the lines take more than half the frame
    "classic": dict(CAP_Y=600, LAB_Y=690, UT=735, UB=1370, BT=1415, BB=1545, PH_TOP=705, PH_BOT=1575, LAB_SIZE=24),
    "lines": dict(CAP_Y=420, LAB_Y=548, UT=610, UB=1350, BT=1400, BB=1545, PH_TOP=575, PH_BOT=1575, LAB_SIZE=40),
}


def layout_for(spec):
    """spec["layout"] if set; otherwise every third episode uses "lines", so the feed doesn't repeat."""
    if spec.get("layout") in LAYOUTS: return spec["layout"]
    return "lines" if int(spec.get("episode") or 0) % 3 == 0 else "classic"


def set_layout(name):
    global LAYOUT
    LAYOUT = name
    globals().update(LAYOUTS[name])
W, H, FPS = 1080, 1920, 30
HERE = os.path.dirname(os.path.abspath(__file__))

# ---- brand tokens ----
INK, SURFACE, MUTED, PAPER = (11, 11, 16), (21, 21, 29), (138, 138, 153), (242, 242, 245)
DIM, FAINT, SOFT = (110, 110, 124), (78, 78, 90), (180, 180, 192)
LINE, BORDER = (34, 34, 44), (42, 42, 54)
SOPRANO, ALTO, TENOR, BASS = (92, 200, 240), (169, 155, 255), (255, 122, 168), (245, 181, 74)
LOWV, HIGHV = (255, 148, 102), (111, 227, 176)   # coral and mint: the two extra lines of 6 voices
VOICES = [BASS, TENOR, ALTO, SOPRANO]          # index 0 = lowest note (4 voices)
VOICES6 = [BASS, LOWV, TENOR, ALTO, HIGHV, SOPRANO]   # 6 voices (bass + 5 upper, since 2026-11-23)
L, R = 72, 940                                  # safe-zone content edges

PLAYHEAD, FUTURE, THEME, TEXTURE, DEFAULT_ACCENT = (255, 255, 255), "solid", "night", {}, (255, 122, 168)

# ---- themes (the jam app's looks: src/lib/theme/themes.ts + the html[data-theme] blocks in globals.css) ----
def _h(x): x = x.lstrip("#"); return tuple(int(x[i:i + 2], 16) for i in (0, 2, 4))
THEMES = {   # bg surface line border fg soft muted dim faint accent playhead | bass low tenor alto high soprano | future line
    # (low = coral, high = mint: the two extra lines of the 6-voice voicing, 2026-11-23)
    "night": ("#0B0B10 #15151D #22222C #2A2A36 #F2F2F5 #B4B4C0 #8A8A99 #6E6E7C #4E4E5A #FF7AA8 #FFFFFF",
              "#F5B54A #FF9466 #FF7AA8 #A99BFF #6FE3B0 #5CC8F0", "solid"),
    "riso": ("#F2EEE5 #E9E4D8 #D8D2C3 #CFC8B6 #1B1B2F #3D3D52 #55556A #8A8A96 #B5B1A6 #C81E78 #1B1B2F",
             "#F2A60C #E8642A #F0409A #7A56B8 #1E9E6A #0077C0", "solid"),
    "chalk": ("#222B29 #2C3634 #3A4643 #46524F #ECEBE6 #C9C9C2 #A3ABA6 #7F8984 #566360 #FF9BBA #F2F2EE",
              "#FFC870 #FFAE8A #FF9AB8 #BFB2FF #8FE8C2 #7FD3F7", "solid"),
    "blueprint": ("#1A4577 #1F4F87 #2D5F9B #4C7DB8 #F4F8FF #D2E2F7 #B0C7E7 #86A6D1 #5F86B8 #FFA3C4 #FFFFFF",
                  "#FFCB6B #FFB48E #FF9EC0 #C8B8FF #9AF0CA #8DD8FF", "dashed"),
    "graph": ("#EFF0E4 #E6E8D8 #D3D9C2 #C4CCB0 #1A241E #36423A #52605A #8A948C #B4BBA8 #B4235A #1A241E",
              "#C47F14 #C9592B #C2306B #5B45C8 #2E8A5C #1B6F96", "solid"),
    "score": ("#EBE0C8 #E2D6BB #D2C4A4 #C4B592 #231C16 #3F342A #5E5040 #8C7C66 #B8A88A #A82462 #231C16",
              "#A86A0C #B4542C #BE3068 #5A46C8 #3E7E4E #1F6E96", "dotted"),
    "paper": ("#E3DFD4 #DAD6CA #CBC7B9 #BDB9AA #1C1A18 #3A3733 #57534C #8A867D #B2AEA2 #A81F55 #1C1A18",
              "#C98A12 #C85A2A #D43A78 #6B52D6 #2A8A5E #2386B6", "solid"),
}
ROTATION = ["riso", "chalk", "blueprint", "graph", "score", "paper"]


def theme_for(spec):
    """spec["theme"] if set; otherwise Night on even episodes and the other looks in turn on odd ones,
    so every other post keeps the brand look and the feed still reads as one page."""
    if spec.get("theme") in THEMES: return spec["theme"]
    ep = int(spec.get("episode") or 0)
    return "night" if ep % 2 == 0 else ROTATION[(ep // 2) % len(ROTATION)]


def texture(name, w, h):
    """The theme's background texture as a cairo ARGB surface (None for a flat background)."""
    if name == "night": return None
    if name in ("chalk", "paper"):
        from scipy.ndimage import gaussian_filter
        rng = np.random.default_rng(4 if name == "chalk" else 9)
        n = gaussian_filter(rng.standard_normal((h, w)), (0.6, 14) if name == "chalk" else (2.5, 6))
        n = (n - n.mean()) / (n.std() + 1e-9)
        a = np.clip((n - 0.6) * 0.10, 0, 0.22 if name == "chalk" else 0.16)
        col = (255, 255, 255) if name == "chalk" else (77, 69, 56)
        stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, w)
        buf = np.zeros((h, stride // 4, 4), np.uint8)
        for i, c in enumerate(col[::-1]): buf[:, :w, i] = (c * a).astype(np.uint8)   # BGRA, premultiplied
        buf[:, :w, 3] = (255 * a).astype(np.uint8)
        return cairo.ImageSurface.create_for_data(bytearray(buf.tobytes()), cairo.FORMAT_ARGB32, w, h, stride)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h); cr = cairo.Context(surf)

    def grid(rgb, big, small, a_big, a_small):
        for step, a in ((small, a_small), (big, a_big)):
            cr.set_source_rgba(*[v / 255 for v in rgb], a); cr.set_line_width(2 if step == big else 1.5)
            for x in range(0, w + 1, step): cr.move_to(x + 0.5, 0); cr.line_to(x + 0.5, h)
            for y in range(0, h + 1, step): cr.move_to(0, y + 0.5); cr.line_to(w, y + 0.5)
            cr.stroke()
    if name == "blueprint": grid((255, 255, 255), 240, 48, 0.10, 0.04)
    elif name == "graph": grid((60, 140, 90), 192, 38, 0.22, 0.10)
    elif name == "score":   # staves of five lines
        cr.set_source_rgba(140 / 255, 116 / 255, 81 / 255, 0.35); cr.set_line_width(1.5)
        for top in range(64, h, 288):
            for k in range(5): cr.move_to(0, top + k * 27 + 0.5); cr.line_to(w, top + k * 27 + 0.5)
        cr.stroke()
    elif name == "riso":   # halftone dots fading out from the top right
        dots = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h); dc = cairo.Context(dots)
        dc.set_source_rgba(240 / 255, 64 / 255, 154 / 255, 0.5)
        for y in range(8, h, 16):
            for x in range(8, w, 16): dc.arc(x, y, 2.2, 0, 6.2832); dc.fill()
        g = cairo.RadialGradient(w * 0.88, 115, 0, w * 0.88, 115, 1100)
        g.add_color_stop_rgba(0, 1, 1, 1, 1); g.add_color_stop_rgba(1, 1, 1, 1, 0)
        cr.set_source_surface(dots); cr.mask(g)
    surf.flush()
    return surf


def set_theme(name):
    """Switch every colour token (module globals, read at draw time) to a theme."""
    global INK, SURFACE, LINE, BORDER, PAPER, SOFT, MUTED, DIM, FAINT, PLAYHEAD
    global BASS, TENOR, ALTO, SOPRANO, VOICES, VOICES6, LOWV, HIGHV, FUTURE, THEME, TEXTURE, DEFAULT_ACCENT
    base, voices, FUTURE = THEMES[name]
    (INK, SURFACE, LINE, BORDER, PAPER, SOFT, MUTED, DIM, FAINT, DEFAULT_ACCENT, PLAYHEAD) = [_h(x) for x in base.split()]
    BASS, LOWV, TENOR, ALTO, HIGHV, SOPRANO = [_h(x) for x in voices.split()]
    VOICES = [BASS, TENOR, ALTO, SOPRANO]
    VOICES6 = [BASS, LOWV, TENOR, ALTO, HIGHV, SOPRANO]
    THEME, TEXTURE = name, {}


def paint_bg(cr, w=None, h=None):
    w, h = w or W, h or H
    cr.set_source_rgb(*rgb1(INK)); cr.paint()
    if (w, h) not in TEXTURE: TEXTURE[(w, h)] = texture(THEME, w, h)
    if TEXTURE[(w, h)] is not None: cr.set_source_surface(TEXTURE[(w, h)]); cr.paint()


INTER = HERE + "/fonts/Inter-"
SEMI, MED = INTER + "SemiBold.otf", INTER + "Medium.otf"
MONO, MONO_M = HERE + "/fonts/JetBrainsMono-Regular.ttf", HERE + "/fonts/JetBrainsMono-Medium.ttf"
FALLBACK = HERE + "/fonts/DejaVuSans.ttf"


def hexrgb(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
def mixc(c, a, bg=None):
    bg = INK if bg is None else bg; a = max(0.0, min(1.0, a)); return tuple(int(c[i] * a + bg[i] * (1 - a)) for i in range(3))
def ease(x): x = max(0.0, min(1.0, x)); return 1 - (1 - x) ** 3
def rgb1(c): return [v / 255 for v in c]


# ---- text with tracking + per-glyph fallback ----
class TX:
    def __init__(self):
        self._f, self._cmap = {}, {}

    def font(self, file, size):
        k = (file, size)
        if k not in self._f: self._f[k] = ImageFont.truetype(file, size)
        return self._f[k]

    def has(self, file, ch):
        if file not in self._cmap: self._cmap[file] = set(TTFont(file).getBestCmap())
        return ord(ch) in self._cmap[file]

    def runs(self, text, file):
        out = []
        for ch in text:
            f = file if (ch == " " or self.has(file, ch)) else FALLBACK
            if out and out[-1][1] == f: out[-1][0] += ch
            else: out.append([ch, f])
        return out

    def width(self, text, file, size, track=0.0):
        w = 0.0
        for run, f in self.runs(text, file):
            fo = self.font(f, size)
            if track: w += sum(fo.getlength(c) + track * size for c in run)
            else: w += fo.getlength(run)
        return w

    def draw(self, d, x, base, text, file, size, fill, track=0.0):
        for run, f in self.runs(text, file):
            fo = self.font(f, size)
            if track:
                for c in run:
                    d.text((x, base), c, font=fo, fill=fill, anchor="ls"); x += fo.getlength(c) + track * size
            else:
                d.text((x, base), run, font=fo, fill=fill, anchor="ls"); x += fo.getlength(run)
        return x

    def base(self, top, file, size, lh=1.2):
        asc, desc = self.font(file, size).getmetrics()
        return top + (lh * size - (asc + desc)) / 2 + asc


tx = TX()


def tokens(text, color, hi_color):
    """Words with *highlight* markup; glue punctuation that touches a highlight."""
    toks, hi, prev = [], False, ""
    for part in re.split(r"(\*)", text):
        if part == "*": hi = not hi; continue
        glue = bool(part) and bool(prev) and not part[0].isspace() and not prev[-1].isspace() and bool(toks)
        if part: prev = part
        for j, w in enumerate(part.split()):
            toks.append([w, hi_color if hi else color, glue and j == 0])
    return toks


def wrap(toks, file, size, track, max_w):
    lines, cur, cw = [], [], 0.0
    sp = tx.width(" ", file, size)
    for w, c, glue in toks:
        ww = tx.width(w, file, size, track)
        gap = 0 if (glue or not cur) else sp
        if cur and not glue and cw + gap + ww > max_w:
            lines.append(cur); cur, cw, gap = [], 0.0, 0
        cur.append((w, c, cw + gap)); cw += gap + ww
    if cur: lines.append(cur)
    return lines


def logo(cr, x, y, size, sw):
    s = size / 120
    cr.save(); cr.translate(x, y); cr.scale(s, s)
    cr.set_line_width(sw); cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for col, segs in ((SOPRANO, [("M", 16, 32), ("H", 104, 32)]),
                      (ALTO, [("M", 16, 58), ("H", 42, 58), ("C", 54, 58, 52, 46, 64, 46), ("H", 104, 46)]),
                      (TENOR, [("M", 16, 74), ("H", 104, 74)]),
                      (BASS, [("M", 16, 86), ("H", 42, 86), ("C", 54, 86, 52, 98, 64, 98), ("H", 104, 98)])):
        cr.set_source_rgb(*rgb1(col))
        for sg in segs:
            if sg[0] == "M": cr.move_to(*sg[1:])
            elif sg[0] == "H": cr.line_to(*sg[1:])
            else: cr.curve_to(*sg[1:])
        cr.stroke()
    cr.restore()


def rrect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0); cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416); cr.arc(x + r, y + r, r, 3.1416, 4.7124); cr.close_path()


def glow(cr, x, y, r, col, a):
    g = cairo.RadialGradient(x, y, 0, x, y, r)
    g.add_color_stop_rgba(0, *rgb1(col), a); g.add_color_stop_rgba(0.45, *rgb1(col), a * 0.55)
    g.add_color_stop_rgba(1, *rgb1(col), 0)
    cr.set_source(g); cr.arc(x, y, r, 0, 6.2832); cr.fill()


def to_pil(surf):
    buf = np.frombuffer(surf.get_data(), np.uint8).reshape(H, surf.get_stride() // 4, 4)[:, :W]
    return Image.fromarray(buf[:, :, [2, 1, 0]].copy())


INTERVALS = {1: "half step", 2: "whole step", 3: "minor 3rd", 4: "major 3rd", 5: "perfect 4th",
             6: "tritone", 7: "perfect 5th", 12: "octave"}


def loops(spec):
    return LOOP and spec.get("loop", True)


MAX_SECONDS = 18   # watch-time cap for song reels (2026-11-24): the short ones (14–15 s) did best


def apply_cut(spec):
    """"cut": indices of the sketch chords to keep (e.g. [0, 1, 2, 3]), so a long song shows only the
    part with the "aha". Voicings stay as built from the full progression; "hook_focus" and
    "explain" (indices into the full list) are remapped. A guess reel reveals on the last kept chord."""
    keep = spec.get("cut")
    if not keep: return spec
    remap = {old: new for new, old in enumerate(keep)}
    out = {**spec, "chords": [spec["chords"][i] for i in keep]}
    if "hook_focus" in spec:
        out["hook_focus"] = remap.get(spec["hook_focus"], len(keep) - 1)
    if isinstance(spec.get("explain"), list):
        out["explain"] = [remap[i] for i in spec["explain"] if i in remap]
    return out


def cap_length(spec, out, beat, min_sec):
    """Song reels: squeeze the loop to at most "max_seconds" (default MAX_SECONDS) by shortening
    every chord in proportion, never below min_sec per chord. Jam reels are meant to be played
    along with, so they keep their length."""
    if spec.get("jam"): return out
    limit = spec.get("max_seconds", MAX_SECONDS)
    total = sum(c["beats"] for c in out) * beat
    if total <= limit: return out
    floor_b = max(1, int(np.ceil(min_sec / beat - 1e-6)))
    f = limit / total
    return [{**c, "beats": max(floor_b, int(round(c["beats"] * f)))} for c in out]


def expand(spec):
    """Musical timing. Chords given in real bars ("bars", may be 0.5 / 0.25) become:
    a whole-bar intro on the first chord (the hook plays over it), the loop with every
    chord stretched by the same power of two (so proportions match the record and
    every chord lands on whole bars), and a whole-bar ending back on the first chord.
    Specs without "bars" keep their old "beats" timing."""
    if not any("bars" in c for c in spec["chords"]):
        return spec
    spec = apply_cut(spec)
    bpb = spec.get("beats_per_bar", 4)
    bar = bpb * 60 / spec["bpm"]
    MIN = spec.get("min_chord_seconds", 2.0 if loops(spec) else 2.4)   # long enough to hear each chord
    chords = [dict(c) for c in spec["chords"]]
    ending = chords.pop() if chords[-1].get("ending") else None
    if loops(spec): ending = None   # the loop goes straight back to the first chord
    k = spec.get("stretch") or 1
    grid = 1 / bpb if loops(spec) else 1   # loop mode: chords may land on any beat, not only whole bars
    while not spec.get("stretch") and k < 8 and (
            min(c["bars"] for c in chords) * k * bar < MIN
            or any(abs(c["bars"] * k / grid - round(c["bars"] * k / grid)) > 1e-6 for c in chords)):
        k *= 2

    def pow2_bars(sec):
        n = 1
        while n * bar < sec - 1e-6: n *= 2
        return n

    first = chords[0]
    if loops(spec):   # no long held intro: movement from the first second, the hook over the first bar
        beat = 60 / spec["bpm"]
        cap = max(bpb, int(4.5 / beat))   # no straight line longer than ~4.5 s: viewers scroll away
        out = [{**c, "beats": min(cap, int(round(c["bars"] * k * bpb)))} for c in chords]
        out = cap_length(spec, out, beat, MIN)
        once = sum(c["beats"] for c in out) * beat   # short loops play twice (captions on the first pass),
        if once < 12 and (spec.get("jam") or 2 * once <= spec.get("max_seconds", MAX_SECONDS) + 0.5):   # if that still fits the cap
            out = out + [{**c, "_repeat": True} for c in out]
        return {**spec, "chords": out, "hook_beats": bpb, "_intro": 0, "_stretch": k}
    intro_bars = pow2_bars(spec.get("hook_seconds", 3.6))
    out = [{"name": first["name"], "roman": first.get("roman", ""), "tag": first.get("tag", ""),
            "notes": first["notes"], "beats": intro_bars * bpb, "intro": True}]
    for c in chords:
        out.append({**c, "beats": int(round(c["bars"] * k)) * bpb})
    if ending is not None:
        nb = max(pow2_bars(2.0), int(round(ending.get("bars", 1))))
        out.append({**ending, "beats": nb * bpb})
    elif chords[-1]["name"] != first["name"] and not loops(spec):
        out.append({"name": first["name"], "roman": first.get("roman", ""), "tag": first.get("tag", ""),
                    "notes": first["notes"], "beats": pow2_bars(2.0) * bpb, "ending": True})
    return {**spec, "chords": out, "hook_beats": intro_bars * bpb, "_intro": 1, "_stretch": k}


class Reel:
    def __init__(self, spec):
        set_theme(theme_for(spec))
        set_layout(layout_for(spec) if loops(spec) else "classic")
        self.spec = spec = expand(spec)
        sr.GLIDE = sr.glide_for(spec, sr.profile_for(spec)) if loops(spec) else 0.18   # per song since 2026-11-20
        self.song = s = sr.Song(spec)
        acc = spec.get("accent", "#FF7AA8")
        self.accent = DEFAULT_ACCENT if acc.upper() == "#FF7AA8" else hexrgb(acc)   # the brand pink follows the theme
        self.hook_end = s.hook_end or sr.LEAD_IN
        self.outro_start = s.end + 0.3
        self.voice_cols = [VOICES[min(i, 3)] if s.nv <= 4 else VOICES6[i % 6] for i in range(s.nv)]
        # which voices move into each chord
        self.moved = [np.zeros(s.nv, bool)] + [s.pitch[i] != s.pitch[i - 1] for i in range(1, len(s.starts))]
        self.focus = []
        for i, c in enumerate(spec["chords"]):
            f = c.get("focus")
            if f is not None and i > 0 and not self.moved[i][f]: f = None   # only a moving note gets the chip
            if f is None and i > 0:
                cand = [v for v in range(1, s.nv) if self.moved[i][v]] or [v for v in range(s.nv) if self.moved[i][v]]
                f = cand[0] if cand else None
            self.focus.append(f)
        self.names = []
        for c in spec["chords"]:
            if c["name"] not in [n for n, _ in self.names]: self.names.append((c["name"], c.get("roman", "")))
        self.hits = [np.array([e[0] for e in s.arp if e[1] == v]) for v in range(s.nv)]
        self.vels = [np.array([e[3] for e in s.arp if e[1] == v]) for v in range(s.nv)]
        up = s.pitch[:, 1:].flatten(); bs = s.pitch[:, 0]
        self.urange, self.brange = (up.min() - 1, up.max() + 1), (bs.min() - 1, bs.max() + 1)

    def explains(self, ci):
        """Explain only what's interesting: the chords listed in "explain" (indices into the sketch's
        chords), else just the hook's focus chord. Without loop mode every chord keeps its caption."""
        sp = self.spec
        if not loops(sp): return True
        i = ci - sp.get("_intro", 0)
        if sp["chords"][ci].get("_repeat"): return False
        return i in (sp["explain"] if isinstance(sp.get("explain"), list) else [sp.get("hook_focus", len(sp["chords"]) - 1)])

    # pitch → y in two lanes (upper voices roomy, bass compact)
    def ymap(self, v, p, ut, ub, bt, bb):
        lo, hi = self.brange if v == 0 else self.urange
        top, bot = (bt, bb) if v == 0 else (ut, ub)
        return bot - (p - lo) / (hi - lo) * (bot - top)

    def flash(self, v, now):
        h = self.hits[v]
        k = np.searchsorted(h, now, side="right") - 1
        return float(self.vels[v][k] * np.exp(-(now - h[k]) / 0.11)) if k >= 0 else 0.0

    # ------------------------------------------------------------- frames --
    def header(self, cr, d, big):
        sz, sw = (44, 8) if big else (36, 9)
        logo(cr, L, 240 - sz / 2, sz, sw)
        fs = 26 if big else 22
        tx.draw(d, L + sz + (14 if big else 12), tx.base(240 - fs * 0.6, SEMI, fs), "chords that move", SEMI, fs,
                PAPER if big else SOFT, -0.03)

    def hook(self, now):
        """Hook = the live song (lines + playhead) with the headline on top."""
        return self.chord(now, hook=True)

    def chord(self, now, hook=False):
        s, sp = self.song, self.spec
        ci = s.chord_at(now); ch = sp["chords"][ci]
        since = now - max(s.starts[ci], self.hook_end)
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H); cr = cairo.Context(surf)
        paint_bg(cr)
        logo(cr, L, 240 - 18, 36, 9)
        # stepper bar
        y_bar = 427
        frac = np.clip((now - s.starts[0]) / (s.end - s.starts[0]), 0, 1)
        if not hook and LAYOUT == "classic":
            cr.set_source_rgb(*rgb1(LINE)); rrect(cr, L, y_bar, R - L, 4, 2); cr.fill()
        if frac > 0.002 and not hook and LAYOUT == "classic":
            cr.set_source_rgb(*rgb1(PAPER)); rrect(cr, L, y_bar, max(4, (R - L) * frac), 4, 2); cr.fill()
        # ---- voice lines ----
        PX, PH = 110, 640
        pre = 0.0   # 1 during the hook: upcoming lines bright (a preview of the whole loop)
        if loops(sp):
            PH = 420   # loop mode: one fixed playhead position for the whole reel (a moving one irritated)
            if self.hook_end: pre = 1 - ease((now - (self.hook_end - 0.5)) / 0.7)
        t_left, t_right = now - PH / PX, now + (W - PH) / PX
        ts = np.linspace(max(t_left, 0), min(t_right, s.end), 360)
        xs = PH + (ts - now) * PX
        emph = [float(self.moved[ci][v]) * ease(since / 0.25) for v in range(s.nv)]
        heads = []
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        for v in range(s.nv):
            col = rgb1(self.voice_cols[v])
            ys = self.ymap(v, s.voice_curve(v, ts), UT, UB, BT, BB)
            past = ts <= now
            for fut in (True, False):
                idx = np.where(~past if fut else past)[0]
                if len(idx) < 2: continue
                if not fut and idx[-1] + 1 < len(ts): idx = np.append(idx, idx[-1] + 1)
                e = emph[v]
                a, lw = (0.22, LW - 2) if fut else (0.75 + 0.25 * e, LW + LW_MOVE * e)
                if fut and THEME != "night": a = 0.35   # textured and light backgrounds need more ink
                if fut: a = a + (0.7 - a) * pre
                cr.set_source_rgba(*col, a); cr.set_line_width(lw)
                cr.set_dash({"dashed": [14, 10], "dotted": [0.1, 12]}.get(FUTURE, []) if fut else [])
                cr.move_to(xs[idx[0]], ys[idx[0]])
                for j in idx[1:]: cr.line_to(xs[j], ys[j])
                cr.stroke()
            if now <= s.end:
                hy = float(self.ymap(v, s.voice_curve(v, np.array([now]))[0], UT, UB, BT, BB))
                heads.append((v, hy))
        cr.set_source_rgba(*rgb1(PAPER), 0.35); cr.set_line_width(2)
        cr.move_to(PH, PH_TOP + (90 if hook and LAYOUT == "lines" else 0)); cr.line_to(PH, PH_BOT); cr.stroke()
        for v, hy in heads:
            e, fl = emph[v], self.flash(v, now)
            glow(cr, PH, hy, (GLOW + 20 * e) * (1 + 0.2 * fl), self.voice_cols[v], 0.45 + 0.4 * e + 0.25 * fl)
            cr.set_source_rgb(*rgb1(PLAYHEAD)); cr.arc(PH, hy, DOT + 4 * e, 0, 6.2832); cr.fill()
        # chip (moving note)
        fv = self.focus[ci]
        chip = None
        text = ch.get("text", "") if self.explains(ci) else ""
        if sp.get("guess") and loops(sp) and ci == len(sp["chords"]) - 1:   # the reveal (no end card in loop mode)
            text = f"It's *{sp['title']}* — {sp['artist']}"
        cap_toks = tokens(text, PAPER, self.voice_cols[fv] if fv is not None else self.accent)
        cap_lines = wrap(cap_toks, MED, CAP_SIZE, -0.02, R - L)[:2]
        if fv is not None and ci > 0 and not hook and s.pitch[ci, fv] != s.pitch[ci - 1, fv]:
            a_ = sp["chords"][ci - 1]["notes"][fv]; b_ = ch["notes"][fv]
            semis = int(s.pitch[ci, fv] - s.pitch[ci - 1, fv])
            t1 = f"{sr.pretty(a_)} → {sr.pretty(b_)}"
            t2 = f"{'↑' if semis > 0 else '↓'} {INTERVALS.get(abs(semis), f'{abs(semis)} semitones')}"
            w1, w2 = tx.width(t1, MONO, 24), tx.width(t2, MONO, 22)
            cw_ = 22 + 12 + 14 + w1 + 14 + w2 + 22
            cy = CHIP_Y
            ca = ease((since - 0.35) / 0.3)
            if ca > 0:
                cr.set_source_rgb(*rgb1(mixc(SURFACE, ca))); rrect(cr, L, cy, cw_, 56, 28); cr.fill_preserve()
                cr.set_source_rgb(*rgb1(mixc(BORDER, ca))); cr.set_line_width(1); cr.stroke()
                cr.set_source_rgb(*rgb1(mixc(self.voice_cols[fv], ca))); cr.arc(L + 28, cy + 28, 6, 0, 6.2832); cr.fill()
                chip = (cy, ca, t1, t2, w1)
        img = to_pil(surf); d = ImageDraw.Draw(img)
        tx.draw(d, L + 48, tx.base(240 - 13, SEMI, 22), "chords that move", SEMI, 22, SOFT, -0.03)
        hd = "GUESS THE SONG" if sp.get("guess") else f"{sp['artist'].upper()} — {sp['title'].upper()}"
        if hook:
            hd = f"EP. {int(sp['episode']):02d}" if sp.get("episode") else ""
        tx.draw(d, R - tx.width(hd, MONO, 22, 0.12), tx.base(240 - 13, MONO, 22), hd, MONO, 22, MUTED, 0.12)
        if hook:
            label = "GUESS THE SONG" if sp.get("guess") else f"{sp['artist'].upper()} — {sp['title'].upper()}"
            pw = tx.width(label, MONO, 22, 0.12) + 44
            d.rounded_rectangle([L, 400, L + pw, 450], radius=25, outline=BORDER, width=2)
            tx.draw(d, L + 22, tx.base(400, MONO, 22, 50 / 22), label, MONO, 22, SOFT, 0.12)
            for li, line in enumerate(wrap(tokens(sp["hook"], PAPER, self.accent), SEMI, HOOK_SIZE, -0.045, R - L)[:3]):
                b = tx.base(HOOK_Y + li * HOOK_SIZE * 1.02, SEMI, HOOK_SIZE, 1.0)
                for w, c, x in line: tx.draw(d, L + x, b, w, SEMI, HOOK_SIZE, c, -0.045)
            cap_lines = []
        # stepper
        n = len(self.names) if not hook and LAYOUT == "classic" else 0
        colw = (R - L - 12 * (n - 1)) / max(n, 1)
        for i, (nm, rom) in enumerate(self.names[:n]):
            on = nm == ch["name"]
            x = L + i * (colw + 12)
            tx.draw(d, x, tx.base(340, SEMI, 34), pretty_chord(nm), SEMI, 34, PAPER if on else DIM)
            tx.draw(d, x, tx.base(387, MONO, 18), rom, MONO, 18, self.accent if on else DIM)
        # big chord: 12 px rise + fade
        k = ease(since / 0.3)
        a = k; dy = 12 * (1 - k)
        name = pretty_chord(ch["name"])
        pill_w = (tx.width(ch.get("roman", ""), MONO_M, 24) + 36 + 28) if ch.get("roman") else 0
        csz = CHORD_MAX
        while csz > CHORD_MIN and tx.width(name, SEMI, csz, -0.06) + max(pill_w, 150 if ch.get("tag") else 0) > R - L:
            csz -= 10
        cb = Y_CHORD + dy
        wname = tx.width(name, SEMI, csz, -0.06)
        big = not hook and LAYOUT == "classic"
        if big: tx.draw(d, L, cb, name, SEMI, csz, mixc(PAPER, a), -0.06)
        if ch.get("roman") and big:
            px = L + wname + 28
            pw = tx.width(ch["roman"], MONO_M, 24) + 36
            ptop = cb - 82
            d.rounded_rectangle([px, ptop, px + pw, ptop + 45], radius=22, fill=mixc(self.accent, a))
            tx.draw(d, px + 18, tx.base(ptop, MONO_M, 24, 45 / 24), ch["roman"], MONO_M, 24, INK)
            if ch.get("tag"):
                tx.draw(d, px, tx.base(ptop + 55, MONO, 20), ch["tag"].upper(), MONO, 20, mixc(MUTED, a), 0.1)
        # caption, word by word
        k_word = 0
        for li, line in enumerate(cap_lines):
            b = tx.base(CAP_Y + li * CAP_LH, MED, CAP_SIZE, 1.25)
            for w, c, x in line:
                wa = ease((since - 0.15 - k_word * 0.04) / 0.22); k_word += 1
                if wa > 0: tx.draw(d, L + x, b, w, MED, CAP_SIZE, mixc(c, wa), -0.02)
        if chip:
            cy, ca, t1, t2, w1 = chip
            b = tx.base(cy, MONO, 24, 56 / 24)
            tx.draw(d, L + 48, b, t1, MONO, 24, mixc(PAPER, ca, SURFACE))
            tx.draw(d, L + 48 + w1 + 14, b, t2, MONO, 22, mixc(MUTED, ca, SURFACE))
        # roll: chord labels (past sticky left, current white, future faint)
        labs = []
        for i, c in enumerate(sp["chords"]):
            lx = PH + (s.starts[i] - now) * PX
            if i > 0 and sp["chords"][i - 1]["name"] == c["name"]:   # same chord continues
                labs[-1][3] = i; continue
            labs.append([max(L, lx), pretty_chord(c["name"]), i, i])
        for j in range(len(labs) - 2, -1, -1):
            wj = tx.width(labs[j][1], MONO, LAB_SIZE)
            labs[j][0] = min(labs[j][0], labs[j + 1][0] - wj - 30)
        for lx, nm, i, i_end in labs:
            if lx > R + 40 or (hook and LAYOUT == "lines"): continue   # the hook sits where the labels go
            fade = np.clip((lx - (L - 30)) / 30, 0, 1)
            col = PAPER if i <= ci <= i_end else (DIM if i_end < ci else FAINT)
            if fade > 0: tx.draw(d, lx, LAB_Y, nm, SEMI if LAYOUT == "lines" else MONO, LAB_SIZE, mixc(col, fade))
        for v, hy in heads:
            note = sr.pretty(ch["notes"][v])
            if emph[v] > 0.5:
                tx.draw(d, PH + 28, hy - 16, note, MONO_M, 36, self.voice_cols[v])
            else:
                tx.draw(d, PH + 24, hy - 12, note, MONO, 26, self.voice_cols[v])
        return img

    def outro(self, now):
        sp = self.spec
        k = ease((now - self.outro_start) / 0.6)
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H); cr = cairo.Context(surf)
        paint_bg(cr)
        cr.save(); cr.translate(0, 300)
        cr.set_source_rgba(*rgb1(PAPER), 0.3); cr.set_line_width(2); cr.move_to(700, 10); cr.line_to(700, 410); cr.stroke()
        cr.set_line_width(14); cr.set_line_cap(cairo.LINE_CAP_ROUND)
        reveal = -20 + 1120 * k
        cr.save(); cr.rectangle(-20, 0, reveal + 20, 420); cr.clip()
        for col, path in ((SOPRANO, [(-20, 80), (1100, 80)]), (TENOR, [(-20, 260), (1100, 260)])):
            cr.set_source_rgb(*rgb1(col)); cr.move_to(*path[0]); cr.line_to(*path[1]); cr.stroke()
        for col, y0, y1 in ((ALTO, 210, 150), (BASS, 300, 360)):
            cr.set_source_rgb(*rgb1(col)); cr.move_to(-20, y0); cr.line_to(420, y0)
            cr.curve_to(520, y0, 500, y1, 600, y1); cr.line_to(1100, y1); cr.stroke()
        cr.restore()
        if reveal > 700:
            p = ease((reveal - 700) / 120)
            cr.set_source_rgb(*rgb1(PLAYHEAD))
            for y in (80, 150, 260, 360): cr.arc(700, y, 16 * p, 0, 6.2832); cr.fill()
        cr.restore()
        img = to_pil(surf); d = ImageDraw.Draw(img)
        if sp.get("guess"):   # the reveal
            tx.draw(d, L, tx.base(800, MONO, 26), "THE SONG WAS", MONO, 26, MUTED, 0.14)
            y = 850
            for line in wrap(tokens(sp["title"], self.accent, self.accent), SEMI, 104, -0.045, R - L)[:2]:
                bb = tx.base(y, SEMI, 104, 1.0)
                for w, c, x in line: tx.draw(d, L + x, bb, w, SEMI, 104, c, -0.045)
                y += 108
            tx.draw(d, L, tx.base(y + 20, MONO, 30), sp["artist"].upper(), MONO, 30, PAPER, 0.12)
            tx.draw(d, L, tx.base(1220, MONO, 26), sp.get("handle", "@chordsthatmove"), MONO, 26, PAPER)
            return img
        if sp.get("jam"):   # send people to the tool with this progression
            tx.draw(d, L, tx.base(800, MONO, 26), "BUILD YOUR OWN JAM", MONO, 26, MUTED, 0.14)
            b = tx.base(850, SEMI, 104, 1.0)
            tx.draw(d, L, b, "chordsthatmove", SEMI, 104, PAPER, -0.045)
            tx.draw(d, L, b + 108, ".com/jam", SEMI, 104, self.accent, -0.045)
            tx.draw(d, L, tx.base(1180, MED, 40), "Free · in your browser · link in bio", MED, 40, SOFT)
            tx.draw(d, L, tx.base(1260, MONO, 26), sp.get("handle", "@chordsthatmove"), MONO, 26, PAPER)
            return img
        b = tx.base(820, SEMI, 112, 0.95)
        tx.draw(d, L, b, "chords", SEMI, 112, PAPER, -0.045)
        x = tx.draw(d, L, b + 106, "that ", SEMI, 112, PAPER, -0.045)
        tx.draw(d, x, b + 106, "move", SEMI, 112, self.accent, -0.045)
        hy = 1220
        tx.draw(d, L, tx.base(hy, MONO, 26), sp.get("handle", "@chordsthatmove"), MONO, 26, PAPER)
        return img


    # ------------------------------------------------------------ covers --
    def cover(self):
        """Grid cover (4:5, 1080x1350) after Grid-Cover.dc.html, plus a 9:16 reel cover
        that holds the same design inside Instagram's centre grid crop."""
        s, sp = self.song, self.spec
        CW, CH, PX_, PY = 1080, 1350, 96, 104
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, CW, CH); cr = cairo.Context(surf)
        paint_bg(cr, CW, CH)
        off = sp.get("_intro", 0)              # skip the intro chord added by expand()
        cols = list(sp["chords"][off:])
        if len(cols) > 1 and cols[-1]["name"] == cols[0]["name"]: cols = cols[:-1]
        n = len(cols); fi = min(sp.get("hook_focus", n - 1), n - 1)
        # overview lines (888 x 200) above the bottom row
        gx, gy, gw = PX_, 1350 - PY - 72 - 60 - 200, 888
        cw = gw / n
        yv = lambda v, i: self.ymap(v, s.pitch[i + off, v], gy + 20, gy + 130, gy + 160, gy + 192)
        cr.set_line_width(6); cr.set_line_cap(cairo.LINE_CAP_ROUND)
        for v in range(s.nv):
            cr.set_source_rgb(*rgb1(self.voice_cols[v]))
            cr.move_to(gx, yv(v, 0))
            for i in range(1, n):
                xb = gx + i * cw; y0, y1 = yv(v, i - 1), yv(v, i)
                cr.line_to(xb - 14, y0); cr.curve_to(xb, y0, xb, y1, xb + 14, y1)
            cr.line_to(gx + gw - 8, yv(v, n - 1)); cr.stroke()
        fv = self.focus[fi + off] if self.focus[fi + off] is not None else 2 % s.nv
        cr.set_source_rgb(*rgb1(PLAYHEAD)); cr.arc(gx + fi * cw + 30, yv(fv, fi), 10, 0, 6.2832); cr.fill()
        logo(cr, CW - PX_ - 72, CH - PY - 72, 72, 8)
        buf = np.frombuffer(surf.get_data(), np.uint8).reshape(CH, surf.get_stride() // 4, 4)[:, :CW]
        img = Image.fromarray(buf[:, :, [2, 1, 0]].copy()); d = ImageDraw.Draw(img)
        guess = sp.get("guess")   # guess mode: no song name on the cover, the chord row is the clue
        kicker = (f"EP. {int(sp['episode']):02d}" if sp.get("episode") else "") if guess else sp["artist"].upper()
        tx.draw(d, PX_, tx.base(PY, MONO, 26), kicker, MONO, 26, MUTED, 0.14)
        big = "Guess the song" if guess else sp["title"]
        # title: as big as fits (two lines max)
        size = 210
        while size > 110:
            lines = wrap(tokens(big, PAPER, PAPER), SEMI, size, -0.06, CW - 2 * PX_)
            widest = max(line[-1][2] + tx.width(line[-1][0], SEMI, size, -0.06) for line in lines)
            if len(lines) <= (1 if size > 160 else 2) and widest <= CW - 2 * PX_: break
            size -= 10
        for li, line in enumerate(lines):
            b = tx.base(PY + 46 + li * size * 0.88, SEMI, size, 0.85)
            for w, c, x in line: tx.draw(d, PX_ + x, b, w, SEMI, size, PAPER, -0.06)
        # chord row
        csz = 64
        names = [pretty_chord(c["name"]) for c in cols]
        while csz > 36 and sum(tx.width(nm, SEMI, csz, -0.03) for nm in names) + 26 * (n - 1) > gw: csz -= 4
        x = PX_
        for i, nm in enumerate(names):
            tx.draw(d, x, gy - 40, nm, SEMI, csz, self.accent if i == fi else DIM, -0.03)
            x += tx.width(nm, SEMI, csz, -0.03) + 26
        # bottom line: cover text with accent phrase
        ctext = sp.get("cover_text", sp["hook"])
        lines = wrap(tokens(ctext, PAPER, self.accent), MED, 40, 0, 600)
        b0 = CH - PY - len(lines) * 48 + 8
        for li, line in enumerate(lines):
            for w, c, x in line: tx.draw(d, PX_ + x, tx.base(b0 + li * 48, MED, 40, 1.2), w, MED, 40, c)
        grid = img
        reel = Image.new("RGB", (W, H), INK)
        reel.paste(grid, (0, (H - CH) // 2))
        return grid, reel

    def frame(self, now):
        X = 0.35
        if now < self.hook_end - X / 2:
            return self.hook(now)
        if now < self.hook_end + X / 2:
            return Image.blend(self.hook(now), self.chord(now), ease((now - self.hook_end + X / 2) / X))
        if loops(self.spec):   # last 0.35 s blend into the first frame, so the replay starts seamlessly
            end = self.song.end
            if now < end - X: return self.chord(now)
            return Image.blend(self.chord(min(now, end - 1e-3)), self.hook(0.0), ease((now - (end - X)) / X))
        if now < self.outro_start:
            return self.chord(now)
        if now < self.outro_start + 0.45:
            return Image.blend(self.chord(now), self.outro(now), ease((now - self.outro_start) / 0.45))
        return self.outro(now)


def pretty_chord(n): return sr.pretty_chord(n)


def stills(spec, outdir, times):
    r = Reel(spec); os.makedirs(outdir, exist_ok=True)
    for t in map(float, times):
        p = os.path.join(outdir, f"frame_{t:05.2f}.jpg"); r.frame(t).save(p, quality=90); print(p)


def wrap_audio(path, seconds):
    """Cut the audio to the loop length and add what rings on after it (reverb, echoes, the pad's
    release) back onto the start, so the replay continues without a cut."""
    from scipy.io import wavfile
    rate, x = wavfile.read(path)
    x = x.astype(np.float64)
    n = int(round(seconds * rate))
    head, tail = x[:n].copy(), x[n:n * 2]
    head[:len(tail)] += tail
    head *= min(1.0, 0.89 * 32767 / max(1.0, np.max(np.abs(head))))
    wavfile.write(path, rate, head.astype(np.int16))


def render(spec, out):
    r = Reel(spec); s = r.song
    base = os.path.splitext(out)[0]
    wav, silent, tmp = base + ".wav", base + ".video.tmp.mp4", base + ".tmp.mp4"
    sr.synth(s, wav)
    n_frames = int(s.total * FPS)
    if loops(r.spec):
        n_frames = int(round(s.end * FPS))
        wrap_audio(wav, n_frames / FPS)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                           "-crf", "19", "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
    for i in range(n_frames):
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
    elif cmd == "cover":
        g, r = Reel(spec).cover(); g.save(sys.argv[3] + "_grid.png"); r.save(sys.argv[3] + "_reel.png"); print(sys.argv[3])
