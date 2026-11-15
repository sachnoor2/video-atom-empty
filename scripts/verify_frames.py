"""Verify the rendered PNG sequence before anything is assembled.

- every absolute frame index 0..N-1 exists exactly once, with real pixels in it
- no shot is secretly a still: duplicate-frame ratio per shot must stay under 20%

Run: python scripts/verify_frames.py --shotlist shotlist.json --frames public/frames
"""
import argparse
import hashlib
import json
import os
import sys


def digest(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shotlist", default="shotlist.json")
    ap.add_argument("--frames", default="public/frames")
    ap.add_argument("--min-bytes", type=int, default=20000)
    ap.add_argument("--max-dup", type=float, default=0.20)
    args = ap.parse_args()

    with open(args.shotlist) as fh:
        doc = json.load(fh)
    total = doc["totalFrames"]
    shots = doc["shots"]

    missing = []
    tiny = []
    for i in range(total):
        p = os.path.join(args.frames, f"frame_{i:06d}.png")
        if not os.path.exists(p):
            missing.append(i)
        elif os.path.getsize(p) < args.min_bytes:
            tiny.append(i)

    if missing:
        print(f"FAIL missing frames: {len(missing)} of {total}; "
              f"first 10 = {missing[:10]}, last = {missing[-1]}")
        sys.exit(2)
    if tiny:
        print(f"FAIL blank/truncated frames: {len(tiny)}; first 10 = {tiny[:10]}")
        sys.exit(2)

    bad = []
    for s in shots:
        digests = [digest(os.path.join(args.frames, f"frame_{i:06d}.png"))
                   for i in range(s["start"], s["end"] + 1)]
        dup = sum(1 for a, b in zip(digests, digests[1:]) if a == b)
        n = len(digests)
        ratio = dup / max(n - 1, 1)
        status = "ok" if ratio <= args.max_dup else "STILL"
        print(f"SHOT {s['id']} frames={n} duplicate_ratio={ratio:.3f} {status}")
        if ratio > args.max_dup:
            bad.append((s["id"], ratio))

    print(f"VERIFY frames 0..{total - 1} all present, {len(shots)} shots checked")
    if bad:
        print(f"FAIL shots reading as stills: {bad}")
        sys.exit(3)
    print("VERIFY ok: contiguous sequence, every shot is moving")


if __name__ == "__main__":
    main()
