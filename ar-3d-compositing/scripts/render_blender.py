#!/usr/bin/env python3
"""
Render simple 3D elements (cubes, bar charts, spheres, panels) with REAL
cast shadows onto a transparent background, matched to a real camera, so
the result can be laid directly over the source photo/video.

The shadow is not a painted ellipse: a sun light casts it onto an
invisible ground plane flagged as a Cycles shadow catcher. The catcher
itself renders fully transparent; only the darkening from the shadow
survives in the alpha channel, so it lands on the real floor/desk in the
composite and follows the light direction you set.

Requires the `bpy` module (Blender as a Python package). bpy only ships
for specific Python versions (currently 3.13 for Blender 5.x), so use a
dedicated venv:

    uv venv -p 3.13 bpyenv && . bpyenv/bin/activate && uv pip install bpy
    python scripts/render_blender.py scene.json --out out/render

Renders on GPU by default (--device AUTO tries OptiX/CUDA/HIP/oneAPI/Metal
in that order and falls back to CPU if none are found); pass --device CPU
to force CPU, or e.g. --device OPTIX to require a specific backend.

Output: out/render/frame_0001.png ... (straight RGBA), plus
out/render.webm (VP8 + alpha) unless --no-webm. Frame numbers in the
PNG names match the spec's frame numbers.

World frame (Blender, meters): X right, Y away from camera (depth), Z up.
The ground plane is z = 0. estimate_orientation.py's --blender flag
prints forward/up already converted into this frame.

Scene spec (JSON). Every color and the light direction are REQUIRED —
there are deliberately no style defaults, so each shot's look comes from
its own footage (see sample_palette.py), not from this script:

{
  "resolution": [1920, 1080],          # match the plate exactly
  "fps": 30,
  "frames": [1, 90],
  "samples": 32,                        # Cycles samples; 16-64 is plenty
  "camera": {
    "hfov_deg": 70,                     # same value given to estimate_orientation.py
    "position": [0, 0, 1.1],            # meters; z = camera height above the ground plane
    "forward": [0, 0.94, -0.34],        # from estimate_orientation.py --blender
    "up": [0, 0.34, 0.94]
  },
  "light": {
    "azimuth_deg": 210,                 # compass direction the light COMES FROM (0 = +Y/away, 90 = +X/right)
    "elevation_deg": 40,                # height of the light above the horizon
    "softness_deg": 3,                  # sun angular size: ~0.5 hard sunlight, 5-15 soft window/overcast
    "strength": 3.0,
    "color": "#fff4e6",
    "ambient": 0.35,                    # fill so shadow sides aren't black
    "ambient_color": "#dfe6ee"
  },
  "shadow_strength": 1.0,               # 0-1, scales how dark the caught shadow is
  "objects": [
    {"type": "cube", "name": "block", "size": [0.3, 0.3, 0.3],
     "location": [0.2, 2.0], "rotation_deg": 15,
     "color": "#c2553a", "roughness": 0.45, "metallic": 0.0,
     "keyframes": [{"frame": 1, "scale": 0.0}, {"frame": 20, "scale": 1.0},
                   {"frame": 60, "location": [0.4, 2.0], "rotation_deg": 45}]},
    {"type": "bar_chart", "name": "chart", "location": [-0.4, 2.2], "rotation_deg": -10,
     "values": [0.2, 0.35, 0.3, 0.55], "max_height": 0.5,
     "bar_width": 0.09, "bar_depth": 0.09, "gap": 0.04,
     "colors": ["#2f5d62", "#2f5d62", "#2f5d62", "#e0a458"],
     "roughness": 0.5, "grow": {"start": 10, "stagger": 6, "duration": 18}},
    {"type": "sphere", "radius": 0.08, "location": [0.0, 1.6], "color": "#..."},
    {"type": "tesseract", "size": 0.12, "location": [0, 0.4], "height": 0.15, "color": "#...",
     "rod_radius": 0.004, "w_distance": 2.5, "spin_period": 120, "turn_period": 240, "tilt_deg": 20},
                                        # 4D hypercube spinning through w; origin at its CENTER, so
                                        # "height" is the center's height above the ground plane
    {"type": "panel", "size": [0.4, 0.25], "location": [...], "height": 0.3, "color": "#...",
     "rotation_deg": 0}
  ]
}

Objects sit ON the ground (their base at z = 0) unless given "height"
(meters to lift the base). Keyframes accept any of: location [x, y],
height, rotation_deg, scale (uniform number or [x, y, z]).
"""
import argparse
import json
import math
import os
import subprocess
import sys

