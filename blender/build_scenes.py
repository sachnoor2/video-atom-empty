"""Procedurally build every Blender shot for the atom short.

Every shot is a real animation: camera move + subject motion + secondary motion +
light change. Frames are numbered ABSOLUTELY across the film, so each scene is
built with its own absolute frame range from shotlist.json.

Run: python blender/build_scenes.py --shotlist shotlist.json --out scenes
"""
import argparse
import json
import math
import os

import bpy
from mathutils import Vector

# ---------------------------------------------------------------- palette
BG = (0.006, 0.010, 0.020)
CYAN = (0.10, 0.72, 0.90)
DEEP_CYAN = (0.020, 0.230, 0.330)
MAGENTA = (0.86, 0.28, 0.86)
DEEP_MAGENTA = (0.300, 0.045, 0.330)
AMBER = (0.98, 0.62, 0.22)
BONE = (0.94, 0.93, 0.90)
INK = (0.012, 0.018, 0.030)


# ---------------------------------------------------------------- helpers
def set_in(node, names, value):
    for n in names:
        if n in node.inputs:
            try:
                node.inputs[n].default_value = value
                return True
            except Exception:
                pass
    return False


def make_mat(name, base=(0.5, 0.5, 0.5), rough=0.32, metal=0.0, emit=None,
             emit_strength=0.0, alpha=1.0, transmission=0.0, coat=0.0, ior=1.45):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    set_in(b, ["Base Color"], (*base, 1.0))
    set_in(b, ["Roughness"], rough)
    set_in(b, ["Metallic"], metal)
    set_in(b, ["IOR"], ior)
    set_in(b, ["Alpha"], alpha)
    set_in(b, ["Coat Weight", "Clearcoat"], coat)
    set_in(b, ["Coat Roughness"], 0.06)
    set_in(b, ["Transmission Weight", "Transmission"], transmission)
    if emit is not None:
        set_in(b, ["Emission Color", "Emission"], (*emit, 1.0))
        set_in(b, ["Emission Strength"], emit_strength)
    if alpha < 1.0:
        try:
            m.surface_render_method = "BLENDED"
        except Exception:
            try:
                m.blend_method = "BLEND"
            except Exception:
                pass
    m.use_backface_culling = False
    return m


