"""Photos: normalize (HEIC -> JPEG, EXIF orientation), thumbnails, metadata, perceptual hash."""
from pathlib import Path

from PIL import ExifTags, Image, ImageOps
import pillow_heif

pillow_heif.register_heif_opener()

EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}
IMAGE_MAX = 1600       # what perceive looks at
THUMB_MAX = 384        # contact sheets
HASH_SIZE = 16         # 256-bit dhash for photo near-duplicates (8x8 merges different guests posing in front of one backdrop)


def load(path: Path) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def save_scaled(im: Image.Image, dst: Path, max_side: int):
    im = im.copy(); im.thumbnail((max_side, max_side))
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=85)


def metadata(path: Path) -> dict:
    """Raw metadata as found in the file; trust is assessed later (timetrust.py), never here."""
    ex = Image.open(path).getexif()
    if not ex: return {}
    ifd = ex.get_ifd(ExifTags.IFD.Exif)
    gps = ex.get_ifd(ExifTags.IFD.GPSInfo)
    m = {"exif_datetime_original": ifd.get(36867), "exif_offset_original": ifd.get(36881), "exif_datetime": ex.get(306),
         "make": ex.get(271), "model": ex.get(272), "software": ex.get(305)}
    if gps.get(2) and gps.get(4):
        dec = lambda v, ref: round((float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600) * (-1 if ref in ("S", "W") else 1), 6)
        m["gps"] = [dec(gps[2], gps.get(1)), dec(gps[4], gps.get(3))]
    return {k: (v.strip("\x00 ") if isinstance(v, str) else v) for k, v in m.items() if v}


def dhash(im: Image.Image, size=8) -> int:
    g = im.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(g.getdata()); w = size + 1
    return sum(1 << i for i, (a, b) in enumerate((px[r * w + c], px[r * w + c + 1]) for r in range(size) for c in range(size)) if a > b)


def process(path: Path, out: Path, item_id: str) -> dict:
    im = load(path)
    img, thumb = out / "images" / f"{item_id}.jpg", out / "thumbs" / f"{item_id}.jpg"
    save_scaled(im, img, IMAGE_MAX); save_scaled(im, thumb, THUMB_MAX)
    return {"width": im.width, "height": im.height, "image": img, "thumb": thumb, "dhash": dhash(im, HASH_SIZE), "raw_metadata": metadata(path)}
