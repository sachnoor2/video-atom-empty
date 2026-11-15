"""Turn the measured manifest into the shot list that Blender and Remotion share.

Shot boundaries are the scene boundaries, so a sentence is never cut in half.
Frame numbers are absolute across the whole film.

Run: python scripts/make_shotlist.py
"""
import argparse
import json
import math

CAMERA = ["push-in", "push-in", "orbit", "pull-back", "pull-back", "track",
          "push-in", "orbit", "push-in", "orbit", "pull-back", "orbit"]
MOTION = [
    ["lattice vibration", "dust motes", "light flicker", "foreground blur"],
    ["lattice shimmer", "core twinkle", "dust motes", "light flicker"],
    ["nucleon jiggle", "cluster rotation", "dust motes", "light flicker"],
    ["electron drift", "camera pull-back", "dust motes", "light flicker"],
    ["marble rotation", "dome rim pulse", "grid parallax", "light flicker"],
    ["electron drift", "core jiggle", "camera track", "dust motes"],
    ["core pulse", "nucleon jiggle", "dust motes", "light flicker"],
    ["field ring pulse", "ring rotation", "electron drift", "light flicker"],
    ["cloud approach", "surface sparkle", "dust motes", "light flicker"],
    ["cloud squash", "surface sparkle", "camera orbit", "light flicker"],
    ["lattice shimmer", "camera pull-back", "core twinkle", "dust motes"],
    ["electron drift", "camera orbit", "dust motes", "light flicker"],
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="src/manifest.json")
    ap.add_argument("--out", default="shotlist.json")
    args = ap.parse_args()

    with open(args.manifest) as fh:
        man = json.load(fh)
    fps = man["fps"]
    shots = []
    cursor = 0
    for i, sc in enumerate(man["scenes"]):
        frames = int(sc["frames"])
        shots.append({
            "id": sc["id"],
            "text": sc["text"],
            "start": cursor,
            "end": cursor + frames - 1,
            "seconds": round(frames / fps, 3),
            "blend": f"scenes/{sc['id']}.blend",
            "audio": sc["audio"],
            "camera": CAMERA[i % len(CAMERA)],
            "motion": MOTION[i % len(MOTION)],
            "samples": 48,
        })
        cursor += frames

    total = cursor
    doc = {"fps": fps, "width": man.get("width", 720), "height": man.get("height", 1280),
           "totalFrames": total, "durationSeconds": round(total / fps, 3),
           "shotsPerMinute": round(len(shots) / (total / fps / 60.0), 2),
           "shots": shots}
    with open(args.out, "w") as fh:
        json.dump(doc, fh, indent=2)
    print(f"SHOTLIST {args.out}: {len(shots)} shots, {total} frames, "
          f"{doc['durationSeconds']}s, {doc['shotsPerMinute']} shots/min")

    # shard plan: one shard per shot, all rendered in parallel
    plan = [{"index": i, "shots": [i], "frames": s["end"] - s["start"] + 1}
            for i, s in enumerate(shots)]
    with open("shardplan.json", "w") as fh:
        json.dump(plan, fh)
    print("SHARDPLAN " + json.dumps(plan))


if __name__ == "__main__":
    main()
