import pytest

from gameanything import layout
from gameanything.conversation import CardError, Thread


def _proj(tmp_path):
    for rel in ("4_design/targets_ucsd/a.png", "2_perceive/keyframes/v/k001.jpg", "0_inbox/orig.jpg", "config/x.png",
                "conversation/files/c.png", "4_design/.cache/h.png", "4_design/world_plan.yaml", "5_build/m1/play/s.png"):
        f = tmp_path / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(b"x")
    return tmp_path


def test_media_file_rule(tmp_path):
    p = _proj(tmp_path)
    assert layout.media_file(p, "4_design/targets_ucsd/a.png")                 # a folder nobody listed ahead of time
    assert layout.media_file(p, "/media/2_perceive/keyframes/v/k001.jpg?v=3")
    for bad in ("0_inbox/orig.jpg", "config/x.png", "conversation/files/c.png", "4_design/.cache/h.png", "4_design/world_plan.yaml",
                "4_design/targets_ucsd/missing.png", "../x.png", "4_design/../config/x.png", ""):
        assert layout.media_file(p, bad) is None, bad


def test_card_refuses_broken_picture(tmp_path):
    p = _proj(tmp_path); t = Thread(p)
    ok = {"kind": "candidates", "key": "k", "title": "t", "items": [{"id": "a", "title": "A", "image": "/media/4_design/targets_ucsd/a.png"}]}
    try: t.card(ok)
    except CardError as e: assert "图" not in str(e), e                        # other card rules may differ; never the picture rule
    for url in ("/media/4_design/targets_ucsd/missing.png", "/media/0_inbox/orig.jpg", "/build/m1/play/none.png"):
        bad = {**ok, "key": "k2", "items": [{"id": "a", "title": "A", "image": url}]}
        with pytest.raises(CardError, match="网页打不开"): t.card(bad)
