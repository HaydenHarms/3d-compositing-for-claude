#!/usr/bin/env python3
"""
Crop a region of a photo (or a rendered RGBA frame) with a pixel-coordinate
grid burned in, so you can read off exact placement/occlusion coordinates
instead of eyeballing a downscaled preview.

Usage:
    python3 pixel_grid.py <photo.jpg> --cx 1400 --cy 1600 --size 700 --step 100 --out crop.png
    python3 pixel_grid.py <photo.jpg> --full --step 200 --out overview.png
    python3 pixel_grid.py <rendered_frame.png> --cx 950 --cy 400 --size 400 --step 50 --out crop.png

--cx/--cy/--size crop a square region centered on (cx,cy) of the given size
(in the source's actual pixel coordinates — run --full first if you don't
know roughly where to look). --step controls grid line spacing. Labels are
the REAL pixel coordinates in the original (un-cropped) source, so you can
feed them straight into build_occlusion_mask.py / composite_test.py /
gesture_remap.py's --crop.

**On a translucent/gradient RGBA source (a 3D render's alpha-channel PNG,
not a photo): a downscaled grid overlay is NOT reliable for finding edges.**
A photographed object has a crisp, high-contrast edge that survives
downscaling; a rendered object's edge is often a soft gradient over
translucent fill, and at reduced scale it's easy to misjudge where it
actually falls — confirmed the hard way, misreading a column's edge by
~300px this way. This script auto-flattens RGBA input onto a solid
background (white by default, --flatten-color to change) before drawing
the grid, which restores real contrast — but even then, for a precision
read, keep --size small enough that you're looking at a genuinely
full-resolution crop, not a wide view that gets downscaled for viewing.
"""
import argparse
from PIL import Image, ImageDraw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--cx", type=int)
    ap.add_argument("--cy", type=int)
    ap.add_argument("--size", type=int, default=700)
    ap.add_argument("--step", type=int, default=100)
    ap.add_argument("--full", action="store_true", help="grid the whole photo instead of a crop")
    ap.add_argument("--flatten-color", default="255,255,255", help="background to flatten RGBA input onto, e.g. for a rendered alpha-channel frame")
    ap.add_argument("--out", default="grid.png")
    args = ap.parse_args()

    raw = Image.open(args.photo)
    if raw.mode == "RGBA":
        bg_color = tuple(int(v) for v in args.flatten_color.split(","))
        flat = Image.new("RGB", raw.size, bg_color)
        flat.paste(raw, (0, 0), raw)
        im = flat
    else:
        im = raw.convert("RGB")
    w, h = im.size

    if args.full:
        x0, y0, x1, y1 = 0, 0, w, h
    else:
        if args.cx is None or args.cy is None:
            raise SystemExit("--cx and --cy are required unless --full is given")
        half = args.size // 2
        x0, y0 = max(0, args.cx - half), max(0, args.cy - half)
        x1, y1 = min(w, args.cx + half), min(h, args.cy + half)

    crop = im.crop((x0, y0, x1, y1)).copy()
    d = ImageDraw.Draw(crop)
    step = args.step

    for x in range(x0 - (x0 % step), x1, step):
        lx = x - x0
        d.line([(lx, 0), (lx, crop.height)], fill=(255, 0, 0), width=1)
        d.text((lx + 2, 2), str(x), fill=(255, 255, 0))
    for y in range(y0 - (y0 % step), y1, step):
        ly = y - y0
        d.line([(0, ly), (crop.width, ly)], fill=(0, 255, 255), width=1)
        d.text((2, ly + 2), str(y), fill=(0, 255, 0))

    crop.save(args.out)
    print(f"wrote {args.out}  (region x:{x0}-{x1} y:{y0}-{y1} of {w}x{h} source)")


if __name__ == "__main__":
    main()
