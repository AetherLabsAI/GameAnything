"""fal (https://fal.ai): one queue REST API for many models: pictures, edits / variants, image -> 3D, sound, music, voice, video.

POST https://queue.fal.run/<model id> (Authorization: Key $FAL_KEY, or FAL_API_KEY) -> {request_id, status_url, response_url}; poll status_url until
COMPLETED (IN_QUEUE / IN_PROGRESS before), then GET response_url. The status / response URLs of a model with a sub-path use only
owner/app, so the returned URLs are used, never rebuilt. Input pictures are sent inline as data URIs (no upload to fal storage).
Model ids follow universal-modder's um/fal.py (checked against the fal catalog 2026-09); prices from fal's model pages (2026-10-26)
where marked verified, else a wide range (check `fal.ai/models/<id>` before a big batch)."""
from .base import Adapter, AdapterError, Cap, Model, Price, data_uri, ext_of, job_pictures, save, urls_in

QUEUE = "https://queue.fal.run"
SRC = "fal.ai/models/<id> page, 2026-10-26"
UNV = "not checked: um/fal.py default model, price range guessed"


def _p(lo, hi=None, src=UNV, ok=False): return Price(lo, hi if hi is not None else lo, source=src, verified=ok)


class Fal(Adapter):
    name = "fal"; title = "fal.ai"; vendor = ("fal",); key = "FAL_KEY"; homepage = "https://fal.ai/dashboard/keys"
    caps = {
        "image": Cap("image", {
            "fal-ai/nano-banana-2": Model("fal-ai/nano-banana-2", _p(0.06, 0.16, SRC + " ($0.08 at 1K; 0.5K-4K = 0.75x-2x)", True)),
            "openai/gpt-image-2": Model("openai/gpt-image-2", _p(0.01, 0.25), "transparent background: options background=transparent"),
            "fal-ai/flux/schnell": Model("fal-ai/flux/schnell", _p(0.003, 0.01)),
        }),
        "edit": Cap("edit", {
            "fal-ai/nano-banana-2/edit": Model("fal-ai/nano-banana-2/edit", _p(0.06, 0.16, SRC + " (same as nano-banana-2)", False)),
        }, sends="text+images"),
        "image-to-3d": Cap("image-to-3d", {
            "fal-ai/trellis-2": Model("fal-ai/trellis-2", _p(0.25, 0.35, SRC + " ($0.25 512p, $0.30 1024p, $0.35 1536p)", True), extra={"field": "image_url"}),
            "fal-ai/hunyuan-3d/v3.1/pro/image-to-3d": Model("fal-ai/hunyuan-3d/v3.1/pro/image-to-3d", _p(0.2, 0.6), extra={"field": "input_image_url"}),
            "tripo3d/h3.1/image-to-3d": Model("tripo3d/h3.1/image-to-3d", _p(0.2, 0.6), extra={"field": "image_url"}),
            "meshy/v7.1/image-to-3d": Model("meshy/v7.1/image-to-3d", _p(0.3, 0.9), extra={"field": "image_url"}),
        }, sends="images"),
        "sfx": Cap("sfx", {"fal-ai/elevenlabs/sound-effects/v2": Model("fal-ai/elevenlabs/sound-effects/v2", _p(0.01, 0.12))}),
        "music": Cap("music", {"elevenlabs/music/v2.5": Model("elevenlabs/music/v2.5", _p(0.1, 1.5), "up to about a minute")}),
        "voice": Cap("voice", {"fal-ai/elevenlabs/tts/eleven-v3": Model("fal-ai/elevenlabs/tts/eleven-v3", _p(0.01, 0.2))}),
        "video": Cap("video", {"bytedance/seedance-2.5/image-to-video": Model("bytedance/seedance-2.5/image-to-video", _p(0.3, 2.5), "5 s clip")},
                     sends="text+images"),
    }

    def inputs(self, cap, m, job, pics):
        o = dict(job.get("options") or {}); o.pop("crop", None); n = int(job.get("n") or 1); p = job.get("prompt")
        uris = [data_uri(b, mime) for b, mime in pics]
        if cap == "image": return {"prompt": p, "num_images": n, **o}
        if cap == "edit": return {"prompt": p, "image_urls": uris, "num_images": n, **o}
        if cap == "image-to-3d": return {m.extra.get("field", "image_url"): uris[0], **o}
        if cap == "sfx": return {"text": p, **o}
        if cap == "music": return {"prompt": p, **o}
        if cap == "voice": return {"text": p, **o}
        if cap == "video": return {"image_url": uris[0], "prompt": p or "", **o}
        raise AdapterError(f"fal: no inputs for {cap}")

    def run(self, ctx, cap, job):
        m = self.model(cap, job.get("model")); h = {"Authorization": f"Key {ctx.key}"}
        body = {k: v for k, v in self.inputs(cap, m, job, job_pictures(ctx, job)).items() if v is not None}
        sub = ctx.http.call("POST", f"{QUEUE}/{m.id}", headers=h, json=body).json()
        rid = sub.get("request_id")
        if not rid: raise AdapterError(f"fal did not queue the request: {str(sub)[:300]}")
        status_url = sub.get("status_url") or f"{QUEUE}/{m.id}/requests/{rid}/status"
        response_url = sub.get("response_url") or f"{QUEUE}/{m.id}/requests/{rid}"
        while True:
            st = ctx.http.call("GET", status_url, headers=h).json()
            s = st.get("status")
            if s == "COMPLETED":
                if st.get("error"): raise AdapterError(f"fal {m.id} failed: {str(st['error'])[:300]}")
                break
            if s not in ("IN_QUEUE", "IN_PROGRESS"): raise AdapterError(f"fal {m.id}: unexpected status {s!r}")
            ctx.wait(f"fal request {rid}")
        res = ctx.http.call("GET", response_url, headers=h).json()
        files = self.download(ctx, cap, job, res)
        if not files: raise AdapterError(f"fal {m.id} finished but returned no files")
        return {"files": files, "request_id": rid, "cost_usd": None, "meta": {"seed": res.get("seed")}}

    def download(self, ctx, cap, job, res):
        name, files, first = job["name"], [], None; three_d = cap in ("image-to-3d", "text-to-3d")
        for i, (trail, url, ctype) in enumerate(urls_in(res)):
            key = trail.split("[")[0].split(".")[-1] or "file"; first = first or key
            ext = ext_of(url, ctype)
            if three_d:
                stem = "model" if key == first else key.removeprefix("model_") or f"file_{i}"
                path = ctx.out / f"{stem}{ext}"
            else:
                k = sum(1 for f in files if f.role == "main")
                path = ctx.out / (f"{name}{ext}" if key == first and k == 0 else f"{name}_{k + 1}{ext}" if key == first else f"{name}_{key}{ext}")
            while any(f.path == path for f in files): path = path.with_name(path.stem + "_x" + path.suffix)
            files.append(save(path, ctx.http.get_bytes(url), "main" if key == first else "extra"))
        return files
