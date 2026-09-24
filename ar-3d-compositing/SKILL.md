---
name: ar-3d-compositing
description: Insert simple 3D elements (cubes, bar charts, spheres, panels) into a real photo OR video so they appear to physically sit in the space — rendered in Blender with the real camera's orientation, lit to match the footage, casting REAL shadows onto the real floor/desk via a shadow catcher, and hidden behind real foreground objects or a moving person where appropriate. Use whenever the user wants 3D objects, charts, or motion-graphics elements "in my room", "on my desk", overlaid on a photo/video they upload, special-effects-style inserts, or an AR-style "put this in my ___" composite — including talking-head / presenter videos where someone gestures at the inserted element (see references/talking-head.md). Self-contained: renders its own 3D content; does not depend on any other skill.
---

# AR 3D Compositing

Takes a photo or video of a real space (the **plate**) and produces a
version where simple 3D elements appear to exist inside it: standing on
the real surface, lit from the same direction as the room, casting real
shadows onto that surface, and partly hidden behind whatever real objects
are closer to the camera.

The renderer is Blender (headless, via the `bpy` package). Nothing is
drawn in 2D after the fact — shadows come from an actual light hitting an
invisible **shadow-catcher** ground plane, so they have the right
direction, softness, and falloff for free.

## The look comes from the footage — there is no house style

This skill deliberately has no default palette, material, glow, or
overlay treatment, and `render_blender.py` refuses to run without explicit
colors and a light direction. Every shot is styled from its own plate:

- **Colors:** run `scripts/sample_palette.py` on the plate. Choose object
  colors from its harmonized suggestions (plus at most one accent for the
  element that should draw the eye). Scene-matched, slightly saturated
  solid materials are the baseline. If the user names colors or a brand
  palette, those win.
- **Light:** read the direction and softness from the real shadows in the
  plate (step 3). The light and ambient colors start from the palette
  script's suggestions.
- **Treatment:** plain physically-lit objects by default. Only add a
  stylized treatment (emissive/glowing, translucent, wireframe, labels,
  vignettes, scanlines) when the user asks for it — never as a default,
  and never carried over from a previous video.

State the chosen palette and light in one line before the first test
render so the user can redirect before anything expensive runs. When
making several videos in a row, vary composition, object choice, and
palette per shot rather than reusing the last spec.

## Requirements

- `bpy` in its own venv (bpy only ships for specific Python versions —
  currently 3.13 for Blender 5.x):
  ```bash
  uv venv -p 3.13 bpyenv && . bpyenv/bin/activate && uv pip install bpy pillow numpy
  ```
  Run `render_blender.py` inside that venv; everything else runs on the
  system Python.
- `Pillow` + `numpy` on the system Python; `ffmpeg` (already present).
- CPU rendering is fine for this kind of content: ~30 s per 960x540 frame
  at 16 samples on a single core. Budget accordingly and test on stills.

## Workflow

### 1. Normalize the plate

Phone photos carry EXIF rotation that `ffmpeg` doesn't always honor.
Normalize before picking any pixel coordinate:

```python
from PIL import Image, ImageOps
im = ImageOps.exif_transpose(Image.open(path))
im.convert("RGB").save("plate.jpg", quality=95)
```

For video, extract one representative frame
(`ffmpeg -ss 1 -i clip.mp4 -frames:v 1 frame.png`) to do steps 2-5 on.
Note the plate's exact resolution and frame rate — the render must match
both.

### 2. Recover the camera orientation

The render's camera must point the same way the real one did, or the
inserted objects' floor won't converge with the real floor. Recover it
from two sets of real-world-parallel lines visible in the plate:

```bash
python3 scripts/estimate_orientation.py --self-test   # confirms the math first
python3 scripts/estimate_orientation.py \
  --width 1920 --height 1080 --fov-deg 70 \
  --depth-line "x1,y1 x2,y2" --depth-line "x3,y3 x4,y4" \
  --vertical-line "x1,y1 x2,y2" --vertical-line "x3,y3 x4,y4" \
  --blender
```

`--depth-line`: two edges parallel in the real world along the surface's
depth axis (two desk edges, two floor seams), NEAR point first.
`--vertical-line`: two real-world-vertical edges (door jamb, monitor
bezel), BOTTOM point first. Pick lines from the SAME rigid object where
possible. `--blender` prints a ready-to-paste camera block for the scene
spec. `--fov-deg` is horizontal FOV — ~65-75 for phone main lenses and
webcams, ~100-120 for ultrawide; use the same value in the spec's
`hfov_deg`.

**Sanity-check the roll.** The script warns when the vertical-line result
implies much more roll than a zero-roll (pitch-only) baseline. If the
plate doesn't visibly look rotated by that amount, use the zero-roll `up`
it prints — one crooked reference object silently corrupts this axis.

**Camera height** (`camera.position[2]`, meters) sets scale: objects are
specified in meters, so a 1.1 m desk-shot camera makes a 0.2 m cube look
like a 0.2 m cube. Use a real estimate (seated eye level ~1.2 m, a phone
held over a desk ~0.4-0.6 m above it) or, better, a known-size reference
in frame (letter paper 0.216 x 0.279 m).

If there are no clean parallel lines, a level camera
(`forward [0,1,0]`, `up [0,0,1]`) with a pitch estimated from where the
horizon would sit is a workable fallback — confirm with a still.

### 3. Read the light from the plate