import bpy
from mathutils import Matrix, Vector


# ---------- helpers ----------

def hex_rgb(h, field):
    if not isinstance(h, str) or not h.startswith("#") or len(h) != 7:
        raise SystemExit(f"{field}: expected a '#rrggbb' color, got {h!r}. "
                         "Colors are required on purpose — pick them from the footage "
                         "(scripts/sample_palette.py) rather than leaving a default.")
    srgb = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    # Blender material colors are linear
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]


def require(d, key, where):
    if key not in d:
        raise SystemExit(f"scene spec: '{where}.{key}' is required")
    return d[key]


def make_material(name, color_hex, roughness=0.5, metallic=0.0, field="color", emission=None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*hex_rgb(color_hex, field), 1.0)
    bsdf.inputs["Roughness"].default_value = float(roughness)
    bsdf.inputs["Metallic"].default_value = float(metallic)
    if emission:  # {"color": "#rrggbb", "strength": 8} -> self-lit / neon; only when asked for
        bsdf.inputs["Emission Color"].default_value = (*hex_rgb(emission["color"], f"{field}.emission"), 1.0)
        bsdf.inputs["Emission Strength"].default_value = float(emission.get("strength", 5.0))
    return mat


def base_box(name, sx, sy, sz):
    """Box with its origin at the CENTER OF ITS BASE, so scaling grows it up
    out of the ground rather than out of its middle."""
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    ob = bpy.context.active_object
    ob.name = name
    me = ob.data
    for v in me.vertices:
        v.co.z += 0.5
    me.transform(Matrix.Diagonal((sx, sy, sz, 1.0)))
    me.update()
    return ob


def place(ob, loc, height=0.0, rot_deg=0.0):
    ob.location = (loc[0], loc[1], height)
    ob.rotation_euler = (0.0, 0.0, math.radians(rot_deg))


def apply_keyframes(ob, kfs, base_height):
    for kf in kfs or []:
        f = int(kf["frame"])
        if "location" in kf or "height" in kf:
            x, y = kf.get("location", (ob.location.x, ob.location.y))
            z = kf.get("height", base_height)
            ob.location = (x, y, z)
            ob.keyframe_insert("location", frame=f)
        if "rotation_deg" in kf:
            ob.rotation_euler = (0.0, 0.0, math.radians(kf["rotation_deg"]))
            ob.keyframe_insert("rotation_euler", frame=f)
        if "scale" in kf:
            s = kf["scale"]
            s = (s, s, s) if isinstance(s, (int, float)) else tuple(s)
            ob.scale = tuple(max(v, 1e-4) for v in s)  # exact 0 breaks shading
            ob.keyframe_insert("scale", frame=f)


# ---------- scene building ----------

