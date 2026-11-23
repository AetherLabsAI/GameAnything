"""Stage A of the memory pipeline (note: design in the GameAnything notes, "ingest-pipeline"): local and deterministic, no LLM.

    folder of memories  ->  <project>/1_ingest/pack.yaml + derived/ (images, thumbs, frames, audio, transcripts, docs, contact)

The user's files are only read (hashed, decoded); everything written goes under <project>/1_ingest/ (layout.py).
Re-running is incremental: an item whose sha256 is unchanged and whose derived files exist is not processed again.
"""
import hashlib
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

from . import docs, images, persons, timetrust, video
from .. import layout

SCHEMA = "gameanything.memory_pack/v0"
INGEST_VERSION = 2     # bump when derived data changes meaning (e.g. the hash size); a different version ignores the cache
NEAR_DUP = 16          # 256-bit dhash distance: re-sent / re-encoded copies of one shot (~3); different guests in front of one
                       # backdrop measured 42+ on a real wedding set, so they stay apart
SKIP_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def kind_of(p: Path):
    e = p.suffix.lower()
    if e in images.EXT: return "photo"
    if e in video.VIDEO_EXT: return "video"
    if e in video.AUDIO_EXT: return "audio"
    if e in docs.DOC_EXT: return "document"
    return None


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "item"


def scan(folder: Path):
    found, skipped = [], []
    natural = lambda p: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(p.relative_to(folder)))]
    for p in sorted(folder.rglob("*"), key=natural):
        if not p.is_file(): continue
        rel = p.relative_to(folder)
        if any(part.startswith(".") or part == "__MACOSX" for part in rel.parts) or p.name in SKIP_NAMES or p.name.startswith("._"):
            continue
        k = kind_of(p)
        (found if k else skipped).append((p, k) if k else {"file": rel.as_posix(), "why": f"unsupported type {p.suffix or '(none)'}"})
    return found, skipped


def rel(p, root):
    return Path(p).relative_to(root).as_posix() if p else None


def process_item(it, src: Path, D: Path, transcribe: bool, whisper_model, vocab=(), simplify=False):
    k, iid = it["kind"], it["id"]
    if k == "photo":
        r = images.process(src, D, iid)
        it.update(width=r["width"], height=r["height"], raw_metadata=r["raw_metadata"], dhash=f"{r['dhash']:064x}",
                  derived={"image": r["image"], "thumb": r["thumb"]})
    elif k in ("video", "audio"):
        pr = video.probe(src)
        it.update(duration=pr["duration"], raw_metadata=pr["raw_metadata"], derived={})
        if pr["has_video"]:
            fr = video.keyframes(src, pr["duration"], D / "frames" / iid)
            it["derived"]["frames"] = [{"t": f["t"], "file": f["file"]} for f in fr]
            if fr:
                im = images.load(fr[0]["file"]); images.save_scaled(im, D / "thumbs" / f"{iid}.jpg", images.THUMB_MAX)
                it["derived"]["thumb"] = D / "thumbs" / f"{iid}.jpg"
        if pr["has_audio"]:
            wav = video.extract_audio(src, D / "audio" / f"{iid}.wav"); it["derived"]["audio"] = wav
            if transcribe:
                print(f"[ingest] transcribing {iid} ({pr['duration']:.0f}s, local Whisper) ...", flush=True)
                tr = video.transcribe(wav, D / "transcripts" / f"{iid}.json", whisper_model, vocab)
                it["derived"]["transcript"] = D / "transcripts" / f"{iid}.json"
                it["speech"] = {"language": tr["language"], "language_prob": tr["language_prob"], "speech_seconds": tr["speech_seconds"],
                                "segments": len(tr["segments"]), "suspect_segments": sum(1 for x in tr["segments"] if x.get("suspect")),
                                "vocab_sha": _vocab_sha(vocab), "preview": " ".join(s["text"] for s in tr["segments"])[:200]}
    elif k == "document":
        r = docs.process(src, D / "docs" / iid, simplify=simplify)
        it.update(pages=len(r["pages"]), derived={"pages": [{k2: v for k2, v in pg.items()} for pg in r["pages"]]}, **({"simplified": True} if r.get("simplified") else {}))
        if r["pages"] and r["pages"][0].get("image"):
            images.save_scaled(images.load(r["pages"][0]["image"]), D / "thumbs" / f"{iid}.jpg", images.THUMB_MAX)
            it["derived"]["thumb"] = D / "thumbs" / f"{iid}.jpg"
    return it