Find a real shadow in the plate (a mug, a laptop, a person's arm on the
desk). Its direction gives the light's `azimuth_deg` (the compass
direction the light comes FROM: 0 = from straight ahead/far side, 90 =
from the right, 180 = from behind the camera, 270 = from the left); its
length relative to the object's height gives `elevation_deg`
(`atan(height / shadow_length)`). Hard-edged shadows mean low
`softness_deg` (0.5-2); fuzzy window/overcast light means 5-15. If there
are no visible shadows at all, the scene is diffusely lit: use high
softness, lower sun strength, higher ambient.

### 4. Write the scene spec

JSON, documented in full at the top of `scripts/render_blender.py`.
Objects: `cube`, `sphere`, `panel`, `bar_chart` (with staggered grow-in).
All positions are meters on the ground plane (`location: [x, y]`, y =
distance away from the camera); objects stand on the surface unless given
a `height`. Keyframes animate location, height, rotation, and scale.

Place objects where there is actually open surface in the plate — use
`pixel_grid.py` (step 5) to see where that is, and remember y is depth:
larger y = farther away = smaller and higher in frame.

### 5. Test on stills

```bash
. bpyenv/bin/activate
python scripts/render_blender.py scene.json --out out/still --frames 45 45 --no-webm
deactivate
python3 scripts/composite_plate.py plate.jpg out/still/frame_0045.png --out test.png
```

Look at it. Check, in order: do objects sit ON the surface (not floating,
not sunk)? Does their floor convergence match the real floor? Do their
shadows point the same way as real shadows in the plate? Are they the
right size next to real objects? Iterate the spec; use `--scale 0.5` and
`--samples 8` for faster iteration.

Use `pixel_grid.py` for exact coordinates rather than eyeballing a
downscaled preview:

```bash
python3 scripts/pixel_grid.py plate.jpg --cx 1400 --cy 800 --size 600 --step 100 --out crop.png
```

### 6. Occlusion (anything real in front of the objects)

If a real object sits between the camera and an inserted element, cut it
back out of the plate and layer it on top. Static object in a static
shot: trace it with `pixel_grid.py` and build a cutout:

```bash
python3 scripts/build_occlusion_mask.py plate.jpg out/occlusion.png \
  --polygon "1195,1600 1500,1550 1600,1660 1580,1725 1330,1725 1195,1660"
```

A moving person (hands passing in front) needs per-frame occlusion — see
`references/talking-head.md`.

### 7. Full render and composite

```bash
. bpyenv/bin/activate
python scripts/render_blender.py scene.json --out out/render
deactivate
python3 scripts/composite_plate.py plate.jpg out/render out/occlusion.png --out final.mp4
# or over a video plate (keeps its audio):
python3 scripts/composite_plate.py clip.mp4 out/render --out final.mp4
```

`render_blender.py` writes a PNG sequence plus an alpha `.webm` (VP8);
verify alpha with `scripts/check_alpha.sh out/render.webm`. The composite
is a pixel-for-pixel overlay because the render already matches the
plate's camera and resolution. `--grain` (default 4) adds light noise so
clean CG matches camera noise; raise it for dim/noisy footage, set 0 for
clean studio plates. Verify the output by tiling a handful of frames
(`ffmpeg -i final.mp4 -vf "select='not(mod(n,15))',tile=4x2" -frames:v 1 check.png`)
and viewing it before presenting.

## Scope: fixed cameras only

Everything here assumes the camera does not move during the shot
(tripod, propped phone, webcam, or a still photo). One orientation solve
holds for every frame. A moving camera needs a per-frame camera solve
(e.g. MegaSaM or COLMAP on a GPU machine) exported as a camera path —
out of scope for this skill; don't fake it with a static camera over
moving footage, the objects will visibly slide.

## Neon / glowing objects (only when asked)

Give an object `"emission": {"color": "#3fb8ff", "strength": 9}` in the
spec to make it self-lit (it also stops casting a shadow). Cycles has no
bloom, so add the halo in 2D after rendering:

```bash
python3 scripts/add_glow.py plate.jpg out/render out/glow --color "#3fb8ff" --radii 12 40 120 --strength 1.6
```

This writes finished composited frames; encode them directly with ffmpeg.
For small objects on CPU, `render_blender.py --border X0 Y0 X1 Y1` renders
only that region (fractions, y from top) — often a 5x speedup.

## Other renders

`composite_ar.py` / `composite_test.py` remain for placing a
transparent render from some other tool that was NOT camera-matched to
the plate (scale + anchor placement by eye). Prefer the Blender path —
it gets tilt, scale, and shadows right by construction.

## Common pitfalls

- Skipping EXIF normalization — every coordinate afterward is wrong on a
  rotated photo.
- Render resolution not matching the plate — the overlay will be offset
  or scaled wrong. Set `resolution` to the plate's exact size.
- Mismatched `hfov_deg` between `estimate_orientation.py` and the spec —
  perspective will be subtly off; use the same number in both.
- Shadow direction disagreeing with real shadows in the plate — the
  single fastest "this is fake" tell. Check it on the first still.
- Objects floating: the ground plane is z = 0; anything with a `height`
  is lifted on purpose. For a desk shot, the camera height is measured
  from the desk surface, not the floor.
- Leaving `view_transform` on Filmic/AgX — colors picked from the footage
  come out washed. The script sets Standard; don't change it.
- Judging alpha from a bare `ffprobe` on a VP8 webm — it reports yuv420p
  even when alpha is present. Decode with `-c:v libvpx`
  (`check_alpha.sh` does this).
- Rendering full video to test a placement tweak — always stills first.
- Reusing the previous shot's palette or layout. Each plate gets its own.
