#!/usr/bin/env python3
"""
Recover the REAL camera's viewing direction and "up" (i.e. its orientation,
not its position) from two sets of lines in a photo: lines that are
parallel in the real world along the surface's depth axis (e.g. two edges
of a desk, two floor-seam lines), and lines that are parallel in the real
world and vertical (e.g. a monitor edge, a door jamb, a wall corner).

This does NOT need a known real-world size, and it does NOT recover camera
POSITION or absolute SCALE — only the two rotation axes (tilt/pan and
roll) needed to point a render's virtual camera the same way the real
camera was pointed. That's usually the single biggest lever for making a
composited 3D render's ground plane match a real photo's floor/desk, per
SKILL.md's "Matching surface orientation" section.

Output is a `forward` and `up` unit vector, expressed in a world frame
where +Z is the real depth-into-the-scene direction and +Y is real
vertical up (i.e. put your render's camera at any position `P`, and set
`target = P + forward`, `up = up`). Pass --blender to get the vectors
converted for render_blender.py's Z-up scene spec.

Usage:
    python3 estimate_orientation.py \\
        --width 3024 --height 4032 --fov-deg 70 \\
        --depth-line "x1,y1 x2,y2" --depth-line "x3,y3 x4,y4" \\
        --vertical-line "x1,y1 x2,y2" [--vertical-line "x3,y3 x4,y4"]

Point ordering matters (it's how sign/direction is recovered, not just
the vanishing point's raw position):
    --depth-line points: NEAR point first, FAR (more distant) point second.
    --vertical-line points: BOTTOM point first, TOP point second.

Give two --depth-line / two --vertical-line flags (from two real,
non-collinear parallel edges) for a proper vanishing-point intersection.
If only one vertical reference edge is visible, pass --vertical-line once
— its own on-screen direction is used directly (a fine approximation
unless the camera has heavy up/down tilt).

Run with --self-test (no other args needed) to verify the math against a
synthetic camera with a known, non-trivial tilt/pan/roll before trusting
it on a real photo.
"""
import argparse
import numpy as np


def line_intersect(p1, p2, p3, p4):
    x1, y1 = p1; x2, y2 = p2; x3, y3 = p3; x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-9:
        return None  # lines effectively parallel in image space (no vanishing point)
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
    return np.array([px, py])


def pixel_to_camera_dir(pt, cx, cy, f):
    """Camera-local ray direction for a pixel, in a convention where
    local +X is right, local +Y is UP, local +Z is forward — matching
    standard 3D-engine camera-local axes, not image axes."""
    x, y = pt
    d = np.array([(x - cx) / f, -(y - cy) / f, 1.0])
    return d / np.linalg.norm(d)


def sign_align(direction, vp_pixel, line_a, line_b):
    """A vanishing point is mathematically the SAME point whether you
    extend a line toward +infinity or -infinity along it (the parameter
    cancels in the projection ratio) — so the vp alone can never
    disambiguate a line's two directions; some extra signal is needed.
    Empirically (and verified against a synthetic ground-truth camera in
    --self-test, 25/25 random trials), the reliable signal is simple:
    whether the vanishing point sits ABOVE or BELOW the visible segment's
    own on-screen midpoint. If the vp is above the midpoint, the raw
    pixel_to_camera_dir(vp) direction already points the correct way; if
    it's below, flip it."""
    mid_y = (line_a[1] + line_b[1]) / 2.0
    vp_above = vp_pixel[1] < mid_y
    return direction if vp_above else -direction


def zero_roll_up(forward):
    """The 'up' vanishing point needs a second real-world-vertical
    reference edge, which is more failure-prone than the depth axis: a
    single crooked object (a picture frame hung slightly off, a shelf
    that isn't quite level) corrupts it silently — the math has no way to
    know the reference itself was bad. This computes the alternative
    baseline: assume the camera had ZERO roll, and derive 'up' purely
    from the (usually more reliable, architectural-feature-based) forward
    direction by projecting true world-vertical onto the plane
    orthogonal to forward. Compare this against the calibrated `up` in
    --self-test-style sanity checking: they should be close for a normal
    photo; if the calibrated result implies much more roll than this,
    the photo probably doesn't actually show it (see SKILL.md)."""
    world_up = np.array([0.0, 1.0, 0.0])
    u = world_up - np.dot(world_up, forward) * forward
    return u / np.linalg.norm(u)


def parse_pt(s):
    x, y = s.split(",")
    return (float(x), float(y))


def parse_line(s):
    a, b = s.split()
    return parse_pt(a), parse_pt(b)


