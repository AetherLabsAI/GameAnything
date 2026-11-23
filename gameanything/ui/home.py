"""The home page's data: one row per stage (state + a plain sentence + where to go), the few things waiting for the user,
and the side panel (what was sent to models, cost, save backups). Read from the project files only; no state of its own."""
from pathlib import Path

import yaml

from .. import delivery, layout
from ..translate import Tr
from .i18n import T, round_name

MILESTONE_NAMES = {"m1": "第 1 期：婚礼仪式", "m2": "第 2 期：合影、喜宴、敬酒、捧花", "improve": "整天改进", "improve2": "改进 2", "improve3": "改进 3", "jukebox": "唱片机", "m3": "第 3 期：婚后", "final": "收尾交付"}


def _y(p: Path, default=None):
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or default
    except FileNotFoundError:
        return default


def home_state(root: Path, lang="zh") -> dict:
    rem, des, art, B = root / layout.REMEMBER, root / layout.DESIGN, root / layout.DESIGN / "art", root / "5_build"
    items = len((_y(layout.pack(root), {}) or {}).get("items", []))
    cards = len(list(layout.cards(root).glob("*.json"))) if layout.cards(root).exists() else 0
    board = (_y(rem / "board.yaml", {}) or {}).get("experience_board", {})
    people = (_y(rem / "people.yaml", {}) or {}).get("people", [])
    plan = (_y(des / "world_plan.yaml", {}) or {}).get("world_plan", {})
    looks = _y(art / "looks.yaml", {}) or {}; review = _y(art / "review.yaml", {}) or {}
    ms = (plan.get("milestones") or {})
    todo, steps = [], []

    def step(key, title, state, text, href=None):
        steps.append({"key": key, "title": title, "state": state, "text": text, "href": href})

    # 1 素材 / 2 回忆板 / 3 人物 / 4 设计
    step("ingest", "素材", "done" if items else "todo", f"{items} 个文件已在本机整理好" + (f"，{cards} 张观察卡" if cards else "") if items else "还没有导入素材")
    bs = board.get("status")
    # 「确认这一天」 is her board_review.yaml (the agent sets board.yaml's status later, or never): once she confirmed, stop asking (QA 2026-10-29)
    from .. import decisions
    brv = _y(root / layout.FEEDBACK / "board_review.yaml", {}) or {}
    if decisions.confirmed(root, "board", bs == "confirmed" or (isinstance(brv, dict) and brv.get("state") == "confirmed")): bs = "confirmed"
    elif bs == "confirmed": bs = "draft"
    step("board", "回忆板", "done" if bs == "confirmed" else "wait" if board else "todo",
         f"{len(board.get('moments', []))} 个时刻，已确认" if bs == "confirmed" else "草稿等你确认" if board else "导入素材之后整理")
    if board and bs != "confirmed": todo.append({"text": T(lang, "确认回忆板里的时刻和顺序"), "href": None})
    tagged = sum(1 for p in people if p.get("name"))
    step("people", "人物", "done" if people else "todo", f"{len(people)} 个人，{tagged} 个有名字" if people else "还没有标记", "/people")
    pst = plan.get("status")
    step("design", "设计", "done" if pst == "confirmed" else "wait" if plan else "todo",
         "World Plan 已确认" if pst == "confirmed" else "方案等你确认" if plan else "回忆板确认之后")
    # 5 形象：looks without a verdict (or marked 要改), and portrait requests not yet done
    unseen = [k for k in looks if (review.get(k) or {}).get("status") in (None, "todo")]
    change = [k for k in looks if (review.get(k) or {}).get("status") == "change"]
    step("looks", "形象", "wait" if unseen else "run" if change else "done" if looks else "todo",
         (f"{len(unseen)} 个形象等你看" if unseen else f"{len(change)} 个按你的意见在改" if change else f"{len(looks)} 个形象都已确认") if looks else "设计确认之后", "/looks")
    if unseen: todo.append({"text": T(lang, "看 {n} 个新形象（行走图和头像）", len(unseen)), "href": "/looks"})
    # 6 构建 / 7 试玩：one line per milestone
    builds = []
    for m, v in ms.items():
        st = (v or {}).get("status", "planned"); play = B / m / "play"
        review_m = _y(play / "user_review.yaml", None); req = _y(play / "next_round_request.yaml", None)
        builds.append({"m": m, "name": MILESTONE_NAMES.get(m, m), "status": st, "what": (v or {}).get("what", ""),
                       "play": delivery.has_play(play), "reviewed": bool(review_m), "request": (req or {}).get("state")})
        if delivery.has_play(play) and st == "built" and not review_m and not req:
            todo.append({"text": T(lang, "看{name}的试玩录像", name=round_name(MILESTONE_NAMES.get(m, m), lang, Tr(root, lang))), "href": f"/play?m={m}"})
    running = [b for b in builds if b["status"] == "building"]
    done_b = [b for b in builds if b["status"] in ("built", "accepted")]
    step("build", "构建", "run" if running else "done" if done_b and all(b["status"] in ("built", "accepted") for b in builds) else "todo" if not done_b else "wait",
         f"正在做：{running[0]['name']}" if running else f"已做完 {len(done_b)} 期" if done_b else "设计和形象确认之后")
    step("play", "试玩", "wait" if any(t["href"] and t["href"].startswith("/play") for t in todo) else "done" if done_b else "todo",
         f"{sum(b['play'] for b in builds)} 期可以看录像" if done_b else "构建完成之后", "/play" if done_b else None)
    fin = (ms.get("final") or {}).get("status")
    step("install", "装进游戏", "done" if fin == "accepted" else "todo", "收尾交付那一期：先备份存档，再装进你自己的游戏")
    # side panel
    led = layout.ledger_requests(_y(root / layout.LEDGER, {}))
    cost = sum(r.get("cost_usd") or 0 for r in led)
    sent = {}
    for r in led: sent[r.get("purpose", "看图").split(" ")[0]] = sent.get(r.get("purpose", "看图").split(" ")[0], 0) + 1
    backups = sorted((root / "backups").glob("*.zip")) if (root / "backups").exists() else []
    return {"title": (_y(root / layout.CONFIG / "project.yaml", {}) or {}).get("title") or root.name, "steps": steps, "todo": todo[:3],
            "more_todo": max(0, len(todo) - 3), "builds": builds,
            "side": {"requests": len(led), "by_purpose": sent, "image_cost_usd": round(cost, 3), "backups": [b.name for b in backups]}}
