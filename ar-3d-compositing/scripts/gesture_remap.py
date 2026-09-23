#!/usr/bin/env python3
"""
Map a multi-beat animation onto a person's discrete gestures in a talking-
head video: not one clip played back at a fixed speed, but a piecewise
timeline where each (video_time -> source_frame) breakpoint you specify
becomes a linear segment, and consecutive breakpoints with the SAME source
frame become a hold. This is what makes "the chunk lands as your fist
closes, then holds, then the ceiling appears and it clamps down as your
hand opens toward a pinch" read as one continuous story instead of a
sequence of clips cut together.

Handles the whole pipeline: extracts the needed source-render frame range
with alpha (correcting internally for the fact that ffmpeg's `select`
filter renumbers extracted frames sequentially from 1 — it does NOT
preserve original frame numbers; get this wrong and you silently composite
the wrong frames, or loudly get a FileNotFoundError), crops, resizes,
extracts every frame of the background video, composites according to the
breakpoint timeline, and re-encodes with the background's original audio.

Usage:
    python3 gesture_remap.py \\
        --source-render render.webm --source-decoder libvpx \\
        --source-frame-range 60 419 \\
        --crop 770,0,1380,760 \\
        --background talking_head.mp4 \\
        --breakpoints breakpoints.txt \\
        --target-width 190 --place 5,10 \\
        --fade-in 2.0,2.2 \\
        --out final.mp4

breakpoints.txt format — one "time_seconds source_frame" pair per line,
frame numbers referring to the ORIGINAL render's frame numbers (whatever
--source-frame-range uses, not a re-sequenced index). Blank lines and
lines starting with # are ignored:

    # video_time_seconds  source_frame
    2.00   60      # fade-in begins (3D element not yet moving)
    2.17   66      # gesture 1 starts: bar begins rising
    3.00   108     # gesture 1 ends: bar fully risen
    3.80   214     # gesture 2 ends: chunk stacked
    4.40   214     # hold through the pause between gestures 2 and 3
    5.60   320     # gesture 3 ends: chunk clamped

Before writing a breakpoint file: extract the background video at a higher
framerate than its native rate (`--fps 10` or higher below native) and
find the actual gesture transition times by inspection — don't estimate
from watching at native speed, the boundaries are usually tighter or
looser than they feel.
"""
import argparse
import bisect
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image


def run(cmd):
    subprocess.run(cmd, check=True)


def extract_source_frames(render, decoder, lo, hi, out_dir):
    """Extract frames [lo, hi] (inclusive, original frame numbers) from the
    source render, returning a dict {original_frame_num: PIL.Image}."""
    pattern = os.path.join(out_dir, "s%06d.png")
    cmd = [
        "ffmpeg", "-v", "error", "-c:v", decoder, "-i", render,
        "-vf", f"select='between(n\\,{lo}\\,{hi})'", "-vsync", "0",
        "-pix_fmt", "rgba", pattern, "-y",
    ]
    run(cmd)
    files = sorted(f for f in os.listdir(out_dir) if f.startswith("s") and f.endswith(".png"))
    if len(files) != hi - lo + 1:
        print(f"WARNING: expected {hi - lo + 1} frames in range [{lo},{hi}], "
              f"got {len(files)} — the range may extend past the render's length.",
              file=sys.stderr)
    # ffmpeg's select+vsync 0 numbers output sequentially from 1, NOT by
    # original frame number — map file index back to the real frame number.
    frames = {}
    for i, fn in enumerate(files):
        original_frame_num = lo + i
        frames[original_frame_num] = Image.open(os.path.join(out_dir, fn)).convert("RGBA")
    return frames


def extract_background_frames(video, out_dir):
    pattern = os.path.join(out_dir, "v%06d.png")
    run(["ffmpeg", "-v", "error", "-i", video, pattern, "-y"])
    files = sorted(f for f in os.listdir(out_dir) if f.startswith("v") and f.endswith(".png"))
    return [os.path.join(out_dir, f) for f in files]


def parse_breakpoints(path):
    pts = []
    with open(path) as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            t_str, f_str = line.split()[:2]
            pts.append((float(t_str), int(f_str)))
    pts.sort(key=lambda p: p[0])
    if len(pts) < 2:
        raise SystemExit("need at least 2 breakpoints")
    return pts


