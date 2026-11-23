"""OpenRouter image models (OPENROUTER_API_KEY): what most projects' gen_*.py used (Seedream 5.0 lite through portraits.openrouter).

POST https://openrouter.ai/api/v1/chat/completions {model, modalities: [image], messages: [{role: user, content: [text, image_url...]}]};
the picture is choices[0].message.images[0].image_url.url (a data URI); usage.cost is the real price of the call (recorded).
Price: $0.035 per picture, the cost OpenRouter reported on 359 real Seedream 5.0 lite calls in this machine's project ledgers (2026-10)."""
import base64

from .base import Adapter, AdapterError, Cap, Model, Price, data_uri, job_pictures, save

API = "https://openrouter.ai/api/v1/chat/completions"
SEEDREAM = Model("bytedance-seed/seedream-5-0-lite", Price(0.035, 0.04, source="usage.cost of 359 real calls (privacy ledgers, 2026-10)", verified=True))


class OpenRouter(Adapter):
    name = "openrouter"; title = "OpenRouter"; vendor = ("openrouter", "seedream"); key = "OPENROUTER_API_KEY"
    homepage = "https://openrouter.ai/settings/keys"
    caps = {"image": Cap("image", {SEEDREAM.id: SEEDREAM}, sends="text"),
            "edit": Cap("edit", {SEEDREAM.id: SEEDREAM}, sends="text+images")}

    def run(self, ctx, cap, job):
        m = self.model(cap, job.get("model")); o = dict(job.get("options") or {}); o.pop("crop", None)
        content = [{"type": "text", "text": job["prompt"]}] + [{"type": "image_url", "image_url": {"url": data_uri(b, mime)}} for b, mime in job_pictures(ctx, job)]
        body = {"model": m.id, "modalities": ["image"], "messages": [{"role": "user", "content": content}], **o}
        files, cost, ids = [], 0.0, []
        for i in range(int(job.get("n") or 1)):
            r = ctx.http.call("POST", API, headers={"Authorization": f"Bearer {ctx.key}"}, json=body, timeout=300).json()
            try: url = r["choices"][0]["message"]["images"][0]["image_url"]["url"]
            except (KeyError, IndexError, TypeError): raise AdapterError(f"OpenRouter {m.id}: no picture in the answer ({str(r.get('error') or '')[:200]})") from None
            head, _, b64 = url.partition(",")
            ext = ".jpg" if "jpeg" in head else ".webp" if "webp" in head else ".png"
            files.append(save(ctx.out / f"{job['name'] if i == 0 else job['name'] + f'_{i + 1}'}{ext}", base64.b64decode(b64)))
            if r.get("id"): ids.append(str(r["id"]))
            c = (r.get("usage") or {}).get("cost"); cost = cost + c if isinstance(c, (int, float)) and cost is not None else None
        return {"files": files, "request_id": ",".join(ids) or None, "cost_usd": cost, "meta": {}}