def build_object(spec, idx):
    t = require(spec, "type", f"objects[{idx}]")
    name = spec.get("name", f"{t}_{idx}")
    loc = require(spec, "location", f"objects[{idx}]")
    h = float(spec.get("height", 0.0))
    rot = float(spec.get("rotation_deg", 0.0))
    rough, metal = spec.get("roughness", 0.5), spec.get("metallic", 0.0)
    where = f"objects[{idx}]"

    if t == "cube":
        sx, sy, sz = spec.get("size", [0.25, 0.25, 0.25])
        ob = base_box(name, sx, sy, sz)
        ob.data.materials.append(make_material(name, require(spec, "color", where), rough, metal, f"{where}.color"))
        place(ob, loc, h, rot)
        apply_keyframes(ob, spec.get("keyframes"), h)
        return [ob]

    if t == "sphere":
        r = float(spec.get("radius", 0.1))
        bpy.ops.mesh.primitive_uv_sphere_add(radius=r, segments=48, ring_count=24)
        ob = bpy.context.active_object
        ob.name = name
        for v in ob.data.vertices:
            v.co.z += r
        bpy.ops.object.shade_smooth()
        ob.data.materials.append(make_material(name, require(spec, "color", where), rough, metal, f"{where}.color"))
        place(ob, loc, h, rot)
        apply_keyframes(ob, spec.get("keyframes"), h)
        return [ob]

    if t == "panel":  # thin upright card, e.g. a floating chart backdrop or sign
        w, ht = spec.get("size", [0.4, 0.25])
        ob = base_box(name, w, float(spec.get("thickness", 0.01)), ht)
        ob.data.materials.append(make_material(name, require(spec, "color", where), rough, metal, f"{where}.color"))
        place(ob, loc, h, rot)
        apply_keyframes(ob, spec.get("keyframes"), h)
        return [ob]

    if t == "bar_chart":
        values = require(spec, "values", where)
        colors = require(spec, "colors", where)
        if len(colors) != len(values):
            raise SystemExit(f"{where}: 'colors' needs one entry per value ({len(values)})")
        maxh = float(spec.get("max_height", 0.4))
        vmax = max(values) or 1.0
        bw, bd, gap = spec.get("bar_width", 0.08), spec.get("bar_depth", 0.08), spec.get("gap", 0.03)
        # parent empty carries the chart's placement/rotation/keyframes
        parent = bpy.data.objects.new(name, None)
        bpy.context.collection.objects.link(parent)
        place(parent, loc, h, rot)
        total = len(values) * bw + (len(values) - 1) * gap
        grow = spec.get("grow")
        bars = []
        for i, (v, c) in enumerate(zip(values, colors)):
            bar = base_box(f"{name}_bar{i}", bw, bd, maxh * v / vmax)
            bar.data.materials.append(make_material(bar.name, c, rough, metal, f"{where}.colors[{i}]"))
            bar.parent = parent
            bar.location = (-total / 2 + bw / 2 + i * (bw + gap), 0.0, 0.0)
            if grow:
                s = int(grow.get("start", 1)) + i * int(grow.get("stagger", 5))
                e = s + int(grow.get("duration", 15))
                bar.scale = (1, 1, 1e-4); bar.keyframe_insert("scale", frame=s)
                bar.scale = (1, 1, 1.0); bar.keyframe_insert("scale", frame=e)
            bars.append(bar)
        apply_keyframes(parent, spec.get("keyframes"), h)
        return bars

    if t == "tesseract":  # 4D hypercube, projected to 3D, spinning through the 4th dimension
        edge = float(spec.get("size", 0.12))          # edge length of the outer cube, meters
        rod = float(spec.get("rod_radius", edge * 0.035))
        wdist = float(spec.get("w_distance", 2.5))   # perspective distance in w (bigger = flatter)
        period = float(spec.get("spin_period", 120)) # frames per full 4D turn (XW + YW planes)
        turn3d = float(spec.get("turn_period", 0))   # frames per full 3D turn about Z (0 = none)
        tilt = math.radians(float(spec.get("tilt_deg", 20)))
        import itertools
        verts4 = [list(v) for v in itertools.product((-1, 1), repeat=4)]
        edges = [(i, j) for i in range(16) for j in range(i + 1, 16)
                 if sum(a != b for a, b in zip(verts4[i], verts4[j])) == 1]
        cu = bpy.data.curves.new(name, "CURVE")
        cu.dimensions = "3D"
        cu.bevel_depth, cu.bevel_resolution = rod, 4
        cu.use_fill_caps = True
        for _ in edges:
            sp = cu.splines.new("POLY"); sp.points.add(1)
        ob = bpy.data.objects.new(name, cu)
        bpy.context.collection.objects.link(ob)
        cu.materials.append(make_material(name, require(spec, "color", where), rough, metal, f"{where}.color",
                                          spec.get("emission")))
        if spec.get("emission"):
            ob.visible_shadow = False  # a light source shouldn't block light
        # joint spheres at the 16 corners so rods meet cleanly
        bpy.ops.mesh.primitive_uv_sphere_add(radius=rod * 1.6, segments=16, ring_count=8)
        joint = bpy.context.active_object; bpy.ops.object.shade_smooth()
        joint.data.materials.append(cu.materials[0])
        joints = [joint] + [joint.copy() for _ in range(15)]
        for j in joints[1:]:
            bpy.context.collection.objects.link(j)
        for j in joints:
            j.parent = ob
        place(ob, loc, h, rot)
        base_rot = rot

        def project(f):
            a = 2 * math.pi * f / period
            b = a * 0.5
            out = []
            for x, y, z, w in verts4:
                x, w = x * math.cos(a) - w * math.sin(a), x * math.sin(a) + w * math.cos(a)
                y, w = y * math.cos(b) - w * math.sin(b), y * math.sin(b) + w * math.cos(b)
                k = 1.0 / (wdist - w)
                x, y, z = x * k, y * k, z * k
                y, z = y * math.cos(tilt) - z * math.sin(tilt), y * math.sin(tilt) + z * math.cos(tilt)
                out.append(Vector((x, y, z)) * (edge / 2) * (wdist - 1))
            return out

        def update(scene, *_):
            f = scene.frame_current
            P = project(f)
            for sp, (i, j) in zip(cu.splines, edges):
                sp.points[0].co = (*P[i], 1.0); sp.points[1].co = (*P[j], 1.0)
            for jo, v in zip(joints, P):
                jo.location = v
            if turn3d:
                ob.rotation_euler[2] = math.radians(base_rot) + 2 * math.pi * f / turn3d

        bpy.app.handlers.frame_change_pre.append(update)
        update(bpy.context.scene)
        apply_keyframes(ob, spec.get("keyframes"), h)
        return [ob]

    raise SystemExit(f"{where}: unknown type {t!r} (cube, sphere, panel, bar_chart, tesseract)")


