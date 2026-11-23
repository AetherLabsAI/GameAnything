"""Optional features (2026-11-01): parts of GameAnything that need a large package the basic install leaves out, installed only after her
yes on a card. Without one, the feature is skipped with a note (never an error), and the agent asks once.

    transcribe  speech in her videos -> text (faster-whisper, local, offline once the model is downloaded)
    detect      person boxes on the people page's photos (PyTorch + torchvision Faster R-CNN, local)

    status()                   -> {name: {installed, version}}
    request(root, name, ...)   -> {state: installed | go | pending | refused, code, why, card?}: her answer on the card (posts it when needed)
    install(root, name, ...)   -> request() and, on her yes, the install into the Python GameAnything runs in (uv pip, else pip); state done | failed
    command(name)              -> the install command, for someone at their own terminal

`gameanything extras status|install <name> --project P` (cli.py). Exit codes like `native launch`: 0 installed / done, 2 pending, 3 refused / failed.
jsonschema (perceive) is a basic dependency since 2026-11-01; `dev` (Playwright, UI screenshots) is for contributors (CONTRIBUTING.md).
"""
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SESSION = "m2w-extras"                       # the card is posted by the tool, not by an agent session

FEATURES = {
    "transcribe": {
        "modules": ["faster_whisper"], "dist": "faster-whisper", "pip": ["faster-whisper>=1.0"],
        "title": "本地语音转文字", "title_en": "Speech to text, on this computer",
        "what": "把视频里说的话转成文字，agent 才知道视频里谁说了什么（在这台电脑上转，不上传）",
        "what_en": "turns what people say in your videos into text, so the agent knows who said what (done on this computer, nothing is uploaded)",
        "size": "约 150 MB；第一次转文字时再下载一个约 1.6 GB 的语音模型",
        "size_en": "about 150 MB; the first transcription then downloads a speech model of about 1.6 GB",
        "without": "视频照样导入，只是不知道里面说了什么", "without_en": "videos are still added, but what is said in them stays unknown",
    },
    "detect": {
        "modules": ["torch", "torchvision"], "dist": "torch", "pip": ["torch>=2.1", "torchvision>=0.16"],
        "title": "照片里自动框出人", "title_en": "Find people in photos automatically",
        "what": "在「人物 → 标记照片里的人」里先把每个人框好，你只要起名字（在这台电脑上找，不识别是谁、不上传）",
        "what_en": "draws a box around each person on the people page, so you only add names (done on this computer; it does not recognise anyone and uploads nothing)",
        "size": "几百 MB 到 2 GB 多（看系统和显卡）；第一次用时再下载约 170 MB 的模型",
        "size_en": "a few hundred MB to over 2 GB (depends on the system and graphics card); the first use then downloads a model of about 170 MB",
        "without": "照片照样导入，人物页里要你自己框人", "without_en": "photos are still added; on the people page you draw the boxes yourself",
    },
}


def card_key(name): return f"extra-{name}"


def available(name) -> bool:
    try: return all(importlib.util.find_spec(m) is not None for m in FEATURES[name]["modules"])
    except (ImportError, ValueError): return False


def status() -> dict:
    out = {}
    for n, f in FEATURES.items():
        ok = available(n)
        try: ver = importlib.metadata.version(f["dist"]) if ok else None
        except importlib.metadata.PackageNotFoundError: ver = None
        out[n] = {"installed": ok, "version": ver}
    return out


def command(name, which=shutil.which) -> list:
    """Into the Python that runs GameAnything: uv pip when uv is there (a `uv tool install` has no pip), else pip."""
    uv = which("uv")
    if uv: return [uv, "pip", "install", "--python", sys.executable, *FEATURES[name]["pip"]]
    return [sys.executable, "-m", "pip", "install", *FEATURES[name]["pip"]]


# ---------------------------------------------------------------- the card and her answer
def _file(root) -> Path: return Path(root) / "conversation" / ".extras.json"


def _used(root) -> set:
    try: return set(json.loads(_file(root).read_text(encoding="utf-8")).get("used") or [])
    except (OSError, ValueError, AttributeError): return set()


def _mark_used(root, aid):
    f = _file(root); f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp"); tmp.write_text(json.dumps({"used": sorted(_used(root) | {aid})}), encoding="utf-8"); os.replace(tmp, f)


