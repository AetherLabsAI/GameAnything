"""What every generation adapter shares: capabilities, prices, the run context, saving outputs with their sha256."""
import base64
import hashlib
import io
import mimetypes
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

CAPS = ("image", "edit", "image-to-3d", "text-to-3d", "sfx", "music", "voice", "video")
KIND = {"image": "image", "edit": "image", "image-to-3d": "3d", "text-to-3d": "3d", "sfx": "audio", "music": "audio", "voice": "audio",
        "video": "video"}
# where the outputs go by default (under <project>/4_design/), when the request names no --out
DEFAULT_OUT = {"image": "art/gen", "3d": "art/3d", "audio": "audio/gen", "video": "video/gen"}
NEEDS_IMAGES = {"edit", "image-to-3d", "video"}
NEEDS_PROMPT = {"image", "edit", "text-to-3d", "sfx", "music", "voice"}
MAX_INLINE = 8 << 20                     # pictures are sent inline (data URI / base64): at most 8 MiB each after shrinking


class AdapterError(RuntimeError):
    pass


@dataclass
class Price:
    lo: float
    hi: float
    per: str = "output"                  # output = one picture / model / clip; the request's n multiplies it
    source: str = ""
    verified: bool = False


@dataclass
class Model:
    id: str
    price: Price
    note: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Cap:
    name: str
    models: dict                          # id -> Model; the first one is the default
    sends: str = "text"                   # text | text+images | images: what leaves the computer (for the permission card)

    @property
    def default(self) -> str: return next(iter(self.models))


@dataclass
class Output:
    path: Path
    sha256: str
    bytes: int
    role: str = "main"                    # main | texture | preview | meta


@dataclass
class Ctx:
    """One job's run: where its files go, the key, the HTTP door, the log, and how to wait."""
    root: Path
    out: Path
    key: str
    http: object
    log: object = print
    poll_secs: float = 5.0
    deadline: float = 0.0
    sleep: object = time.sleep

    def wait(self, what="the result"):
        if self.deadline and time.time() > self.deadline: raise AdapterError(f"timed out waiting for {what}")
        self.sleep(self.poll_secs)


class Adapter:
    name = ""
    title = ""
    vendor = ()                           # words a permission card's `to` uses for this provider (lower case)
    key = None                            # the env / key-file name of the API key; None = no key (local)
    local = False                         # True: nothing leaves the computer (ComfyUI)
    caps: dict = {}
    homepage = ""

    def cap(self, name) -> Cap:
        if name not in self.caps: raise AdapterError(f"{self.name} cannot do {name} (it can: {', '.join(self.caps)})")
        return self.caps[name]

    def model(self, cap, model=None) -> Model:
        c = self.cap(cap); m = model or c.default
        if m in c.models: return c.models[m]
        raise AdapterError(f"{self.name}:{cap} has no model {m!r} in its table (known: {', '.join(c.models)}); "
                           "add it to the adapter with its price first")

    def price(self, cap, model=None, options=None) -> Price:
        return self.model(cap, model).price

    def available(self, http=None):
        """(ok, why) for a local adapter; paid ones are 'available' when their key is there (checked by the caller)."""
        return True, ""

    def run(self, ctx: Ctx, cap: str, job: dict) -> dict:
        """-> {"files": [Output], "request_id": str|None, "cost_usd": float|None, "meta": {...}}"""
        raise NotImplementedError


# ---------------------------------------------------------------- helpers
def sha256(b: bytes) -> str: return hashlib.sha256(b).hexdigest()


def save(path: Path, data: bytes, role="main") -> Output:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.part"); tmp.write_bytes(data); tmp.replace(path)
    return Output(path, sha256(data), len(data), role)


EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif", "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
       "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/ogg": ".ogg", "video/mp4": ".mp4", "model/gltf-binary": ".glb"}


def ext_of(url: str = "", ctype: str = "", default=".bin") -> str:
    m = re.search(r"\.([a-z0-9]{2,5})$", (url or "").split("?")[0].lower())
    if m: return "." + m.group(1)
    return EXT.get((ctype or "").split(";")[0].strip().lower(), default)


def picture_bytes(path: Path, max_side=2048):
    """-> (bytes, mime) of a picture to send: as it is when small, else shrunk (JPEG) so it fits MAX_INLINE."""
    data = Path(path).read_bytes(); mime = mimetypes.guess_type(str(path))[0] or "image/png"
    if len(data) <= MAX_INLINE // 2 and mime in ("image/png", "image/jpeg", "image/webp"): return data, mime
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB"); im.thumbnail((max_side, max_side))
        b = io.BytesIO(); im.save(b, "JPEG", quality=90); data, mime = b.getvalue(), "image/jpeg"
    except Exception as e:                                     # PIL missing or not a picture
        if len(data) > MAX_INLINE: raise AdapterError(f"{Path(path).name} is too big to send ({len(data):,} bytes) and could not be shrunk: {e}")
    if len(data) > MAX_INLINE: raise AdapterError(f"{Path(path).name} is still too big to send after shrinking")
    return data, mime


def crop(path: Path, box):
    """(bytes, mime) of the picture cropped to box = (left, top, right, bottom) fractions (gen_meshy3d.py's CROP)."""
    from PIL import Image
    l, t, r, b = [float(x) for x in box]
    if not (0 <= l < r <= 1 and 0 <= t < b <= 1): raise AdapterError("crop should be [left, top, right, bottom] fractions between 0 and 1")
    im = Image.open(path).convert("RGB"); w, h = im.size
    buf = io.BytesIO(); im.crop((int(l * w), int(t * h), int(r * w), int(b * h))).save(buf, "PNG"); return buf.getvalue(), "image/png"


def data_uri(data: bytes, mime: str) -> str: return f"data:{mime};base64," + base64.b64encode(data).decode()


def job_pictures(ctx: Ctx, job: dict):
    """[(bytes, mime)] of the job's input pictures (project-relative paths, already checked by genrun / gen.plan)."""
    out = []
    for i, rel in enumerate(job.get("images") or []):
        p = ctx.root / rel
        out.append(crop(p, job["options"]["crop"]) if i == 0 and (job.get("options") or {}).get("crop") else picture_bytes(p))
    return out


def urls_in(obj, trail=""):
    """(json path, url, content type) of every downloadable file in a result (fal-style {url, content_type} objects)."""
    if isinstance(obj, dict):
        u = obj.get("url")
        if isinstance(u, str) and u.startswith("http"): yield trail, u, obj.get("content_type") or ""
        for k, v in obj.items():
            if k != "url": yield from urls_in(v, f"{trail}.{k}" if trail else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj): yield from urls_in(v, f"{trail}[{i}]")