def fresnel_mat(name, color, strength=8.0, power=2.6, alpha=0.0):
    """Transparent in the middle, glowing at the silhouette: an atom's edge, and
    nothing else. A tinted glass ball would hide the emptiness the video is about."""
    m = bpy.data.materials.get(name)
    if m:
        return m
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
    nt.links.new(lw.outputs["Facing"], pw.inputs[0])
    nt.links.new(pw.outputs[0], mix.inputs["Fac"])
    nt.links.new(trans.outputs[0], mix.inputs[1])
    nt.links.new(emis.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    try:
        m.surface_render_method = "BLENDED"
    except Exception:
        pass
    m.use_backface_culling = False
    return m


def smooth(ob):
    if ob.type != "MESH":
        return ob
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def sphere(name, r, loc, mat, subdiv=3, scale=None):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subdiv, radius=r, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    ob.data.materials.append(mat)
    if scale:
        ob.scale = scale
    return smooth(ob)


def torus(name, R, r, loc, mat, rot=(0, 0, 0), segs=96):
    bpy.ops.mesh.primitive_torus_add(major_radius=R, minor_radius=r, location=loc,
                                     major_segments=segs, minor_segments=8)
    ob = bpy.context.active_object
    ob.name = name
    ob.rotation_euler = rot
    ob.data.materials.append(mat)
    return smooth(ob)


def plane(name, size, loc, mat, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_plane_add(size=size, location=loc, rotation=rot)
    ob = bpy.context.active_object
    ob.name = name
    ob.data.materials.append(mat)
    return ob


def fcurves_of(ob):
    """Blender 5.x keeps fcurves in action layers/channelbags; 4.x does not."""
    ad = getattr(ob, "animation_data", None)
    if not ad or not ad.action:
        return []
    act = ad.action
    if hasattr(act, "fcurves"):
        return list(act.fcurves)
    out = []
    for layer in act.layers:
        for strip in layer.strips:
            for cb in strip.channelbags:
                out.extend(cb.fcurves)
    return out


def ease(ob, interp="BEZIER", easing="EASE_IN_OUT"):
    """Every keyframe eased: linear interpolation is the tell of a cheap render."""
    for fc in fcurves_of(ob):
        for kp in fc.keyframe_points:
            kp.interpolation = interp
            if interp == "BEZIER":
                kp.easing = easing
                kp.handle_left_type = "AUTO_CLAMPED"
                kp.handle_right_type = "AUTO_CLAMPED"
        fc.update()


def look_at(ob, target):
    d = Vector(target) - ob.location
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def add_camera(loc, target, lens=55.0, fstop=2.0, focus=None):
    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = loc
    look_at(cam, target)
    cam_data.lens = lens
    cam_data.sensor_width = 36.0
    cam_data.dof.use_dof = True
    cam_data.dof.aperture_fstop = fstop
    cam_data.dof.aperture_blades = 7
    if focus is not None:
        cam_data.dof.focus_distance = focus
    bpy.context.scene.camera = cam
    return cam


def cam_keys(cam, keys):
    """keys: [(frame, loc, target)] — one continuous move, eased."""
    for f, loc, target in keys:
        cam.location = loc
        look_at(cam, target)
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)
    ease(cam)


def focus_keys(cam, keys):
    for f, d in keys:
        cam.data.dof.focus_distance = d
        cam.data.dof.keyframe_insert("focus_distance", frame=f)


def area_light(loc, target, size, energy, color):
    d = bpy.data.lights.new("Area", type="AREA")
    d.shape = "DISK"
    d.size = size
    d.energy = energy
    d.color = color
    ob = bpy.data.objects.new("Area", d)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    look_at(ob, target)
    return ob


def point_light(loc, energy, color, radius=0.4):
    d = bpy.data.lights.new("Point", type="POINT")
    d.energy = energy
    d.color = color
    d.shadow_soft_size = radius
    ob = bpy.data.objects.new("Point", d)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    return ob


def light_flicker(light, f0, f1, base, amp, phase=0.0, nkeys=6):
    for i in range(nkeys):
        t = f0 + (f1 - f0) * i / (nkeys - 1)
        light.data.energy = base * (1.0 + amp * math.sin(phase + i * 1.7))
        light.data.keyframe_insert("energy", frame=int(round(t)))
    light.data.energy = base
    ease(light)


def jitter(ob, f0, f1, amp, phase, nkeys=5, axis=(1, 1, 1)):
    base = ob.location.copy()
    for i in range(nkeys):
        t = f0 + (f1 - f0) * i / (nkeys - 1)
        ob.location = base + Vector((
            amp * axis[0] * math.sin(phase + i * 2.1),
            amp * axis[1] * math.sin(phase * 1.3 + i * 1.4),
            amp * axis[2] * math.sin(phase * 0.7 + i * 2.7),
        ))
        ob.keyframe_insert("location", frame=int(round(t)))
    ob.location = base
    ease(ob)


def spin(ob, f0, f1, turns=1.0, axis="Z"):
    idx = {"X": 0, "Y": 1, "Z": 2}[axis]
    a0 = ob.rotation_euler[idx]
    for frac in (0.0, 0.5, 1.0):
        ob.rotation_euler[idx] = a0 + turns * 2 * math.pi * frac
        ob.keyframe_insert("rotation_euler", frame=int(round(f0 + (f1 - f0) * frac)))
    ob.rotation_euler[idx] = a0
    ease(ob)


def pulse(ob, f0, f1, amp=0.06, nkeys=6, phase=0.0):
    base = ob.scale.copy()
    for i in range(nkeys):
        t = f0 + (f1 - f0) * i / (nkeys - 1)
        ob.scale = base * (1.0 + amp * math.sin(phase + i * 1.9))
        ob.keyframe_insert("scale", frame=int(round(t)))
    ob.scale = base
    ease(ob)


def dust(f0, f1, n=10, spread=6.0, r=0.02, mat=None, z0=-1.0, z1=3.0):
    """Floating motes: secondary motion in every shot."""
    mat = mat or make_mat("dust", base=(0.55, 0.75, 0.9), rough=0.5,
                          emit=(0.55, 0.85, 1.0), emit_strength=2.0)
    for i in range(n):
        a = (i * 2.399963) % (2 * math.pi)
        rad = spread * (0.25 + ((i * 0.618) % 1.0))
        z = z0 + (z1 - z0) * (((i * 0.37) % 1.0))
        ob = sphere(f"dust{i}", r, (rad * math.cos(a), rad * math.sin(a), z), mat, subdiv=1)
        jitter(ob, f0, f1, amp=spread * 0.05, phase=i * 0.9, nkeys=4)


def fg_bokeh(cam, f0, f1, dist, r, n=2):
    """Dark shapes just off the lens: the depth signature of every shot."""
    mat = make_mat("fgblur", base=(0.006, 0.012, 0.020), rough=0.9,
                   emit=(0.02, 0.10, 0.16), emit_strength=0.25)
    spots = [(1.25, 0.95, -dist), (-1.35, -1.05, -dist * 1.2), (0.35, -1.35, -dist * 0.85)]
    for i in range(min(n, len(spots))):
        ob = sphere(f"fgbokeh{i}", r * (0.85 + 0.3 * i), spots[i], mat, subdiv=2)
        ob.parent = cam
        ob.matrix_parent_inverse = cam.matrix_world.inverted()
        ob.location = spots[i]
        jitter(ob, f0, f1, amp=r * 0.2, phase=i * 1.7, nkeys=4)


def setup_render(f0, f1, samples=48):
    sc = bpy.context.scene
    sc.frame_start = f0
    sc.frame_end = f1
    sc.render.resolution_x = 720
    sc.render.resolution_y = 1280
    sc.render.resolution_percentage = 100
    sc.render.fps = 30
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.compression = 60
    sc.render.use_motion_blur = True
    sc.render.motion_blur_shutter = 0.35
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.05
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    # OIDN's GPU path wants an EGL context; headless CPU runners have none.
    for attr in ("denoising_use_gpu", "preview_denoising_use_gpu"):
        try:
            setattr(sc.cycles, attr, False)
        except Exception:
            pass
    sc.cycles.max_bounces = 4
    sc.cycles.transmission_bounces = 4
    sc.cycles.transparent_max_bounces = 4
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.cycles.seed = 7
    sc.cycles.use_animated_seed = False
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Punchy"
    except Exception:
        pass
    sc.view_settings.exposure = -0.25


def setup_world(color=BG, strength=0.18):
    w = bpy.data.worlds.new("W")
    bpy.context.scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (*color, 1.0)
    bg.inputs[1].default_value = strength


def add_glare(threshold=1.0, size=0.55, strength=0.32):
    """Bloom, so the emissive cores glow the way the reference look does."""
    sc = bpy.context.scene
    if hasattr(sc, "compositing_node_group"):
        nt = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
        sc.compositing_node_group = nt
    else:
        sc.use_nodes = True
        nt = sc.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rl = nt.nodes.new("CompositorNodeRLayers")
    gl = nt.nodes.new("CompositorNodeGlare")
    if "Type" in gl.inputs:          # Blender 5.x: glare settings are node inputs
        gl.inputs["Type"].default_value = "Fog Glow"
        gl.inputs["Quality"].default_value = "High"
        gl.inputs["Threshold"].default_value = threshold
        gl.inputs["Size"].default_value = size
        gl.inputs["Strength"].default_value = strength
    else:                            # Blender 4.x
        gl.glare_type = "FOG_GLOW"
        gl.quality = "HIGH"
        gl.threshold = threshold
        gl.size = 8
        gl.mix = -0.35
    if "CompositorNodeComposite" in dir(bpy.types):
        comp = nt.nodes.new("CompositorNodeComposite")
        nt.links.new(rl.outputs["Image"], gl.inputs["Image"])
        nt.links.new(gl.outputs["Image"], comp.inputs["Image"])
    else:                            # Blender 5.x: the tree is a node group
        nt.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        comp = nt.nodes.new("NodeGroupOutput")
        nt.links.new(rl.outputs["Image"], gl.inputs["Image"])
        nt.links.new(gl.outputs["Image"], comp.inputs[0])


def wipe():
    """Empty the file without read_factory_settings: in the bpy module that call
    re-enters the module's own initialiser, which is a hard crash."""
    sc = bpy.context.scene
    try:
        sc.compositing_node_group = None
    except Exception:
        pass
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.curves, bpy.data.materials,
                 bpy.data.cameras, bpy.data.lights, bpy.data.node_groups, bpy.data.actions,
                 bpy.data.worlds, bpy.data.images, bpy.data.collections):
        for item in list(coll):
            try:
                coll.remove(item)
            except Exception:
                pass


