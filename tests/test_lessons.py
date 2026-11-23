"""Agent experience memory (gameanything/lessons.py, `gameanything lessons`): the entry format round trip, the three layers and the merged view,
adding with dedupe by similarity, the privacy guard of the shared layers, review (confirm / drop / merge), and the game package's LESSONS.md."""
import json

import pytest

from gameanything import cli, lessons as L, projects
from gameanything.games import tools

ENTRY = """# Terraria：经验（lessons）

前言，保留原样。

## 开发

### terraria-001
- date: 2026-10-20
- game: terraria
- role: builder
- 现象: 构建时报找不到 ModSources 文件夹
- 原因: 第一次运行 tModLoader 之前没有 ModSources
- 做法: 构建前先建好 ModSources
  或者先开一次 tModLoader 到主菜单
- 证据: m2 第 1 轮 14:05
- 可信度: tried once
- status: confirmed
这一行不是字段，也要留着

## 试玩

### terraria-002
- date: 2026-10-21
- game: terraria
- role: playtester
- symptom: 回放第一帧是黑的
- fix: 等 2 秒再截图
- confidence: 多次验证
- status: candidate
"""


@pytest.fixture
def layers(tmp_path, monkeypatch):
    """Game files under tmp/games/<id>.md, role files under tmp/roles/; the local layer is the test's own GAMEANYTHING_HOME (conftest)."""
    g, r = tmp_path / "games", tmp_path / "roles"
    g.mkdir(); r.mkdir()
    monkeypatch.setattr(L, "game_file", lambda gid: g / f"{gid}.md")
    monkeypatch.setattr(L, "ROLE_DIR", r)
    def all_files():
        out = [("game", f) for f in sorted(g.glob("*.md"))] + [("role", f) for f in sorted(r.glob("*.md"))]
        if L.local_dir().is_dir(): out += [("local", f) for f in sorted(L.local_dir().glob("*.md"))]
        return out
    monkeypatch.setattr(L, "all_files", all_files)
    return g, r


def test_parse_render_round_trip_keeps_everything():
    ch = L.parse(ENTRY)
    # byte for byte (unknown lines and the preamble included), except that English field names are written back in Chinese
    assert L.unparse(ch) == ENTRY.replace("- symptom:", "- 现象:").replace("- fix:", "- 做法:").replace("- confidence:", "- 可信度:")
    es = L.entries(ENTRY)
    assert [e["id"] for e in es] == ["terraria-001", "terraria-002"]
    a, b = es
    assert a["做法"] == "构建前先建好 ModSources\n或者先开一次 tModLoader 到主菜单" and a["_section"] == "开发" and a["_extra"] == ["这一行不是字段，也要留着"]
    assert b["现象"] == "回放第一帧是黑的" and b["做法"] == "等 2 秒再截图" and b["_section"] == "试玩"          # English field names are read too
    assert L.norm_conf(b["可信度"]) == "verified repeatedly" and L.problems(ENTRY) == []
    bad = ENTRY.replace("- role: playtester", "- role: tester").replace("- status: candidate", "- status: maybe") + "\n### terraria-001\n- 现象: x\n"
    ps = L.problems(bad)
    assert any("used twice" in p for p in ps) and any("tester" in p for p in ps) and any("maybe" in p for p in ps) and any("no 做法" in p for p in ps)


def test_template_is_parsable_and_has_both_sections():
    t = L.game_template("Terraria")
    assert "## 开发" in t and "## 试玩" in t and L.entries(t) == [] and L.problems(t) == []


def test_add_places_entries_in_their_section_with_ids(layers):
    g, _ = layers
    r1 = L.add("terraria", "builder", "构建报错找不到 ModSources", "第一次运行前没有", "先建文件夹", "m2 r1 14:05")
    r2 = L.add("terraria", "playtester", "回放第一帧是黑的", "渲染没准备好", "等 2 秒再截", "m2 r1 00:01")
    r3 = L.add("terraria", "builder", "存档按钮点了没反应", "UI 层级不对", "把按钮放到最上层", "m3 r2")
    assert [r["action"] for r in (r1, r2, r3)] == ["added"] * 3 and [r["id"] for r in (r1, r2, r3)] == ["terraria-001", "terraria-002", "terraria-003"]
    text = (g / "terraria.md").read_text(encoding="utf-8")
    dev, play = text.index("## 开发"), text.index("## 试玩")
    assert dev < text.index("### terraria-001") < text.index("### terraria-003") < play < text.index("### terraria-002")
    e = {x["id"]: x for x in L.entries(text)}
    assert e["terraria-001"]["status"] == "candidate" and e["terraria-001"]["可信度"] == "tried once" and e["terraria-001"]["game"] == "terraria"
    assert e["terraria-002"]["role"] == "playtester" and L.problems(text) == []
    # a file whose section is missing gets it
    (g / "minecraft.md").write_text("# Minecraft\n\n## 开发\n", encoding="utf-8")
    L.add("minecraft", "playtester", "x 现象", "", "y 做法", "")
    assert "## 试玩" in (g / "minecraft.md").read_text(encoding="utf-8")


