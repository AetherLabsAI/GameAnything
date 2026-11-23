"""The unified generation interface (gameanything/gen + genrun adapter requests). Every adapter runs against a fake HTTP door: nothing
in this file opens a socket. queue -> agentd checks both cards (to whom, which files, how much) -> in-process run with the owner's key
-> files + index.yaml (sha256) + privacy ledger; refusals; GAMEANYTHING_GEN_OFF; the keys of 「我的 agent」 and the keyring."""
import base64
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from gameanything import agent_providers, agentd, cli, gen, genrun, keys, osdirs, projects, users
from gameanything.conversation import CardError, Thread
from gameanything.gen import http as H
from gameanything.gen.base import Ctx
from test_hub import Client, hub  # noqa: F401,F811  (the hub fixture)

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-picture" * 20
GLB = b"glTF" + b"\x00" * 60
FAL = "fal-secret-id:fal-secret-value-123456"
MESHY = "msy_meshy_secret_value_123456"


# ---------------------------------------------------------------- a fake HTTP door
class Fake(H.Http):
    """Routes (method, url regex) -> handler(url, kw) returning a dict (JSON) or bytes. Records every call (with headers and body)."""
    def __init__(self, routes): self.routes = routes; self.calls = []

    def call(self, method, url, headers=None, json=None, data=None, timeout=120, retries=None):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "json": json, "data": data})
        for (m, pat), fn in self.routes.items():
            if m == method and re.search(pat, url):
                r = fn(url, {"json": json, "data": data, "headers": headers or {}})
                if isinstance(r, Exception): raise r
                return H.Response(200, {}, r if isinstance(r, bytes) else __import__("json").dumps(r).encode())
        raise H.GenHTTPError(404, url, "no fake route")


def seq(*answers):
    it = iter(answers); last = [None]

    def fn(url, kw):
        try: last[0] = next(it)
        except StopIteration: pass
        return last[0]
    return fn


def fal_routes(result, status=("IN_PROGRESS", "COMPLETED")):
    return {("POST", r"^https://queue\.fal\.run/fal-ai/"): lambda u, k: {"request_id": "rq1", "status_url": "https://queue.fal.run/fal-ai/x/requests/rq1/status",
                                                                        "response_url": "https://queue.fal.run/fal-ai/x/requests/rq1"},
            ("GET", r"/requests/rq1/status$"): seq(*[{"status": s} for s in status]),
            ("GET", r"/requests/rq1$"): lambda u, k: result,
            ("GET", r"^https://cdn\.example/.*\.png"): lambda u, k: PNG, ("GET", r"^https://cdn\.example/.*\.glb"): lambda u, k: GLB}


def ctx(tmp_path, http, key="k"):
    root = tmp_path / "p"; (root / "2_perceive").mkdir(parents=True, exist_ok=True); (root / "2_perceive" / "ref.png").write_bytes(PNG)
    return Ctx(root=root, out=root / "4_design" / "art" / "gen", key=key, http=http, poll_secs=0, sleep=lambda s: None)


def job(name="a", prompt="a red lantern", images=(), n=1, **options):
    return {"name": name, "prompt": prompt, "images": list(images), "n": n, "options": options}


# ---------------------------------------------------------------- each adapter, fake HTTP
def test_fal_image_queue_poll_download(tmp_path):
    f = Fake(fal_routes({"images": [{"url": "https://cdn.example/a.png", "content_type": "image/png"}, {"url": "https://cdn.example/b.png"}], "seed": 7}))
    c = ctx(tmp_path, f); r = gen.ADAPTERS["fal"].run(c, "image", {**job(n=2, aspect_ratio="16:9"), "model": "fal-ai/nano-banana-2"})
    sub = f.calls[0]
    assert sub["url"] == "https://queue.fal.run/fal-ai/nano-banana-2" and sub["headers"]["Authorization"] == "Key k"
    assert sub["json"] == {"prompt": "a red lantern", "num_images": 2, "aspect_ratio": "16:9"}
    assert [x.path.name for x in r["files"]] == ["a.png", "a_2.png"] and r["request_id"] == "rq1" and r["meta"]["seed"] == 7
    assert r["files"][0].sha256 == hashlib.sha256(PNG).hexdigest()
    assert not any("Authorization" in x["headers"] for x in f.calls if "cdn.example" in x["url"]), "downloads never carry the key"