def setup_camera(cam_spec, res):
    cam_data = bpy.data.cameras.new("cam")
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.angle = math.radians(float(require(cam_spec, "hfov_deg", "camera")))
    cam_data.clip_start, cam_data.clip_end = 0.01, 500
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.collection.objects.link(cam)

    fwd = Vector(require(cam_spec, "forward", "camera")).normalized()
    up = Vector(require(cam_spec, "up", "camera"))
    up = (up - up.dot(fwd) * fwd).normalized()          # orthogonalize
    right = fwd.cross(up).normalized()
    # Blender camera looks down its local -Z with local +Y up
    rot = Matrix((right, up, -fwd)).transposed()
    cam.matrix_world = Matrix.Translation(Vector(require(cam_spec, "position", "camera"))) @ rot.to_4x4()
    bpy.context.scene.camera = cam


def setup_light(l):
    az = math.radians(float(require(l, "azimuth_deg", "light")))
    el = math.radians(float(require(l, "elevation_deg", "light")))
    # direction the light travels (from the light toward the scene)
    to_light = Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))
    sun_data = bpy.data.lights.new("sun", type="SUN")
    sun_data.energy = float(l.get("strength", 3.0))
    sun_data.angle = math.radians(float(l.get("softness_deg", 3.0)))
    sun_data.color = hex_rgb(require(l, "color", "light"), "light.color")
    sun = bpy.data.objects.new("sun", sun_data)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = (-to_light).to_track_quat("-Z", "Y").to_euler()

    world = bpy.data.worlds.new("world")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (*hex_rgb(require(l, "ambient_color", "light"), "light.ambient_color"), 1)
    bg.inputs["Strength"].default_value = float(l.get("ambient", 0.35))


def setup_shadow_catcher(strength):
    bpy.ops.mesh.primitive_plane_add(size=200)
    g = bpy.context.active_object
    g.name = "shadow_catcher"
    g.is_shadow_catcher = True
    mat = bpy.data.materials.new("catcher")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 1.0
    g.data.materials.append(mat)
    return g


# GPU backend priority for --device AUTO: OptiX (NVIDIA RTX) first since it's
# fastest and lowest-VRAM via its denoiser, then the other vendor backends.
GPU_DEVICE_ORDER = ["OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"]


