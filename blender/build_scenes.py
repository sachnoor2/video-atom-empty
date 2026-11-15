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
BG = (0.010, 0.014, 0.026)
CYAN = (0.10, 0.78, 0.92)
MAGENTA = (0.90, 0.42, 0.96)
AMBER = (0.99, 0.72, 0.32)
BONE = (0.94, 0.93, 0.90)
INK = (0.030, 0.038, 0.055)


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


def make_mat(name, base=(0.5, 0.5, 0.5), rough=0.35, metal=0.0, emit=None,
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


def smooth(ob):
    if ob.type != "MESH":
        return ob
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def sphere(name, r, loc, mat, subdiv=2, scale=None):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subdiv, radius=r, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    ob.data.materials.append(mat)
    if scale:
        ob.scale = scale
    return smooth(ob)


def torus(name, R, r, loc, mat, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_torus_add(major_radius=R, minor_radius=r, location=loc,
                                     major_segments=64, minor_segments=12)
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
        v = base * (1.0 + amp * math.sin(phase + i * 1.7))
        light.data.energy = v
        light.data.keyframe_insert("energy", frame=int(round(t)))
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
    for i, frac in enumerate((0.0, 0.5, 1.0)):
        ob.rotation_euler[idx] = a0 + turns * 2 * math.pi * frac
        ob.keyframe_insert("rotation_euler", frame=int(round(f0 + (f1 - f0) * frac)))
    ob.rotation_euler[idx] = a0
    ease(ob)


def pulse(ob, f0, f1, amp=0.06, nkeys=6, phase=0.0):
    base = ob.scale.copy()
    for i in range(nkeys):
        t = f0 + (f1 - f0) * i / (nkeys - 1)
        k = 1.0 + amp * math.sin(phase + i * 1.9)
        ob.scale = base * k
        ob.keyframe_insert("scale", frame=int(round(t)))
    ob.scale = base
    ease(ob)


def dust(f0, f1, n=26, spread=6.0, r=0.02, mat=None, z0=-1.0, z1=3.0):
    """Floating motes: secondary motion in every shot."""
    mat = mat or make_mat("dust", base=(0.7, 0.8, 0.9), rough=0.6,
                          emit=(0.6, 0.85, 1.0), emit_strength=3.0, alpha=1.0)
    for i in range(n):
        a = (i * 2.399963) % (2 * math.pi)
        rad = spread * (0.25 + ((i * 0.618) % 1.0))
        z = z0 + (z1 - z0) * (((i * 0.37) % 1.0))
        ob = sphere(f"dust{i}", r, (rad * math.cos(a), rad * math.sin(a), z), mat, subdiv=1)
        jitter(ob, f0, f1, amp=spread * 0.05, phase=i * 0.9, nkeys=4)


def fg_bokeh(cam, f0, f1, dist, r, n=3, tint=(0.02, 0.06, 0.09)):
    """Dark, out-of-focus shapes parented to the camera: the depth signature."""
    mat = make_mat("fgblur", base=tint, rough=0.8,
                   emit=(0.05, 0.16, 0.22), emit_strength=0.6, alpha=1.0)
    spots = [(0.85, 0.62, -dist), (-1.05, -0.75, -dist * 1.35), (0.2, -1.15, -dist * 0.8)]
    for i in range(min(n, len(spots))):
        ob = sphere(f"fgbokeh{i}", r * (0.7 + 0.5 * i), spots[i], mat, subdiv=2)
        ob.parent = cam
        ob.matrix_parent_inverse = cam.matrix_world.inverted()
        ob.location = spots[i]
        jitter(ob, f0, f1, amp=r * 0.25, phase=i * 1.7, nkeys=4)
    return None


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
    sc.render.motion_blur_shutter = 0.5
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.02
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
    sc.cycles.max_bounces = 6
    sc.cycles.transmission_bounces = 6
    sc.cycles.transparent_max_bounces = 12
    sc.cycles.seed = 7
    sc.cycles.use_animated_seed = False
    sc.render.threads_mode = "AUTO"
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    sc.view_settings.exposure = 0.35


def setup_world(color=BG, strength=0.35):
    w = bpy.data.worlds.new("W")
    bpy.context.scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (*color, 1.0)
    bg.inputs[1].default_value = strength


def add_glare(threshold=1.1, size=0.62, strength=0.4):
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
    comp = None
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
    try:
        sc.use_nodes = False
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


def reset(samples=48, f0=0, f1=90):
    wipe()
    try:
        bpy.context.preferences.edit.keyframe_new_interpolation_type = "BEZIER"
        bpy.context.preferences.edit.keyframe_new_handle_type = "AUTO_CLAMPED"
    except Exception:
        pass
    setup_world()
    setup_render(f0, f1, samples)
    add_glare()


def nucleon_cluster(f0, f1, radius=0.85, count=14, nuc_r=0.30, glow=1.4):
    """A nucleus: protons cyan, neutrons magenta, all jiggling."""
    mp = make_mat("proton", base=CYAN, rough=0.25, emit=CYAN, emit_strength=glow, coat=0.4)
    mn = make_mat("neutron", base=MAGENTA, rough=0.3, emit=MAGENTA, emit_strength=glow * 0.8,
                  coat=0.4)
    grp = bpy.data.objects.new("cluster", None)
    bpy.context.scene.collection.objects.link(grp)
    for i in range(count):
        a = i * 2.399963
        rr = radius * (0.30 + 0.62 * ((i * 0.618) % 1.0))
        z = radius * 0.7 * math.cos(i * 1.7)
        loc = (rr * math.cos(a), rr * math.sin(a), z)
        ob = sphere(f"nuc{i}", nuc_r * (0.82 + 0.3 * ((i * 0.29) % 1.0)), loc,
                    mp if i % 2 == 0 else mn, subdiv=2)
        ob.parent = grp
        ob.matrix_parent_inverse = grp.matrix_world.inverted()
        ob.location = loc
        jitter(ob, f0, f1, amp=nuc_r * 0.22, phase=i * 1.1, nkeys=4)
    spin(grp, f0, f1, turns=0.35, axis="Z")
    return grp


def electron_cloud(f0, f1, radius=2.4, count=120, size=0.022, glow=9.0, shells=(0.82, 1.0)):
    mat = make_mat("electron", base=CYAN, rough=0.2, emit=(0.55, 0.95, 1.0),
                   emit_strength=glow, alpha=1.0)
    grp = bpy.data.objects.new("cloud", None)
    bpy.context.scene.collection.objects.link(grp)
    for i in range(count):
        u = (i * 0.7548776662) % 1.0
        v = (i * 0.5698402910) % 1.0
        th = 2 * math.pi * u
        ph = math.acos(1 - 2 * v)
        r = radius * (shells[0] + (shells[1] - shells[0]) * ((i * 0.37) % 1.0))
        loc = (r * math.sin(ph) * math.cos(th), r * math.sin(ph) * math.sin(th),
               r * math.cos(ph) * 0.85)
        ob = sphere(f"e{i}", size * (0.7 + 0.6 * ((i * 0.11) % 1.0)), loc, mat, subdiv=1)
        ob.parent = grp
        ob.matrix_parent_inverse = grp.matrix_world.inverted()
        ob.location = loc
        jitter(ob, f0, f1, amp=radius * 0.055, phase=i * 0.7, nkeys=4)
    spin(grp, f0, f1, turns=0.55, axis="Z")
    return grp


def atom_shell(radius, mat_name="shell"):
    mat = make_mat(mat_name, base=(0.45, 0.85, 0.95), rough=0.08, transmission=0.92,
                   alpha=0.10, emit=(0.25, 0.7, 0.9), emit_strength=0.25, ior=1.05)
    ob = sphere("shell", radius, (0, 0, 0), mat, subdiv=4)
    return ob


# ---------------------------------------------------------------- shots
def shot_lattice(f0, f1, xray=False, pullback=False):
    """Solid-looking matter: a crystal lattice of atoms."""
    if xray:
        m_atom = make_mat("atomglass", base=(0.55, 0.9, 0.95), rough=0.06, transmission=0.95,
                          alpha=0.16, emit=(0.2, 0.65, 0.85), emit_strength=0.3, ior=1.06)
        m_core = make_mat("core", base=BONE, rough=0.2, emit=(1.0, 0.85, 0.6),
                          emit_strength=26.0)
    else:
        m_atom = make_mat("atomskin", base=(0.16, 0.30, 0.36), rough=0.34, metal=0.15,
                          coat=0.5, emit=(0.05, 0.22, 0.28), emit_strength=0.55)
        m_core = None
    step = 1.15
    n = 5
    objs = []
    for i in range(n):
        for j in range(n):
            for k in range(3):
                x = (i - (n - 1) / 2) * step
                y = (j - (n - 1) / 2) * step
                z = (k - 1) * step * 1.0
                ob = sphere(f"at{i}{j}{k}", 0.52, (x, y, z), m_atom, subdiv=3)
                jitter(ob, f0, f1, amp=0.045, phase=(i * 1.3 + j * 2.1 + k * 0.7), nkeys=5)
                objs.append(ob)
                if m_core:
                    c = sphere(f"co{i}{j}{k}", 0.085, (x, y, z), m_core, subdiv=2)
                    c.parent = ob
                    c.matrix_parent_inverse = ob.matrix_world.inverted()
                    c.location = (0, 0, 0)
                    pulse(c, f0, f1, amp=0.22, nkeys=6, phase=i + j + k)

    key = area_light((2.4, -3.0, 2.6), (0, 0, 0), 2.6, 700, (0.72, 0.92, 1.0))
    rim = area_light((-3.0, 1.6, -1.2), (0, 0, 0), 3.2, 420, (1.0, 0.66, 0.35))
    light_flicker(key, f0, f1, 700, 0.06, 0.3)
    light_flicker(rim, f0, f1, 420, 0.09, 1.1)
    dust(f0, f1, n=24, spread=2.6, r=0.014, z0=-1.2, z1=1.4)

    if pullback:
        cam = add_camera((0.0, -1.15, 0.15), (0, 0.4, 0), lens=42, fstop=2.4, focus=1.6)
        cam_keys(cam, [(f0, (0.0, -1.15, 0.15), (0, 0.4, 0)),
                       (f1, (0.35, -7.6, 1.5), (0, 0.2, 0))])
        focus_keys(cam, [(f0, 1.6), (f1, 8.2)])
        fg_bokeh(cam, f0, f1, dist=0.55, r=0.16)
    else:
        cam = add_camera((0.0, -3.4, 0.25), (0, 0.6, 0), lens=58, fstop=1.9, focus=3.9)
        cam_keys(cam, [(f0, (0.0, -3.4, 0.25), (0, 0.6, 0)),
                       (f1, (0.16, -1.05, 0.10), (0, 1.1, 0))])
        focus_keys(cam, [(f0, 3.9), (f1, 1.7)])
        fg_bokeh(cam, f0, f1, dist=0.7, r=0.22)
    return cam


def shot_nucleus(f0, f1):
    reset(f0=f0, f1=f1)
    nucleon_cluster(f0, f1, radius=0.9, count=15, nuc_r=0.30, glow=1.6)
    halo = make_mat("halo", base=(0.4, 0.8, 0.95), rough=0.1, transmission=0.9, alpha=0.12,
                    emit=(0.3, 0.75, 0.95), emit_strength=0.6)
    sphere("halo", 1.55, (0, 0, 0), halo, subdiv=4)
    key = area_light((2.2, -2.6, 2.2), (0, 0, 0), 2.4, 620, (0.7, 0.92, 1.0))
    rim = area_light((-2.4, 1.4, -1.6), (0, 0, 0), 2.8, 500, (1.0, 0.6, 0.32))
    light_flicker(key, f0, f1, 620, 0.07, 0.5)
    light_flicker(rim, f0, f1, 500, 0.11, 2.0)
    dust(f0, f1, n=20, spread=2.2, r=0.013)
    cam = add_camera((-1.9, -2.7, 0.55), (0, 0, 0), lens=62, fstop=1.8, focus=3.3)
    cam_keys(cam, [(f0, (-1.9, -2.7, 0.55), (0, 0, 0)),
                   (f1, (1.75, -2.35, -0.35), (0, 0, 0))])
    focus_keys(cam, [(f0, 3.3), (f1, 3.0)])
    fg_bokeh(cam, f0, f1, dist=0.6, r=0.18)
    return cam


def shot_atom(f0, f1):
    """The nucleus is absurdly small: pull back to the whole atom."""
    reset(f0=f0, f1=f1)
    nucleon_cluster(f0, f1, radius=0.13, count=12, nuc_r=0.045, glow=3.0)
    atom_shell(2.55)
    electron_cloud(f0, f1, radius=2.5, count=110, size=0.019, glow=11.0)
    key = area_light((3.2, -3.4, 3.0), (0, 0, 0), 3.4, 900, (0.68, 0.9, 1.0))
    rim = area_light((-3.4, 2.0, -2.0), (0, 0, 0), 3.6, 620, (1.0, 0.62, 0.34))
    light_flicker(key, f0, f1, 900, 0.05, 0.2)
    light_flicker(rim, f0, f1, 620, 0.1, 1.4)
    dust(f0, f1, n=22, spread=3.4, r=0.02)
    cam = add_camera((0.0, -0.62, 0.10), (0, 0, 0), lens=40, fstop=2.0, focus=0.63)
    cam_keys(cam, [(f0, (0.0, -0.62, 0.10), (0, 0, 0)),
                   (f1, (0.9, -7.4, 1.05), (0, 0, 0))])
    focus_keys(cam, [(f0, 0.63), (f1, 7.5)])
    fg_bokeh(cam, f0, f1, dist=0.5, r=0.1)
    return cam


def shot_marble(f0, f1):
    """Marble to kilometre: the scale dive, on a real ground grid."""
    reset(f0=f0, f1=f1)
    marble = make_mat("marble", base=(0.85, 0.87, 0.9), rough=0.14, coat=0.8,
                      emit=(0.5, 0.75, 0.9), emit_strength=0.35)
    m = sphere("marble", 1.0, (0, 0, 1.0), marble, subdiv=3)
    spin(m, f0, f1, turns=1.4, axis="Z")
    pulse(m, f0, f1, amp=0.02, nkeys=4)

    dome_mat = make_mat("dome", base=(0.3, 0.75, 0.9), rough=0.1, transmission=0.95,
                        alpha=0.09, emit=(0.2, 0.6, 0.85), emit_strength=0.4, ior=1.03)
    sphere("dome", 600.0, (0, 0, 0), dome_mat, subdiv=3)

    grid_mat = make_mat("grid", base=(0.05, 0.10, 0.13), rough=0.5,
                        emit=(0.15, 0.5, 0.65), emit_strength=1.6)
    p = plane("ground", 4000, (0, 0, 0), grid_mat)
    tex = p.data.materials[0].node_tree
    chk = tex.nodes.new("ShaderNodeTexChecker")
    chk.inputs["Scale"].default_value = 200.0
    chk.inputs["Color1"].default_value = (0.02, 0.06, 0.09, 1)
    chk.inputs["Color2"].default_value = (0.1, 0.42, 0.55, 1)
    bsdf = tex.nodes["Principled BSDF"]
    tex.links.new(chk.outputs["Color"], bsdf.inputs["Base Color"])
    tex.links.new(chk.outputs["Color"], bsdf.inputs["Emission Color"])

    # the stadium rim, so the scale reads
    ring_mat = make_mat("ring", base=(1.0, 0.7, 0.35), rough=0.3, emit=(1.0, 0.62, 0.28),
                        emit_strength=6.0)
    ring = torus("rim", 600.0, 6.0, (0, 0, 4.0), ring_mat, rot=(0, 0, 0))
    pulse(ring, f0, f1, amp=0.004, nkeys=4)

    sun = area_light((400, -500, 700), (0, 0, 0), 400, 900000, (0.75, 0.9, 1.0))
    light_flicker(sun, f0, f1, 900000, 0.05, 0.4)
    point_light((0, -3, 6), 900, (1.0, 0.8, 0.55), radius=2.0)
    dust(f0, f1, n=14, spread=90.0, r=1.6, z0=2.0, z1=60.0)

    cam = add_camera((0.0, -4.2, 1.9), (0, 0, 1.0), lens=45, fstop=2.2, focus=4.3)
    cam_keys(cam, [(f0, (0.0, -4.2, 1.9), (0, 0, 1.0)),
                   (f1, (0.0, -1250.0, 620.0), (0, 0, 60.0))])
    focus_keys(cam, [(f0, 4.3), (f1, 1300.0)])
    return cam


def shot_crosssection(f0, f1):
    """Cut the atom open: almost all of it is nothing."""
    reset(f0=f0, f1=f1)
    shell_mat = make_mat("cut", base=(0.35, 0.8, 0.92), rough=0.08, transmission=0.94,
                         alpha=0.13, emit=(0.2, 0.62, 0.85), emit_strength=0.35, ior=1.04)
    s = sphere("cut", 2.6, (0, 0, 0), shell_mat, subdiv=4)
    # slice the sphere in half with a boolean so the inside is visible
    bpy.ops.mesh.primitive_cube_add(size=6.0, location=(0, 3.2, 0))
    cutter = bpy.context.active_object
    cutter.name = "cutter"
    cutter.display_type = "WIRE"
    mod = s.modifiers.new("cut", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    cutter.hide_render = True
    cutter.hide_viewport = True

    nucleon_cluster(f0, f1, radius=0.10, count=12, nuc_r=0.034, glow=3.4)
    electron_cloud(f0, f1, radius=2.55, count=80, size=0.017, glow=9.0, shells=(0.9, 1.0))
    key = area_light((3.0, -2.2, 2.4), (0, 0, 0), 3.0, 780, (0.7, 0.9, 1.0))
    rim = area_light((-3.2, -1.0, -2.2), (0, 0, 0), 3.2, 560, (1.0, 0.6, 0.34))
    light_flicker(key, f0, f1, 780, 0.06, 0.9)
    light_flicker(rim, f0, f1, 560, 0.09, 1.9)
    dust(f0, f1, n=18, spread=3.2, r=0.018)
    cam = add_camera((-2.6, -3.2, 0.9), (0, 0, 0), lens=48, fstop=2.0, focus=4.2)
    cam_keys(cam, [(f0, (-2.6, -3.2, 0.9), (0, 0, 0)),
                   (f1, (2.2, -3.9, 0.2), (0, 0, 0))])
    focus_keys(cam, [(f0, 4.2), (f1, 4.6)])
    fg_bokeh(cam, f0, f1, dist=0.75, r=0.2)
    return cam


def shot_core(f0, f1):
    """Almost all the mass sits in that tiny core."""
    reset(f0=f0, f1=f1)
    nucleon_cluster(f0, f1, radius=0.62, count=18, nuc_r=0.24, glow=2.2)
    dense = make_mat("dense", base=(1.0, 0.85, 0.6), rough=0.15, emit=(1.0, 0.72, 0.38),
                     emit_strength=16.0)
    c = sphere("core", 0.30, (0, 0, 0), dense, subdiv=3)
    pulse(c, f0, f1, amp=0.13, nkeys=7, phase=0.4)
    key = area_light((1.8, -2.0, 1.6), (0, 0, 0), 1.8, 420, (0.72, 0.9, 1.0))
    rim = area_light((-1.9, 1.2, -1.4), (0, 0, 0), 2.2, 520, (1.0, 0.55, 0.28))
    light_flicker(key, f0, f1, 420, 0.08, 0.6)
    light_flicker(rim, f0, f1, 520, 0.13, 2.4)
    dust(f0, f1, n=16, spread=1.6, r=0.01)
    cam = add_camera((0.0, -3.1, 0.35), (0, 0, 0), lens=70, fstop=1.8, focus=3.2)
    cam_keys(cam, [(f0, (0.0, -3.1, 0.35), (0, 0, 0)),
                   (f1, (0.35, -1.15, 0.08), (0, 0, 0))])
    focus_keys(cam, [(f0, 3.2), (f1, 1.2)])
    fg_bokeh(cam, f0, f1, dist=0.55, r=0.16)
    return cam


def shot_fields(f0, f1):
    """The rest is fields, not stuff."""
    reset(f0=f0, f1=f1)
    nucleon_cluster(f0, f1, radius=0.34, count=10, nuc_r=0.15, glow=2.6)
    line_mat = make_mat("field", base=(0.4, 0.95, 1.0), rough=0.2, emit=(0.35, 0.95, 1.0),
                        emit_strength=9.0)
    for i in range(10):
        a = i * 2 * math.pi / 10
        bpy.ops.mesh.primitive_torus_add(major_radius=1.1 + 0.22 * i,
                                         minor_radius=0.012, location=(0, 0, 0),
                                         major_segments=96, minor_segments=6)
        ring = bpy.context.active_object
        ring.name = f"ring{i}"
        ring.rotation_euler = (math.radians(78), math.radians(12 * i), a)
        ring.data.materials.append(line_mat)
        smooth(ring)
        k0 = 0.75 + 0.02 * i
        ring.scale = (k0, k0, k0)
        ring.keyframe_insert("scale", frame=f0)
        ring.scale = (k0 * 1.16, k0 * 1.16, k0 * 1.16)
        ring.keyframe_insert("scale", frame=int((f0 + f1) / 2))
        ring.scale = (k0 * 0.94, k0 * 0.94, k0 * 0.94)
        ring.keyframe_insert("scale", frame=f1)
        ring.scale = (k0, k0, k0)
        ease(ring)
        spin(ring, f0, f1, turns=0.12 * (1 if i % 2 else -1), axis="Z")
    electron_cloud(f0, f1, radius=1.9, count=46, size=0.026, glow=10.0)
    key = point_light((0, 0, 0), 90, (0.6, 0.95, 1.0), radius=0.3)
    light_flicker(key, f0, f1, 90, 0.2, 0.3, nkeys=8)
    rim = area_light((-2.6, 1.8, 1.6), (0, 0, 0), 2.6, 480, (1.0, 0.6, 0.35))
    light_flicker(rim, f0, f1, 480, 0.08, 1.2)
    dust(f0, f1, n=18, spread=2.4, r=0.014)
    cam = add_camera((-2.1, -2.9, 0.7), (0, 0, 0), lens=50, fstop=2.0, focus=3.6)
    cam_keys(cam, [(f0, (-2.1, -2.9, 0.7), (0, 0, 0)),
                   (f1, (1.4, -3.4, 0.1), (0, 0, 0))])
    focus_keys(cam, [(f0, 3.6), (f1, 3.7)])
    fg_bokeh(cam, f0, f1, dist=0.7, r=0.19)
    return cam


def shot_contact(f0, f1, macro=False):
    """Two electron clouds refuse to overlap: you never touch anything."""
    reset(f0=f0, f1=f1)
    a_mat = make_mat("cloudA", base=(0.35, 0.85, 0.95), rough=0.1, transmission=0.9,
                     alpha=0.16, emit=(0.25, 0.8, 0.95), emit_strength=0.7)
    b_mat = make_mat("cloudB", base=(0.98, 0.55, 0.35), rough=0.1, transmission=0.9,
                     alpha=0.16, emit=(1.0, 0.5, 0.3), emit_strength=0.7)
    R = 1.25
    A = sphere("cloudA", R, (-3.4, 0, 0), a_mat, subdiv=4)
    B = sphere("cloudB", R, (3.4, 0, 0), b_mat, subdiv=4)
    # approach, squash on contact, hold the gap
    for ob, sign in ((A, 1.0), (B, -1.0)):
        for i, (fr, x, sq) in enumerate((
            (f0, 3.4, 1.00),
            (int(f0 + (f1 - f0) * 0.55), 2.62, 0.94),
            (int(f0 + (f1 - f0) * 0.75), 2.55, 0.86),
            (f1, 2.62, 0.92),
        )):
            ob.location = (sign * x, 0, 0)
            ob.scale = (R * sq, R / max(sq, 0.5), R / max(sq, 0.5))
            ob.keyframe_insert("location", frame=fr)
            ob.keyframe_insert("scale", frame=fr)
        ease(ob)
    # electrons as surface sparkle
    e_mat = make_mat("e2", base=CYAN, rough=0.2, emit=(0.6, 0.95, 1.0), emit_strength=14.0)
    e2_mat = make_mat("e3", base=(1.0, 0.7, 0.45), rough=0.2, emit=(1.0, 0.6, 0.35),
                      emit_strength=14.0)
    for i in range(40):
        u = (i * 0.7548776662) % 1.0
        v = (i * 0.5698402910) % 1.0
        th = 2 * math.pi * u
        ph = math.acos(1 - 2 * v)
        for ob, mat, side in ((A, e_mat, -1), (B, e2_mat, 1)):
            loc = (side * R * abs(math.sin(ph) * math.cos(th)),
                   R * math.sin(ph) * math.sin(th), R * math.cos(ph))
            e = sphere(f"p{i}{side}", 0.035, loc, mat, subdiv=1)
            e.parent = ob
            e.matrix_parent_inverse = ob.matrix_world.inverted()
            e.location = loc
            jitter(e, f0, f1, amp=0.07, phase=i + side, nkeys=4)
    gap = point_light((0, 0, 0), 60, (1.0, 0.8, 0.55), radius=0.2)
    light_flicker(gap, f0, f1, 60, 0.35, 0.2, nkeys=8)
    key = area_light((0, -3.4, 2.4), (0, 0, 0), 3.0, 620, (0.7, 0.9, 1.0))
    light_flicker(key, f0, f1, 620, 0.06, 0.8)
    rim = area_light((0, 3.0, -2.0), (0, 0, 0), 3.0, 520, (1.0, 0.62, 0.36))
    light_flicker(rim, f0, f1, 520, 0.09, 1.6)
    dust(f0, f1, n=16, spread=2.6, r=0.016)
    if macro:
        cam = add_camera((0.3, -1.5, 0.42), (0, 0, 0), lens=85, fstop=1.6, focus=1.6)
        cam_keys(cam, [(f0, (0.3, -1.5, 0.42), (0, 0, 0)),
                       (f1, (-0.9, -1.85, -0.28), (0, 0, 0))])
        focus_keys(cam, [(f0, 1.6), (f1, 2.0)])
        fg_bokeh(cam, f0, f1, dist=0.4, r=0.12)
    else:
        cam = add_camera((0.6, -6.6, 1.5), (0, 0, 0), lens=52, fstop=2.2, focus=6.8)
        cam_keys(cam, [(f0, (0.6, -6.6, 1.5), (0, 0, 0)),
                       (f1, (-0.4, -5.2, 0.9), (0, 0, 0))])
        focus_keys(cam, [(f0, 6.8), (f1, 5.4)])
        fg_bokeh(cam, f0, f1, dist=0.9, r=0.24)
    return cam


def shot_void(f0, f1):
    """Atoms are almost all space: one atom alone in the dark."""
    reset(f0=f0, f1=f1)
    nucleon_cluster(f0, f1, radius=0.09, count=10, nuc_r=0.03, glow=4.0)
    atom_shell(2.2)
    electron_cloud(f0, f1, radius=2.15, count=70, size=0.016, glow=12.0)
    key = area_light((3.0, -3.0, 2.6), (0, 0, 0), 3.0, 760, (0.66, 0.88, 1.0))
    rim = area_light((-3.0, 2.2, -1.8), (0, 0, 0), 3.0, 520, (1.0, 0.6, 0.34))
    light_flicker(key, f0, f1, 760, 0.06, 0.3)
    light_flicker(rim, f0, f1, 520, 0.1, 1.5)
    dust(f0, f1, n=26, spread=3.6, r=0.02, z0=-1.6, z1=1.8)
    cam = add_camera((-2.0, -3.6, 0.9), (0, 0, 0), lens=44, fstop=2.0, focus=4.2)
    cam_keys(cam, [(f0, (-2.0, -3.6, 0.9), (0, 0, 0)),
                   (f1, (2.3, -3.1, 0.25), (0, 0, 0))])
    focus_keys(cam, [(f0, 4.2), (f1, 3.9)])
    fg_bokeh(cam, f0, f1, dist=0.85, r=0.22)
    return cam


# order must match narration.json
BUILDERS = [
    lambda f0, f1: shot_lattice(f0, f1, xray=False, pullback=False),   # 01-table
    lambda f0, f1: shot_lattice(f0, f1, xray=True, pullback=False),    # 02-empty
    lambda f0, f1: shot_nucleus(f0, f1),                               # 03-atom
    lambda f0, f1: shot_atom(f0, f1),                                  # 04-nucleus
    lambda f0, f1: shot_marble(f0, f1),                                # 05-marble
    lambda f0, f1: shot_crosssection(f0, f1),                          # 06-percent
    lambda f0, f1: shot_core(f0, f1),                                  # 07-mass
    lambda f0, f1: shot_fields(f0, f1),                                # 08-fields
    lambda f0, f1: shot_contact(f0, f1, macro=False),                  # 09-touch
    lambda f0, f1: shot_contact(f0, f1, macro=True),                   # 10-push
    lambda f0, f1: shot_lattice(f0, f1, xray=True, pullback=True),     # 11-feeling
    lambda f0, f1: shot_void(f0, f1),                                  # 12-space
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shotlist", default="shotlist.json")
    ap.add_argument("--out", default="scenes")
    ap.add_argument("--samples", type=int, default=48)
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
