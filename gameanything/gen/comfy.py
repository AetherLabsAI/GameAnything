"""A local ComfyUI server (no key, nothing leaves the computer; http://127.0.0.1:8188 or COMFYUI_URL). Ported from um/comfy.py.

image: ComfyUI's default text-to-image graph with the first checkpoint the server lists (options: checkpoint, width, height, steps, cfg,
seed, negative), or options.workflow = a project-relative workflow saved with Export (API) plus options.set {"<node id or title>.<input>":
value}. POST /prompt, poll /history/<id>, download each output with /view. When no server answers, list / estimate say so and a run
fails with a clear reason (nothing is retried)."""
import json
import os
import random
import uuid

from .base import Adapter, AdapterError, Cap, Model, Price, save

DEFAULT_URL = "http://127.0.0.1:8188"
NEGATIVE = "blurry, low quality, jpeg artifacts, watermark, text, signature"
FREE = Model("default-graph", Price(0, 0, source="local: no API cost", verified=True), "SD 1.5 / SDXL checkpoint, or options.workflow")


def base_url(env=None) -> str: return ((env or os.environ).get("COMFYUI_URL") or DEFAULT_URL).rstrip("/")


def txt2img(prompt, ckpt, negative=NEGATIVE, width=512, height=512, steps=25, cfg=7.0, seed=0, n=1):
    return {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": n}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
            "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "normal",
                                                        "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "m2w", "images": ["8", 0]}}}


def apply_set(wf, sets: dict):
    wf = json.loads(json.dumps(wf))
    for k, v in (sets or {}).items():
        ref, _, inp = str(k).rpartition(".")
        node = ref if ref in wf else next((n for n, d in wf.items() if str((d.get("_meta") or {}).get("title", "")).lower() == ref.lower()), None)
        if not node or not inp: raise AdapterError(f"ComfyUI workflow has no node {ref!r}")
        wf[node].setdefault("inputs", {})[inp] = v
    return wf


class Comfy(Adapter):
    name = "comfy"; title = "ComfyUI (local)"; vendor = (); key = None; local = True; homepage = "https://www.comfy.org"
    caps = {"image": Cap("image", {FREE.id: FREE}, sends="nothing (local)")}

    def __init__(self, env=None): self.env = env

    def available(self, http=None):
        from . import http as H
        h = http or H.default(); u = base_url(self.env)
        try:
            h.call("GET", f"{u}/system_stats", timeout=3, retries=0); return True, f"ComfyUI at {u}"
        except Exception as e:
            return False, f"no ComfyUI at {u} ({type(e).__name__})"

    def _checkpoint(self, ctx, u):
        try: names = ctx.http.call("GET", f"{u}/models/checkpoints", timeout=30).json()
        except Exception: names = None
        if isinstance(names, list) and names: return str(names[0])
        raise AdapterError("ComfyUI lists no checkpoints (put one in ComfyUI/models/checkpoints, or pass options.workflow)")

    def run(self, ctx, cap, job):
        u = base_url(self.env); o = dict(job.get("options") or {})
        ok, why = self.available(ctx.http)
        if not ok: raise AdapterError(why)
        if o.get("workflow"):
            wf = json.loads((ctx.root / o["workflow"]).read_text(encoding="utf-8"))
            if isinstance(wf.get("prompt"), dict): wf = wf["prompt"]
            wf = apply_set(wf, o.get("set"))
        else:
            ck = o.get("checkpoint") or self._checkpoint(ctx, u)
            big = "xl" in ck.lower() or "1024" in ck
            wf = txt2img(job["prompt"], ck, o.get("negative", NEGATIVE), int(o.get("width", 1024 if big else 512)), int(o.get("height", 1024 if big else 512)),
                         int(o.get("steps", 25)), float(o.get("cfg", 7.0)), int(o.get("seed", random.randrange(2 ** 32))), int(job.get("n") or 1))
        r = ctx.http.call("POST", f"{u}/prompt", json={"prompt": wf, "client_id": uuid.uuid4().hex}).json()
        pid = r.get("prompt_id")
        if r.get("node_errors") or not pid: raise AdapterError(f"ComfyUI refused the workflow: {json.dumps(r.get('node_errors') or r)[:300]}")
        while True:
            hist = (ctx.http.call("GET", f"{u}/history/{pid}").json() or {}).get(pid)
            if hist:
                st = hist.get("status") or {}
                if st.get("status_str") == "error": raise AdapterError("ComfyUI failed (see its console)")
                if st.get("completed", True): break
            ctx.wait(f"ComfyUI prompt {pid}")
        outs = [x for node in sorted(hist.get("outputs") or {}, key=lambda k: (len(k), k)) for items in hist["outputs"][node].values()
                if isinstance(items, list) for x in items if isinstance(x, dict) and x.get("filename")]
        from urllib.parse import urlencode
        files = []
        for i, f in enumerate(outs):
            q = urlencode({"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")})
            ext = os.path.splitext(f["filename"])[1] or ".png"
            files.append(save(ctx.out / f"{job['name'] if i == 0 else job['name'] + f'_{i + 1}'}{ext}", ctx.http.get_bytes(f"{u}/view?{q}")))
        if not files: raise AdapterError("ComfyUI finished but saved nothing (the workflow needs a SaveImage node)")
        return {"files": files, "request_id": pid, "cost_usd": 0.0, "meta": {"url": u}}