def reset(samples=20, f0=0, f1=90):
    wipe()
    try:
        bpy.context.preferences.edit.keyframe_new_interpolation_type = "BEZIER"
        bpy.context.preferences.edit.keyframe_new_handle_type = "AUTO_CLAMPED"
    except Exception:
        pass
    setup_world()
    setup_render(f0, f1, samples)


# ---------------------------------------------------------------- elements
def nucleon_cluster(f0, f1, radius=0.85, count=14, nuc_r=0.28, glow=0.55):
    """A nucleus: protons deep cyan, neutrons deep magenta, all jiggling."""
    mp = make_mat("proton", base=(0.012, 0.105, 0.165), rough=0.16, coat=0.35,
                  emit=CYAN, emit_strength=glow * 0.16)
    mn = make_mat("neutron", base=(0.150, 0.020, 0.195), rough=0.18, coat=0.35,
                  emit=MAGENTA, emit_strength=glow * 0.13)
    grp = bpy.data.objects.new("cluster", None)
    bpy.context.scene.collection.objects.link(grp)
    for i in range(count):
        a = i * 2.399963
        rr = radius * (0.30 + 0.62 * ((i * 0.618) % 1.0))
        z = radius * 0.62 * math.cos(i * 1.7)
        loc = (rr * math.cos(a), rr * math.sin(a), z)
        ob = sphere(f"nuc{i}", nuc_r * (0.84 + 0.26 * ((i * 0.29) % 1.0)), loc,
                    mp if i % 2 == 0 else mn, subdiv=3)
        ob.parent = grp
        ob.matrix_parent_inverse = grp.matrix_world.inverted()
        ob.location = loc
        jitter(ob, f0, f1, amp=nuc_r * 0.2, phase=i * 1.1, nkeys=4)
    spin(grp, f0, f1, turns=0.3, axis="Z")
    return grp