def test_add_dedupes_similar_lessons(layers):
    g, _ = layers
    L.add("terraria", "builder", "构建报错：找不到 ModSources 文件夹", "第一次运行 tModLoader 之前没有 ModSources", "先建文件夹", "m2 r1")
    r = L.add("terraria", "builder", "构建报错找不到 ModSources 文件夹！", "第一次运行之前没有 ModSources", "mkdir", "m3 r2 10:00")
    assert r["action"] == "merged" and r["id"] == "terraria-001" and r["similar"][0][1] >= L.SIMILAR
    e = L.entries((g / "terraria.md").read_text(encoding="utf-8"))
    assert len(e) == 1 and e[0]["证据"] == "m2 r1\nm3 r2 10:00" and e[0]["可信度"] == "verified repeatedly" and e[0]["做法"] == "先建文件夹"
    # different symptom: a new entry; --force: a new entry even when similar
    assert L.add("terraria", "builder", "游戏窗口一直是全屏", "设置没存", "改 config.json", "")["action"] == "added"
    assert L.add("terraria", "builder", "构建报错找不到 ModSources 文件夹", "第一次运行之前没有", "x", "", force=True)["action"] == "added"
    assert len(L.entries((g / "terraria.md").read_text(encoding="utf-8"))) == 3
    assert L.similarity({"现象": "abc"}, {"现象": ""}) == 0.0


def test_layers_and_merged_view(layers):
    g, r = layers
    (g / "terraria.md").write_text(ENTRY, encoding="utf-8")
    L.add(None, "builder", "交付前忘了 play.yaml", "", "最后一步跑 gameanything build deliver", "m3", general=True)
    L.add(None, "playtester", "截图时游戏窗口被挡住", "", "只用 gameanything native shot", "", general=True)
    L.add("terraria", "builder", "这台机器的 dotnet 不在 PATH", "", "设 DOTNET_ROOT", "", local=True)
    L.add(None, "builder", "这台机器的磁盘快满了", "", "临时文件放数据盘", "", local=True, general=True)
    assert (r / "builder.md").is_file() and (projects.home() / "lessons" / "terraria.md").is_file() and (projects.home() / "lessons" / "general.md").is_file()
    v = L.show("terraria", "builder")
    assert [e["id"] for e in v] == ["terraria-001", "builder-001", "local-terraria-001", "local-general-001"]      # confirmed first, then game / role / local
    assert [e["_layer"] for e in v] == ["game", "role", "local", "local"]
    assert [e["id"] for e in L.show("terraria", "playtester")] == ["terraria-002", "playtester-001"]
    assert {e["id"] for e in L.show("terraria")} >= {"terraria-001", "terraria-002", "builder-001", "playtester-001"}
    assert [e["id"] for e in L.show("minecraft", "builder")] == ["builder-001", "local-general-001"]        # another game: only the general ones
    txt = L.show_text("terraria", "builder")
    assert "== 已确认 ==" in txt and txt.index("terraria-001") < txt.index("builder-001")
    assert "playtester-001" in L.show_text("minecraft", "playtester")
    for f in L.local_dir().glob("*.md"): f.unlink()
    for f in r.glob("*.md"): f.unlink()
    assert "还没有经验" in L.show_text("minecraft", "builder")


def test_privacy_guard_on_shared_layers(layers, tmp_path):
    with pytest.raises(L.LessonError, match="私人内容"): L.add("terraria", "builder", "IMG_2041.HEIC 太暗", "", "调亮", "")
    with pytest.raises(L.LessonError, match="私人内容"): L.add("terraria", "builder", "x", "", "看 1_ingest/derived/a 里的图", "")
    with pytest.raises(L.LessonError, match="私人内容"): L.add("terraria", "builder", "发给 someone@example.com", "", "y", "")
    with pytest.raises(L.LessonError, match="私人内容"): L.add("terraria", "builder", "路径 /home/alice/x 没有", "", "y", "")
    p = tmp_path / "proj"; (p / "config").mkdir(parents=True); (p / "3_remember").mkdir()
    (p / "config" / "vocab.txt").write_text("王小明,李雷\n", encoding="utf-8")
    (p / "3_remember" / "people.yaml").write_text("people:\n  - {id: p1, name: 韩梅梅}\n", encoding="utf-8")
    assert {"王小明", "李雷", "韩梅梅"} <= L.project_names(p)
    with pytest.raises(L.LessonError, match="韩梅梅"): L.add("terraria", "builder", "韩梅梅的头像不对", "", "重画", "", project=p)
    assert L.add("terraria", "builder", "韩梅梅的头像不对", "", "重画", "", project=p, local=True)["action"] == "added"     # local: allowed
    with pytest.raises(L.LessonError, match="--fix"): L.add("terraria", "builder", "x", "", "", "")
    with pytest.raises(L.LessonError, match="--role"): L.add("terraria", "critic", "x", "", "y", "")


