"""Pictures from the videos of an adaptation project's work (local only, nothing is sent): keyframes per shot and the key people.

    gameanything visuals --project P [--no-people] [--threshold 0.3]

1. keyframes: ffmpeg scene-change detection splits each ingested video into shots; a few representative frames per shot (start /
   middle / end, near-identical ones dropped) go to 2_perceive/keyframes/<video item>/kNNN.jpg. index.yaml lists every shot with its
   start / end, its frames ({file, t}) and the transcript lines spoken in it (`said`), so the agent can match shots to scenes.
2. people: person boxes in every keyframe (the ingest `detect` extra, torchvision Faster R-CNN, when its weights are on this computer;
   else OpenCV face boxes when cv2 is installed; else a centre crop), crops clustered by appearance (colour histogram of the box) into
   2_perceive/people/<cNN>/NNN.jpg; 2_perceive/people/index.yaml lists the clusters (the largest crop first). Detection only: it never
   tells who someone is; the agent and she name them.

The agent then links them in 3_remember/adaptation.yaml: a scene `frames: [{file, t}]`, a character `image:` / `frames:`. The pages and
cards show them under /media/2_perceive/... They are reference material: never shipped into the game, never published, and sent to a
model only after a `permission` card. Each run adds a `local:` line to privacy_ledger.yaml (what was made, nothing sent).
"""
import re
import subprocess
from datetime import datetime
from pathlib import Path

import yaml

from . import layout

KEY_DIR = f"{layout.PERCEIVE}/keyframes"
PEOPLE_DIR = f"{layout.PERCEIVE}/people"
THRESHOLD = 0.30          # ffmpeg scene score for a cut
MIN_SHOT = 0.4            # seconds: a shorter shot is merged into the one before
PER_SHOT = 3
MAX_FRAMES = 150
FRAME_DIFF = 6            # min dhash distance between frames kept in one shot
SIMILAR = 0.62            # histogram intersection to join a people cluster
MAX_CROPS = 6


def _y(p: Path, default=None):
    try: return yaml.safe_load(p.read_text(encoding="utf-8")) or default
    except (OSError, yaml.YAMLError): return default


def videos(root: Path) -> list:
    """[{id, file, duration, transcript}] of the ingested videos of the project (pack.yaml items kind video, included)."""
    out = []
    for it in (_y(layout.pack(Path(root)), {}) or {}).get("items") or []:
        if it.get("kind") == "video" and it.get("included", True) and it.get("file"):
            out.append({"id": str(it.get("id")), "file": str(it["file"]), "duration": float(it.get("duration") or 0),
                        "transcript": ((it.get("derived") or {}).get("transcript"))})
    return out


def index(root: Path) -> dict:
    return _y(Path(root) / KEY_DIR / "index.yaml", {}) or {}


def people_index(root: Path) -> dict:
    return _y(Path(root) / PEOPLE_DIR / "index.yaml", {}) or {}