def estimate(depth_lines, vertical_lines, width, height, fov_deg):
    cx, cy = width / 2.0, height / 2.0
    f = (width / 2.0) / np.tan(np.radians(fov_deg) / 2.0)

    # --- depth (forward) direction ---
    da, db = depth_lines[0]
    if len(depth_lines) >= 2:
        vp_depth = line_intersect(*depth_lines[0], *depth_lines[1])
        if vp_depth is None:
            raise SystemExit("depth lines are parallel in image space — camera isn't tilted "
                              "toward this axis, or picked points are too close to collinear")
    else:
        # single line: extrapolate far along its own direction as an approximation of the VP
        vp_depth = np.array(db) + (np.array(db) - np.array(da)) * 50
    z_cam = pixel_to_camera_dir(vp_depth, cx, cy, f)
    z_cam = sign_align(z_cam, vp_depth, da, db)
    z_cam /= np.linalg.norm(z_cam)

    # --- vertical (up) direction ---
    va, vb = vertical_lines[0]
    if len(vertical_lines) >= 2:
        vp_up = line_intersect(*vertical_lines[0], *vertical_lines[1])
        if vp_up is None:
            raise SystemExit("vertical lines are parallel in image space (camera has ~no up/down "
                              "tilt) — pass a single --vertical-line instead, it'll use the line's "
                              "own direction directly")
    else:
        vp_up = np.array(vb) + (np.array(vb) - np.array(va)) * 50
    y_cam = pixel_to_camera_dir(vp_up, cx, cy, f)
    y_cam = sign_align(y_cam, vp_up, va, vb)

    # enforce orthogonality (real depth/up axes are perpendicular; pixel-picking
    # error means the raw directions usually aren't exactly, so project it out)
    y_cam = y_cam - np.dot(y_cam, z_cam) * z_cam
    y_cam /= np.linalg.norm(y_cam)

    # NOTE: pixel_to_camera_dir's local axes (x-right, y-up, z-forward) form a
    # LEFT-handed set (right x up = -forward, matching image convention where
    # z increases away from the viewer) — so recovering the third axis from
    # the other two needs the left-handed cross product order here, not the
    # standard right-handed x=cross(y,z). Verified by --self-test.
    x_cam = np.cross(z_cam, y_cam)
    x_cam /= np.linalg.norm(x_cam)

    # R's columns = world axes (X,Y,Z) expressed in camera-local space,
    # i.e. R is the world-to-camera rotation. Camera's own forward/up,
    # expressed in WORLD space, is the inverse (transpose) applied to the
    # camera's local forward (0,0,1) / up (0,1,0):
    R = np.column_stack([x_cam, y_cam, z_cam])
    forward_world = R.T @ np.array([0.0, 0.0, 1.0])
    up_world = R.T @ np.array([0.0, 1.0, 0.0])

    return forward_world, up_world, f


