"""<project>/README.md: where the project is now and what each folder holds. Rewritten after every stage (and by `gameanything status`).
Language from <project>/config/project.yaml (`lang: zh` or `en`, default en)."""
from pathlib import Path

import yaml

from . import layout

T = {
    "zh": {"title": "# {name}\n\n由 GameAnything 自动生成，每个阶段跑完都会更新。\n",
           "now": "## 现在\n{now}\n", "folders": "## 文件夹\n", "done": "✓", "todo": "·",
           "f_config": "你提供的设置：{n} 个文件（vocab.txt 是转写用的人名 / 专有名词）",
           "f_ingest": "A 本地整理：{items} 个文件 → `pack.yaml`；`derived/` 里有缩略图、总览图（contact/）、视频关键帧、转写（transcripts/ 里的 .txt 最好读）、请柬页",
           "f_perceive": "B 观察卡：`cards/` 里 {cards} 张（每个文件一张）；`requests/`、`agent_output/` 是中间产物",
           "f_remember": "C 整理结果：{files}",
           "f_feedback": "要你看的和你说的：{files}",
           "f_ledger": "发送记录：{n} 次请求把内容发给了模型（时间、发了哪些文件）",
           "next_ingest": "下一步：`gameanything ingest <素材文件夹> --project <本项目>`",
           "next_perceive": "下一步：B 观察卡（会把缩小后的图片和文字发给模型，先确认）",
           "next_remember": "下一步：C 整理出 Experience Board 草稿",
           "next_answer": "下一步：**请看 `feedback/questions.md`，回答写进对话或 `feedback/answers.md`**；然后一起改定 `3_remember/board.yaml`",
           "next_design": "下一步：board 已确认，进入设计（World Plan）",
           "next_plan": "下一步：**请看 `feedback/design_questions.md`，选完之后 World Plan 定稿**（完整方案在 `4_design/world_plan.yaml`）",
           "f_design": "设计：{files}",
           "next_build": "下一步：World Plan 已确认 → 批量做美术（在“形象确认”页里看效果、提意见），同时实测几个待验证的技术点，然后构建"},
    "en": {"title": "# {name}\n\nWritten by GameAnything; updated after every stage.\n",
           "now": "## Now\n{now}\n", "folders": "## Folders\n", "done": "✓", "todo": "·",
           "f_config": "your settings: {n} file(s) (vocab.txt: names / terms for speech-to-text)",
           "f_ingest": "A local ingest: {items} files -> `pack.yaml`; `derived/` holds thumbnails, contact sheets, keyframes, transcripts (.txt is the readable one), document pages",
           "f_perceive": "B observation cards: {cards} in `cards/`; `requests/` and `agent_output/` are intermediate",
           "f_remember": "C results: {files}",
           "f_feedback": "for you to read / your answers: {files}",
           "f_ledger": "privacy ledger: {n} request(s) sent content to a model",
           "next_ingest": "next: `gameanything ingest <folder> --project <this project>`",
           "next_perceive": "next: B observation cards (sends reduced images and text to the model; asks first)",
           "next_remember": "next: C draft the Experience Board",
           "next_answer": "next: **read `feedback/questions.md` and answer** (in the chat or `feedback/answers.md`); then finalize `3_remember/board.yaml`",
           "next_design": "next: the board is confirmed; design (World Plan)",
           "next_plan": "next: **answer `feedback/design_questions.md`** to finalize the World Plan (`4_design/world_plan.yaml`)",
           "f_design": "design: {files}",
           "next_build": "next: the World Plan is confirmed -> art (review it on the look page), technical checks, then build"},
}


def project_config(project: Path) -> dict:
    f = project / layout.CONFIG / "project.yaml"
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.exists() else {}


def write(project: Path) -> str:
    project = project.resolve(); cfg = project_config(project); t = T.get(cfg.get("lang", "en"), T["en"])
    pk = layout.pack(project)
    items = len(yaml.safe_load(pk.read_text(encoding="utf-8"))["items"]) if pk.exists() else 0
    cards = len(list(layout.cards(project).glob("*.json"))) if layout.cards(project).exists() else 0
    rem = sorted(p.name for p in (project / layout.REMEMBER).glob("*")) if (project / layout.REMEMBER).exists() else []
    fb = sorted(p.name for p in (project / layout.FEEDBACK).glob("*")) if (project / layout.FEEDBACK).exists() else []
    led = project / layout.LEDGER
    nreq = len(layout.ledger_requests(yaml.safe_load(led.read_text(encoding="utf-8")))) if led.exists() else 0
    board = project / layout.REMEMBER / "board.yaml"
    confirmed = board.exists() and (yaml.safe_load(board.read_text(encoding="utf-8")) or {}).get("experience_board", {}).get("status") == "confirmed"
    des = sorted(p.name for p in (project / layout.DESIGN).glob("*")) if (project / layout.DESIGN).exists() else []
    wp = project / layout.DESIGN / "world_plan.yaml"
    plan_ok = wp.exists() and (yaml.safe_load(wp.read_text(encoding="utf-8")) or {}).get("world_plan", {}).get("status") == "confirmed"
    now = (t["next_ingest"] if not items else t["next_perceive"] if cards < items else t["next_remember"] if "board.yaml" not in rem
           else t["next_answer"] if not confirmed else (t["next_build"] if plan_ok else t["next_plan"]) if "world_plan.yaml" in des else t["next_design"])
    cfgn = len(list((project / layout.CONFIG).glob("*"))) if (project / layout.CONFIG).exists() else 0
    rows = [(layout.CONFIG, cfgn > 0, t["f_config"].format(n=cfgn)),
            (layout.INGEST, items > 0, t["f_ingest"].format(items=items)),
            (layout.PERCEIVE, items > 0 and cards >= items, t["f_perceive"].format(cards=cards)),
            (layout.REMEMBER, bool(rem), t["f_remember"].format(files=", ".join(f"`{x}`" for x in rem) or "-")),
            (layout.DESIGN, bool(des), t["f_design"].format(files=", ".join(f"`{x}`" for x in des) or "-")),
            (layout.FEEDBACK, bool(fb), t["f_feedback"].format(files=", ".join(f"`{x}`" for x in fb) or "-")),
            (layout.LEDGER, nreq > 0, t["f_ledger"].format(n=nreq))]
    md = (t["title"].format(name=cfg.get("title") or project.name) + "\n" + t["now"].format(now=now) + "\n" + t["folders"]
          + "\n".join(f"- {t['done'] if ok else t['todo']} `{name}{'' if '.' in name else '/'}` {desc}" for name, ok, desc in rows) + "\n")
    (project / "README.md").write_text(md, encoding="utf-8")
    return md