def source_frame_at(t, breakpoints):
    times = [p[0] for p in breakpoints]
    if t < times[0]:
        return None
    if t >= times[-1]:
        return breakpoints[-1][1]
    i = bisect.bisect_right(times, t) - 1
    t0, f0 = breakpoints[i]
    t1, f1 = breakpoints[i + 1]
    if t1 == t0:
        return f0
    frac = (t - t0) / (t1 - t0)
    return f0 + (f1 - f0) * frac


def alpha_mult_at(t, fade_in):
    if fade_in is None:
        return 1.0
    s, e = fade_in
    if t < s:
        return 0.0
    if t < e:
        return (t - s) / (e - s)
    return 1.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-render", required=True)
    ap.add_argument("--source-decoder", default="libvpx", help="explicit decoder for the alpha render (libvpx for vp8/vp9)")
    ap.add_argument("--source-frame-range", nargs=2, type=int, metavar=("LO", "HI"), required=True)
    ap.add_argument("--crop", required=True, help="x0,y0,x1,y1 in the source render's pixel space")
    ap.add_argument("--background", required=True, help="the talking-head video")
    ap.add_argument("--breakpoints", required=True, help="path to breakpoints file — see script docstring for format")
    ap.add_argument("--target-width", type=int, required=True)
    ap.add_argument("--place", required=True, help="x,y placement in the background frame")
    ap.add_argument("--fade-in", default=None, help="start,end seconds for an opacity fade-in; omit for a hard cut-in")
    ap.add_argument("--fps", type=int, default=30, help="background video's frame rate")
    ap.add_argument("--crf", type=int, default=16)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    lo, hi = args.source_frame_range
    x0, y0, x1, y1 = (int(v) for v in args.crop.split(","))
    place_x, place_y = (int(v) for v in args.place.split(","))
    fade_in = tuple(float(v) for v in args.fade_in.split(",")) if args.fade_in else None
    breakpoints = parse_breakpoints(args.breakpoints)

    with tempfile.TemporaryDirectory() as tmp:
        src_dir = os.path.join(tmp, "src"); os.makedirs(src_dir)
        bg_dir = os.path.join(tmp, "bg"); os.makedirs(bg_dir)
        out_dir = os.path.join(tmp, "out"); os.makedirs(out_dir)

        print("extracting source render frames...")
        src_frames_raw = extract_source_frames(args.source_render, args.source_decoder, lo, hi, src_dir)

        print("cropping + resizing source frames...")
        src_frames = {}
        for num, im in src_frames_raw.items():
            c = im.crop((x0, y0, x1, y1))
            th = int(args.target_width * c.height / c.width)
            src_frames[num] = c.resize((args.target_width, th))

        print("extracting background frames...")
        bg_files = extract_background_frames(args.background, bg_dir)
        n_frames = len(bg_files)
        print(f"{n_frames} background frames at {args.fps}fps")

        print("compositing...")
        for i, bg_path in enumerate(bg_files, start=1):
            t = (i - 1) / args.fps
            bg = Image.open(bg_path).convert("RGB")
            sf = source_frame_at(t, breakpoints)
            if sf is not None:
                nearest = min(max(round(sf), lo), hi)
                holo = src_frames[nearest]
                amult = alpha_mult_at(t, fade_in)
                if amult < 1.0:
                    if amult <= 0.0:
                        holo = None
                    else:
                        a = holo.split()[-1].point(lambda p, m=amult: int(p * m))
                        holo = holo.copy()
                        holo.putalpha(a)
                if holo is not None:
                    bg.paste(holo, (place_x, place_y), holo)
            bg.save(os.path.join(out_dir, f"o{i:06d}.png"))

        print("encoding...")
        has_audio = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
             "-of", "csv=p=0", args.background],
            capture_output=True, text=True,
        ).stdout.strip() != ""

        cmd = ["ffmpeg", "-v", "error", "-framerate", str(args.fps),
               "-i", os.path.join(out_dir, "o%06d.png")]
        if has_audio:
            cmd += ["-i", args.background, "-map", "0:v", "-map", "1:a:0", "-c:a", "aac", "-shortest"]
        cmd += ["-c:v", "libx264", "-crf", str(args.crf), "-pix_fmt", "yuv420p", args.out, "-y"]
        run(cmd)

    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
