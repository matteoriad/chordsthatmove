#!/usr/bin/env python3
"""Re-voice every queue file in 6 voices (2026-11-23): bass + 5 upper voices from voicing.py.

  python3 songs/revoice.py [songs/queue/*.json]

Everything else in a file stays as it is. Each chord's `focus` (the voice its caption talks
about) follows its note: the first upper voice with the same note name in the new voicing.
"""
import glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import voicing  # noqa: E402

strip = lambda n: re.sub(r"-?\d+$", "", n)


def revoice(spec, voices=voicing.VOICES):
    old = [c.get("notes") or [] for c in spec["chords"]]
    new = voicing.voice([{"name": c["name"]} for c in spec["chords"]], voices)
    for c, o, n in zip(spec["chords"], old, new):
        c["notes"] = n
        if c.get("focus") is not None:
            f = c["focus"]
            want = strip(o[f]) if f < len(o) else None
            hit = [i for i in range(1, len(n)) if strip(n[i]) == want]
            if hit: c["focus"] = hit[0]
            else: c.pop("focus")
    return spec


if __name__ == "__main__":
    paths = sys.argv[1:] or sorted(glob.glob(os.path.join(HERE, "queue", "*.json")))
    for p in paths:
        spec = json.load(open(p))
        json.dump(revoice(spec), open(p, "w"), indent=1, ensure_ascii=False)
        print(os.path.basename(p))