def near_duplicates(items):
    """Union-find over photo dhashes; -> list of groups (ids), largest image first (= the representative)."""
    ph = [it for it in items if it["kind"] == "photo" and it.get("dhash")]
    parent = {it["id"]: it["id"] for it in ph}
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for i, a in enumerate(ph):
        for b in ph[i + 1:]:
            if bin(int(a["dhash"], 16) ^ int(b["dhash"], 16)).count("1") <= NEAR_DUP: parent[find(a["id"])] = find(b["id"])
    groups = {}
    for it in ph: groups.setdefault(find(it["id"]), []).append(it)
    out = []
    for g in groups.values():
        if len(g) > 1:
            g.sort(key=lambda it: -(it["width"] * it["height"])); out.append([it["id"] for it in g])
    return out


def contact_sheets(items, D: Path, cols=6, per=30):
    T = images.THUMB_MAX // 1.5; T = int(T)
    withthumb = [it for it in items if (it.get("derived") or {}).get("thumb")]
    sheets = []
    for s in range(0, len(withthumb), per):
        chunk = withthumb[s:s + per]; rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * T, rows * (T + 18)), "white"); d = ImageDraw.Draw(sheet)
        for i, it in enumerate(chunk):
            im = Image.open(it["derived"]["thumb"]); im.thumbnail((T, T))
            x, y = (i % cols) * T, (i // cols) * (T + 18)
            sheet.paste(im, (x + (T - im.width) // 2, y + (T - im.height) // 2)); d.text((x + 3, y + T + 2), f"{it['id']} [{it['kind']}]", fill="black")
        dst = D / "contact" / f"sheet{s // per + 1}.jpg"; dst.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(dst, "JPEG", quality=80); sheets.append(dst)
    return sheets


def to_yaml(x, root):
    if isinstance(x, Path): return rel(x, root)
    if isinstance(x, dict): return {k: to_yaml(v, root) for k, v in x.items()}
    if isinstance(x, list): return [to_yaml(v, root) for v in x]
    return x


def from_yaml(x, root):
    """Derived paths back to absolute Paths (for cache checks)."""
    if isinstance(x, dict): return {k: (root / v if k in ("image", "thumb", "file", "audio", "transcript", "text", "persons") and isinstance(v, str) else from_yaml(v, root)) for k, v in x.items()}
    if isinstance(x, list): return [from_yaml(v, root) for v in x]
    return x


def derived_ok(d):
    if isinstance(d, Path): return d.exists()
    if isinstance(d, dict): return all(derived_ok(v) for k, v in d.items() if k in ("image", "thumb", "file", "audio", "transcript", "text", "frames", "pages"))
    if isinstance(d, list): return all(derived_ok(v) for v in d)
    return True


def _vocab_sha(vocab):
    return hashlib.sha256("\n".join(vocab).encode()).hexdigest()[:12]


def load_vocab(project: Path, extra=()):
    """<project>/config/vocab.txt (one name / term per line, # comments) + --vocab; order kept, duplicates dropped."""
    f = layout.vocab(project)
    words = [l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")] if f.exists() else []
    return list(dict.fromkeys([*words, *extra]))


def ingest(folder: Path, project: Path, transcribe=True, whisper_model=None, vocab=(), detect=True):
    folder, project = folder.resolve(), project.resolve()
    if not folder.is_dir(): sys.exit(f"not a folder: {folder}")
    from .. import extras
    asked = transcribe; transcribe = transcribe and extras.available("transcribe")   # not installed: videos are added, speech stays untranscribed
    P = project / layout.INGEST; D = layout.derived(project); D.mkdir(parents=True, exist_ok=True)
    old = {}
    prev = yaml.safe_load(open(P / "pack.yaml", encoding="utf-8")) if (P / "pack.yaml").exists() else None
    if prev and prev.get("ingest_version") == INGEST_VERSION:
        for it in prev.get("items", []):
            it["derived"] = from_yaml(it.get("derived") or {}, project); old[it["sha256"]] = it
    vocab = load_vocab(project, vocab)
    cfg = yaml.safe_load(open(project / layout.CONFIG / "project.yaml", encoding="utf-8")) if (project / layout.CONFIG / "project.yaml").exists() else {}
    simplify = (cfg or {}).get("kind") == "adaptation"           # adaptation projects are shown in simplified Chinese: convert traditional documents
    if vocab and transcribe: print(f"[ingest] transcription vocabulary: {len(vocab)} terms", flush=True)
    found, skipped = scan(folder)
    print(f"[ingest] {folder}: {len(found)} files ({', '.join(f'{n} {k}' for k, n in sorted(_count(k for _, k in found).items()))}), "
          f"{len(skipped)} skipped", flush=True)
    items, used = [], set()
    for p, k in found:
        iid = f"{k}_{slug(p.stem)}"; n = 2
        while iid in used: iid = f"{k}_{slug(p.stem)}_{n}"; n += 1
        used.add(iid)
        items.append({"id": iid, "kind": k, "file": str(p), "sha256": sha256(p), "bytes": p.stat().st_size, "included": True})
    todo = []
    for i, it in enumerate(items):
        o = old.get(it["sha256"])
        if o and o["kind"] == it["kind"] and derived_ok(o.get("derived")) and (not transcribe or it["kind"] == "photo" or not (o.get("derived") or {}).get("audio")
                                                          or (o.get("speech") or {}).get("vocab_sha") == _vocab_sha(vocab)):
            items[i] = {**o, "file": it["file"], "included": o.get("included", True)}
        else:
            todo.append(it)
    print(f"[ingest] {len(items) - len(todo)} unchanged (cached), {len(todo)} to process", flush=True)
    photos = [it for it in todo if it["kind"] == "photo"]; rest = [it for it in todo if it["kind"] != "photo"]
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda it: process_item(it, Path(it["file"]), D, transcribe, whisper_model, vocab, simplify), photos))
    for it in rest:
        process_item(it, Path(it["file"]), D, transcribe, whisper_model, vocab, simplify)
    if detect and persons.available():                 # person boxes for the tagging UI (cached per item, independent of the rest)
        need = [it for it in items if it["kind"] == "photo" and not (D / "persons" / f"{it['id']}.json").exists()]
        if need: print(f"[ingest] finding people in {len(need)} photos (local detector, no identification) ...", flush=True)
        for it in need: persons.detect(it["derived"]["image"], D / "persons" / f"{it['id']}.json")
    missing = []
    if asked and not transcribe:
        n = sum(1 for it in items if it["kind"] == "video" and (it.get("derived") or {}).get("audio") and not it.get("speech"))
        if n: missing.append({"feature": "transcribe", "items": n})
    if detect and not persons.available():
        n = sum(1 for it in items if it["kind"] == "photo" and not (D / "persons" / f"{it['id']}.json").exists())
        if n: missing.append({"feature": "detect", "items": n})
    for it in items:
        if it["kind"] == "photo" and (D / "persons" / f"{it['id']}.json").exists(): it["derived"]["persons"] = D / "persons" / f"{it['id']}.json"
    notes = timetrust.assess(items)
    groups = near_duplicates(items)
    for gi, g in enumerate(groups):
        for j, iid in enumerate(g):
            it = next(x for x in items if x["id"] == iid); it["near_duplicate_group"] = gi + 1; it["representative"] = (j == 0)
    if groups: notes.append(f"{len(groups)} near-duplicate photo groups ({sum(len(g) for g in groups)} photos); the largest of each is its representative")
    for m in missing:
        s = "" if m["items"] == 1 else "s"
        notes.append({"transcribe": f"speech in {m['items']} video{s} not transcribed: the optional speech-to-text is not installed",
                      "detect": f"no person boxes in {m['items']} photo{s}: the optional person finder is not installed"}[m["feature"]]
                     + f" (gameanything extras install {m['feature']} --project <P> asks her on a card)")
    sheets = contact_sheets(items, D)
    pack = {"schema": SCHEMA, "ingest_version": INGEST_VERSION, "updated": datetime.now().isoformat(timespec="seconds"), "source_folder": str(folder),
            "privacy": {"ingest": "local only, nothing sent", "model_api_ledger": f"{layout.LEDGER} (written by gameanything perceive)"},
            "summary": {"items": len(items), **_count(it["kind"] for it in items), "skipped": skipped, "notes": notes, "optional_missing": missing,
                        "contact_sheets": sheets, "near_duplicate_groups": groups},
            "items": items}
    (P / "pack.yaml").write_text(yaml.safe_dump(to_yaml(pack, project), allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")
    print(f"[ingest] wrote {P / 'pack.yaml'}")
    for n in notes: print("  -", n)
    return pack


def _count(ks):
    c = {}
    for k in ks: c[k] = c.get(k, 0) + 1
    return c