def test_review_confirm_drop_merge(layers):
    g, _ = layers
    L.add("terraria", "builder", "构建报错找不到 ModSources", "第一次运行前没有", "先建文件夹", "m2 r1")
    L.add("terraria", "builder", "窗口全屏切不回来", "设置没存", "改 config.json", "m2 r2")
    L.add("terraria", "builder", "构建失败：没有 ModSources", "", "开一次游戏", "m3 r1", force=True)
    assert [e["id"] for e in L.candidates()] == ["terraria-001", "terraria-002", "terraria-003"]
    assert "3 条候选" in L.review_text()
    L.confirm("terraria-002")
    L.merge("terraria-001", "terraria-003")
    es = {e["id"]: e for e in L.entries((g / "terraria.md").read_text(encoding="utf-8"))}
    assert set(es) == {"terraria-001", "terraria-002"} and es["terraria-002"]["status"] == "confirmed"
    assert es["terraria-001"]["证据"] == "m2 r1\nm3 r1" and es["terraria-001"]["可信度"] == "verified repeatedly" and es["terraria-001"]["做法"] == "先建文件夹"
    L.drop("terraria-001")
    assert [e["id"] for e in L.entries((g / "terraria.md").read_text(encoding="utf-8"))] == ["terraria-002"]
    with pytest.raises(L.LessonError, match="找不到"): L.confirm("terraria-009")
    with pytest.raises(L.LessonError): L.merge("terraria-002", "terraria-002")
    # merge across files: a local lesson into a game one
    L.add("terraria", "builder", "本机 dotnet 版本不对", "", "装 8.0", "m4", local=True)
    L.merge("terraria-002", "local-terraria-001")
    assert L.entries((projects.home() / "lessons" / "terraria.md").read_text(encoding="utf-8")) == []
    assert "m4" in L.entries((g / "terraria.md").read_text(encoding="utf-8"))[0]["证据"]


def test_cli(layers, capsys):
    g, _ = layers
    assert cli.main(["lessons", "add", "--game", "terraria", "--role", "builder", "--symptom", "构建报错找不到 ModSources", "--cause", "没建",
                     "--fix", "先建", "--evidence", "m2 r1"]) == 0
    assert "terraria-001" in capsys.readouterr().out
    assert cli.main(["lessons", "add", "--game", "terraria", "--role", "builder", "--symptom", "构建报错，找不到 ModSources", "--cause", "没建",
                     "--fix", "先建", "--evidence", "m3 r1"]) == 0
    assert "很像" in capsys.readouterr().out
    assert cli.main(["lessons", "show", "--game", "terraria", "--role", "builder", "--json"]) == 0
    v = json.loads(capsys.readouterr().out); assert [e["id"] for e in v] == ["terraria-001"] and v[0]["证据"] == "m2 r1\nm3 r1"
    assert cli.main(["lessons", "review"]) == 0 and "1 条候选" in capsys.readouterr().out
    assert cli.main(["lessons", "review", "--confirm", "terraria-001"]) == 0 and "确认 terraria-001" in capsys.readouterr().out
    assert cli.main(["lessons", "review", "--json"]) == 0 and json.loads(capsys.readouterr().out) == []
    for bad in (["lessons", "add", "--game", "terraria", "--symptom", "x", "--fix", "y"], ["lessons", "add", "--role", "builder", "--symptom", "x", "--fix", "y"],
                ["lessons", "add", "--game", "terraria", "--role", "builder", "--symptom", "IMG_1.jpg", "--fix", "y"]):
        with pytest.raises(SystemExit): cli.main(bad)


def test_game_packages_ship_lessons(tmp_path):
    """`gameanything game new` writes an empty LESSONS.md with both sections; `gameanything game check` reports its state (warnings only)."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    r = tools.new("my_game2", "My Game", loader="bepinex", root=tmp_path)
    f = tmp_path / "gameanything" / "games" / "my_game2" / "LESSONS.md"
    assert str(f) in r["files"] and "## 开发" in f.read_text(encoding="utf-8") and L.problems(f.read_text(encoding="utf-8")) == []
    c = tools.check("terraria")
    les = [i for i in c["items"] if "LESSONS.md" in i["text"]]
    assert les and all(i["level"] in ("ok", "warning") for i in les)


def test_real_lesson_files_parse():
    """Every lessons file in the checkout (game packages, role files) parses and has no format problems."""
    from gameanything import games as registry
    fs = [s.path / "LESSONS.md" for s in registry.games().values()] + [L.ROLE_DIR / f"{r}.md" for r in L.ROLES]
    for f in fs:
        if f.is_file(): assert L.problems(f.read_text(encoding="utf-8")) == [], f
