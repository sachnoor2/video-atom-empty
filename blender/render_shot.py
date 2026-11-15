"""Render shots (or an absolute frame range) as a PNG sequence, building each
scene in-process.

The scene for a shot is rebuilt from blender/build_scenes.py rather than opened
from a .blend: in the bpy module a file reload tears down the running script, and
rebuilding is a few seconds either way.

Run:
  python blender/render_shot.py --shotlist shotlist.json --out frames --from 0 --to 69
  python blender/render_shot.py --shotlist shotlist.json --out preview --shots 3 --preview 2
"""
import argparse
import importlib.util
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def load_builder():
    spec = importlib.util.spec_from_file_location("build_scenes",
                                                  os.path.join(HERE, "build_scenes.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--shotlist", default="shotlist.json")
    ap.add_argument("--out", default="out/frames")
    ap.add_argument("--shots", default="")
    ap.add_argument("--from", dest="frm", type=int, default=None)
    ap.add_argument("--to", dest="to", type=int, default=None)
    ap.add_argument("--samples", type=int, default=0)
    ap.add_argument("--preview", type=int, default=0,
                    help="render N evenly spaced frames per shot instead of the full range")
    args = ap.parse_args(argv)

    with open(args.shotlist) as fh:
        shots = json.load(fh)["shots"]
    os.makedirs(args.out, exist_ok=True)
    bs = load_builder()

    if args.frm is not None:
        lo = args.frm
        hi = args.to if args.to is not None else shots[-1]["end"]
        todo = []
        for idx, shot in enumerate(shots):
            a, b = max(shot["start"], lo), min(shot["end"], hi)
            if a <= b:
                todo.append((idx, shot, list(range(a, b + 1))))
    else:
        want = ([int(x) for x in args.shots.split(",") if x.strip() != ""]
                if args.shots else list(range(len(shots))))
        todo = []
        for idx in want:
            shot = shots[idx]
            if args.preview:
                span = shot["end"] - shot["start"]
                frames = sorted({shot["start"] + int(round(span * k / max(args.preview - 1, 1)))
                                 for k in range(args.preview)})
            else:
                frames = list(range(shot["start"], shot["end"] + 1))
            todo.append((idx, shot, frames))

    import bpy
    for idx, shot, frames in todo:
        samples = args.samples or shot.get("samples", 48)
        bs.reset(samples=samples, f0=shot["start"], f1=shot["end"])
        bs.BUILDERS[idx](shot["start"], shot["end"])
        sc = bpy.context.scene
        sc.render.use_persistent_data = True
        times = []
        for f in frames:
            t0 = time.time()
            sc.frame_set(f)
            name = (f"preview_{shot['id']}_{f:06d}.png" if args.preview
                    else f"frame_{f:06d}.png")
            sc.render.filepath = os.path.join(os.path.abspath(args.out), name)
            bpy.ops.render.render(write_still=True)
            times.append(time.time() - t0)
            print(f"RENDER {shot['id']} frame {f} {times[-1]:.2f}s", flush=True)
        ordered = sorted(times)
        med = ordered[len(ordered) // 2] if ordered else 0.0
        print(f"BENCH {shot['id']} frames={len(times)} median_s_per_frame={med:.2f}", flush=True)


if __name__ == "__main__":
    main()