def test_fal_image_to_3d_sends_the_picture_inline(tmp_path):
    f = Fake(fal_routes({"model_glb": {"url": "https://cdn.example/m.glb"}}, status=("COMPLETED",)))
    c = ctx(tmp_path, f); c.out = c.root / "4_design" / "art" / "3d" / "lantern"
    r = gen.ADAPTERS["fal"].run(c, "image-to-3d", {**job("lantern", None, ["2_perceive/ref.png"]), "model": "fal-ai/trellis-2"})
    assert f.calls[0]["json"]["image_url"].startswith("data:image/png;base64,") and [x.path.name for x in r["files"]] == ["model.glb"]
    f2 = Fake(fal_routes({"detail": "x"}, status=("FAILED",)))
    with pytest.raises(gen.AdapterError, match="status"): gen.ADAPTERS["fal"].run(ctx(tmp_path, f2), "image", {**job(), "model": "fal-ai/nano-banana-2"})


def meshy_routes(kind="image-to-3d", final="SUCCEEDED"):
    task = {"status": final, "consumed_credits": 30, "model_urls": {"glb": "https://cdn.example/m.glb", "obj": "https://cdn.example/m.obj"},
            "texture_urls": [{"base_color": "https://cdn.example/t.png"}], "thumbnail_url": "https://cdn.example/p.png", "task_error": {"message": "bad picture"}}
    return {("POST", rf"api\.meshy\.ai/openapi/v[12]/{kind}$"): seq({"result": "t1"}, {"result": "t2"}),
            ("GET", rf"/{kind}/t[12]$"): seq({"status": "IN_PROGRESS"}, task, task, task),
            ("GET", r"cdn\.example/.*\.(glb|obj)"): lambda u, k: GLB, ("GET", r"cdn\.example/.*\.png"): lambda u, k: PNG}


def test_meshy_image_to_3d_port_of_gen_meshy3d(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    f = Fake(meshy_routes()); c = ctx(tmp_path, f); c.out = c.root / "4_design" / "art" / "3d" / "geisel"
    Image.new("RGB", (100, 50), "white").save(c.root / "2_perceive" / "ref.png")
    r = gen.ADAPTERS["meshy"].run(c, "image-to-3d", {**job("geisel", None, ["2_perceive/ref.png"], crop=[0.1, 0.2, 1.0, 0.8], target_polycount=20000), "model": "meshy-6"})
    b = f.calls[0]["json"]
    assert f.calls[0]["headers"]["Authorization"] == "Bearer k" and b["ai_model"] == "meshy-6" and b["should_texture"] is True and b["target_polycount"] == 20000
    assert "crop" not in b and Image.open(__import__("io").BytesIO(base64.b64decode(b["image_url"].split(",", 1)[1]))).size == (90, 30)
    assert sorted(x.path.name for x in r["files"]) == ["model.glb", "model.obj", "preview.png", "task.json", "texture_0_base_color.png"]
    assert "cdn.example" not in (c.out / "task.json").read_text(encoding="utf-8") and r["meta"]["credits"] == 30
    with pytest.raises(gen.AdapterError, match="bad picture"):
        gen.ADAPTERS["meshy"].run(ctx(tmp_path, Fake(meshy_routes(final="FAILED"))), "image-to-3d", {**job("x", None, ["2_perceive/ref.png"]), "model": "meshy-6"})


def test_meshy_text_to_3d_preview_then_refine(tmp_path):
    f = Fake(meshy_routes("text-to-3d")); c = ctx(tmp_path, f); c.out = c.root / "4_design" / "art" / "3d" / "bun"
    r = gen.ADAPTERS["meshy"].run(c, "text-to-3d", {**job("bun", "a steamed bun", enable_pbr=True), "model": "meshy-6"})
    posts = [x["json"] for x in f.calls if x["method"] == "POST"]
    assert posts[0]["mode"] == "preview" and "enable_pbr" not in posts[0] and posts[1] == {"mode": "refine", "preview_task_id": "t1", "enable_pbr": True}
    assert r["request_id"] == "t2" and r["meta"]["credits"] == 60
    assert gen.ADAPTERS["meshy"].price("text-to-3d", "meshy-6", {"should_texture": False}).hi < gen.ADAPTERS["meshy"].price("text-to-3d", "meshy-6").hi


def test_openai_image_json_and_edit_multipart(tmp_path):
    ans = {"data": [{"b64_json": base64.b64encode(PNG).decode()}]}
    f = Fake({("POST", r"api\.openai\.com/v1/images/generations$"): lambda u, k: ans, ("POST", r"api\.openai\.com/v1/images/edits$"): lambda u, k: ans})
    c = ctx(tmp_path, f)
    gen.ADAPTERS["openai"].run(c, "image", {**job(background="transparent"), "model": "gpt-image-2"})
    assert f.calls[0]["json"] == {"model": "gpt-image-2", "prompt": "a red lantern", "n": 1, "background": "transparent", "quality": "medium"}
    r = gen.ADAPTERS["openai"].run(c, "edit", {**job("e", "make it blue", ["2_perceive/ref.png"]), "model": "gpt-image-2"})
    e = f.calls[1]; assert e["headers"]["Content-Type"].startswith("multipart/form-data; boundary=") and b'name="image[]"' in e["data"] and PNG in e["data"]
    assert r["files"][0].path.name == "e.png"
    assert gen.ADAPTERS["openai"].price("image", "gpt-image-2", {"quality": "low"}).lo < gen.ADAPTERS["openai"].price("image", "gpt-image-2", {"quality": "high"}).lo


def test_openrouter_records_the_real_cost(tmp_path):
    ans = {"choices": [{"message": {"images": [{"image_url": {"url": "data:image/png;base64," + base64.b64encode(PNG).decode()}}]}}], "usage": {"cost": 0.035}, "id": "gen-1"}
    f = Fake({("POST", r"openrouter\.ai/api/v1/chat/completions$"): lambda u, k: ans})
    r = gen.ADAPTERS["openrouter"].run(ctx(tmp_path, f), "edit", {**job("t", "game screenshot", ["2_perceive/ref.png"], n=2), "model": "bytedance-seed/seedream-5-0-lite"})
    assert r["cost_usd"] == pytest.approx(0.07) and r["request_id"] == "gen-1,gen-1" and f.calls[0]["json"]["modalities"] == ["image"] and len(f.calls[0]["json"]["messages"][0]["content"]) == 2


def test_a_refused_key_says_so_and_is_not_billed(tmp_path):
    """The live smoke (2026-10-26): Google answers an invalid key with HTTP 400 and a JSON body; the note says why, nothing is counted as spent."""
    body = json.dumps({"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT",
                                 "details": [{"reason": "API_KEY_INVALID"}]}})
    f = Fake({("POST", r"chat/completions$"): lambda u, k: H.GenHTTPError(400, u, body)})
    c = ctx(tmp_path, f)
    r = gen.run(c.root, gen.normalize(c.root, "openrouter:image", {"jobs": [{"name": "a", "prompt": "a lighthouse"}]}), "k", http=f, log=lambda m: None)
    assert r["cost_usd"] == 0 and r["failed"][0]["error"].endswith("API key not valid. Please pass a valid API key. (INVALID_ARGUMENT)")
    f2 = Fake({("POST", r"chat/completions$"): lambda u, k: H.GenHTTPError(422, u, '{"detail": "bad prompt"}')})
    r2 = gen.run(c.root, gen.normalize(c.root, "openrouter:image", {"jobs": [{"name": "b", "prompt": "x"}]}), "k", http=f2, log=lambda m: None)
    assert r2["cost_usd"] > 0 and "bad prompt" in r2["failed"][0]["error"], "other refusals may still be billed: counted"


