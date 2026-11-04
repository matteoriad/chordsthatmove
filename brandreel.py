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
sr.TAIL = 4.0            # room for the outro
W, H, FPS = 1080, 1920, 30
HERE = os.path.dirname(os.path.abspath(__file__))

# ---- brand tokens ----
INK, SURFACE, MUTED, PAPER = (11, 11, 16), (21, 21, 29), (138, 138, 153), (242, 242, 245)
DIM, FAINT, SOFT = (110, 110, 124), (78, 78, 90), (180, 180, 192)
LINE, BORDER = (34, 34, 44), (42, 42, 54)
SOPRANO, ALTO, TENOR, BASS = (92, 200, 240), (169, 155, 255), (255, 122, 168), (245, 181, 74)
VOICES = [BASS, TENOR, ALTO, SOPRANO]          # index 0 = lowest note
L, R = 72, 940                                  # safe-zone content edges

INTER = HERE + "/fonts/Inter-"
SEMI, MED = INTER + "SemiBold.otf", INTER + "Medium.otf"
MONO, MONO_M = HERE + "/fonts/JetBrainsMono-Regular.ttf", HERE + "/fonts/JetBrainsMono-Medium.ttf"
FALLBACK = HERE + "/fonts/DejaVuSans.ttf"


def hexrgb(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
def mixc(c, a, bg=INK): a = max(0.0, min(1.0, a)); return tuple(int(c[i] * a + bg[i] * (1 - a)) for i in range(3))
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


class Reel:
    def __init__(self, spec):
        self.spec = spec
        self.song = s = sr.Song(spec)
        self.accent = hexrgb(spec.get("accent", "#FF7AA8"))
        self.hook_end = s.hook_end or sr.LEAD_IN
        self.outro_start = s.end + 0.3
        self.voice_cols = [VOICES[min(i, 3)] if s.nv <= 4 else VOICES[i % 4] for i in range(s.nv)]
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
        cr.set_source_rgb(*rgb1(INK)); cr.paint()
        logo(cr, L, 240 - 18, 36, 9)
        # stepper bar
        y_bar = 427
        frac = np.clip((now - s.starts[0]) / (s.end - s.starts[0]), 0, 1)
        if not hook:
            cr.set_source_rgb(*rgb1(LINE)); rrect(cr, L, y_bar, R - L, 4, 2); cr.fill()
        if frac > 0.002 and not hook:
            cr.set_source_rgb(*rgb1(PAPER)); rrect(cr, L, y_bar, max(4, (R - L) * frac), 4, 2); cr.fill()
        # ---- voice lines ----
        PX, PH = 110, 640
        UT, UB, BT, BB = 1160, 1390, 1430, 1500
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
                a, lw = (0.22, 4) if fut else (0.75 + 0.25 * e, 4 + 2 * e)
                cr.set_source_rgba(*col, a); cr.set_line_width(lw)
                cr.move_to(xs[idx[0]], ys[idx[0]])
                for j in idx[1:]: cr.line_to(xs[j], ys[j])
                cr.stroke()
            if now <= s.end:
                hy = float(self.ymap(v, s.voice_curve(v, np.array([now]))[0], UT, UB, BT, BB))
                heads.append((v, hy))
        cr.set_source_rgba(*rgb1(PAPER), 0.35); cr.set_line_width(2)
        cr.move_to(PH, 1136); cr.line_to(PH, 1540); cr.stroke()
        for v, hy in heads:
            e, fl = emph[v], self.flash(v, now)
            glow(cr, PH, hy, (34 + 14 * e) * (1 + 0.2 * fl), self.voice_cols[v], 0.45 + 0.4 * e + 0.25 * fl)
            cr.set_source_rgb(1, 1, 1); cr.arc(PH, hy, 6 + 3 * e, 0, 6.2832); cr.fill()
        # chip (moving note)
        fv = self.focus[ci]
        chip = None
        cap_toks = tokens(ch.get("text", ""), PAPER, self.voice_cols[fv] if fv is not None else self.accent)
        cap_lines = wrap(cap_toks, MED, 46, -0.02, R - L)
        if fv is not None and ci > 0 and not hook and s.pitch[ci, fv] != s.pitch[ci - 1, fv]:
            a_ = sp["chords"][ci - 1]["notes"][fv]; b_ = ch["notes"][fv]
            semis = int(s.pitch[ci, fv] - s.pitch[ci - 1, fv])
            t1 = f"{sr.pretty(a_)} → {sr.pretty(b_)}"
            t2 = f"{'↑' if semis > 0 else '↓'} {INTERVALS.get(abs(semis), f'{abs(semis)} semitones')}"
            w1, w2 = tx.width(t1, MONO, 24), tx.width(t2, MONO, 22)
            cw_ = 22 + 12 + 14 + w1 + 14 + w2 + 22
            cy = max(1010, 830 + len(cap_lines) * 57.5 + 30)
            ca = ease((since - 0.35) / 0.3)
            if ca > 0:
                cr.set_source_rgb(*rgb1(mixc(SURFACE, ca))); rrect(cr, L, cy, cw_, 56, 28); cr.fill_preserve()
                cr.set_source_rgb(*rgb1(mixc(BORDER, ca))); cr.set_line_width(1); cr.stroke()
                cr.set_source_rgb(*rgb1(mixc(self.voice_cols[fv], ca))); cr.arc(L + 28, cy + 28, 6, 0, 6.2832); cr.fill()
                chip = (cy, ca, t1, t2, w1)
        img = to_pil(surf); d = ImageDraw.Draw(img)
        tx.draw(d, L + 48, tx.base(240 - 13, SEMI, 22), "chords that move", SEMI, 22, SOFT, -0.03)
        hd = f"{sp['artist'].upper()} — {sp['title'].upper()}"
        if hook:
            hd = f"EP. {int(sp['episode']):02d}" if sp.get("episode") else ""
        tx.draw(d, R - tx.width(hd, MONO, 22, 0.12), tx.base(240 - 13, MONO, 22), hd, MONO, 22, MUTED, 0.12)
        if hook:
            label = f"{sp['artist'].upper()} — {sp['title'].upper()}"
            pw = tx.width(label, MONO, 22, 0.12) + 44
            d.rounded_rectangle([L, 420, L + pw, 470], radius=25, outline=(46, 46, 58), width=2)
            tx.draw(d, L + 22, tx.base(420, MONO, 22, 50 / 22), label, MONO, 22, SOFT, 0.12)
            for li, line in enumerate(wrap(tokens(sp["hook"], PAPER, self.accent), SEMI, 104, -0.045, R - L)):
                b = tx.base(510 + li * 104, SEMI, 104, 1.0)
                for w, c, x in line: tx.draw(d, L + x, b, w, SEMI, 104, c, -0.045)
            cap_lines = []
        # stepper
        n = len(self.names) if not hook else 0
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
        csz = 280
        while csz > 150 and tx.width(name, SEMI, csz, -0.06) + max(pill_w, 150 if ch.get("tag") else 0) > R - L:
            csz -= 10
        cb = 540 + 205 + dy
        wname = tx.width(name, SEMI, csz, -0.06)
        if not hook: tx.draw(d, L, cb, name, SEMI, csz, mixc(PAPER, a), -0.06)
        if ch.get("roman") and not hook:
            px = L + wname + 28
            pw = tx.width(ch["roman"], MONO_M, 24) + 36
            ptop = 540 + 238 - 14 - (45 + 10 + 24) + dy
            d.rounded_rectangle([px, ptop, px + pw, ptop + 45], radius=22, fill=mixc(self.accent, a))
            tx.draw(d, px + 18, tx.base(ptop, MONO_M, 24, 45 / 24), ch["roman"], MONO_M, 24, INK)
            if ch.get("tag"):
                tx.draw(d, px, tx.base(ptop + 55, MONO, 20), ch["tag"].upper(), MONO, 20, mixc(MUTED, a), 0.1)
        # caption, word by word
        k_word = 0
        for li, line in enumerate(cap_lines):
            b = tx.base(830 + li * 57.5, MED, 46, 1.25)
            for w, c, x in line:
                wa = ease((since - 0.15 - k_word * 0.04) / 0.22); k_word += 1
                if wa > 0: tx.draw(d, L + x, b, w, MED, 46, mixc(c, wa), -0.02)
        if chip:
            cy, ca, t1, t2, w1 = chip
            b = tx.base(cy, MONO, 24, 56 / 24)
            tx.draw(d, L + 48, b, t1, MONO, 24, mixc(PAPER, ca, SURFACE))
            tx.draw(d, L + 48 + w1 + 14, b, t2, MONO, 22, mixc(MUTED, ca, SURFACE))
        # roll: chord labels (past sticky left, current white, future faint)
        labs = []
        for i, c in enumerate(sp["chords"]):
            lx = PH + (s.starts[i] - now) * PX
            labs.append([max(L, lx), pretty_chord(c["name"]), i])
        for j in range(len(labs) - 2, -1, -1):
            wj = tx.width(labs[j][1], MONO, 22)
            labs[j][0] = min(labs[j][0], labs[j + 1][0] - wj - 30)
        for lx, nm, i in labs:
            if lx > R + 40: continue
            fade = np.clip((lx - (L - 30)) / 30, 0, 1)
            col = PAPER if i == ci else (DIM if i < ci else FAINT)
            if fade > 0: tx.draw(d, lx, 1126, nm, MONO, 22, mixc(col, fade))
        for v, hy in heads:
            note = sr.pretty(ch["notes"][v])
            if emph[v] > 0.5:
                tx.draw(d, PH + 24, hy - 14, note, MONO_M, 34, self.voice_cols[v])
            else:
                tx.draw(d, PH + 20, hy - 10, note, MONO, 24, self.voice_cols[v])
        return img

    def outro(self, now):
        sp = self.spec
        k = ease((now - self.outro_start) / 0.6)
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H); cr = cairo.Context(surf)
        cr.set_source_rgb(*rgb1(INK)); cr.paint()
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
            cr.set_source_rgb(1, 1, 1)
            for y in (80, 150, 260, 360): cr.arc(700, y, 16 * p, 0, 6.2832); cr.fill()
        cr.restore()
        nxt = sp.get("next")
        if nxt:
            cr.set_source_rgb(*rgb1(SURFACE)); rrect(cr, L, 1220, R - L, 128, 24); cr.fill_preserve()
            cr.set_source_rgb(*rgb1(BORDER)); cr.set_line_width(1); cr.stroke()
            cr.set_source_rgb(*rgb1(PAPER)); cr.set_line_width(2.5); cr.set_line_cap(cairo.LINE_CAP_ROUND)
            ax, ay = R - 32 - 40, 1284
            cr.move_to(ax + 8, ay); cr.line_to(ax + 32, ay); cr.move_to(ax + 22, ay - 10); cr.line_to(ax + 32, ay)
            cr.line_to(ax + 22, ay + 10); cr.stroke()
        img = to_pil(surf); d = ImageDraw.Draw(img)
        b = tx.base(820, SEMI, 112, 0.95)
        tx.draw(d, L, b, "chords", SEMI, 112, PAPER, -0.045)
        x = tx.draw(d, L, b + 106, "that ", SEMI, 112, PAPER, -0.045)
        tx.draw(d, x, b + 106, "move", SEMI, 112, self.accent, -0.045)
        hy = 1220
        if nxt:
            tx.draw(d, L + 32, tx.base(1250, MONO, 20), "NEXT EPISODE", MONO, 20, mixc(MUTED, 1, SURFACE), 0.12)
            tx.draw(d, L + 32, tx.base(1282, SEMI, 36), nxt, SEMI, 36, PAPER, -0.02)
            hy = 1220 + 128 + 20
        tx.draw(d, L, tx.base(hy, MONO, 26), sp.get("handle", "@chordsthatmove"), MONO, 26, PAPER)
        return img


    # ------------------------------------------------------------ covers --
    def cover(self):
        """Grid cover (4:5, 1080x1350) after Grid-Cover.dc.html, plus a 9:16 reel cover
        that holds the same design inside Instagram's centre grid crop."""
        s, sp = self.song, self.spec
        CW, CH, PX_, PY = 1080, 1350, 96, 104
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, CW, CH); cr = cairo.Context(surf)
        cr.set_source_rgb(*rgb1(INK)); cr.paint()
        cols = list(sp["chords"])
        if len(cols) > 1 and cols[-1]["name"] == cols[0]["name"]: cols = cols[:-1]
        n = len(cols); fi = min(sp.get("hook_focus", n - 1), n - 1)
        # overview lines (888 x 200) above the bottom row
        gx, gy, gw = PX_, 1350 - PY - 72 - 60 - 200, 888
        cw = gw / n
        yv = lambda v, i: self.ymap(v, s.pitch[i, v], gy + 20, gy + 130, gy + 160, gy + 192)
        cr.set_line_width(6); cr.set_line_cap(cairo.LINE_CAP_ROUND)
        for v in range(s.nv):
            cr.set_source_rgb(*rgb1(self.voice_cols[v]))
            cr.move_to(gx, yv(v, 0))
            for i in range(1, n):
                xb = gx + i * cw; y0, y1 = yv(v, i - 1), yv(v, i)
                cr.line_to(xb - 14, y0); cr.curve_to(xb, y0, xb, y1, xb + 14, y1)
            cr.line_to(gx + gw - 8, yv(v, n - 1)); cr.stroke()
        fv = self.focus[fi] if self.focus[fi] is not None else 2 % s.nv
        cr.set_source_rgb(1, 1, 1); cr.arc(gx + fi * cw + 30, yv(fv, fi), 10, 0, 6.2832); cr.fill()
        logo(cr, CW - PX_ - 72, CH - PY - 72, 72, 8)
        buf = np.frombuffer(surf.get_data(), np.uint8).reshape(CH, surf.get_stride() // 4, 4)[:, :CW]
        img = Image.fromarray(buf[:, :, [2, 1, 0]].copy()); d = ImageDraw.Draw(img)
        tx.draw(d, PX_, tx.base(PY, MONO, 26), sp["artist"].upper(), MONO, 26, MUTED, 0.14)
        # title: as big as fits (two lines max)
        size = 210
        while size > 110:
            lines = wrap(tokens(sp["title"], PAPER, PAPER), SEMI, size, -0.06, CW - 2 * PX_)
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


def render(spec, out):
    r = Reel(spec); s = r.song
    base = os.path.splitext(out)[0]
    wav, silent, tmp = base + ".wav", base + ".video.tmp.mp4", base + ".tmp.mp4"
    sr.synth(s, wav)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                           "-crf", "19", "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
    for i in range(int(s.total * FPS)):
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
