#!/usr/bin/env python3
"""
Pull a color palette from the actual footage so every shot's 3D elements
are chosen from what's already in frame, instead of a house style.

    python3 sample_palette.py plate.jpg            # a photo or an extracted frame
    python3 sample_palette.py clip.mp4 --at 2.5    # grabs the frame at 2.5 s

Prints:
  - dominant scene colors (k-means over the frame), with their share of
    the image, plus average brightness and warm/cool balance — use these
    for the light "color"/"ambient_color" and to judge how saturated the
    inserted objects can be before they look pasted on
  - suggested object colors: each dominant color nudged in saturation and
    lightness (harmonizing), plus one complementary accent derived from
    the most saturated scene color (for the one element that should pop)

This is a starting point, not a rule: pick from it, and if the user asked
for specific colors (brand colors, "make it red"), those win.
"""
import argparse
import colorsys
import os
import subprocess
import tempfile

import numpy as np
from PIL import Image


def frame_from(path, at):
    if path.lower().endswith((".mp4", ".mov", ".m4v", ".webm", ".mkv")):
        out = os.path.join(tempfile.mkdtemp(), "f.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", path, "-frames:v", "1", out], check=True)
        path = out
    return Image.open(path).convert("RGB")


def kmeans(px, k, iters=20, seed=0):
    rng = np.random.default_rng(seed)
    c = px[rng.choice(len(px), k, replace=False)]
    for _ in range(iters):
        lab = ((px[:, None] - c[None]) ** 2).sum(-1).argmin(1)
        c = np.array([px[lab == i].mean(0) if (lab == i).any() else c[i] for i in range(k)])
    counts = np.bincount(lab, minlength=k).astype(float)
    order = counts.argsort()[::-1]
    c, counts = c[order], counts[order]
    # merge near-duplicate clusters (a mostly one-tone frame otherwise
    # returns six shades of the same color)
    keep_c, keep_n = [], []
    for ci, ni in zip(c, counts):
        for j, kc in enumerate(keep_c):
            if np.linalg.norm(ci - kc) < 28:
                keep_n[j] += ni
                break
        else:
            keep_c.append(ci); keep_n.append(ni)
    n = np.array(keep_n)
    return np.array(keep_c), n / n.sum()


def hexc(rgb):
    return "#%02x%02x%02x" % tuple(int(round(max(0, min(255, v)))) for v in rgb)


def adjust(rgb, sat_mul=1.0, light=None, hue_shift=0.0):
    h, l, s = colorsys.rgb_to_hls(*(np.array(rgb) / 255))
    h = (h + hue_shift) % 1.0
    s = min(1.0, s * sat_mul)
    if light is not None:
        l = light
    return np.array(colorsys.hls_to_rgb(h, l, s)) * 255


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--at", type=float, default=0.0, help="seconds into a video to sample")
    ap.add_argument("-k", type=int, default=6)
    args = ap.parse_args()

    im = frame_from(args.source, args.at)
    im.thumbnail((320, 320))
    px = np.asarray(im, dtype=np.float64).reshape(-1, 3)
    cents, share = kmeans(px, args.k)

    lum = (px @ [0.2126, 0.7152, 0.0722]).mean() / 255
    warm = (px[:, 0].mean() - px[:, 2].mean()) / 255
    print(f"scene brightness: {lum:.2f}   warm/cool balance: {warm:+.2f} ({'warm' if warm > 0.03 else 'cool' if warm < -0.03 else 'neutral'})")
    print("\ndominant scene colors:")
    sats = []
    for c, s in zip(cents, share):
        h, l, sat = colorsys.rgb_to_hls(*(c / 255))
        sats.append(sat)
        print(f"  {hexc(c)}  {s*100:4.1f}%  (lightness {l:.2f}, saturation {sat:.2f})")

    print("\nsuggested object colors (harmonized with the scene):")
    for c in cents[:4]:
        print(f"  {hexc(adjust(c, sat_mul=1.35, light=0.42))}   {hexc(adjust(c, sat_mul=1.2, light=0.6))}")
    vivid = cents[int(np.argmax(sats))]
    print("\naccent (complement of the most saturated scene color):")
    print(f"  {hexc(adjust(vivid, sat_mul=1.6, light=0.5, hue_shift=0.5))}")
    print(f"\nlight color starting point: {hexc(adjust(cents[0], sat_mul=0.25, light=0.94))}"
          f"   ambient starting point: {hexc(adjust(cents[0], sat_mul=0.2, light=0.85))}")


if __name__ == "__main__":
    main()