def test_comfy_local_and_absent(tmp_path, monkeypatch):
    hist = {"p1": {"status": {"completed": True}, "outputs": {"9": {"images": [{"filename": "m2w_0001.png", "subfolder": "", "type": "output"}]}}}}
    f = Fake({("GET", r"127\.0\.0\.1:8188/system_stats$"): lambda u, k: {}, ("GET", r"/models/checkpoints$"): lambda u, k: ["sd_xl_base.safetensors"],
              ("POST", r"/prompt$"): lambda u, k: {"prompt_id": "p1"}, ("GET", r"/history/p1$"): seq({}, hist), ("GET", r"/view\?"): lambda u, k: PNG})
    r = gen.ADAPTERS["comfy"].run(ctx(tmp_path, f), "image", {**job(seed=3), "model": "default-graph"})
    wf = [x for x in f.calls if x["method"] == "POST"][0]["json"]["prompt"]
    assert wf["4"]["inputs"]["ckpt_name"] == "sd_xl_base.safetensors" and wf["5"]["inputs"]["width"] == 1024 and wf["3"]["inputs"]["seed"] == 3
    assert r["cost_usd"] == 0 and r["files"][0].path.name == "a.png"
    gone = Fake({("GET", r"system_stats"): lambda u, k: H.GenHTTPError(0, u, "refused")})
    assert gen.ADAPTERS["comfy"].available(gone)[0] is False
    with pytest.raises(gen.AdapterError, match="no ComfyUI"): gen.ADAPTERS["comfy"].run(ctx(tmp_path, gone), "image", {**job(), "model": "default-graph"})
    monkeypatch.setattr(H, "DEFAULT", gone)
    row = [x for x in gen.listing({}) if x["tool"] == "comfy:image"][0]; assert row["ready"] is False and "no ComfyUI" in row["key"]


def test_post_is_never_retried_on_a_5xx(monkeypatch):
    import urllib.error, urllib.request
    n = []

    def boom(req, timeout=0):
        n.append(req.get_method()); raise urllib.error.HTTPError(req.full_url, 502, "bad", {}, __import__("io").BytesIO(b"x"))
    monkeypatch.setattr(urllib.request, "urlopen", boom); h = H.Http(); h.backoff = 0
    with pytest.raises(H.GenHTTPError): h.call("POST", "https://x.example/a", json={})
    with pytest.raises(H.GenHTTPError): h.call("GET", "https://x.example/a")
    assert n == ["POST", "GET", "GET", "GET", "GET"]