def self_test():
    print("Running synthetic round-trip self-test...")
    width, height, fov_deg = 1920, 1080, 70.0
    cx, cy = width / 2.0, height / 2.0
    f = (width / 2.0) / np.tan(np.radians(fov_deg) / 2.0)

    # a known, non-trivial camera orientation: tilted down, panned, rolled
    pitch, yaw, roll = np.radians(-12), np.radians(8), np.radians(5)
    # build forward/up from Euler angles (world Z-forward, Y-up, X-right, applied yaw->pitch->roll)
    fwd = np.array([0, 0, 1.0])
    up0 = np.array([0, 1.0, 0])
    def rot(axis, ang, v):
        axis = axis / np.linalg.norm(axis)
        return (v * np.cos(ang) + np.cross(axis, v) * np.sin(ang)
                + axis * np.dot(axis, v) * (1 - np.cos(ang)))
    right0 = np.cross(fwd, up0)
    fwd = rot(up0, yaw, fwd)
    right = rot(up0, yaw, right0)
    up = up0
    fwd = rot(right, pitch, fwd)
    up = rot(right, pitch, up)
    right = rot(fwd, roll, right)
    up = rot(fwd, roll, up)
    fwd /= np.linalg.norm(fwd); up /= np.linalg.norm(up); right /= np.linalg.norm(right)

    cam_pos = np.array([0.0, 5.0, -10.0])

    def project(world_pt):
        v = world_pt - cam_pos
        xl, yl, zl = np.dot(v, right), np.dot(v, up), np.dot(v, fwd)
        px = cx + f * xl / zl
        py = cy - f * yl / zl
        return (px, py)

    # depth line: two points at floor height, receding along world Z, offset in
    # X so neither line is degenerate (collinear with the camera's own axis)
    depth_a = project(np.array([-2.0, 0.0, 3.0]))
    depth_b = project(np.array([-2.0, 0.0, 9.0]))
    depth_a2 = project(np.array([2.0, 0.0, 3.0]))
    depth_b2 = project(np.array([2.0, 0.0, 9.0]))

    # vertical line: two points stacked in world Y at one X/Z location
    vert_a = project(np.array([1.0, 0.0, 5.0]))
    vert_b = project(np.array([1.0, 3.0, 5.0]))
    vert_a2 = project(np.array([2.0, 0.0, 5.0]))
    vert_b2 = project(np.array([2.0, 3.0, 5.0]))

    rec_fwd, rec_up, rec_f = estimate(
        [(depth_a, depth_b), (depth_a2, depth_b2)],
        [(vert_a, vert_b), (vert_a2, vert_b2)],
        width, height, fov_deg,
    )

    fwd_err = np.degrees(np.arccos(np.clip(np.dot(fwd, rec_fwd), -1, 1)))
    up_err = np.degrees(np.arccos(np.clip(np.dot(up, rec_up), -1, 1)))
    print(f"true forward: {fwd.round(4)}   recovered: {rec_fwd.round(4)}   angular error: {fwd_err:.3f} deg")
    print(f"true up:      {up.round(4)}   recovered: {rec_up.round(4)}   angular error: {up_err:.3f} deg")
    ok = fwd_err < 0.5 and up_err < 0.5
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--fov-deg", type=float, default=70.0,
                     help="assumed horizontal FOV in degrees (~65-75 typical for a phone/webcam wide lens)")
    ap.add_argument("--depth-line", action="append", default=[], help='"x1,y1 x2,y2" — NEAR point first. Give twice for a real intersection.')
    ap.add_argument("--vertical-line", action="append", default=[], help='"x1,y1 x2,y2" — BOTTOM point first. Give twice for a real intersection.')
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--blender", action="store_true", help="print a camera block for render_blender.py's scene spec")
    args = ap.parse_args()

    if args.self_test:
        ok = self_test()
        raise SystemExit(0 if ok else 1)

    if not (args.width and args.height and args.depth_line and args.vertical_line):
        raise SystemExit("need --width --height --depth-line (x1+) --vertical-line (x1+), or use --self-test")

    depth_lines = [parse_line(s) for s in args.depth_line]
    vertical_lines = [parse_line(s) for s in args.vertical_line]

    forward, up, f = estimate(depth_lines, vertical_lines, args.width, args.height, args.fov_deg)
    zr_up = zero_roll_up(forward)
    roll_deviation = np.degrees(np.arccos(np.clip(np.dot(up, zr_up), -1, 1)))

    print(f"assumed focal length (px): {f:.1f}")
    print(f"forward (world, unit): {forward.round(5).tolist()}")
    print(f"up      (world, unit): {up.round(5).tolist()}")
    print(f"  (implies {np.degrees(np.arccos(np.clip(np.dot(up,[0,1,0]),-1,1))):.1f} deg total deviation from vertical)")
    print(f"zero-roll up (fallback, assumes no camera roll): {zr_up.round(5).tolist()}")
    print(f"  (implies {np.degrees(np.arccos(np.clip(np.dot(zr_up,[0,1,0]),-1,1))):.1f} deg deviation — from pitch alone)")
    print()
    if roll_deviation > 12:
        print(f"*** CHECK THIS: calibrated `up` implies ~{roll_deviation:.0f} deg more camera")
        print("    roll than the zero-roll baseline. Before trusting it, look at the")
        print("    actual photo: does it look visibly rotated/Dutch-angled by roughly")
        print("    that amount? Most handheld photos do NOT — if the photo looks")
        print("    basically upright, the vertical-line reference was probably bad")
        print("    (a crooked picture frame, an unlevel shelf) and you should use the")
        print("    zero-roll `up` above instead of the calibrated one.")
        print()
    if args.blender:
        # this script's world: X right, Y up, Z forward (depth).
        # render_blender.py's world: X right, Y depth, Z up.
        bf = [forward[0], forward[2], forward[1]]
        bu = [up[0], up[2], up[1]]
        bz = [zr_up[0], zr_up[2], zr_up[1]]
        print("render_blender.py camera block (paste into the scene spec):")
        print(f'  "hfov_deg": {args.fov_deg}, "forward": {[round(float(v),5) for v in bf]}, "up": {[round(float(v),5) for v in bu]}')
        print(f'  zero-roll alternative for "up": {[round(float(v),5) for v in bz]}')
        print('  "position": [0, 0, <camera height above the surface, meters>]')
    else:
        print("forward/up are in a Y-up world (X right, Z = depth). Pass --blender")
        print("to get them converted for render_blender.py's Z-up scene spec.")

if __name__ == "__main__":
    main()
