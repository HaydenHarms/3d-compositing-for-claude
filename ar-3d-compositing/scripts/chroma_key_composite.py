#!/usr/bin/env python3
"""
Compositing for the talking-head / presenter case: a person filmed
against a solid color (green/blue) screen, with a transparent 3D render
placed BEHIND them so real hands/body correctly occlude the 3D elements
wherever they overlap it — pixel-accurate, every frame, no hand-traced
masks needed. This is the recommended default for a moving subject; see
references/talking-head.md for why (hand/finger mattes from general ML
segmentation are noisy and temporally unstable — a real key is not).

Layer order (back to front):
    background (a photo, a color, or another video) 
    -> transparent 3D render
    -> person, with the key color made transparent

Usage:
    python3 chroma_key_composite.py subject.mp4 render.webm out/final.mp4 \\
        --background room.jpg --key-color 0x00FF00 --similarity 0.18 --blend 0.08

    # or a plain color background instead of a photo:
    python3 chroma_key_composite.py subject.mp4 render.webm out/final.mp4 \\
        --background-color 0x101418

--similarity/--blend tune the key: raise --similarity if green is still
showing through hair/edges, lower it if part of the person is getting
keyed out. Always check a still frame before trusting a full render (see
SKILL.md's iterate-on-stills discipline) — chroma key edges are the
number one thing worth eyeballing.
"""
import argparse
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subject", help="talking-head clip filmed against a solid color screen")
    ap.add_argument("render", help="transparent 3D render (webm/vp8 alpha, etc — see check_alpha.sh)")
    ap.add_argument("out")
    ap.add_argument("--background", help="a photo/video to use as the backdrop")
    ap.add_argument("--background-color", default=None, help="flat color backdrop instead, e.g. 0x101418")
    ap.add_argument("--key-color", default="0x00FF00", help="the screen color to key out")
    ap.add_argument("--similarity", type=float, default=0.18)
    ap.add_argument("--blend", type=float, default=0.08)
    ap.add_argument("--decoder", default="libvpx", help="explicit decoder for the alpha render")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=16)
    args = ap.parse_args()

    if not args.background and not args.background_color:
        raise SystemExit("need --background <photo/video> or --background-color <hex>")

    inputs = []
    if args.background:
        # loop if it's a still image; harmless flag for video backgrounds too
        inputs += ["-loop", "1", "-i", args.background]
        bg_label = "[0:v]"
        next_idx = 1
    else:
        inputs += ["-f", "lavfi", "-i", f"color=c={args.background_color}:s=1920x1080:r={args.fps}"]
        bg_label = "[0:v]"
        next_idx = 1

    inputs += ["-c:v", args.decoder, "-i", args.render]
    render_label = f"[{next_idx}:v]"
    next_idx += 1

    inputs += ["-i", args.subject]
    subject_label = f"[{next_idx}:v]"

    filt = (
        f"{bg_label}{render_label}scale2ref[bgm][fgr];"
        f"[fgr]{'' }[fg];"
    )
    # simpler, explicit chain: scale background to 1920x1080 canvas, overlay
    # render, then overlay the keyed subject on top
    filt = (
        f"{bg_label}scale=1920:1080,setsar=1[bg];"
        f"{render_label}scale=1920:1080[fg];"
        f"[bg][fg]overlay=0:0:shortest=1[stage];"
        f"{subject_label}chromakey={args.key_color}:{args.similarity}:{args.blend}[keyed];"
        f"[stage][keyed]overlay=0:0:shortest=1[out]"
    )

    cmd = ["ffmpeg", "-v", "error", *inputs,
           "-filter_complex", filt, "-map", "[out]",
           "-r", str(args.fps), "-c:v", "libx264", "-crf", str(args.crf),
           "-pix_fmt", "yuv420p", args.out, "-y"]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
