# Why Solid Things Are Almost Empty

A 3D short: every frame of every shot is a Blender animation, rendered by Cycles on CPU as an
absolute-numbered PNG sequence, then cut in Remotion.

- 720 × 1280, 30 fps, 12 shots, English narration (Kokoro `am_michael`).
- Shot lengths are derived from the measured narration audio, never typed by hand.
- Blender is pinned to the same version locally and on the runner (`bpy==5.0.1`), so a scene that
  builds here renders there.

## Run it

Workflow `render` (`workflow_dispatch`):

- `mode: preview` — two frames per shot at 16 samples, one matrix job per shot. Use this to check the
  look before spending render time.
- `mode: full` — Kokoro narration → measured manifest → shot list → foley → one Cycles shard per shot
  → frame verification → Remotion assembly → ffprobe QA → release asset.

## Local

```bash
python -m pip install --python-version 3.11 --only-binary=:all: --target ./bpy311 bpy==5.0.1
PYTHONPATH=./bpy311 python3.11 blender/build_scenes.py --shotlist shotlist.json --out scenes
PYTHONPATH=./bpy311 python3.11 blender/render_shot.py --shotlist shotlist.json --out frames --shots 0
```

`blender/build_scenes.py` holds one builder per shot; `BUILDERS` order must match `narration.json`.
