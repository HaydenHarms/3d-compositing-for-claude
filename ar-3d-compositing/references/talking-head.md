# Talking-head / presenter variant

For a video where a person (hands, body) is filmed interacting with
inserted 3D elements — "I'm gesturing and the chart/objects respond" —
two things change from the static-room-photo case the main
SKILL.md workflow was built around, one in your favor and one that's a
genuinely different, harder problem.

## What's easier here: the camera is fixed

A talking-head setup is a tripod or webcam at a fixed position for the
whole shot. That means **calibrate once, valid for the entire video** —
same as the static photo case, not the much harder "camera moves through
the scene" AR problem. Run `estimate_orientation.py` (main SKILL.md, step
2) once against a single representative frame, and the resulting
`forward`/`up` holds for every frame of the render.

This also means a **desk setup usually gives you a better calibration
target than an empty room does.** A swung-open door (the static-room
example in the main SKILL.md) couldn't serve as a flat reference. A desk
edge, a laptop, or — best of all — a sheet of standard printer paper
(8.5"x11", a size everyone actually knows precisely) sitting in frame is
a genuinely reliable, fully-visible, known-size flat reference. If one's
available, this is a legitimate case for going beyond orientation-only
matching (main SKILL.md step 2's camera-height note) into real
position/scale calibration — worth the extra step here specifically
because of what's below.

## Why scale matters more here than in an empty room

In a static room photo, a viewer has no precise mental ruler for "is that
inserted object exactly the right size" — a scale mismatch of even 20-30% often
just reads as artistic license. Put a hand directly next to the model and
that stops being true immediately: hands are a universal, extremely
well-calibrated size reference every viewer already carries. Any scale
error becomes obvious the moment fingers approach the object. This is
the practical reason to prefer a real measured reference (paper, card,
laptop bezel) over eyeballed scale for this use case specifically — the
tolerance for error is much smaller.

## What's harder here: the subject moves

The existing occlusion approach (`build_occlusion_mask.py`, main
SKILL.md step 6) hand-traces ONE static polygon and reuses it for the
whole video — that only works because the box and the propped-open bed
rail in the reference room photo don't move. Hands moving in and out of
the objects' space need occlusion recomputed **every single frame**,
which a static polygon fundamentally cannot do.

### Default: chroma key (green/blue screen)

If you have any control over the shoot, this is the recommended default,
not a fallback — it turns "recompute a moving person's silhouette every
frame" into a solved, deterministic problem instead of an estimated one.
Film the person against a solid color screen; every frame, any pixel
matching that color becomes transparent, and the 3D render sits
*behind* that layer:

```bash
python3 scripts/chroma_key_composite.py subject.mp4 render.webm out/final.mp4 \
    --background room.jpg --key-color 0x00FF00 --similarity 0.18 --blend 0.08
```

Layer order (back to front): background photo/color → transparent
3D render → subject with the key color removed. Wherever a hand
passes in front of where the 3D elements are, the subject layer (opaque,
real pixels) simply wins — no estimation involved. Tested against a
synthetic key/composite in this skill's own validation; on a real clip,
check a still frame first and tune `--similarity`/`--blend`:
raise `--similarity` if key color survives at hair/edges, lower it if
part of the subject gets keyed out along with the background.

### Fallback: ML person/hand segmentation (no green screen)

If a physical screen genuinely isn't an option, per-frame person
segmentation (e.g. `mediapipe`'s selfie/hand segmentation, or `rembg`)
can substitute for a hard key. Be aware going in, though — this is
guidance, not a validated pipeline the way the rest of this skill's
scripts are:

- Model downloads may hit network restrictions in a sandboxed
  environment (mediapipe's models often come from Google's CDN, which
  may not be reachable; `rembg`'s U2Net weights come from GitHub
  releases, more likely to work). Verify the model actually downloads
  before building anything on top of it.
- Segmentation edges — especially fingers — are the hardest case for
  these models and are usually **temporally unstable**: the matte edge
  flickers frame to frame even when the hand isn't moving much, which
  reads as far more distracting on video than a slightly-imprecise but
  *stable* hand-traced polygon would in the static case. A wobbly matte
  around fingers is often more noticeable than the occlusion problem it's
  solving.
- If you go this route, budget time to smooth the matte temporally
  (e.g. a short rolling average across frames on the alpha channel)
  rather than using each frame's raw segmentation output directly.

Prefer the green screen whenever the shoot allows it — it's the
difference between a solved problem and an estimated one.

## Mapping a multi-beat animation to a gesture sequence

If the source animation has more than one distinct story beat (a value
rising, then something arriving and landing, then something being
refined/constrained, then a closing reveal — most explainer animations do), and the person's video has more
than one distinct gesture, **default to using the whole story, not one
clip padded with holds and fades.** A single clip that appears, holds,
and vanishes reads as "a bar," not a walkthrough — the fuller version,
where each gesture triggers the next beat, is barely more work and is
what actually answers "I want a walkthrough" instead of "I want a
proof that compositing works." Scope down to one clip only when the
person's video genuinely has just one gesture to hang it on.

**Find gesture boundaries by inspection, not by feel.** Extract the
talking-head video at a higher framerate than its native rate (e.g. 10fps
against a 30fps source) and look through it — gesture transitions are
almost always tighter or looser than they feel watching at native speed.
Write down the actual start/end timestamp of each distinct motion (a
raise, a hand closing, a hold, an opening, a drop) before touching any
compositing code.

**Match beats to gestures by semantic shape, not by chronological
order.** Read what each beat of the source animation actually depicts,
and pick the gesture whose *shape* matches it — a hand closing into a
fist reads as committing/solidifying, which is a good match for
something arriving and landing; a hand opening or pinching reads as
refining/adjusting, a good match for a value being constrained or
trimmed down; a drop reads as concluding. Read beat frame ranges from the scene spec's keyframes (they are
the render's real frame numbers) rather than guessing from the rendered
video.

**Build one continuous piecewise timeline, not separate clips cut
together.** `scripts/gesture_remap.py` takes a list of
`(video_time, source_frame)` breakpoints and linearly interpolates the
source-render frame to show between each pair — consecutive breakpoints
with the *same* source frame become a hold (matching a gesture-hold in
the video), and the transition from a hold back into motion is seamless
because it's the same underlying timeline, not a re-triggered clip. This
is what makes "chunk lands, holds through the fist, ceiling appears and
it clamps down as the hand opens" read as one action instead of three
cuts. Before trusting a hold point, check that the frame just before it
and the frame just after visually match (same values, same state) — if
the source animation is still changing something else (a caption fading,
a counter still ticking) at that exact frame, the hold will visibly
"catch" mid-transition.

```bash
python3 scripts/gesture_remap.py \
  --source-render out/render.webm --source-decoder libvpx \
  --source-frame-range 60 419 \
  --crop 770,0,1380,760 \
  --background talking_head.mp4 \
  --breakpoints breakpoints.txt \
  --target-width 190 --place 5,10 \
  --fade-in 2.0,2.2 \
  --out final.mp4
```

This handles the full pipeline in one call — including extracting the
needed source frame range with alpha and background video frames, so you
don't have to juggle temp directories by hand. It also absorbs a real
gotcha: `ffmpeg -vf select=... -vsync 0` renumbers extracted frames
sequentially from 1, it does **not** preserve the original render's frame
numbers — get this wrong doing it by hand and you'll silently (or, if
you're lucky, loudly via a `FileNotFoundError`) composite the wrong
frames. The script tracks this offset internally so your breakpoints file
can just reference the original render's real frame numbers.

**Locating the crop region precisely, on a translucent render, needs a
different approach than on a photo.** `pixel_grid.py` now auto-flattens
RGBA input (a rendered alpha-channel frame) onto a solid background
before drawing the grid — do this rather than eyeballing a downscaled
preview of the raw transparent frame. A photographed object has a crisp
edge that survives downscaling; a rendered object's edge is often a soft
gradient over translucent fill, and misjudging it by hundreds of pixels
this way is easy (confirmed directly — a column's true edge was off by
~300px from a first read).

## Putting it together

1. Calibrate orientation once (main SKILL.md step 2) against a
   representative frame — camera doesn't move, so this holds for the
   whole video.
2. If a known-size flat reference is in frame, solve real scale/position
   too (worth it here — see "why scale matters more," above); otherwise
   place by eye as usual, but check scale specifically against where a
   hand will be, not just against the room in general.
3. Build the scene spec and render with `render_blender.py` (main
   SKILL.md steps 3-7) using the calibrated camera block. On a green-
   screen shoot there's no real surface behind the person, so caught
   shadows land on whatever backdrop plate you composite in — set the
   light direction to match that backdrop.
4. If the source animation has multiple story beats and the gesture
   video has multiple distinct motions, map the whole story across them
   (see "Mapping a multi-beat animation," above) — don't default to a
   single clip unless the gesture video only supports one.
5. Composite with `chroma_key_composite.py` if you have a green screen
   (strongly preferred); otherwise fall back to per-frame ML segmentation
   with the caveats above, or `gesture_remap.py`'s simple crop-and-place
   compositing if occlusion isn't needed for the shot.
6. Iterate on stills before a full render, same discipline as everywhere
   else in this skill — pull a frame where a hand should be crossing the
   objects and check the occlusion looks right before rendering the rest.