# ---------------------------------------------------------------- specs, estimates
def project(owner=None):
    e = projects.create("灯笼", "memory", **({"owner": owner} if owner else {})); T = Thread(Path(e["path"]))
    refs = T.root / "2_perceive" / "landmark_refs" / "harbor"; refs.mkdir(parents=True, exist_ok=True); (refs / "1.png").write_bytes(PNG)
    (T.root / "1_ingest" / "derived").mkdir(parents=True, exist_ok=True); (T.root / "1_ingest" / "derived" / "her.png").write_bytes(PNG)
    return T


def test_normalize_checks_paths_and_shape():
    T = project(); R = T.root
    ok = gen.normalize(R, "fal:edit", {"jobs": [{"name": "h_A", "prompt": "p", "images": ["2_perceive/landmark_refs/harbor/1.png"]}], "out": "targets"})
    assert ok["out"] == "targets" and ok["model"] == "fal-ai/nano-banana-2/edit" and ok["jobs"][0]["images"] == ["2_perceive/landmark_refs/harbor/1.png"]
    assert gen.normalize(R, "meshy:image-to-3d", {"jobs": [{"name": "g", "images": ["2_perceive/landmark_refs/harbor/1.png"]}]})["out"] == "art/3d"
    (R / "conversation" / "x.png").write_bytes(PNG)
    bad = [("fal:image", {"jobs": [{"name": "a", "prompt": "p", "images": ["2_perceive/landmark_refs/harbor/1.png"]}]}, "只发文字"),
           ("fal:edit", {"jobs": [{"name": "a", "prompt": "p", "images": ["../x.png"]}]}, "不在项目"),
           ("fal:edit", {"jobs": [{"name": "a", "prompt": "p", "images": ["conversation/x.png"]}]}, "不能发送"),
           ("fal:edit", {"jobs": [{"name": "a", "prompt": "p", "images": ["2_perceive/nope.png"]}]}, "找不到"),
           ("fal:image", {"jobs": [{"name": "../a", "prompt": "p"}]}, "名字"), ("fal:image", {"jobs": [{"name": "a"}]}, "prompt"),
           ("fal:image", {"jobs": [{"name": "a", "prompt": "p"}], "out": "../../x"}, "4_design"), ("fal:image", {"jobs": [{"name": "a", "prompt": "p"}], "out": "tools"}, "out"),
           ("fal:image", {"jobs": [{"name": "a", "prompt": "p", "n": 99}]}, "n "), ("fal:image", {"jobs": []}, "jobs"),
           ("fal:nope", {"jobs": [{"name": "a", "prompt": "p"}]}, "不能做"), ("zz:image", {}, "没有这个"),
           ("fal:image", {"model": "made/up", "jobs": [{"name": "a", "prompt": "p"}]}, "price")]
    for tool, spec, msg in bad:
        with pytest.raises(gen.GenSpecError, match=msg): gen.normalize(R, tool, spec)


def test_estimate_feeds_the_go_card():
    e = gen.estimate("fal:image", n=4)
    assert e["estimate"]["cost_usd"] == [0.24, 0.64] and e["cost_usd_max"] == 0.64 and e["outputs"] == 4 and e["price"]["verified"]
    T = Thread(project().root)
    T.card({"kind": "go", "key": "g", "title": "画 4 张", "milestone": "preview", "items": ["4 张"], "estimate": e["estimate"], "cost_usd": e["cost_usd_max"]})
    m = gen.estimate("meshy:image-to-3d", n=3); assert m["estimate"]["cost_usd"] == [1.44, 2.25] and not m["price"]["verified"]
    assert gen.estimate("comfy:image", n=5)["cost_usd_max"] == 0


