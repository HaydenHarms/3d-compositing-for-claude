#!/usr/bin/env python3
"""
Neon bloom for emissive renders. Cycles has no bloom, so glow is added in 2D:
the render's bright pixels are blurred at several radii and SCREEN-blended
over the plate, then the sharp render goes on top. The core blows out toward
white and a colored halo spills onto the surroundings.

    python3 add_glow.py plate.jpg out/render out/glow --color "#3fb8ff" --radii 12 40 120 --strength 1.6

Writes composited frame_####.png files (RGB) into the output directory.
"""
import argparse, glob, os
import numpy as np
from PIL import Image, ImageFilter

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plate"); ap.add_argument("render"); ap.add_argument("out")
    ap.add_argument("--color", required=True, help="halo tint, e.g. #3fb8ff")
    ap.add_argument("--radii", nargs="+", type=float, default=[12, 40, 120], help="blur radii in plate pixels")
    ap.add_argument("--strength", type=float, default=1.5)
    ap.add_argument("--core", type=float, default=0.6, help="0-1, pushes the object's core toward white")
    a = ap.parse_args()
    plate = Image.open(a.plate).convert("RGB")
    P = np.asarray(plate, np.float32) / 255
    tint = np.array([int(a.color[i:i+2], 16) / 255 for i in (1, 3, 5)], np.float32)
    frames = sorted(glob.glob(os.path.join(a.render, "frame_*.png"))) if os.path.isdir(a.render) else [a.render]
    os.makedirs(a.out, exist_ok=True)
    for f in frames:
        r = Image.open(f).convert("RGBA").resize(plate.size, Image.LANCZOS)
        R = np.asarray(r, np.float32) / 255
        al = R[..., 3:4]
        # only the lit object blooms, not caught shadows (dark, partial alpha)
        lum = R[..., :3].max(-1, keepdims=True)
        src = al * lum
        glow = np.zeros_like(P)
        for rad in a.radii:
            g = Image.fromarray((src[..., 0] * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(rad))
            glow += (np.asarray(g, np.float32)[..., None] / 255) * tint
        glow = np.clip(glow * a.strength / len(a.radii) * 2, 0, 1)
        out = 1 - (1 - P) * (1 - glow)                      # screen
        obj = R[..., :3] + (1 - R[..., :3]) * a.core * lum  # hot core
        out = out * (1 - al) + np.maximum(obj, out) * al
        Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8)).save(os.path.join(a.out, os.path.basename(f)))

if __name__ == "__main__":
    main()
