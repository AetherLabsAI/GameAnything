"""Dialogue portraits from the user's photos (the HDSI approach, 2026-10-11): an image model gets the person's head-and-shoulders
crop plus one vanilla portrait as the style reference, then the result is keyed from its flat background and pixelized to
64x64 with the vanilla portraits' colours. One sheet = 2 columns x N rows of 64x64 (the game's portrait layout).

Privacy: generating SENDS the face crop to the image model's provider (default: Seedream via OpenRouter, i.e. ByteDance's
model behind OpenRouter). That is a different destination from the model that looked at the photos in perceive, so it needs
its own consent (`--yes` after the list of what will be sent); every request goes into the project's privacy ledger.
The photo is only a reference: it is never put into the mod.
"""
import base64
import io
import json
import urllib.request
from pathlib import Path

import yaml
from PIL import Image

PROMPT = ("Pixel art character portrait in the style of Stardew Valley NPC dialogue portraits (the second image shows that style: "
          "chunky pixels, dark brown outline, soft cel shading, big readable face filling the frame, head and shoulders cropped at "
          "the chest, flat solid {bg} background). Subject: the person in the centre of the first photo (ignore anyone at the edges): {looks}. Expression: {expr}. "
          "Keep their hairstyle{glasses} and clothing. Square image, the face centred, no text.")
EXPR_PROMPT = ("The first image is a pixel art portrait of a character. Draw the SAME portrait again: exactly the same person, face shape, "
               "hair colour and hairstyle, glasses (only if it already has them), clothes and their colours, framing, pixel style and flat {bg} background. Change only the "
               "facial expression, to: {expr}. Square image, no text.")
EXPRESSIONS = {"neutral": "calm, a gentle smile", "happy": "a big happy smile", "laugh": "laughing, eyes closed with joy",
               "touched": "moved, slightly teary but smiling", "surprised": "pleasantly surprised", "shy": "a shy, warm smile"}
BG = "#4f7ad6"                               # flat blue: easy to key, absent from faces and most clothes
STYLE_REF = {"female": "Haley", "male": "Harvey", "girl": "Jas", "boy": "Vincent", "older_female": "Caroline", "older_male": "Harvey"}


BGS = {"blue": "#4f7ad6", "green": "#3fa34d", "magenta": "#c63fc6"}


def pick_bg(look):
    """The flat background colour farthest from every colour of the person's look (so keying never eats clothes or a veil)."""
    from . import palette as pal
    cols = [pal.hex2rgb(c) for c in (look.get("colors") or {}).values()] or [(240, 240, 240)]
    return max(BGS.values(), key=lambda b: min(pal.dist(pal.hex2rgb(b), c) for c in cols))


def best_box(person_id, tags, person=None, prefer=()):
    """The user's chosen portrait reference (people.yaml portrait_ref, set in `gameanything ui`), else the biggest tagged box.
    Size alone often picks a profile shot (a close-up taken from the side), so the UI lets the user choose."""
    ref = (person or {}).get("portrait_ref")
    if ref: return {"item": ref["item"], "box": ref["box"], "person": person_id}
    bs = [t for t in tags if t.get("person") == person_id]
    return max(bs, key=lambda t: (t["item"] in prefer, (t["box"][3] - t["box"][1])), default=None)   # posed group photos face the camera


def face_crop(pack_items, tag, pad=0.06, head_share=0.42) -> Image.Image:
    """Head and shoulders from the ORIGINAL photo (full resolution): the top ~42% of the person's box, padded, squared."""
    it = next(i for i in pack_items if i["id"] == tag["item"])
    from PIL import ImageOps
    im = ImageOps.exif_transpose(Image.open(it["file"])).convert("RGB"); W, H = im.size
    x0, y0, x1, y1 = tag["box"]; h = (y1 - y0) * head_share; cx = (x0 + x1) / 2 * W; side = max((x1 - x0) * W, h * H) * (1 + 2 * pad)
    top = max(0, y0 * H - pad * side)
    box = (max(0, cx - side / 2), top, min(W, cx + side / 2), min(H, top + side))
    c = im.crop(box); c.thumbnail((768, 768)); return c


