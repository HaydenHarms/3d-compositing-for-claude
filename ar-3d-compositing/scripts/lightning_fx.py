#!/usr/bin/env python3
"""
Procedural "force lightning" asset: branching electric bolts streaming out of
a fan of fingertip origin points, rendered on a TRANSPARENT background as a
seamless loop. Output: PNG sequence (straight RGBA), alpha .webm (VP8),
.mov (ProRes 4444, alpha), and a preview GIF on black.

    python3 lightning_fx.py --out out/lightning --frames 48 --fps 24

Origins sit on the left edge and bolts travel right; flip/rotate the asset in
your editor to aim it. Place the origin points over the fingertips.
"""
import argparse, math, os, random, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

def bolt(rng, p0, p1, depth, rough):
    """Midpoint-displacement bolt from p0 to p1 -> list of points."""
    pts = [p0, p1]
    disp = rough * math.dist(p0, p1)
    for _ in range(depth):
        new = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy) or 1
            o = rng.uniform(-disp, disp)
            new += [(mx - dy / L * o, my + dx / L * o), b]
        pts = new
        disp *= 0.55
    return pts

def draw_frame(W, H, origins, rng, reach, intensity):
    core = Image.new("L", (W, H)); cd = ImageDraw.Draw(core)
    for (ox, oy), fan in origins:
        for _ in range(rng.randint(1, 3)):                     # main bolts per finger
            ang = fan + rng.uniform(-0.35, 0.35)
            L = reach * rng.uniform(0.55, 1.0)
            end = (ox + math.cos(ang) * L, oy + math.sin(ang) * L)
            pts = bolt(rng, (ox, oy), end, 7, 0.22)
            w = rng.choice([3, 4, 5])
            cd.line(pts, fill=255, width=w, joint="curve")
            for _ in range(rng.randint(2, 6)):                 # forks
                i = rng.randint(len(pts) // 6, len(pts) - 2)
                s = pts[i]
                a2 = ang + rng.uniform(-0.9, 0.9)
                l2 = L * rng.uniform(0.12, 0.4)
                e2 = (s[0] + math.cos(a2) * l2, s[1] + math.sin(a2) * l2)
                cd.line(bolt(rng, s, e2, 5, 0.3), fill=200, width=max(1, w - 2), joint="curve")
        r = 10 + 6 * intensity                                   # hot spot at the fingertip
        cd.ellipse([ox - r, oy - r, ox + r, oy + r], fill=255)
    C = np.asarray(core, np.float32) / 255
    blur = lambda rad: np.asarray(core.filter(ImageFilter.GaussianBlur(rad)), np.float32) / 255
    g1, g2, g3 = blur(4), blur(14), blur(40)
    white = np.clip(C * 1.2, 0, 1)
    blue = np.array([0.45, 0.62, 1.0]); violet = np.array([0.55, 0.35, 1.0])
    rgb = (white[..., None] * 1.0
           + g1[..., None] * blue * 2.2
           + g2[..., None] * blue * 1.6
           + g3[..., None] * violet * 1.4) * intensity
    rgb = np.clip(rgb, 0, 1)
    a = np.clip(rgb.max(-1), 0, 1)                             # additive light -> alpha from brightness
    col = np.where(a[..., None] > 1e-4, rgb / np.maximum(a[..., None], 1e-4), 0)
    return np.dstack([col, a])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/lightning")
    ap.add_argument("--size", nargs=2, type=int, default=[1920, 1080])
    ap.add_argument("--frames", type=int, default=48)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--hold", type=int, default=2, help="frames each bolt shape holds (2 = crackly)")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    W, H = a.size
    # five fingertips in a loose fan on the left, each with its own aim
    origins = [((260, 330), -0.30), ((300, 450), -0.12), ((310, 560), 0.02),
               ((290, 670), 0.15), ((230, 800), 0.32)]
    s = W / 1920
    origins = [((x * s, y * s), f) for (x, y), f in origins]
    os.makedirs(a.out, exist_ok=True)
    master = random.Random(a.seed)
    seeds = [master.randrange(1 << 30) for _ in range(math.ceil(a.frames / a.hold))]
    for f in range(a.frames):
        rng = random.Random(seeds[f // a.hold])
        # pulse is periodic over the loop so first and last frames match in energy
        inten = 0.85 + 0.15 * math.sin(2 * math.pi * f / a.frames * 3) + (0.1 if f % a.hold == 0 else 0)
        img = draw_frame(W, H, origins, rng, reach=W * 0.62, intensity=inten)
        Image.fromarray((img * 255).astype(np.uint8), "RGBA").save(f"{a.out}/frame_{f + 1:04d}.png")
    base = a.out.rstrip("/")
    seq = os.path.join(a.out, "frame_%04d.png")
    run = lambda *c: subprocess.run(["ffmpeg", "-v", "error", "-y", *c], check=True)
    run("-framerate", str(a.fps), "-i", seq, "-c:v", "libvpx", "-pix_fmt", "yuva420p",
        "-auto-alt-ref", "0", "-b:v", "12M", base + ".webm")
    run("-framerate", str(a.fps), "-i", seq, "-c:v", "prores_ks", "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le", base + ".mov")
    run("-framerate", str(a.fps), "-i", seq, "-filter_complex",
        "color=black:s=%dx%d[bg];[bg][0]overlay=shortest=1,scale=960:-1,split[x][y];"
        "[x]palettegen[p];[y][p]paletteuse" % (W, H), "-loop", "0", base + "-preview.gif")
    print("done:", base)

if __name__ == "__main__":
    main()
