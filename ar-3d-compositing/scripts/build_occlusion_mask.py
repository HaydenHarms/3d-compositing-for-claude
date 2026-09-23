#!/usr/bin/env python3
"""
Build an occlusion cutout: a transparent PNG the same size as the source
photo, containing the ORIGINAL photo's pixels only inside one or more
hand-traced polygons (real foreground objects), transparent everywhere
else. Composited as the top layer over a 3D render, this makes real
objects that are physically closer to the camera draw over the 3D render
instead of the render always drawing on top of everything.

Usage:
    python3 build_occlusion_mask.py room.jpg out/occlusion.png \\
        --polygon "1195,1600 1500,1550 1600,1660 1580,1725 1330,1725 1195,1660" \\
        --polygon "1800,1255 2100,1270 2100,1550 1900,1900"

Get polygon points from pixel_grid.py crops of each object. One --polygon
per object; each is "x,y x,y x,y ..." (space-separated points, at least 3).
"""
import argparse
from PIL import Image, ImageDraw, ImageFilter


def parse_polygon(s):
    pts = []
    for pair in s.strip().split():
        x, y = pair.split(",")
        pts.append((int(x), int(y)))
    if len(pts) < 3:
        raise SystemExit(f"polygon needs at least 3 points, got {len(pts)}: {s}")
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("out")
    ap.add_argument("--polygon", action="append", required=True, help='"x,y x,y x,y ..." — repeatable')
    ap.add_argument("--feather", type=int, default=3, help="gaussian blur radius on the mask edge")
    args = ap.parse_args()

    photo = Image.open(args.photo).convert("RGB")
    w, h = photo.size

    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    for poly_str in args.polygon:
        d.polygon(parse_polygon(poly_str), fill=255)

    if args.feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(args.feather))

    cutout = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    cutout.paste(photo, (0, 0))
    cutout.putalpha(mask)
    cutout.save(args.out)

    bbox = mask.point(lambda p: 255 if p > 10 else 0).getbbox()
    print(f"wrote {args.out}  (covers pixel bbox {bbox})")


if __name__ == "__main__":
    main()
