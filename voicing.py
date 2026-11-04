#!/usr/bin/env python3
"""Turn a short song sketch (chord symbols + captions) into a full song spec
with smooth voice leading: bass on the root, three upper voices that move as
little as possible, each note spelled correctly for its chord (D♯ in B major,
E♭ in C minor).

Sketch chords: {"name": "F#m7", "roman": "vi", "tag": "...", "beats": 8,
                "text": "...", "focus_note": "A"  (optional),
                "notes": [...]  (optional: explicit voicing, bass first)}
"""
import itertools, json, re, sys

LETTERS = "CDEFGAB"
NAT = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# quality -> intervals (semitones) and their scale degree (letter steps from root)
QUAL = {
    "":      [(0, 0), (4, 2), (7, 4)],
    "m":     [(0, 0), (3, 2), (7, 4)],
    "7":     [(0, 0), (4, 2), (7, 4), (10, 6)],
    "m7":    [(0, 0), (3, 2), (7, 4), (10, 6)],
    "maj7":  [(0, 0), (4, 2), (7, 4), (11, 6)],
    "6":     [(0, 0), (4, 2), (7, 4), (9, 5)],
    "m6":    [(0, 0), (3, 2), (7, 4), (9, 5)],
    "sus2":  [(0, 0), (2, 1), (7, 4)],
    "sus4":  [(0, 0), (5, 3), (7, 4)],
    "7sus4": [(0, 0), (5, 3), (7, 4), (10, 6)],
    "add9":  [(0, 0), (4, 2), (7, 4), (14, 1)],
    "dim":   [(0, 0), (3, 2), (6, 4)],
    "5":     [(0, 0), (7, 4), (12, 0)],
}
LOW, HIGH = 55, 74          # upper voices between G3 and D5
BASS_LOW = 40               # bass root between E2 and D#3


def parse(name):
    m = re.fullmatch(r"([A-G])([#b]?)(.*?)(?:/([A-G][#b]?))?", name)
    root, acc, qual, slash = m.groups()
    return root, {"#": 1, "b": -1, "": 0}[acc], qual, slash


def spell(root_letter, root_pc, interval, degree, octave_midi):
    letter = LETTERS[(LETTERS.index(root_letter) + degree) % 7]
    pc = (root_pc + interval) % 12
    diff = (pc - NAT[letter] + 6) % 12 - 6
    acc = {0: "", 1: "#", -1: "b", 2: "##", -2: "bb"}[diff]
    octave = (octave_midi - (NAT[letter] + diff)) // 12 - 1
    return f"{letter}{acc}{octave}"


def chord_tones(name):
    letter, acc, qual, slash = parse(name)
    root_pc = (NAT[letter] + acc) % 12
    tones = [((root_pc + i) % 12, i, deg) for i, deg in QUAL[qual]]
    return letter, root_pc, qual, tones, slash


def candidates(name):
    letter, root_pc, qual, tones, _ = chord_tones(name)
    if qual == "5":   # power chord: root, fifth, octave, stacked from the root
        r = 48 + (root_pc - 48) % 12
        if r < 52: r += 12
        return letter, root_pc, [[(r, tones[0]), (r + 7, tones[1]), (r + 12, tones[2])]]
    elif len(tones) == 3:
        picks = [tones]
    else:   # 4 tones: drop the fifth first, else the root
        no5 = [t for t in tones if t[1] != 7]
        no1 = [t for t in tones if t[1] != 0]
        picks = [no5, no1] if len(no5) == 3 else [no1]
    out = []
    for pick in picks:
        opts = [[(m, t) for m in range(LOW, HIGH + 1) if m % 12 == t[0]] for t in pick]
        for combo in itertools.product(*opts):
            ms = [c[0] for c in combo]
            if len(set(ms)) < 3 or max(ms) - min(ms) > 12: continue
            combo = sorted(combo)
            out.append(combo)
    return letter, root_pc, out


def voice(chords):
    prev = None
    result = []
    for c in chords:
        if c.get("notes"):
            result.append(c["notes"]); prev = None
            continue
        letter, root_pc, cands = candidates(c["name"])
        if prev is None:
            best = min(cands, key=lambda cb: abs(sum(m for m, _ in cb) / 3 - 64))
        else:
            best = min(cands, key=lambda cb: sum(abs(m - p) for (m, _), p in zip(cb, prev))
                       + 0.05 * abs(sum(m for m, _ in cb) / 3 - 64))
        prev = [m for m, _ in best]
        _, _, _, _, slash = chord_tones(c["name"])
        if slash:
            bl, ba = slash[0], {"#": 1, "b": -1}.get(slash[1:], 0)
            bpc = (NAT[bl] + ba) % 12
            bm = BASS_LOW + (bpc - BASS_LOW) % 12
            bass = f"{bl}{slash[1:]}{bm // 12 - 1}"
        else:
            bm = BASS_LOW + (root_pc - BASS_LOW) % 12
            bass = spell(letter, root_pc, 0, 0, bm)
        upper = [spell(letter, root_pc, t[1], t[2], m) for m, t in best]
        result.append([bass] + upper)
    return result


def build(sketch):
    spec = {k: v for k, v in sketch.items() if k != "chords"}
    notes = voice(sketch["chords"])
    chords = []
    for c, ns in zip(sketch["chords"], notes):
        cc = {k: v for k, v in c.items() if k not in ("focus_note",)}
        cc["notes"] = ns
        if "focus_note" in c:
            want = c["focus_note"]
            hit = [i for i, n in enumerate(ns) if i > 0 and re.sub(r"-?\d+$", "", n) == want]
            if hit: cc["focus"] = hit[0]
        chords.append(cc)
    spec["chords"] = chords
    return spec


if __name__ == "__main__":
    for path in sys.argv[1:]:
        sk = json.load(open(path))
        sp = build(sk)
        print(sp["title"], "|", " → ".join(f"{c['name']} {c['notes']}" for c in sp["chords"]))
