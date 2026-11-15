"""Material probe: render three shell variants side by side so the rim formula is
confirmed by a picture, not by an argument about what 'Facing' means.

Run: python blender/probe.py --out probe/probe.png
"""
import argparse
import importlib.util
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))


def load_builder():
    spec = importlib.util.spec_from_file_location("build_scenes",
                                                  os.path.join(HERE, "build_scenes.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def shell_mat(name, color, strength, power, mode):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    mix = nt.nodes.new("ShaderNodeMixShader")
    trans = nt.nodes.new("ShaderNodeBsdfTransparent")
    emis = nt.nodes.new("ShaderNodeEmission")
    emis.inputs["Color"].default_value = (*color, 1.0)
    emis.inputs["Strength"].default_value = strength
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.5
    pw = nt.nodes.new("ShaderNodeMath")
    pw.operation = "POWER"
    pw.inputs[1].default_value = power
    if mode == "facing_inverted":
        inv = nt.nodes.new("ShaderNodeMath")
        inv.operation = "SUBTRACT"
        inv.inputs[0].default_value = 1.0
        nt.links.new(lw.outputs["Facing"], inv.inputs[1])
        nt.links.new(inv.outputs[0], pw.inputs[0])
    elif mode == "facing":
        nt.links.new(lw.outputs["Facing"], pw.inputs[0])
    else:  # "fresnel"
        nt.links.new(lw.outputs["Fresnel"], pw.inputs[0])
    nt.links.new(pw.outputs[0], mix.inputs["Fac"])
    nt.links.new(trans.outputs[0], mix.inputs[1])
    nt.links.new(emis.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return m


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="probe/probe.png")
    ap.add_argument("--samples", type=int, default=12)
    args = ap.parse_args(argv)

    bs = load_builder()
    bs.wipe()
    bs.setup_world()
    bs.setup_render(0, 0, args.samples)
    sc = bpy.context.scene
    sc.render.resolution_x = 300
    sc.render.resolution_y = 420

    for i, mode in enumerate(("facing_inverted", "facing", "fresnel")):
        mat = shell_mat(f"probe_{mode}", bs.CYAN, 6.0, 2.4, mode)
        bs.sphere(f"s{i}", 0.7, ((i - 1) * 1.7, 0, 0), mat, subdiv=4)

    bs.area_light((2.0, -3.0, 2.0), (0, 0, 0), 2.0, 120, (0.7, 0.9, 1.0))
    cam = bs.add_camera((0.0, -6.5, 0.0), (0, 0, 0), lens=50, fstop=8.0, focus=6.5)
    cam.data.dof.use_dof = False

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    sc.render.filepath = os.path.abspath(args.out)
    bpy.ops.render.render(write_still=True)
    print(f"PROBE wrote {args.out}: left=facing_inverted  middle=facing  right=fresnel")


if __name__ == "__main__":
    main()
