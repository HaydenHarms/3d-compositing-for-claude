#!/usr/bin/env python3
"""
Full AR composite: static photo (looped) -> transparent 3D render (scaled,
positioned) -> occlusion cutout on top. Wraps the exact three-layer ffmpeg
chain validated by composite_test.py + build_occlusion_mask.py into one
full-video render. Only run this once stills-based placement testing looks
right — this step is the expensive one.

Usage:
    python3 composite_ar.py room.jpg render.webm occlusion.png \\
        --scale 0.9 --anchor-frac-x 0.5 --anchor-frac-y 0.78 \\
        --duration 14.05 --fps 30 --out final.mp4

occlusion.png is optional — pass --no-occlusion to skip that layer (e.g.
nothing in the photo needs to occlude the model).
"""
import argparse
import subprocess
import sys
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("render", help="transparent webm/mov from the alpha render (see SKILL.md step 2)")
    ap.add_argument("occlusion", nargs="?", default=None, help="occlusion cutout PNG from build_occlusion_mask.py")
    ap.add_argument("--scale", type=float, default=0.9)
    ap.add_argument("--anchor-frac-x", type=float, default=0.5)
    ap.add_argument("--anchor-frac-y", type=float, default=0.78)
    ap.add_argument("--duration", type=float, required=True, help="output duration in seconds")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=16)
    ap.add_argument("--decoder", default="libvpx", help="explicit decoder for the alpha render (libvpx for vp8/vp9, prores for mov)")
    ap.add_argument("--out", default="final.mp4")
    ap.add_argument("--no-occlusion", action="store_true")
    args = ap.parse_args()

    room = Image.open(args.photo)
    w = int(room.width * args.scale)
    h = int(w * 1080 / 1920)  # overwritten below once we know the render's real AR
    # get the render's actual aspect via ffprobe so scale isn't a guess
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", args.render],
        capture_output=True, text=True, check=True,
    )
    rw, rh = (int(v) for v in probe.stdout.strip().split(","))
    h = int(w * rh / rw)

    x = int(room.width * args.anchor_frac_x) - w // 2
    y = int(room.height * args.anchor_frac_y) - h

    use_occlusion = args.occlusion and not args.no_occlusion

    inputs = ["-loop", "1", "-i", args.photo,
              "-c:v", args.decoder, "-i", args.render]
    if use_occlusion:
        inputs += ["-loop", "1", "-i", args.occlusion]

    if use_occlusion:
        filt = (f"[1:v]scale={w}:{h}[fg];"
                f"[0:v][fg]overlay={x}:{y}:shortest=1[bg2];"
                f"[bg2][2:v]overlay=0:0:shortest=1[out]")
    else:
        filt = f"[1:v]scale={w}:{h}[fg];[0:v][fg]overlay={x}:{y}:shortest=1[out]"

    cmd = ["ffmpeg", "-v", "error", *inputs,
           "-filter_complex", filt, "-map", "[out]",
           "-t", str(args.duration), "-r", str(args.fps),
           "-c:v", "libx264", "-crf", str(args.crf), "-pix_fmt", "yuv420p",
           args.out, "-y"]

    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"wrote {args.out}  (render placed {w}x{h} at x={x} y={y}"
          + (", with occlusion" if use_occlusion else ", no occlusion") + ")")


if __name__ == "__main__":
    main()
