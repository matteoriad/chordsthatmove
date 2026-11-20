#!/usr/bin/env python3
"""Write a "Jam over this" sketch: a progression to play along with, no song.

The reel loops the progression for about 25–35 s (2–4 times), the caption under each chord names the notes that
land safely on it, and the outro and Instagram caption send people to the jam tool with this
exact progression loaded.

  python3 songs/make_jam.py songs/jams/rainy-night.json 71

reads a short jam file (title, key, scale, scale_notes, bpm, hook, chords [[name, roman, bars]])
and writes songs/sketches/ep71-jam-rainy-night.json; then build the queue file as usual.
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import voicing  # noqa: E402

TARGET = 26   # seconds of loop; the reel adds the intro bar(s), the ending and the outro


def pretty(n): return n.replace("#", "♯").replace("b", "♭") if len(n) > 1 else n


def tones(name):
    letter, root_pc, qual, ts, slash = voicing.chord_tones(name)
    names = []
    for _, interval, deg in ts:
        n = voicing.spell(letter, root_pc, interval, deg, 60 + interval)[:-1]
        n = re.sub(r"-?\d+$", "", n)
        if n not in names: names.append(n)
    return names


def loops_for(jam):
    sec = sum(b for _, _, b in jam["chords"]) * 4 * 60 / jam["bpm"]
    return max(2, min(4, round(TARGET / sec)))


def sketch(jam, episode):
    LOOPS = loops_for(jam)
    chords = []
    for loop in range(LOOPS):
        for i, (name, roman, bars) in enumerate(jam["chords"]):
            ts = " ".join(pretty(t) for t in tones(name))
            if loop == 0 and i == 0:
                text = f"Scale: *{jam['scale']}*. Any of *{' '.join(pretty(n) for n in jam['scale_notes'])}* works."
            elif loop == LOOPS - 1 and i == len(jam["chords"]) - 1:
                text = "Your turn. *Build your own* jam → link in bio."
            else:
                text = f"Over *{pretty(name)}*, land on *{ts}*."
            chords.append({"name": name, "roman": roman, "tag": jam.get("tags", {}).get(name, "jam"),
                           "bars": bars, "text": text})
    first = jam["chords"][0]
    chords.append({"name": first[0], "roman": first[1], "tag": "home", "bars": 1, "ending": True,
                   "text": "Back home. Again? *Hit replay.*"})
    return {
        "title": jam["title"], "artist": "Jam over this", "key": jam["key"], "bpm": jam["bpm"],
        "episode": episode, "jam": True, "stretch": 1, "accent": jam.get("accent", "#FF7AA8"), "handle": "@chordsthatmove",
        "hook": jam["hook"], "hook_focus": jam.get("hook_focus", 1), "cover_text": jam.get("cover_text", jam["hook"]),
        "scale": jam["scale"], "scale_notes": jam["scale_notes"],
        "loop": [{"name": n, "bars": b} for n, _, b in jam["chords"]],
        "question": jam.get("question", "Post your jam and tag @chordsthatmove 🎹"),
        "hashtag": "jamtrack", "chords": chords,
        "explain": [0, len(chords) - 2, len(chords) - 1],   # the scale tip and the "your turn" line
    }


if __name__ == "__main__":
    src, ep = sys.argv[1], int(sys.argv[2])
    jam = json.load(open(src))
    slug = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(HERE, "sketches", f"ep{ep:02d}-jam-{slug}.json")
    json.dump(sketch(jam, ep), open(out, "w"), ensure_ascii=False, indent=1)
    print(out)
