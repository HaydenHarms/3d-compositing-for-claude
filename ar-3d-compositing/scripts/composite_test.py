#!/usr/bin/env python3
"""
Composite ONE transparent render still onto a photo, for fast placement
iteration before committing to a full video render. Run this against a
handful of transparent still frames spanning the animation before doing
anything expensive.

Usage:
    python3 composite_test.py room.jpg frame.png \\
        --scale 0.9 --anchor-frac-x 0.5 --anchor-frac-y 0.78 --out test.png

--scale: render width as a fraction of the photo's width.
--anchor-frac-x/-y: where the render's horizontal-center / BOTTOM edge
    should land, as a fraction of the photo's width/height. Tune
    anchor-frac-y against where the real floor/surface actually is in
    the photo, not a guess — use pixel_grid.py to find it precisely.
"""
import argparse
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("frame", help="transparent PNG still (any renderer)")
    ap.add_argument("--scale", type=float, default=0.9, help="render width as fraction of photo width")
    ap.add_argument("--anchor-frac-x", type=float, default=0.5)
    ap.add_argument("--anchor-frac-y", type=float, default=0.78, help="fraction down the photo the render's BOTTOM edge lands on")
    ap.add_argument("--out", default="composite_test.png")
    args = ap.parse_args()

    room = Image.open(args.photo).convert("RGB")
    fg = Image.open(args.frame).convert("RGBA")
    if fg.mode == "RGBA":
        alpha = fg.split()[-1]
        if alpha.getextrema() == (255, 255):
            print("WARNING: this frame has no transparency (alpha is fully opaque everywhere). "
                  "Did you render with --image-format=png and a transparent AbsoluteFill background?")

    w = int(room.width * args.scale)
    h = int(w * fg.height / fg.width)
    fg_r = fg.resize((w, h))

    x = int(room.width * args.anchor_frac_x) - w // 2
    y = int(room.height * args.anchor_frac_y) - h

    comp = room.copy()
    comp.paste(fg_r, (x, y), fg_r)
    comp.save(args.out)
    print(f"wrote {args.out}  (placed {w}x{h} at x={x} y={y})")


if __name__ == "__main__":
    main()