def card_body(name) -> dict:
    f = FEATURES[name]
    return {"kind": "options", "key": card_key(name), "multi": False, "title": f"要装「{f['title']}」吗？", "feature": name,
            "items": [{"key": "install", "title": "装吧", "desc": f"{f['what']}。大小：{f['size']}。装好后我把已经导入的素材再处理一遍", "recommended": True},
                      {"key": "no", "title": "先不装", "desc": f"{f['without']}。以后想装，在对话里说一声就行"}],
            "en": {"title": f"Install \"{f['title_en']}\"?",
                   "items": [{"key": "install", "title": "Install it", "desc": f"It {f['what_en']}. Size: {f['size_en']}. Once it is in, I process what you added again", "recommended": True},
                             {"key": "no", "title": "Not now", "desc": f"Without it, {f['without_en']}. Say so in the chat if you want it later"}]}}


def _answer(c):
    ans = [a for a in c["answers"] if a.get("from") == "user" and a.get("source") == "ui"]     # her click in the page, nothing typed by an agent
    return ans[-1] if ans else None


def request(root, name, post=True, ask_again=False, reason=None, reason_en=None, is_available=None) -> dict:
    is_available = is_available or available
    if name not in FEATURES: raise ValueError(f"unknown optional feature: {name} ({' / '.join(FEATURES)})")
    if is_available(name): return {"state": "installed", "code": "installed", "why": f"{name} is installed already"}
    from .conversation import Thread
    T = Thread(root); c = next((v for v in T.cards().values() if v["card"].get("key") == card_key(name)), None)

    def ask(why):
        if not post: return {"state": "pending", "code": "asked", "why": why + " (no card posted: --no-post)"}
        f = FEATURES[name]
        cid = T.card(card_body(name), text=reason or f"导入素材时发现有一项可选功能没装：{f['title']}。", text_en=reason_en or
                     f"While adding your files I found an optional feature that is not installed: {f['title_en']}.", session=SESSION)["id"]
        return {"state": "pending", "code": "asked", "card": cid, "why": why + ": a card in the chat asks her; run this again after she answers"}

    if c is None: return ask("not asked yet")
    a = _answer(c); cid = c["event"]["id"]
    if a is None:
        if ask_again: return ask("asking again")
        return {"state": "pending", "code": "waiting", "card": cid, "why": "the card is out and not answered yet: do not post another, carry on without it"}
    pick = ((a.get("answer") or {}).get("picked") or [None])[0]
    if pick == "install":
        if a["id"] in _used(root): return ask("her yes was used for an install that did not stick")
        return {"state": "go", "code": "yes", "card": cid, "answer": a["id"], "why": "she chose 「装吧」"}
    if pick == "no":
        if ask_again: return ask("she said not now; asking again because she brought it up")
        return {"state": "refused", "code": "no", "card": cid, "why": "she chose 「先不装」: carry on without it and do not ask again unless she brings it up (then --ask-again)"}
    return {"state": "pending", "code": "note", "card": cid, "why": "she wrote a note instead of choosing: read it (gameanything chat read)"}


def install(root, name, run=subprocess.run, which=shutil.which, is_available=None, **kw) -> dict:
    is_available = is_available or available
    d = request(root, name, is_available=is_available, **kw)
    if d["state"] != "go": return d
    cmd = command(name, which)
    _mark_used(root, d["answer"])                                       # one yes, one install attempt
    try: r = run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
    except (OSError, subprocess.TimeoutExpired) as e: return {**d, "state": "failed", "code": "error", "command": cmd, "why": f"install did not run: {e}"}
    tail = ((r.stdout or "") + (r.stderr or "")).strip()[-1500:]
    if r.returncode != 0: return {**d, "state": "failed", "code": "pip", "command": cmd, "log": tail, "why": f"the installer stopped (exit {r.returncode})"}
    importlib.invalidate_caches()
    if not is_available(name): return {**d, "state": "failed", "code": "missing", "command": cmd, "log": tail, "why": "installed, but still not importable"}
    return {**d, "state": "done", "code": "done", "command": cmd, "why": f"{name} installed: process the files again (gameanything ingest … --project P)"}
