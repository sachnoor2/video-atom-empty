"""Cost probe: time one real frame of one real shot under different settings, so
the render budget is set from measurements instead of guesses.

Run: python blender/probe_cost.py --shot 0 --samples 16
Writes probe/cost.json and one PNG per variant.
"""
import argparse
import importlib.util
import json
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))


def load_builder():
    spec = importlib.util.spec_from_file_location("build_scenes",
                                                  os.path.join(HERE, "build_scenes.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VARIANTS = [
    ("full", {}),
    ("noglare", {"glare": False}),
    ("nomblur", {"mblur": False}),
    ("nodof", {"dof": False}),
    ("lean", {"glare": False, "mblur": True, "dof": True, "bounces": 3}),
]


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--shotlist", default="shotlist.json")
    ap.add_argument("--shot", type=int, default=0)
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--out", default="probe")
    args = ap.parse_args(argv)

    with open(args.shotlist) as fh:
        shot = json.load(fh)["shots"][args.shot]
    bs = load_builder()
    os.makedirs(args.out, exist_ok=True)
    results = []
    for name, flags in VARIANTS:
        bs.reset(samples=args.samples, f0=shot["start"], f1=shot["end"])
        bs.BUILDERS[args.shot](shot["start"], shot["end"])
        sc = bpy.context.scene
        if not flags.get("glare", True):
            sc.compositing_node_group = None
        if not flags.get("mblur", True):
            sc.render.use_motion_blur = False
        if not flags.get("dof", True):
            sc.camera.data.dof.use_dof = False
        if flags.get("bounces"):
            sc.cycles.max_bounces = flags["bounces"]
            sc.cycles.transmission_bounces = flags["bounces"]
            sc.cycles.transparent_max_bounces = flags["bounces"]
        sc.frame_set(shot["start"] + 10)
        sc.render.filepath = os.path.abspath(os.path.join(args.out, f"cost_{name}.png"))
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        dt = time.time() - t0
        results.append({"variant": name, "seconds": round(dt, 2), "flags": flags})
        print(f"COST {shot['id']} {name} {dt:.1f}s", flush=True)
    with open(os.path.join(args.out, "cost.json"), "w") as fh:
        json.dump({"shot": shot["id"], "samples": args.samples, "results": results}, fh, indent=2)
    print("COSTJSON " + json.dumps(results))


if __name__ == "__main__":
    main()