def cuts(video: str, threshold=THRESHOLD) -> list:
    """Times (s) where ffmpeg sees a scene change."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-an", "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return sorted({round(float(m), 2) for m in re.findall(r"Parsed_showinfo.*?pts_time:\s*([\d.]+)", r.stderr)})


def shots(duration: float, cut_times: list) -> list:
    """[(start, end)] from the cut times; very short shots join the one before."""
    edges = [0.0] + [t for t in cut_times if 0 < t < duration] + [duration]
    out = []
    for a, b in zip(edges, edges[1:]):
        if out and b - a < MIN_SHOT: out[-1] = (out[-1][0], b)
        elif b > a: out.append((a, b))
    return out


def _said(segs, a, b) -> str:
    return " ".join(str(s.get("text") or "").strip() for s in segs if float(s.get("t0", 0)) < b and float(s.get("t1", 0)) > a).strip()


def _grab(video, t, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", str(dst)],
                   check=True, capture_output=True)
    return dst.exists()


def _dhash(path: Path, size=8) -> int:
    """Difference hash of a picture (like ingest.images.dhash; not imported from there: the ingest package pulls in the PDF reader)."""
    from PIL import Image
    g = Image.open(path).convert("L").resize((size + 1, size)); px = list(g.tobytes()); w = size + 1
    return sum(1 << i for i, (a, b) in enumerate((px[r * w + c], px[r * w + c + 1]) for r in range(size) for c in range(size)) if a > b)


def keyframes(root: Path, threshold=THRESHOLD, cut_fn=cuts) -> dict:
    """Write 2_perceive/keyframes/<video id>/kNNN.jpg + index.yaml for every video. -> the index."""
    root = Path(root); base = root / KEY_DIR; out = {"made": datetime.now().isoformat(timespec="seconds"), "threshold": threshold, "videos": {}}
    total = 0
    for v in videos(root):
        tr = _y(root / v["transcript"], {}) if v["transcript"] else {}
        segs = (tr or {}).get("segments") or []
        d = base / v["id"]; d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("k*.jpg"): f.unlink()                      # our own derived files: redo them whole
        rows = []
        for n, (a, b) in enumerate(shots(v["duration"], cut_fn(v["file"], threshold)), 1):
            ln = b - a
            ts = [a + ln / 2] if ln < 2 else [a + 0.3, a + ln / 2, b - 0.3][:PER_SHOT]
            frames, last = [], None
            for t in ts:
                if total >= MAX_FRAMES: break
                dst = d / f"k{total + 1:03d}.jpg"
                if not _grab(v["file"], t, dst): continue
                h = _dhash(dst)
                if last is not None and bin(h ^ last).count("1") < FRAME_DIFF: dst.unlink(); continue
                last = h; total += 1
                frames.append({"file": dst.relative_to(root).as_posix(), "t": round(t, 2)})
            if frames: rows.append({"n": n, "start": round(a, 2), "end": round(b, 2), "frames": frames, "said": _said(segs, a, b)})
        out["videos"][v["id"]] = {"file": Path(v["file"]).name, "duration": v["duration"], "shots": rows}
    base.mkdir(parents=True, exist_ok=True)
    (base / "index.yaml").write_text("# keyframes per shot (gameanything visuals): reference only, never shipped or published; sending them to a model needs a permission card\n"
                                     + yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    return out


# ---------------------------------------------------------------- people
def _detector():
    """-> (name, fn(PIL image) -> [(x0, y0, x1, y1) pixels]). Never downloads anything."""
    try:
        import torch
        from .ingest import persons
        ck = Path(torch.hub.get_dir()) / "checkpoints"
        if persons.available() and any(ck.glob("fasterrcnn_resnet50_fpn_v2*")):
            def fr(im):
                m, tf = persons.model()
                with torch.inference_mode(): o = m([tf(im)])[0]
                return [tuple(float(x) for x in b) for b, s, l in zip(o["boxes"], o["scores"], o["labels"]) if int(l) == persons.PERSON and float(s) >= 0.7]
            return "torchvision-person", fr
    except Exception:
        pass
    try:
        import cv2
        import numpy as np
        cc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if not cc.empty():
            def face(im):
                g = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2GRAY)
                fs = cc.detectMultiScale(g, 1.1, 5, minSize=(max(24, im.width // 25),) * 2)
                # a face box grown to head and shoulders: clothes help the clustering
                return [(max(0, x - w * .6), max(0, y - h * .4), min(im.width, x + w * 1.6), min(im.height, y + h * 2.6)) for x, y, w, h in fs]
            return "opencv-face", face
    except Exception:
        pass
    return "skin-blob", skin_boxes


def skin_boxes(im, cell=8) -> list:
    """No detector installed: skin-coloured blobs (YCbCr range) on a coarse grid, each grown to head and shoulders. Crude, colour
    footage only; she corrects the result on the 角色 page."""
    import numpy as np
    W = 192; sm = im.resize((W, max(8, int(im.height * W / im.width)))); a = np.asarray(sm.convert("YCbCr"), dtype=np.int32)
    y, cb, cr = a[..., 0], a[..., 1], a[..., 2]
    m = (y > 50) & (cb > 80) & (cb < 130) & (cr > 136) & (cr < 175)
    gh, gw = m.shape[0] // cell, m.shape[1] // cell
    g = m[:gh * cell, :gw * cell].reshape(gh, cell, gw, cell).mean(axis=(1, 3)) > 0.45
    seen, out, sx = set(), [], im.width / W
    for r in range(gh):
        for c in range(gw):
            if not g[r, c] or (r, c) in seen: continue
            st, comp = [(r, c)], []; seen.add((r, c))
            while st:
                y0, x0 = st.pop(); comp.append((y0, x0))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = (y0 + dy, x0 + dx)
                    if 0 <= n[0] < gh and 0 <= n[1] < gw and g[n] and n not in seen: seen.add(n); st.append(n)
            if not 2 <= len(comp) <= gh * gw // 4: continue
            r0, r1 = min(p[0] for p in comp), max(p[0] for p in comp) + 1; c0, c1 = min(p[1] for p in comp), max(p[1] for p in comp) + 1
            w, h = (c1 - c0) * cell * sx, (r1 - r0) * cell * sx; x, yy = c0 * cell * sx, r0 * cell * sx
            if not 0.4 <= w / max(h, 1) <= 2.0: continue
            out.append((max(0, x - w * .6), max(0, yy - h * .3), min(im.width, x + w * 1.6), min(im.height, yy + h * 2.6)))
    return out


def _hist(im):
    import numpy as np
    a = np.asarray(im.convert("HSV").resize((48, 64)), dtype=np.int32)
    h = np.histogram2d(a[..., 0].ravel() // 32, a[..., 1].ravel() // 64, bins=[8, 4], range=[[0, 8], [0, 4]])[0].ravel()
    return h / max(1.0, h.sum())


def people(root: Path, detect=None) -> dict:
    """Person crops of every keyframe, clustered by appearance -> 2_perceive/people/<cNN>/NNN.jpg + index.yaml. -> the index."""
    import numpy as np
    from PIL import Image
    root = Path(root); base = root / PEOPLE_DIR
    name, fn = detect or _detector()
    crops = []
    for vid, v in (index(root).get("videos") or {}).items():
        for s in v.get("shots") or []:
            for f in s.get("frames") or []:
                im = Image.open(root / f["file"]).convert("RGB")
                for b in fn(im):
                    x0, y0, x1, y1 = (int(round(x)) for x in b)
                    if (x1 - x0) * (y1 - y0) < im.width * im.height * 0.01: continue
                    c = im.crop((x0, y0, x1, y1)); crops.append({"im": c, "h": _hist(c), "frame": f["file"], "t": f["t"], "video": vid,
                                                                  "box": [round(x0 / im.width, 3), round(y0 / im.height, 3), round(x1 / im.width, 3), round(y1 / im.height, 3)],
                                                                  "area": (x1 - x0) * (y1 - y0)})
    clusters = []
    for c in sorted(crops, key=lambda c: -c["area"]):
        best, sc = None, 0.0
        for k in clusters:
            s = float(np.minimum(c["h"], k["h"]).sum())
            if s > sc: best, sc = k, s
        if best is not None and sc >= SIMILAR:
            best["m"].append(c); best["h"] = np.mean([x["h"] for x in best["m"]], axis=0)
        else: clusters.append({"h": c["h"], "m": [c]})
    if base.is_dir():
        for f in base.glob("c*/*.jpg"): f.unlink()
    rows = []
    for i, k in enumerate(sorted(clusters, key=lambda k: -len(k["m"])), 1):
        cid = f"c{i:02d}"; d = base / cid; d.mkdir(parents=True, exist_ok=True); out = []
        for j, c in enumerate(k["m"][:MAX_CROPS], 1):
            dst = d / f"{j:03d}.jpg"; c["im"].save(dst, quality=88)
            out.append({"file": dst.relative_to(root).as_posix(), "frame": c["frame"], "t": c["t"], "box": c["box"]})
        rows.append({"id": cid, "n": len(k["m"]), "rep": out[0]["file"], "crops": out})
    res = {"made": datetime.now().isoformat(timespec="seconds"), "method": name, "clusters": rows}
    base.mkdir(parents=True, exist_ok=True)
    (base / "index.yaml").write_text("# people seen in the keyframes, clustered by appearance (gameanything visuals). Detection only: nobody is identified;\n"
                                     "# the agent names them with her. Reference only, never shipped or published.\n"
                                     + yaml.safe_dump(res, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    return res


def note_ledger(root: Path, what: str):
    """A `local:` line in privacy_ledger.yaml: made on this computer, nothing sent."""
    p = Path(root) / layout.LEDGER; d = _y(p, {}) or {}
    if isinstance(d, list): d = {"requests": d}
    d.setdefault("requests", []); d.setdefault("local", []).append({"at": datetime.now().isoformat(timespec="seconds"), "what": what, "sent": "nothing",
                                                                   "note": "reference only: never shipped into the game, never published"})
    p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")


def run(root: Path, with_people=True, threshold=THRESHOLD) -> dict:
    root = Path(root)
    if not videos(root): return {"videos": 0}
    k = keyframes(root, threshold)
    n = sum(len(f["frames"]) for v in k["videos"].values() for f in v["shots"])
    r = {"videos": len(k["videos"]), "shots": sum(len(v["shots"]) for v in k["videos"].values()), "frames": n}
    if with_people:
        p = people(root); r.update(people=len(p["clusters"]), method=p["method"])
    note_ledger(root, f"gameanything visuals: {r['frames']} keyframes" + (f", {r.get('people')} people clusters ({r.get('method')})" if with_people else ""))
    return r
