#!/usr/bin/env bash
# Checks whether a rendered video's alpha channel actually survived
# encoding. A bare `ffprobe`/`ffmpeg -i` summary reports pix_fmt=yuv420p
# for a webm/vp8 alpha file even when the alpha IS present — the plain
# decoder path doesn't surface the alpha side-channel. This decodes one
# frame explicitly with the codec's real decoder and checks the alpha
# extrema, which is the only reliable way to tell.
#
# Usage: ./check_alpha.sh render.webm [decoder]
#   decoder defaults to libvpx (vp8/vp9 webm). Use "prores" for a
#   ProRes4444 .mov with yuva444p10le.
set -euo pipefail
FILE="${1:?usage: check_alpha.sh <video> [decoder]}"
DECODER="${2:-libvpx}"
TMP=$(mktemp --suffix=.png)

ffmpeg -v error -c:v "$DECODER" -i "$FILE" -vframes 1 -pix_fmt rgba "$TMP" -y

python3 - "$TMP" <<'PY'
import sys
from PIL import Image
im = Image.open(sys.argv[1])
lo, hi = im.split()[-1].getextrema()
if lo == hi == 255:
    print(f"NO USABLE ALPHA — every pixel is fully opaque (min={lo}, max={hi}).")
    print("Check: the renderer had a transparent background enabled (render_blender.py sets film_transparent),")
    print("and that you decoded with the right explicit decoder (see --decoder flag).")
    sys.exit(1)
else:
    print(f"Alpha channel OK — range {lo}-{hi} (some fully transparent, some opaque, or a gradient).")
PY

rm -f "$TMP"