def electron_cloud(f0, f1, radius=2.4, count=64, size=0.024, glow=3.2, shells=(0.84, 1.0)):
    mat = make_mat("electron", base=(0.35, 0.9, 1.0), rough=0.2,
                   emit=(0.55, 0.92, 1.0), emit_strength=glow)
    grp = bpy.data.objects.new("cloud", None)
    bpy.context.scene.collection.objects.link(grp)
    for i in range(count):
        u = (i * 0.7548776662) % 1.0
        v = (i * 0.5698402910) % 1.0
        th = 2 * math.pi * u
        ph = math.acos(1 - 2 * v)
        r = radius * (shells[0] + (shells[1] - shells[0]) * ((i * 0.37) % 1.0))
        loc = (r * math.sin(ph) * math.cos(th), r * math.sin(ph) * math.sin(th),
               r * math.cos(ph) * 0.9)
        ob = sphere(f"e{i}", size * (0.75 + 0.5 * ((i * 0.11) % 1.0)), loc, mat, subdiv=2)
        ob.parent = grp
        ob.matrix_parent_inverse = grp.matrix_world.inverted()
        ob.location = loc
        jitter(ob, f0, f1, amp=radius * 0.06, phase=i * 0.7, nkeys=4)
    spin(grp, f0, f1, turns=0.5, axis="Z")
    return grp


def atom_shell(radius, color=CYAN, name="shell", strength=7.0, power=2.6):
    return sphere(name, radius, (0, 0, 0),
                  fresnel_mat(name + "m", color, strength=strength, power=power), subdiv=4)


# ---------------------------------------------------------------- shots
def lattice(f0, f1, n=7, depth=3, radius=0.54, step=1.03, xray=False):
    if xray:
        m_atom = fresnel_mat("atomglass", CYAN, strength=5.0, power=2.2)
        m_core = make_mat("core", base=BONE, rough=0.2, emit=(1.0, 0.86, 0.62),
                          emit_strength=4.0)
    else:
        m_atom = make_mat("atomskin", base=(0.045, 0.115, 0.150), rough=0.28, metal=0.25,
                          coat=0.8, emit=(0.05, 0.30, 0.40), emit_strength=0.20)
        m_core = None
    for i in range(n):
        for j in range(n):
            for k in range(depth):
                x = (i - (n - 1) / 2) * step
                y = (j - (n - 1) / 2) * step
                z = (k - (depth - 1) / 2) * step
                ob = sphere(f"at{i}{j}{k}", radius, (x, y, z), m_atom, subdiv=3)
                jitter(ob, f0, f1, amp=0.04, phase=(i * 1.3 + j * 2.1 + k * 0.7), nkeys=5)
                if m_core:
                    c = sphere(f"co{i}{j}{k}", 0.07, (x, y, z), m_core, subdiv=2)
                    c.parent = ob
                    c.matrix_parent_inverse = ob.matrix_world.inverted()
                    c.location = (0, 0, 0)
                    pulse(c, f0, f1, amp=0.25, nkeys=6, phase=i + j + k)
    return m_atom


def shot_table(f0, f1):
    """01 — solid matter up close: a packed crystal wall of atoms."""
    lattice(f0, f1, n=5, depth=7, step=1.05)
    key = area_light((3.4, -9.0, 3.0), (0, 0, 0), 3.0, 900, (0.62, 0.88, 1.0))
    rim = area_light((-3.6, 1.4, -1.6), (0, 0, 0), 3.4, 700, (1.0, 0.55, 0.28))
    top = area_light((0.0, -6.0, 5.0), (0, 0, 0), 4.0, 420, (0.75, 0.9, 1.0))
    light_flicker(key, f0, f1, 900, 0.05, 0.3)
    light_flicker(rim, f0, f1, 700, 0.09, 1.1)
    dust(f0, f1, n=18, spread=3.2, r=0.012, z0=-1.4, z1=1.6)
    cam = add_camera((0.0, -13.0, 0.5), (0, 0, 0), lens=45, fstop=2.2, focus=9.4)
    cam_keys(cam, [(f0, (0.0, -13.0, 0.5), (0, 0, 0)),
                   (f1, (0.25, -9.4, 0.15), (0, 0.4, 0))])
    focus_keys(cam, [(f0, 9.4), (f1, 5.9)])
    fg_bokeh(cam, f0, f1, dist=0.9, r=0.12)
    return cam


