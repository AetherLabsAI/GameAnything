"""OpenAI image models (OPENAI_API_KEY, the same key a hub user gives Codex): text -> picture, and edits / variants of reference pictures.

    image   POST https://api.openai.com/v1/images/generations {model, prompt, n, size, quality, background, output_format}
    edit    POST https://api.openai.com/v1/images/edits (multipart: model, prompt, n, image[] files, ...)
The pictures come back as data[].b64_json. Options: size (1024x1024 | 1536x1024 | 1024x1536 | auto), quality (low | medium | high,
default medium), background (transparent | opaque | auto). Prices per 1024x1024 picture by quality; gpt-image-1 from OpenAI's price list,
gpt-image-2 from secondary sources quoting OpenAI's docs (2026-10-26, unverified)."""
import base64
import secrets

from .base import Adapter, AdapterError, Cap, Model, Price, job_pictures, save

API = "https://api.openai.com/v1/images"
QUALITY = {"gpt-image-2": {"low": 0.006, "medium": 0.053, "high": 0.211}, "gpt-image-1": {"low": 0.011, "medium": 0.042, "high": 0.167}}
SRC = {"gpt-image-2": "secondary sources quoting OpenAI pricing (2026-10-26), 1024x1024; unverified",
       "gpt-image-1": "OpenAI image pricing, 1024x1024 (as of 2025; not re-checked 2026-10-26)"}


def _models():
    return {m: Model(m, Price(q["medium"], q["high"], source=SRC[m], verified=False), "quality low / medium / high") for m, q in QUALITY.items()}


def multipart(fields: dict, files: list):
    """-> (body bytes, content type). fields: name -> str; files: [(field name, file name, bytes, mime)]."""
    b = "----m2w" + secrets.token_hex(8); out = []
    for k, v in fields.items():
        out += [f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n".encode(), str(v).encode("utf-8"), b"\r\n"]
    for k, fn, data, mime in files:
        out += [f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fn}\"\r\nContent-Type: {mime}\r\n\r\n".encode(), data, b"\r\n"]
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


class OpenAIImage(Adapter):
    name = "openai"; title = "OpenAI images"; vendor = ("openai", "gpt-image", "chatgpt"); key = "OPENAI_API_KEY"
    homepage = "https://platform.openai.com/api-keys"
    caps = {"image": Cap("image", _models(), sends="text"), "edit": Cap("edit", _models(), sends="text+images")}

    def price(self, cap, model=None, options=None):
        m = self.model(cap, model); q = (options or {}).get("quality")
        if q in QUALITY[m.id]: v = QUALITY[m.id][q]; return Price(v, v * 1.5, source=SRC[m.id] + " (larger sizes cost more)", verified=False)
        return m.price

    def run(self, ctx, cap, job):
        m = self.model(cap, job.get("model")); o = dict(job.get("options") or {}); o.pop("crop", None)
        o.setdefault("quality", "medium"); n = int(job.get("n") or 1); h = {"Authorization": f"Bearer {ctx.key}"}
        if cap == "image":
            r = ctx.http.call("POST", f"{API}/generations", headers=h, json={"model": m.id, "prompt": job["prompt"], "n": n, **o}, timeout=300).json()
        else:
            pics = job_pictures(ctx, job)
            body, ctype = multipart({"model": m.id, "prompt": job["prompt"], "n": n, **o},
                                    [("image[]", f"ref{i}.{mime.split('/')[-1]}", b, mime) for i, (b, mime) in enumerate(pics)])
            r = ctx.http.call("POST", f"{API}/edits", headers={**h, "Content-Type": ctype}, data=body, timeout=300).json()
        data = [d for d in r.get("data") or [] if d.get("b64_json")]
        if not data: raise AdapterError(f"OpenAI {m.id}: no picture in the answer ({str(r.get('error') or '')[:200]})")
        ext = "." + str(o.get("output_format") or "png")
        files = [save(ctx.out / f"{job['name'] if i == 0 else job['name'] + f'_{i + 1}'}{ext}", base64.b64decode(d["b64_json"])) for i, d in enumerate(data)]
        return {"files": files, "request_id": None, "cost_usd": None, "meta": {"quality": o.get("quality")}}
