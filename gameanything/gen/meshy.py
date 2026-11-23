"""Meshy (https://www.meshy.ai): image -> 3D and text -> 3D, what the projects' gen_meshy3d*.py did.

    image-to-3d   POST /openapi/v1/image-to-3d {image_url: data URI, ai_model, should_texture, enable_pbr, should_remesh,
                  target_polycount, topology, ...}; GET /openapi/v1/image-to-3d/<id> until SUCCEEDED / FAILED / CANCELED
    text-to-3d    POST /openapi/v2/text-to-3d {mode: preview, prompt, ai_model, ...}, then (should_texture, the default) a refine task
                  {mode: refine, preview_task_id, enable_pbr, texture_prompt}
Options (the request's `options`, per job or for all): crop [l, t, r, b] fractions of the first picture (the old CROP), should_texture
(default true), enable_pbr, should_remesh, target_polycount (decimate; with should_remesh, 100..300000), topology (triangle | quad),
texture_prompt, target_formats. Writes <out>/<name>/{model.glb, model.obj?, texture_<n>_<map>.png, preview.png, task.json}.
Credits from docs.meshy.ai/en/api/pricing (2026-10-26): image-to-3d meshy-6 / 7.1 = 20 mesh only, 30 textured; meshy-6-lite /
t2 / t2.5 = 5 / 15; text-to-3d preview 20 (lite 5) + refine 10. Dollars per credit are not published for the API: $0.016-0.025
assumed (subscription credit packs), so the dollar figure is unverified; the ledger records the credits Meshy reports."""
import json

from .base import Adapter, AdapterError, Cap, Model, Price, data_uri, job_pictures, save

API = "https://api.meshy.ai/openapi"
USD_PER_CREDIT = (0.016, 0.025)
SRC = "docs.meshy.ai/en/api/pricing credits (2026-10-26) x $0.016-0.025 per credit (unverified)"
CREDITS = {"meshy-6": (20, 30), "meshy-7.1": (20, 30), "latest": (20, 30), "meshy-6-lite": (5, 15), "meshy-t2": (5, 15), "meshy-t2.5": (5, 15)}
PREVIEW = {"meshy-6": 20, "meshy-7.1": 20, "latest": 20, "meshy-6-lite": 5, "meshy-t2": 5, "meshy-t2.5": 5}
DONE = ("SUCCEEDED", "FAILED", "CANCELED")


def _usd(credits): return Price(round(credits * USD_PER_CREDIT[0], 3), round(credits * USD_PER_CREDIT[1], 3), source=SRC, verified=False)


class Meshy(Adapter):
    name = "meshy"; title = "Meshy"; vendor = ("meshy",); key = "MESHY_API_KEY"; homepage = "https://www.meshy.ai/settings/api"
    caps = {
        "image-to-3d": Cap("image-to-3d", {m: Model(m, _usd(CREDITS[m][1])) for m in ("meshy-6", "meshy-7.1", "meshy-6-lite", "meshy-t2.5")}, sends="images"),
        "text-to-3d": Cap("text-to-3d", {m: Model(m, _usd(PREVIEW[m] + 10)) for m in ("meshy-6", "meshy-7.1", "meshy-6-lite", "meshy-t2.5")}),
    }

    def credits(self, cap, model, options=None) -> int:
        o = options or {}; tex = o.get("should_texture", True) is not False
        if cap == "image-to-3d": return CREDITS[model][1 if tex else 0]
        return PREVIEW[model] + (10 if tex else 0)

    def price(self, cap, model=None, options=None):
        m = self.model(cap, model); return _usd(self.credits(cap, m.id, options))

    def _task(self, ctx, url, body):
        h = {"Authorization": f"Bearer {ctx.key}"}
        tid = ctx.http.call("POST", url, headers=h, json=body).json().get("result")
        if not tid: raise AdapterError("Meshy did not start a task")
        while True:
            t = ctx.http.call("GET", f"{url}/{tid}", headers=h).json()
            if t.get("status") in DONE: break
            ctx.wait(f"Meshy task {tid}")
        if t["status"] != "SUCCEEDED":
            err = t.get("task_error"); err = err.get("message") if isinstance(err, dict) else err
            raise AdapterError(f"Meshy task {tid} {t['status']}: {str(err or '')[:300]}")
        return tid, t

    def run(self, ctx, cap, job):
        m = self.model(cap, job.get("model")); o = dict(job.get("options") or {}); o.pop("crop", None)
        tex = o.get("should_texture", True) is not False
        if cap == "image-to-3d":
            (b, mime), *_ = job_pictures(ctx, job)
            body = {"image_url": data_uri(b, mime), "ai_model": m.id, "should_texture": tex, "topology": "triangle",
                    **({"model_type": "smart-topology"} if m.id.startswith("meshy-t") else {}), **o}
            tid, t = self._task(ctx, f"{API}/v1/image-to-3d", body); credits = t.get("consumed_credits")
        else:
            body = {"mode": "preview", "prompt": job["prompt"], "ai_model": m.id, "topology": "triangle",
                    **{k: v for k, v in o.items() if k not in ("should_texture", "enable_pbr", "texture_prompt")}}
            tid, t = self._task(ctx, f"{API}/v2/text-to-3d", body); credits = t.get("consumed_credits") or 0
            if tex:
                rb = {"mode": "refine", "preview_task_id": tid, **{k: o[k] for k in ("enable_pbr", "texture_prompt") if k in o}}
                tid, t = self._task(ctx, f"{API}/v2/text-to-3d", rb); credits = (credits or 0) + (t.get("consumed_credits") or 0)
        files = []
        for fmt, u in (t.get("model_urls") or {}).items():
            if u and fmt in ("glb", "obj", "fbx", "mtl", "usdz", "stl"): files.append(save(ctx.out / f"model.{fmt}", ctx.http.get_bytes(u), "main" if fmt == "glb" else "extra"))
        for n, tu in enumerate(t.get("texture_urls") or []):
            for k, u in (tu or {}).items():
                if u: files.append(save(ctx.out / f"texture_{n}_{k}.png", ctx.http.get_bytes(u), "texture"))
        if t.get("thumbnail_url"): files.append(save(ctx.out / "preview.png", ctx.http.get_bytes(t["thumbnail_url"]), "preview"))
        if not any(f.role == "main" for f in files): raise AdapterError(f"Meshy task {tid} succeeded but gave no GLB model")
        keep = {k: v for k, v in t.items() if not str(k).endswith(("_urls", "_url"))}       # task.json without the signed download links
        files.append(save(ctx.out / "task.json", json.dumps(keep, ensure_ascii=False, indent=1).encode("utf-8"), "meta"))
        lo, hi = USD_PER_CREDIT
        return {"files": files, "request_id": tid, "cost_usd": None, "meta": {"credits": credits, "usd_range": [round((credits or 0) * lo, 3), round((credits or 0) * hi, 3)]}}