def style_ref(content: Path, kind: str) -> Image.Image:
    v = STYLE_REF.get(kind, "Haley")
    p = Image.open(content / "Portraits" / f"{v}.png").convert("RGBA").crop((0, 0, 64, 64))
    return p.resize((512, 512), Image.NEAREST)


def _b64(im: Image.Image, fmt="PNG"):
    b = io.BytesIO(); im.convert("RGB").save(b, fmt, quality=90); return f"data:image/{fmt.lower()};base64," + base64.b64encode(b.getvalue()).decode()


def openrouter(prompt, refs, model="bytedance-seed/seedream-5-0-lite"):
    """-> (PNG bytes, cost). The user's own key ($OPENROUTER_API_KEY or the keys file in settings, see keys.py); never written anywhere."""
    from .... import keys
    key = keys.get("OPENROUTER_API_KEY")
    content = [{"type": "text", "text": prompt}] + [{"type": "image_url", "image_url": {"url": _b64(r, "JPEG")}} for r in refs]
    body = {"model": model, "modalities": ["image"], "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=300).read())
    url = r["choices"][0]["message"]["images"][0]["image_url"]["url"]
    return base64.b64decode(url.split(",", 1)[1]), (r.get("usage") or {}).get("cost")


def to_portrait(png: bytes, colors=40) -> Image.Image:
    """Generated picture -> 64x64 pixel portrait. The background is removed by a flood fill from the border (so a light
    veil or a white shirt next to it survives), the square is box-downscaled, then quantized to the picture's own colours
    (snapping to vanilla palettes washed out faces: tried 2026-10-15)."""
    im = Image.open(io.BytesIO(png)).convert("RGBA"); W, H = im.size
    side = min(W, H); im = im.crop(((W - side) // 2, 0, (W - side) // 2 + side, side))
    small = im.resize((256, 256), Image.BOX); px = small.load()
    border = [px[x, 0] for x in range(256)] + [px[0, y] for y in range(256)] + [px[255, y] for y in range(256)]
    bg = max(set(b[:3] for b in border), key=lambda c: sum(1 for b in border if sum(abs(b[i] - c[i]) for i in range(3)) < 60))
    near = lambda p: sum(abs(p[i] - bg[i]) for i in range(3)) < 90
    seen, stack = set(), [(x, y) for x in range(256) for y in (0,)] + [(x, y) for x in (0, 255) for y in range(256)]
    while stack:
        x, y = stack.pop()
        if (x, y) in seen or not (0 <= x < 256 and 0 <= y < 256) or not near(px[x, y]): continue
        seen.add((x, y)); px[x, y] = (0, 0, 0, 0); stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    out = small.resize((64, 64), Image.BOX)
    a = out.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    q = out.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT).convert("RGB")
    q.putalpha(a); return q


def sheet(portraits) -> Image.Image:
    rows = (len(portraits) + 1) // 2; s = Image.new("RGBA", (128, 64 * rows), (0, 0, 0, 0))
    for i, p in enumerate(portraits): s.alpha_composite(p, ((i % 2) * 64, (i // 2) * 64))
    return s


def ledger(project: Path, entry):
    f = project / "privacy_ledger.yaml"; d = yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else None
    d = d or {"requests": []}; d["requests"].append(entry); f.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")


def glasses_text(look):
    """Name glasses in the prompt only for people who wear them: a generic "keep their glasses" made the model add glasses to everyone."""
    acc = [a if isinstance(a, str) else a.get("type") for a in look.get("accessories", [])]
    return ", glasses" if "glasses" in acc else " (no glasses)"


def looks_text(person, look):
    """A short appearance description for the prompt, from the person's look recipe comment-free fields and people.yaml."""
    lk = person.get("looks")
    if isinstance(lk, dict): return "; ".join(lk.values())
    return lk or "as in the photo"


def generate(project: Path, content: Path, pid: str, expressions=("neutral",), feedback=None, log=print):
    """Portraits for one person -> 4_design/art/portraits/<pid>_<expr>.png (+ raw). Sends the face crop + a vanilla style
    reference to the image model for each expression; every request goes into the privacy ledger."""
    import pillow_heif; pillow_heif.register_heif_opener()
    from datetime import datetime
    A = project / "4_design" / "art"; (A / "portraits").mkdir(parents=True, exist_ok=True); (A / "portraits_raw").mkdir(exist_ok=True)
    (A / "portrait_inputs").mkdir(exist_ok=True)
    items = yaml.safe_load(open(project / "1_ingest" / "pack.yaml", encoding="utf-8"))["items"]
    tags = yaml.safe_load(open(project / "3_remember" / "tags.yaml", encoding="utf-8"))["tags"]
    person = next(p for p in yaml.safe_load(open(project / "3_remember" / "people.yaml", encoding="utf-8"))["people"] if p["id"] == pid)
    look = (yaml.safe_load(open(A / "looks.yaml", encoding="utf-8")) or {}).get(pid, {})
    board = yaml.safe_load(open(project / "3_remember" / "board.yaml", encoding="utf-8"))["experience_board"]
    prefer = {i for s in board["skeleton"] if s["id"] == "seg_photos" for i in s["items"]}
    t = best_box(pid, tags, person, prefer)
    if not t: log(f"[portrait] {pid}: no tagged photo"); return []
    crop = face_crop(items, t); crop.save(A / "portrait_inputs" / f"{pid}_photo.jpg", quality=90)
    kind = KIND.get(look.get("upper"), "female")
    bg = pick_bg(look); out = []
    # other expressions are edits of the neutral portrait (separate generations from the photo drift: clothes, hair colour)
    exs = list(expressions)
    if any(e != "neutral" for e in exs) and "neutral" not in exs and not (A / "portraits_raw" / f"{pid}_neutral.png").exists(): exs.insert(0, "neutral")
    exs.sort(key=lambda e: e != "neutral")
    for ex in exs:
        base = A / "portraits_raw" / f"{pid}_neutral.png"
        if ex == "neutral" or not base.exists():
            prompt = PROMPT.format(bg=bg, looks=looks_text(person, look), expr=EXPRESSIONS[ex], glasses=glasses_text(look)); refs = [crop, style_ref(content, kind)]
        else:
            prompt = EXPR_PROMPT.format(bg=bg, expr=EXPRESSIONS[ex]); refs = [Image.open(base).convert("RGB"), crop]
        if feedback: prompt += f" Also: {feedback}."
        try:
            png, cost = openrouter(prompt, refs); status = "ok"
        except Exception as e:
            png, cost, status = None, None, f"failed: {str(e)[:200]}"
        ledger(project, {"id": pid, "at": datetime.now().isoformat(timespec="seconds"), "backend": "openrouter", "model": "bytedance-seed/seedream-5-0-lite",
                         "purpose": f"portrait ({ex})", "images": [f"4_design/art/portrait_inputs/{pid}_photo.jpg",
                                                                    f"vanilla style ref ({STYLE_REF.get(kind)})" if ex == "neutral" else f"4_design/art/portraits_raw/{pid}_neutral.png"],
                         "text": ["prompt" + (" + user feedback" if feedback else "")], "status": status, "cost_usd": cost})
        if not png: log(f"[portrait] {pid} {ex}: {status}"); continue
        (A / "portraits_raw" / f"{pid}_{ex}.png").write_bytes(png)
        to_portrait(png).save(A / "portraits" / f"{pid}_{ex}.png"); out.append(ex)
        log(f"[portrait] {pid} {ex}: ok ${cost}")
    return out


KIND = {"Harvey": "male", "Kent": "male", "Demetrius": "male", "Haley": "female", "Penny": "female", "Emily": "female",
        "Caroline": "female", "Jodi": "female", "Evelyn": "older_female", "Jas": "girl"}