def test_cli_list_and_estimate_never_print_a_key(monkeypatch, capsys):
    monkeypatch.setenv("FAL_KEY", FAL); monkeypatch.setattr(H, "DEFAULT", Fake({}))
    assert cli.main(["gen", "list"]) == 0
    out = capsys.readouterr().out
    assert FAL not in out and "fal-secret" not in out and re.search(r"fal:image +ready +FAL_KEY: yes", out) and re.search(r"meshy:image-to-3d +- +MESHY_API_KEY: no", out)
    assert cli.main(["gen", "estimate", "--tool", "meshy:image-to-3d", "--n", "2", "--json"]) == 0
    d = json.loads(capsys.readouterr().out); assert d["estimate"]["account"] == "api" and d["key"] == "MESHY_API_KEY"
    assert cli.main(["gen", "estimate", "--tool", "meshy:image-to-3d", "--option", "should_texture=false", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["estimate"]["cost_usd"] == [0.32, 0.5], "--option values are yaml (false), as for a request"


# ---------------------------------------------------------------- queue -> agentd -> run (the whole path)
def cards(T, to="fal.ai", files=("2_perceive/landmark_refs/**",), cost=1.0, perm="yes", go="start", max_images=None):
    p = T.card({"kind": "permission", "key": "preview-permission", "title": "发给 fal？", "to": to, "will_send": ["文字描述", "公开的地标参考图"],
                "will_not_send": ["你的照片"], **({"files": list(files)} if files is not None else {})})
    g = T.card({"kind": "go", "key": "preview-go", "title": "画预览图", "milestone": "preview", "items": ["2 张"],
                **({"cost_usd": cost} if cost is not None else {}), **({"max_images": max_images} if max_images else {})})
    if perm: T.answer(p["id"], {"decision": perm})
    if go: T.answer(g["id"], {"decision": go})
    return p, g


def notes(T): return [json.loads(f.read_text(encoding="utf-8"))["text"] for f in agentd.inbox(T)]


def daemon():
    def nospawn(*a, **k): raise AssertionError("no agent run in this test")

    def nogen(*a, **k): raise AssertionError("an adapter request never starts a script")
    return agentd.Agentd(claude="/bin/false", spawn=nospawn, quiet=True, gen_spawn=nogen)


def run_once(T):
    D = daemon(); D._gen(None, T); D.wait_gens(); return D


@pytest.fixture
def fal_ok(monkeypatch):
    f = Fake(fal_routes({"images": [{"url": "https://cdn.example/a.png"}]}, status=("COMPLETED",)))
    monkeypatch.setattr(H, "DEFAULT", f); monkeypatch.setattr(genrun, "POLL_SECS", 0); return f


def inputs(T, jobs, **kw):
    f = T.root / "4_design" / "gen" / "previews.yaml"; f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(yaml.safe_dump({"jobs": jobs, **kw}, allow_unicode=True), encoding="utf-8"); return "4_design/gen/previews.yaml"


JOBS = [{"name": "harbor_A", "prompt": "Cities: Skylines screenshot of a harbor", "images": ["2_perceive/landmark_refs/harbor/1.png"]},
        {"name": "harbor_B", "prompt": "same, other angle"}]
JOBS2 = [JOBS[0], {**JOBS[1], "images": ["2_perceive/landmark_refs/harbor/1.png"]}]


def test_end_to_end_adapter_request(fal_ok, monkeypatch, capsys):
    monkeypatch.setenv("FAL_KEY", FAL)
    T = project(); cards(T)
    assert cli.main(["gen", "request", "--project", str(T.root), "--tool", "fal:edit", "--inputs", inputs(T, JOBS2, out="previews"),
                     "--permission-key", "preview-permission", "--go-key", "preview-go"]) == 0
    (q,) = genrun.pending(T.root); d = json.loads(q.read_text(encoding="utf-8"))
    assert d["adapter"] and d["spec"]["tool"] == "fal:edit" and d["estimate"]["cost_usd"] == [0.12, 0.32] and fal_ok.calls == [], "queueing sends nothing"
    run_once(T)
    out = T.root / "4_design" / "previews"
    assert (out / "harbor_A.png").read_bytes() == PNG and (out / "harbor_B.png").exists()
    idx = yaml.safe_load((out / "index.yaml").read_text(encoding="utf-8"))["items"]
    a = idx["harbor_A"]; assert a["adapter"] == "fal" and a["model"] == "fal-ai/nano-banana-2/edit" and a["files"][0]["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert a["files"][0]["path"] == "4_design/previews/harbor_A.png" and a["images_sent"] == ["2_perceive/landmark_refs/harbor/1.png"] and a["go_card"]
    led = yaml.safe_load((T.root / "privacy_ledger.yaml").read_text(encoding="utf-8"))["requests"]
    assert [r["id"] for r in led] == ["gen/previews/harbor_A", "gen/previews/harbor_B"] and led[0]["backend"] == "fal" and led[0]["status"] == "ok"
    assert led[0]["sent"]["images"] == ["2_perceive/landmark_refs/harbor/1.png"] and led[0]["sent"]["text"] == [JOBS[0]["prompt"]]
    (n,) = notes(T); assert "已完成" in n and "做好 2 个" in n and "4_design/previews/" in n
    every = json.dumps([*Path(genrun.used(T.root)[a["go_card"]]["log"]).read_text(encoding="utf-8").splitlines(), led, idx, n], ensure_ascii=False)
    assert FAL not in every and "fal-secret-value" not in every
    assert fal_ok.calls[0]["headers"]["Authorization"] == f"Key {FAL}"
    prog = [e for e in T.events() if e.get("type") == "card" and (e.get("card") or {}).get("kind") == "progress"]
    assert prog and [s["state"] for s in prog[-1]["card"]["steps"]] == ["done", "done"]
    # the same go card never runs twice; an existing output is skipped on a new card
    genrun.request(T.root, "fal:edit", "preview-permission", "preview-go", spec=gen.load_inputs(T.root, "4_design/gen/previews.yaml"))
    n0 = len(fal_ok.calls); run_once(T); assert len(fal_ok.calls) == n0 and any("用过一次" in x for x in notes(T))


@pytest.mark.parametrize("kw,spec_jobs,why", [
    ({"perm": None}, JOBS2, "许可卡"), ({"go": "wait"}, JOBS2, "开工卡"),
    ({"to": "Meshy"}, JOBS2, "发给 fal.ai"), ({"files": None}, JOBS2, "files"), ({"files": ["2_perceive/other/*"]}, JOBS2, "不在许可卡"),
    ({"cost": None}, JOBS2, "多少钱"), ({"cost": 0.05}, JOBS2, "超过了开工卡"), ({"max_images": 1}, JOBS2, "最多 1"),
])
def test_refusals(fal_ok, monkeypatch, kw, spec_jobs, why):
    monkeypatch.setenv("FAL_KEY", FAL)
    T = project(); cards(T, **kw)
    genrun.request(T.root, "fal:edit", "preview-permission", "preview-go", spec={"jobs": spec_jobs})
    run_once(T)
    assert fal_ok.calls == [] and not (T.root / "privacy_ledger.yaml").exists()
    (n,) = notes(T); assert "没有执行" in n and why in n, n
    assert len(list((genrun.queue_dir(T.root) / "rejected").glob("*.json"))) == 1


def test_missing_key_refused_and_her_photos_need_the_card(fal_ok):
    T = project(); cards(T)
    genrun.request(T.root, "fal:image", "preview-permission", "preview-go", spec={"jobs": [{"name": "a", "prompt": "p"}]})
    run_once(T); assert "FAL_KEY" in notes(T)[-1] and "素材生成 API keys" in notes(T)[-1] and fal_ok.calls == []
    T2 = project(); cards(T2)
    genrun.request(T2.root, "fal:edit", "preview-permission", "preview-go", spec={"jobs": [{"name": "a", "prompt": "p", "images": ["1_ingest/derived/her.png"]}]})
    run_once(T2); assert "1_ingest/derived/her.png" in notes(T2)[-1] and fal_ok.calls == []


def test_a_failing_job_does_not_stop_the_others_and_is_ledgered(monkeypatch):
    monkeypatch.setenv("FAL_KEY", FAL); monkeypatch.setattr(genrun, "POLL_SECS", 0)
    r = fal_routes({"images": [{"url": "https://cdn.example/a.png"}]}, status=("COMPLETED",))
    first = [True]

    def submit(u, k):
        if first[0]: first[0] = False; return H.GenHTTPError(422, u, f"bad input; key was {FAL}")
        return {"request_id": "rq1", "status_url": "https://queue.fal.run/fal-ai/x/requests/rq1/status", "response_url": "https://queue.fal.run/fal-ai/x/requests/rq1"}
    r[("POST", r"^https://queue\.fal\.run/fal-ai/")] = submit
    monkeypatch.setattr(H, "DEFAULT", Fake(r))
    T = project(); cards(T)
    genrun.request(T.root, "fal:image", "preview-permission", "preview-go", spec={"jobs": [{"name": "a", "prompt": "p"}, {"name": "b", "prompt": "q"}]})
    run_once(T)
    led = yaml.safe_load((T.root / "privacy_ledger.yaml").read_text(encoding="utf-8"))["requests"]
    assert led[0]["status"].startswith("error") and led[1]["status"] == "ok" and (T.root / "4_design" / "art" / "gen" / "b.png").exists()
    n = notes(T)[-1]; assert "没有全部成功" in n and "失败 1 个" in n and FAL not in n
    assert genrun.used(T.root)[next(iter(genrun.used(T.root)))]["state"] == "failed"


def test_owner_key_on_a_hub_never_the_supervisors(fal_ok, monkeypatch):
    home = Path.home(); monkeypatch.setenv("FAL_KEY", "supervisor-fal-key-0000000000")
    users.add_user("bob", "bob-pass-4567", False, "Bob", home / "bob" / "m2w", home / "bob" / ".claude-m2w")
    users.set_gen_key("bob", "FAL_KEY", FAL)
    T = project(owner="bob"); cards(T)
    genrun.request(T.root, "fal:image", "preview-permission", "preview-go", spec={"jobs": [{"name": "a", "prompt": "p"}]})
    run_once(T)
    assert fal_ok.calls[0]["headers"]["Authorization"] == f"Key {FAL}" and "已完成" in notes(T)[-1]


# ---------------------------------------------------------------- GAMEANYTHING_GEN_OFF and the agent's env
def test_gen_off_blocks_keys_in_a_run(monkeypatch, capsys):
    monkeypatch.setenv("FAL_KEY", FAL)
    env = agent_providers.agent_env(dict(__import__("os").environ), "claude-code")
    assert "FAL_KEY" not in env and env["GAMEANYTHING_GEN_OFF"] == "1", "a resident / builder run never gets a generation key"
    monkeypatch.setenv("GAMEANYTHING_GEN_OFF", "1")
    with pytest.raises(keys.GenOff): keys.get("FAL_KEY")
    with pytest.raises(SystemExit, match="agent"): cli.main(["gen", "key", "status"])
    # genrun's own env drops the flag (a daemon started from inside a run): the owner's key still works there
    e, _ = genrun.env_for(project().root); assert "GAMEANYTHING_GEN_OFF" not in e and keys.lookup("FAL_KEY", e) == FAL


def test_deny_list_covers_the_keyring():
    for cmd in ("secret-tool lookup service m2w-gen key FAL_KEY", "security find-generic-password -s memory2world-m2w-gen -w"):
        assert any(re.fullmatch("".join(".*" if ch == "*" else re.escape(ch) for ch in r[5:-1]), cmd) for r in agentd.DENY)
    assert not any(re.fullmatch("".join(".*" if ch == "*" else re.escape(ch) for ch in r[5:-1]), 'gameanything gen request --project "$P" --tool fal:image --inputs x.yaml --permission p --go g')
                   for r in agentd.DENY)


# ---------------------------------------------------------------- keys: keyring (single user) and 「我的 agent」 (hub)
def test_keyring_lookup_and_cli(monkeypatch, capsys, tmp_path):
    store = {}
    monkeypatch.setattr(osdirs, "secret_get", lambda s, k: store.get((s, k), ""))
    monkeypatch.setattr(osdirs, "secret_set", lambda s, k, v, label: store.__setitem__((s, k), v) or True)
    monkeypatch.setattr(osdirs, "secret_clear", lambda s, k: store.pop((s, k), None) is not None)
    monkeypatch.delenv("GAMEANYTHING_NO_KEYRING")
    kf = tmp_path / "k.txt"; kf.write_text(MESHY + "\n", encoding="utf-8")
    assert cli.main(["gen", "key", "set", "MESHY_API_KEY", "--from-file", str(kf)]) == 0
    assert store[("m2w-gen", "MESHY_API_KEY")] == MESHY and keys.lookup("MESHY_API_KEY") == MESHY and keys.source("MESHY_API_KEY") == "keyring"
    assert keys.lookup("MESHY_API_KEY", {"GAMEANYTHING_KEYS_FILE": ""}) is None, "a hub user's run never reads the OS user's keyring"
    assert cli.main(["gen", "key", "status", "MESHY_API_KEY"]) == 0
    out = capsys.readouterr().out; assert MESHY not in out and "keyring" in out
    assert cli.main(["gen", "key", "remove", "MESHY_API_KEY"]) == 0 and keys.lookup("MESHY_API_KEY") is None


def test_hub_gen_keys_api(hub):
    c = Client(hub).login("carol")
    code, r, _ = c.get("/api/me/genkeys"); assert code == 200 and [k["name"] for k in r["keys"]][:4] == ["FAL_KEY", "MESHY_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"]
    assert not any(k["set"] for k in r["keys"])
    for bad in ("", "short", "sk-ant-api03-" + "x" * 30, "bad/chars!" + "x" * 20):
        code, r, _ = c.post("/api/me/genkeys", {"key": "FAL_KEY", "value": bad}); assert code == 400 and not r["ok"]
    assert c.post("/api/me/genkeys", {"key": "PATH", "value": "x" * 30})[0] == 400
    code, r, _ = c.post("/api/me/genkeys", {"key": "FAL_KEY", "value": FAL}); assert code == 200 and {k["name"]: k["set"] for k in r["keys"]}["FAL_KEY"]
    code, r2, _ = c.post("/api/me/genkeys", {"key": "MESHY_API_KEY", "value": MESHY})
    assert FAL not in json.dumps(r) + json.dumps(r2) + json.dumps(c.get("/api/me/genkeys")[1]) and MESHY not in json.dumps(r2)
    u = users.get_user("carol"); f = Path(u["env_file"]); t = f.read_text(encoding="utf-8")
    assert f"FAL_KEY={FAL}" in t and f"MESHY_API_KEY={MESHY}" in t and (osdirs.system() == "windows" or (f.stat().st_mode & 0o777) == 0o600)
    pc = projects.create("C", "feature", owner="carol"); e, _ = users.gen_env(pc["path"], {})
    assert keys.lookup("FAL_KEY", e) == FAL and "FAL_KEY" not in agent_providers.agent_env(e, "claude-code")
    code, r, _ = c.post("/api/me/genkeys/remove", {"key": "FAL_KEY"}); assert code == 200 and not {k["name"]: k["set"] for k in r["keys"]}["FAL_KEY"]
    assert "FAL_KEY" not in f.read_text(encoding="utf-8") and f"MESHY_API_KEY={MESHY}" in f.read_text(encoding="utf-8")
    assert Client(hub).get("/api/me/genkeys")[0] == 401


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_hub_gen_key_words_have_english():
    from gameanything.ui import STATIC
    js = (STATIC / "hub.js").read_text(encoding="utf-8"); i = js.index("async function paintGenKeys"); part = js[i:js.index("/* 「用 ChatGPT", i)]
    used = sorted({m for m in re.findall(r'\bt\("((?:[^"\\]|\\.)*)"', part) if re.search(r"[一-鿿]", m)})
    probe = ("globalThis.window={addEventListener(){}};globalThis.document={documentElement:{dataset:{},getAttribute(){return null},setAttribute(){}},"
             "addEventListener(){},querySelectorAll(){return[]}};globalThis.localStorage={getItem(){return null},setItem(){}};globalThis.navigator={language:'zh'};\n"
             + (STATIC / "i18n.js").read_text(encoding="utf-8") + f"\nconsole.log(JSON.stringify({json.dumps(used, ensure_ascii=False)}.filter(s=>!(s in EN))))")
    missing = json.loads(subprocess.run(["node", "-"], input=probe, capture_output=True, text=True, check=True, encoding="utf-8").stdout)
    assert used and missing == []


def test_permission_card_files_field():
    T = Thread(project().root)
    with pytest.raises(CardError, match="files"): T.card({"kind": "permission", "title": "t", "to": "fal", "will_send": [], "will_not_send": [], "files": "x"})


def test_fal_api_key_is_the_same_key(fal_ok, monkeypatch, capsys, tmp_path):
    """Her .env says FAL_API_KEY (fal's docs say FAL_KEY): both names work everywhere, and both are stripped from agent runs."""
    monkeypatch.delenv("FAL_KEY", raising=False); monkeypatch.setenv("FAL_API_KEY", FAL)
    assert keys.lookup("FAL_KEY") == FAL and keys.source("FAL_KEY") == "env"
    assert cli.main(["gen", "list"]) == 0 and re.search(r"fal:image +ready +FAL_KEY: yes", capsys.readouterr().out)
    env = agent_providers.agent_env(dict(__import__("os").environ), "claude-code"); assert "FAL_API_KEY" not in env and "FAL_KEY" not in env
    assert users.CRED_RE.match("FAL_API_KEY") and FAL not in genrun.redact(f"x {FAL} y", {"FAL_API_KEY": FAL})
    kf = tmp_path / "k.env"; kf.write_text(f"FAL_API_KEY={FAL}\n", encoding="utf-8")
    assert keys.lookup("FAL_KEY", {"GAMEANYTHING_KEYS_FILE": str(kf)}) == FAL
    T = project(); cards(T)
    genrun.request(T.root, "fal:image", "preview-permission", "preview-go", spec={"jobs": [{"name": "a", "prompt": "p"}]})
    run_once(T); post = [x for x in fal_ok.calls if x["method"] == "POST"]
    assert post[0]["headers"]["Authorization"] == f"Key {FAL}" and "已完成" in notes(T)[-1]


def test_hub_fal_api_key_alias(hub):
    c = Client(hub).login("carol"); u = users.get_user("carol")
    users._edit_env_file(Path(users.env_path(u)), {"FAL_API_KEY": FAL})
    code, r, _ = c.get("/api/me/genkeys"); assert {k["name"]: k["set"] for k in r["keys"]}["FAL_KEY"]
    c.post("/api/me/genkeys", {"key": "FAL_KEY", "value": FAL + "x"})
    t = Path(users.env_path(users.get_user("carol"))).read_text(encoding="utf-8"); assert f"FAL_KEY={FAL}x" in t and "FAL_API_KEY" not in t
    users._edit_env_file(Path(users.env_path(users.get_user("carol"))), {"FAL_API_KEY": FAL})
    code, r, _ = c.post("/api/me/genkeys/remove", {"key": "FAL_KEY"}); assert not {k["name"]: k["set"] for k in r["keys"]}["FAL_KEY"]
    assert "FAL" not in Path(users.env_path(users.get_user("carol"))).read_text(encoding="utf-8")