def configure_device(sc, device):
    """Point Cycles at a GPU backend. AUTO tries each backend in
    GPU_DEVICE_ORDER and falls back to CPU if none has a usable device."""
    if device == "CPU":
        sc.cycles.device = "CPU"
        print("cycles device: CPU")
        return
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for dt in (GPU_DEVICE_ORDER if device == "AUTO" else [device]):
        prefs.compute_device_type = dt
        prefs.get_devices()
        found = [d for d in prefs.devices if d.type == dt]
        if found:
            for d in prefs.devices:
                d.use = d.type == dt  # exclude CPU so it doesn't bottleneck the GPU pass
            sc.cycles.device = "GPU"
            print(f"cycles device: GPU ({dt}) - {', '.join(d.name for d in found)}")
            return
    if device != "AUTO":
        raise SystemExit(f"--device {device}: no matching device found on this machine "
                          "(check GPU drivers, or pass --device CPU).")
    print("cycles device: no GPU backend found, falling back to CPU")
    sc.cycles.device = "CPU"


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--out", required=True, help="output directory for the PNG frames")
    ap.add_argument("--frames", nargs=2, type=int, help="override frame range, e.g. for still tests: --frames 30 30")
    ap.add_argument("--scale", type=float, default=1.0, help="resolution multiplier for fast tests, e.g. 0.5")
    ap.add_argument("--samples", type=int, help="override samples")
    ap.add_argument("--device", default="AUTO",
                     choices=["AUTO", "CPU", "OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"],
                     help="Cycles compute device (default: AUTO, tries GPU backends then falls back to CPU)")
    ap.add_argument("--border", nargs=4, type=float, metavar=("X0", "Y0", "X1", "Y1"),
                     help="only render this region (fractions of width/height, y measured from the TOP); "
                          "output stays full size and transparent elsewhere. Big CPU saver for small objects")
    ap.add_argument("--no-webm", action="store_true")
    args = ap.parse_args(argv)

    spec = json.load(open(args.spec))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    configure_device(sc, args.device)
    sc.cycles.samples = args.samples or int(spec.get("samples", 32))
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
    except TypeError:
        pass
    sc.render.film_transparent = True
    res = require(spec, "resolution", "")
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = int(round(args.scale * 100))
    sc.render.fps = int(spec.get("fps", 30))
    sc.view_settings.view_transform = "Standard"   # don't tone-map colors picked from footage
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    if args.border:
        x0, y0, x1, y1 = args.border
        sc.render.use_border, sc.render.use_crop_to_border = True, False
        sc.render.border_min_x, sc.render.border_max_x = x0, x1
        sc.render.border_min_y, sc.render.border_max_y = 1 - y1, 1 - y0
    lo, hi = args.frames or spec.get("frames", [1, 1])
    sc.frame_start, sc.frame_end = lo, hi

    setup_camera(require(spec, "camera", ""), res)
    setup_light(require(spec, "light", ""))
    setup_shadow_catcher(spec.get("shadow_strength", 1.0))
    for i, o in enumerate(require(spec, "objects", "")):
        build_object(o, i)

    os.makedirs(args.out, exist_ok=True)
    sc.render.filepath = os.path.join(os.path.abspath(args.out), "frame_####")
    bpy.ops.render.render(animation=True)

    ss = float(spec.get("shadow_strength", 1.0))
    if ss < 1.0:
        _scale_shadow_alpha(args.out, lo, hi, ss)

    if not args.no_webm and hi > lo:
        webm = args.out.rstrip("/") + ".webm"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(sc.render.fps),
                        "-start_number", str(lo), "-i", os.path.join(args.out, "frame_%04d.png"),
                        "-c:v", "libvpx", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0",
                        "-b:v", "8M", webm], check=True)
        print("webm:", webm)
    print("frames:", args.out)


def _scale_shadow_alpha(out, lo, hi, k):
    """Lighten caught shadows only: pixels that are pure shadow (near-black,
    partial alpha) get their alpha scaled; object pixels are untouched."""
    from PIL import Image
    import numpy as np
    for f in range(lo, hi + 1):
        p = os.path.join(out, f"frame_{f:04d}.png")
        a = np.array(Image.open(p)).astype(np.float32)
        shadow = (a[..., :3].max(-1) < 8) & (a[..., 3] < 250)
        a[..., 3][shadow] *= k
        Image.fromarray(a.clip(0, 255).astype(np.uint8)).save(p)


if __name__ == "__main__":
    main()