def shot_empty(f0, f1):
    """02 — the same matter, x-ray: dive between the atoms."""
    lattice(f0, f1, n=5, depth=3, step=1.15, xray=True)
    key = area_light((2.6, -3.4, 2.4), (0, 0, 0), 2.6, 240, (0.6, 0.86, 1.0))
    rim = area_light((-2.8, 1.8, -1.2), (0, 0, 0), 3.0, 220, (1.0, 0.58, 0.3))
    light_flicker(key, f0, f1, 240, 0.07, 0.6)
    light_flicker(rim, f0, f1, 220, 0.1, 1.9)
    dust(f0, f1, n=20, spread=2.8, r=0.014, z0=-1.2, z1=1.4)
    cam = add_camera((0.0, -10.5, 0.5), (0, 0, 0), lens=50, fstop=2.0, focus=7.0)
    cam_keys(cam, [(f0, (0.0, -10.5, 0.5), (0, 0, 0)),
                   (f1, (0.22, 0.9, 0.10), (0, 2.4, 0))])
    focus_keys(cam, [(f0, 7.0), (f1, 1.4)])
    fg_bokeh(cam, f0, f1, dist=0.85, r=0.11)
    return cam


def shot_nucleus(f0, f1):
    """03 — the nucleus itself: the whole atom's mass in one speck."""
    nucleon_cluster(f0, f1, radius=0.60, count=15, nuc_r=0.195, glow=1.1)
    atom_shell(1.30, color=CYAN, name="halo", strength=1.8, power=2.6)
    key = area_light((1.9, -2.3, 1.9), (0, 0, 0), 1.8, 210, (0.66, 0.9, 1.0))
    rim = area_light((-2.1, 1.3, -1.5), (0, 0, 0), 2.2, 260, (1.0, 0.5, 0.26))
    light_flicker(key, f0, f1, 210, 0.06, 0.5)
    light_flicker(rim, f0, f1, 260, 0.11, 2.0)
    dust(f0, f1, n=16, spread=1.8, r=0.011)
    cam = add_camera((-2.2, -3.3, 0.7), (0, 0, 0), lens=52, fstop=1.8, focus=4.0)
    cam_keys(cam, [(f0, (-2.2, -3.3, 0.7), (0, 0, 0)),
                   (f1, (2.0, -2.9, -0.35), (0, 0, 0))])
    focus_keys(cam, [(f0, 4.0), (f1, 3.6)])
    fg_bokeh(cam, f0, f1, dist=0.7, r=0.10)
    return cam


def shot_pullback(f0, f1):
    """04 — a hundred thousand times smaller: pull back to the whole atom."""
    nucleon_cluster(f0, f1, radius=0.11, count=12, nuc_r=0.038, glow=1.1)
    atom_shell(2.45, color=CYAN, name="shell", strength=4.2, power=3.2)
    electron_cloud(f0, f1, radius=2.4, count=72, size=0.022, glow=3.4)
    key = area_light((3.0, -3.2, 2.8), (0, 0, 0), 3.2, 340, (0.62, 0.88, 1.0))
    rim = area_light((-3.2, 1.9, -1.9), (0, 0, 0), 3.4, 300, (1.0, 0.52, 0.28))
    light_flicker(key, f0, f1, 340, 0.05, 0.2)
    light_flicker(rim, f0, f1, 300, 0.09, 1.4)
    dust(f0, f1, n=20, spread=3.2, r=0.018)
    cam = add_camera((0.0, -0.72, 0.12), (0, 0, 0), lens=38, fstop=2.0, focus=0.73)
    cam_keys(cam, [(f0, (0.0, -0.72, 0.12), (0, 0, 0)),
                   (f1, (1.1, -8.2, 1.35), (0, 0, 0))])
    focus_keys(cam, [(f0, 0.73), (f1, 8.3)])
    fg_bokeh(cam, f0, f1, dist=0.5, r=0.07)
    return cam


