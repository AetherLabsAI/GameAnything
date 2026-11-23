"""Where the people are in each photo (local, optional): person boxes for the tagging UI, so the user clicks a box instead
of drawing one. Detection only: it finds people, it does not tell who they are (no face recognition, no face features).

Model: torchvision Faster R-CNN ResNet-50 FPN v2 (COCO "person" class); code BSD-3, weights downloaded once by torchvision
into $TORCH_HOME. Optional feature `detect` (extras.py): installed after her yes on a card (`gameanything extras install detect`); without it ingest skips this step.
"""
import json
from pathlib import Path

MODEL = "torchvision/fasterrcnn_resnet50_fpn_v2"
KEEP = 0.5             # stored; the UI shows >= SHOW by default and the rest on request
SHOW = 0.75
PERSON = 1             # COCO label id

_m = None


def available() -> bool:
    try:
        import torch, torchvision  # noqa: F401
        return True
    except ImportError:
        return False


def model():
    global _m
    if _m is None:
        import torch
        from torchvision.models.detection import FasterRCNN_ResNet50_FPN_V2_Weights, fasterrcnn_resnet50_fpn_v2
        torch.set_num_threads(min(16, torch.get_num_threads()))
        w = FasterRCNN_ResNet50_FPN_V2_Weights.DEFAULT
        _m = (fasterrcnn_resnet50_fpn_v2(weights=w, box_score_thresh=KEEP).eval(), w.transforms())
    return _m


def detect(image: Path, dst: Path) -> dict:
    """-> {model, show_threshold, size, boxes: [{box: [x0, y0, x1, y1] (0-1, left-top origin), score}]} written to dst."""
    import torch
    from PIL import Image
    m, tf = model()
    im = Image.open(image).convert("RGB"); W, H = im.size
    with torch.inference_mode():
        out = m([tf(im)])[0]
    boxes = [{"box": [round(float(b[0]) / W, 4), round(float(b[1]) / H, 4), round(float(b[2]) / W, 4), round(float(b[3]) / H, 4)],
              "score": round(float(s), 3)}
             for b, s, l in zip(out["boxes"], out["scores"], out["labels"]) if int(l) == PERSON and float(s) >= KEEP]
    boxes.sort(key=lambda b: b["box"][0])                 # left to right, like the observation cards' p1, p2, ...
    r = {"model": MODEL, "show_threshold": SHOW, "size": [W, H], "boxes": boxes}
    dst.parent.mkdir(parents=True, exist_ok=True); dst.write_text(json.dumps(r, indent=1), encoding="utf-8")
    return r
