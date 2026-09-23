#!/usr/bin/env python3
"""
Lay a camera-matched render (from render_blender.py) over its plate.

Because the render was made with the plate's own resolution and camera,
there is no scaling or anchor-guessing: it's a pixel-for-pixel overlay.
Layers, back to front:
    plate (photo, looped; or video)
    -> render (objects + their real caught shadows)
    -> optional occlusion cutout (build_occlusion_mask.py) so real
       foreground objects stay in front
    -> optional light grain so clean CG matches camera noise

Still test (do this first):
    python3 composite_plate.py plate.jpg out/render/frame_0040.png --out test.png

Full video:
    python3 composite_plate.py plate.jpg out/render --fps 30 --out final.mp4
    python3 composite_plate.py plate.mp4 out/render --start 1 --out final.mp4

A directory of frame_####.png files or a .webm with alpha both work as
the render input.
"""
import argparse
import glob
import os
import re
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plate", help="photo or video the render was camera-matched to")
    ap.add_argument("render", help="a single PNG (still test), a frame directory, or an alpha .webm")
    ap.add_argument("occlusion", nargs="?", default=None, help="optional occlusion cutout PNG")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--start", type=int, default=None, help="first frame number in the render directory")
    ap.add_argument("--grain", type=float, default=4, help="noise strength to match footage (0 = off)")
    ap.add_argument("--crf", type=int, default=16)
    args = ap.parse_args()

    still = args.out.lower().endswith((".png", ".jpg"))
    plate_is_video = args.plate.lower().endswith((".mp4", ".mov", ".m4v", ".webm", ".mkv"))
    cmd = ["ffmpeg", "-v", "error", "-y"]

    if plate_is_video:
        cmd += ["-i", args.plate]
    elif still:
        cmd += ["-i", args.plate]
    else:
        cmd += ["-loop", "1", "-framerate", str(args.fps), "-i", args.plate]

    if os.path.isdir(args.render):
        frames = sorted(glob.glob(os.path.join(args.render, "frame_*.png")))
        if not frames:
            raise SystemExit(f"no frame_####.png in {args.render}")
        start = args.start or int(re.search(r"(\d+)\.png$", frames[0]).group(1))
        cmd += ["-framerate", str(args.fps), "-start_number", str(start),
                "-i", os.path.join(args.render, "frame_%04d.png")]
    elif args.render.endswith(".webm"):
        cmd += ["-c:v", "libvpx", "-i", args.render]
    else:
        cmd += ["-i", args.render]

    fc = "[0:v]format=rgb24[bg];[1:v]format=rgba[fg];[bg][fg]overlay=0:0:shortest=1:format=auto[c0]"
    last = "c0"
    if args.occlusion:
        cmd += ["-loop", "1", "-i", args.occlusion]
        fc += f";[{last}][2:v]overlay=0:0:shortest=1[c1]"
        last = "c1"
    if args.grain > 0:
        fc += f";[{last}]noise=alls={args.grain}:allf=t[cg]"
        last = "cg"
    fc += f";[{last}]format=yuv420p[v]" if not still else f";[{last}]null[v]"

    cmd += ["-filter_complex", fc, "-map", "[v]"]
    if still:
        cmd += ["-frames:v", "1"]
    else:
        if plate_is_video:
            cmd += ["-map", "0:a?", "-c:a", "copy"]
        cmd += ["-c:v", "libx264", "-crf", str(args.crf), "-r", str(args.fps)]
    cmd += [args.out]
    subprocess.run(cmd, check=True)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