def shot_marble(f0, f1):
    """05 — marble to kilometre: the scale dive, on a real ground grid."""
    marble = make_mat("marble", base=(0.95, 0.95, 0.96), rough=0.06, coat=1.0,
                      emit=(0.90, 0.94, 1.0), emit_strength=30.0)
    m = sphere("marble", 1.0, (0, 0, 1.0), marble, subdiv=4)
    spin(m, f0, f1, turns=1.2, axis="Z")

    sphere("dome", 600.0, (0, 0, 0),
           fresnel_mat("domem", CYAN, strength=7.0, power=3.2), subdiv=4)

    grid_mat = make_mat("grid", base=(0.02, 0.05, 0.07), rough=0.55)
    p = plane("ground", 4000, (0, 0, 0), grid_mat)
    tex = p.data.materials[0].node_tree
    chk = tex.nodes.new("ShaderNodeTexChecker")
    chk.inputs["Scale"].default_value = 100.0
    chk.inputs["Color1"].default_value = (0.010, 0.030, 0.045, 1)
    chk.inputs["Color2"].default_value = (0.055, 0.230, 0.300, 1)
    bsdf = tex.nodes["Principled BSDF"]
    tex.links.new(chk.outputs["Color"], bsdf.inputs["Base Color"])
    tex.links.new(chk.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 0.30

    ring = torus("rim", 600.0, 4.0, (0, 0, 3.0),
                 make_mat("ring", base=(1.0, 0.62, 0.25), rough=0.3,
                          emit=(1.0, 0.55, 0.22), emit_strength=3.0))
    pulse(ring, f0, f1, amp=0.004, nkeys=4)

    sun = area_light((350, -420, 620), (0, 0, 0), 320, 260000, (0.72, 0.88, 1.0))
    light_flicker(sun, f0, f1, 260000, 0.04, 0.4)
    point_light((0, -4, 5), 260, (1.0, 0.82, 0.6), radius=1.6)
    dust(f0, f1, n=12, spread=70.0, r=1.4, z0=3.0, z1=60.0)

    cam = add_camera((0.0, -15.0, 4.2), (0, 0, 1.2), lens=40, fstop=2.2, focus=15.1)
    cam_keys(cam, [(f0, (0.0, -15.0, 4.2), (0, 0, 1.2)),
                   (f1, (0.0, -540.0, 290.0), (0, 0, 60.0))])
    focus_keys(cam, [(f0, 15.1), (f1, 570.0)])
    return cam


def shot_crosssection(f0, f1):
    """06 — cut the atom open: almost all of it is nothing."""
    s = atom_shell(2.55, color=CYAN, name="cut", strength=4.2, power=3.2)
    bpy.ops.mesh.primitive_cube_add(size=6.0, location=(0, 3.1, 0))
    cutter = bpy.context.active_object
    cutter.name = "cutter"
    mod = s.modifiers.new("cut", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    cutter.hide_render = True
    cutter.hide_viewport = True
    # a bright ring where the cut lands, so the section reads
    ring = torus("cutring", 2.55, 0.012, (0, 0, 0),
                 make_mat("cutringm", base=(0.5, 0.95, 1.0), rough=0.2,
                          emit=(0.45, 0.95, 1.0), emit_strength=6.0),
                 rot=(math.radians(90), 0, 0))
    pulse(ring, f0, f1, amp=0.004, nkeys=4)

    nucleon_cluster(f0, f1, radius=0.095, count=12, nuc_r=0.032, glow=1.2)
    electron_cloud(f0, f1, radius=2.5, count=54, size=0.020, glow=3.2, shells=(0.93, 1.0))
    key = area_light((2.6, -2.0, 2.2), (0, 0, 0), 2.8, 300, (0.62, 0.88, 1.0))
    rim = area_light((-2.8, -0.8, -2.0), (0, 0, 0), 3.0, 260, (1.0, 0.5, 0.26))
    light_flicker(key, f0, f1, 300, 0.06, 0.9)
    light_flicker(rim, f0, f1, 260, 0.09, 1.9)
    dust(f0, f1, n=16, spread=3.0, r=0.016)
    cam = add_camera((-4.6, -8.4, 1.8), (0, 0, 0), lens=40, fstop=2.0, focus=9.6)
    cam_keys(cam, [(f0, (-4.6, -8.4, 1.8), (0, 0, 0)),
                   (f1, (4.2, -9.6, 0.5), (0, 0, 0))])
    focus_keys(cam, [(f0, 9.6), (f1, 10.5)])
    fg_bokeh(cam, f0, f1, dist=0.8, r=0.12)
    return cam


def shot_core(f0, f1):
    """07 — almost all the mass sits in that tiny core."""
    nucleon_cluster(f0, f1, radius=0.46, count=18, nuc_r=0.165, glow=1.0)
    dense = make_mat("dense", base=(1.0, 0.88, 0.66), rough=0.12,
                     emit=(1.0, 0.72, 0.38), emit_strength=2.2)
    c = sphere("core", 0.22, (0, 0, 0), dense, subdiv=3)
    pulse(c, f0, f1, amp=0.12, nkeys=7, phase=0.4)
    key = area_light((1.5, -1.7, 1.4), (0, 0, 0), 1.5, 190, (0.66, 0.88, 1.0))
    rim = area_light((-1.6, 1.0, -1.2), (0, 0, 0), 1.8, 230, (1.0, 0.48, 0.24))
    light_flicker(key, f0, f1, 190, 0.08, 0.6)
    light_flicker(rim, f0, f1, 230, 0.12, 2.4)
    dust(f0, f1, n=14, spread=1.4, r=0.009)
    cam = add_camera((0.0, -5.6, 0.6), (0, 0, 0), lens=58, fstop=1.8, focus=5.7)
    cam_keys(cam, [(f0, (0.0, -5.6, 0.6), (0, 0, 0)),
                   (f1, (0.30, -4.2, 0.16), (0, 0, 0))])
    focus_keys(cam, [(f0, 5.7), (f1, 4.3)])
    fg_bokeh(cam, f0, f1, dist=0.6, r=0.09)
    return cam


def shot_fields(f0, f1):
    """08 — the rest is fields, not stuff."""
    nucleon_cluster(f0, f1, radius=0.30, count=10, nuc_r=0.115, glow=1.0)
    line_mat = make_mat("field", base=(0.35, 0.92, 1.0), rough=0.2,
                        emit=(0.30, 0.92, 1.0), emit_strength=2.2)
    for i in range(5):
        a = i * 2 * math.pi / 5
        ring = torus(f"ring{i}", 1.05 + 0.24 * i, 0.0070, (0, 0, 0), line_mat,
                     rot=(math.radians(74), math.radians(11 * i), a))
        k0 = 0.8 + 0.02 * i
        for fr, k in ((f0, k0), (int((f0 + f1) / 2), k0 * 1.12), (f1, k0 * 0.95)):
            ring.scale = (k, k, k)
            ring.keyframe_insert("scale", frame=fr)
        ring.scale = (k0, k0, k0)
        ease(ring)
        spin(ring, f0, f1, turns=0.1 * (1 if i % 2 else -1), axis="Z")
    electron_cloud(f0, f1, radius=1.8, count=32, size=0.026, glow=3.0)
    key = point_light((0, 0, 0), 26, (0.6, 0.95, 1.0), radius=0.25)
    light_flicker(key, f0, f1, 26, 0.2, 0.3, nkeys=8)
    rim = area_light((-2.3, 1.6, 1.4), (0, 0, 0), 2.4, 230, (1.0, 0.52, 0.26))
    light_flicker(rim, f0, f1, 230, 0.08, 1.2)
    dust(f0, f1, n=16, spread=2.2, r=0.012)
    cam = add_camera((-2.8, -3.9, 0.9), (0, 0, 0), lens=44, fstop=2.0, focus=4.7)
    cam_keys(cam, [(f0, (-2.8, -3.9, 0.9), (0, 0, 0)),
                   (f1, (2.0, -4.4, 0.2), (0, 0, 0))])
    focus_keys(cam, [(f0, 4.7), (f1, 4.9)])
    fg_bokeh(cam, f0, f1, dist=0.85, r=0.13)
    return cam


def shot_contact(f0, f1, macro=False):
    """09/10 — two electron clouds refuse to overlap: you never touch anything."""
    R = 0.85
    a_mat = fresnel_mat("cloudA", CYAN, strength=9.0, power=2.9)
    b_mat = fresnel_mat("cloudB", (1.0, 0.52, 0.30), strength=9.0, power=2.9)
    A = sphere("cloudA", R, (-1.95, 0, 0), a_mat, subdiv=4)
    B = sphere("cloudB", R, (1.95, 0, 0), b_mat, subdiv=4)
    for ob, sign in ((A, 1.0), (B, -1.0)):
        for fr, x, sq in ((f0, 1.95, 1.00),
                          (int(f0 + (f1 - f0) * 0.55), 1.44, 0.94),
                          (int(f0 + (f1 - f0) * 0.78), 1.34, 0.86),
                          (f1, 1.44, 0.93)):
            ob.location = (sign * x, 0, 0)
            ob.scale = (R * sq, R / sq, R / sq)
            ob.keyframe_insert("location", frame=fr)
            ob.keyframe_insert("scale", frame=fr)
        ease(ob)
    e_mat = make_mat("e2", base=CYAN, rough=0.2, emit=(0.62, 0.95, 1.0), emit_strength=3.0)
    e2_mat = make_mat("e3", base=(1.0, 0.66, 0.4), rough=0.2,
                      emit=(1.0, 0.6, 0.32), emit_strength=3.0)
    for i in range(34):
        u = (i * 0.7548776662) % 1.0
        v = (i * 0.5698402910) % 1.0
        th = 2 * math.pi * u
        ph = math.acos(1 - 2 * v)
        for ob, mat, side in ((A, e_mat, -1), (B, e2_mat, 1)):
            loc = (side * R * abs(math.sin(ph) * math.cos(th)),
                   R * math.sin(ph) * math.sin(th), R * math.cos(ph))
            e = sphere(f"p{i}{side}", 0.026, loc, mat, subdiv=2)
            e.parent = ob
            e.matrix_parent_inverse = ob.matrix_world.inverted()
            e.location = loc
            jitter(e, f0, f1, amp=0.06, phase=i + side, nkeys=4)
    gap = point_light((0, 0, 0), 45, (1.0, 0.86, 0.66), radius=0.12)
    light_flicker(gap, f0, f1, 45, 0.4, 0.2, nkeys=8)
    key = area_light((0, -3.2, 2.2), (0, 0, 0), 2.8, 300, (0.66, 0.88, 1.0))
    light_flicker(key, f0, f1, 300, 0.06, 0.8)
    rim = area_light((0, 2.8, -1.9), (0, 0, 0), 2.8, 260, (1.0, 0.52, 0.28))
    light_flicker(rim, f0, f1, 260, 0.09, 1.6)
    dust(f0, f1, n=14, spread=2.4, r=0.013)
    if macro:
        cam = add_camera((0.20, -4.6, 0.85), (0, 0, 0), lens=45, fstop=1.6, focus=4.7)
        cam_keys(cam, [(f0, (0.20, -4.6, 0.85), (0, 0, 0)),
                       (f1, (-0.70, -4.9, -0.35), (0, 0, 0))])
        focus_keys(cam, [(f0, 4.7), (f1, 5.0)])
        fg_bokeh(cam, f0, f1, dist=0.45, r=0.07)
    else:
        cam = add_camera((0.6, -12.0, 2.6), (0, 0, 0), lens=50, fstop=2.2, focus=12.3)
        cam_keys(cam, [(f0, (0.6, -12.0, 2.6), (0, 0, 0)),
                       (f1, (-0.4, -10.2, 1.9), (0, 0, 0))])
        focus_keys(cam, [(f0, 12.3), (f1, 10.5)])
        fg_bokeh(cam, f0, f1, dist=0.95, r=0.14)
    return cam


def shot_feeling(f0, f1):
    """11 — solid is a feeling: pull back out of the lattice."""
    lattice(f0, f1, n=5, depth=3, step=1.15, xray=True)
    key = area_light((2.8, -3.0, 2.6), (0, 0, 0), 2.8, 260, (0.6, 0.86, 1.0))
    rim = area_light((-3.0, 1.6, -1.4), (0, 0, 0), 3.0, 230, (1.0, 0.55, 0.28))
    light_flicker(key, f0, f1, 260, 0.06, 0.4)
    light_flicker(rim, f0, f1, 230, 0.1, 1.7)
    dust(f0, f1, n=22, spread=3.0, r=0.014, z0=-1.4, z1=1.6)
    cam = add_camera((0.4, -2.6, 0.3), (0, 1.0, 0), lens=44, fstop=2.2, focus=2.8)
    cam_keys(cam, [(f0, (0.4, -2.6, 0.3), (0, 1.0, 0)),
                   (f1, (-2.6, -16.0, 3.4), (0, 0, 0))])
    focus_keys(cam, [(f0, 2.8), (f1, 16.5)])
    fg_bokeh(cam, f0, f1, dist=0.6, r=0.09)
    return cam


def shot_void(f0, f1):
    """12 — atoms are almost all space: one atom alone in the dark."""
    nucleon_cluster(f0, f1, radius=0.085, count=10, nuc_r=0.028, glow=1.6)
    atom_shell(1.25, color=CYAN, name="voidshell", strength=4.5, power=3.0)
    electron_cloud(f0, f1, radius=1.2, count=54, size=0.014, glow=3.4)
    key = area_light((2.8, -2.8, 2.4), (0, 0, 0), 2.8, 300, (0.6, 0.86, 1.0))
    rim = area_light((-2.8, 2.0, -1.7), (0, 0, 0), 2.8, 260, (1.0, 0.52, 0.28))
    light_flicker(key, f0, f1, 300, 0.06, 0.3)
    light_flicker(rim, f0, f1, 260, 0.1, 1.5)
    dust(f0, f1, n=24, spread=3.4, r=0.018, z0=-1.6, z1=1.8)
    cam = add_camera((-1.9, -5.6, 1.1), (0, 0, 0), lens=45, fstop=2.0, focus=6.0)
    cam_keys(cam, [(f0, (-1.9, -5.6, 1.1), (0, 0, 0)),
                   (f1, (2.1, -5.2, 0.4), (0, 0, 0))])
    focus_keys(cam, [(f0, 6.0), (f1, 5.6)])
    fg_bokeh(cam, f0, f1, dist=0.95, r=0.13)
    return cam


# order must match narration.json
BUILDERS = [
    shot_table,          # 01-table
    shot_empty,          # 02-empty
    shot_nucleus,        # 03-atom
    shot_pullback,       # 04-nucleus
    shot_marble,         # 05-marble
    shot_crosssection,   # 06-percent
    shot_core,           # 07-mass
    shot_fields,         # 08-fields
    lambda f0, f1: shot_contact(f0, f1, macro=False),   # 09-touch
    lambda f0, f1: shot_contact(f0, f1, macro=True),    # 10-push
    shot_feeling,        # 11-feeling
    shot_void,           # 12-space
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shotlist", default="shotlist.json")
    ap.add_argument("--out", default="scenes")
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    with open(args.shotlist) as fh:
        shots = json.load(fh)["shots"]
    if len(shots) != len(BUILDERS):
        raise SystemExit(f"shotlist has {len(shots)} shots, {len(BUILDERS)} builders")

    os.makedirs(args.out, exist_ok=True)
    for i, (shot, build) in enumerate(zip(shots, BUILDERS)):
        if args.only and str(i) not in args.only.split(","):
            continue
        reset(samples=args.samples, f0=shot["start"], f1=shot["end"])
        build(shot["start"], shot["end"])
        path = os.path.join(args.out, f"{shot['id']}.blend")
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(path))
        print(f"built {path}  frames {shot['start']}-{shot['end']}")


if __name__ == "__main__":
    main()
