"""Contact sheet of a video: a grid of evenly spaced frames, each stamped with its time, so a reviewer (agent or person)
can see a whole replay in one image and point at a moment ("4:12") instead of watching it all. Needs ffmpeg / ffprobe.
Idea from universal-modder's `um video contact` (MIT, commit 23902ef); written from scratch here.

    gameanything video contact <video> [--out sheet.jpg] [--cols 6] [--rows 5] [--width 320] [--start 0] [--end END]
"""
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def duration(video: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def frame(video: Path, t: float, width: int) -> Image.Image:
    """One frame at time t (seconds), scaled to `width`; -ss before -i seeks fast to the nearest keyframe, then decodes to t."""
    png = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                          "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    import io
    return Image.open(io.BytesIO(png)).convert("RGB")


def stamp(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def contact(video: Path, out: Path, cols=6, rows=5, width=320, start=0.0, end=None) -> dict:
    end = min(end or 1e12, duration(video)); n = cols * rows
    ts = [start + (end - start) * (i + 0.5) / n for i in range(n)]       # centre of each slice: never the black first frame
    frames = [frame(video, t, width) for t in ts]
    w, h = frames[0].size; pad, head = 4, 22
    sheet = Image.new("RGB", (cols * (w + pad) + pad, rows * (h + pad) + pad + head), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
    d.text((pad, 3), f"{video.name}  {stamp(start)}-{stamp(end)}  ({n} frames, one every {(end - start) / n:.1f}s)", fill=(220, 220, 220), font=font)
    for i, (im, t) in enumerate(zip(frames, ts)):
        x, y = pad + (i % cols) * (w + pad), head + pad + (i // cols) * (h + pad)
        sheet.paste(im, (x, y))
        label = stamp(t); tw = d.textlength(label, font=font)
        d.rectangle([x, y, x + tw + 8, y + 18], fill=(0, 0, 0)); d.text((x + 4, y + 1), label, fill=(255, 255, 255), font=font)
    out.parent.mkdir(parents=True, exist_ok=True); sheet.save(out, quality=88)
    return {"sheet": str(out), "frames": [round(t, 1) for t in ts], "size": sheet.size}
