"""`gameanything estimate`: what a build round may cost, before the user presses start (decision D18 part 3).

Ranges come from real past rounds (pricing.yaml: past_rounds / sizes), scaled by a model price table for API accounts.
Subscription accounts get a quota warning instead of dollars. Nothing here is a quote: it is a range from a handful of runs.
"""
import fnmatch
from pathlib import Path

import yaml

SIZES = ("small", "medium", "large")
SUBSCRIPTION_AGENTS = ("claude-code", "codex")


def load():
    return yaml.safe_load((Path(__file__).parent / "pricing.yaml").read_text(encoding="utf-8"))


def _blend(m, w):
    return w["input"] * m["input"] + w["output"] * m["output"]


def find_model(P, model):
    for m in P["models"]:
        if fnmatch.fnmatch(model, m["match"]): return m
    return None


VENDOR = {"claude-code": "anthropic", "codex": "openai", "gemini": "google", "dsh": "deepseek"}


def norm_model(agent, model):
    """A bare model name as the agent CLI takes it (`sonnet`, `gpt-5.5`) -> the price table's provider/model form."""
    if not model or "/" in model: return model
    m = model.lower()
    if agent == "claude-code" and m in ("sonnet", "opus", "haiku", "fable"): m = f"claude-{m}"
    return f"{VENDOR[agent]}/{m}" if agent in VENDOR else model


def _r(x, step=1):
    return int(round(x / step) * step)


def estimate(size, agent="claude-code", model=None, account=None):
    P = load()
    if size not in P["sizes"]: raise ValueError(f"size 应该是 {' / '.join(SIZES)}")
    S = P["sizes"][size]
    model = norm_model(agent, model) or P["default_model"].get(agent)
    account = account or ("subscription" if agent in SUBSCRIPTION_AGENTS and not (model or "").startswith("openrouter/") else "api")
    wall = list(S["wall_h"]); unverified = []
    cost = None; note_zh = []; note_en = []
    ref = find_model(P, P["reference"])
    if account == "api":
        m = find_model(P, model) if model else None
        if not m:
            note_zh.append(f"价格表里没有 {model or '这个模型'}，所以给不出金额。"); note_en.append(f"{model or 'This model'} is not in the price table, so there is no dollar estimate.")
        else:
            ratio = _blend(m, P["blend"]) / _blend(ref, P["blend"])
            lo, hi = S["cost_usd"][0] * ratio * m["spread"][0], S["cost_usd"][1] * ratio * m["spread"][1]
            cost = [_r(lo), max(_r(hi), _r(lo) + 1)]
            taken = m.get("taken") or P["prices_taken"]
            note_zh.append(f"按过去 Claude Sonnet 跑的 {len(S['basis'])} 期折算，价格表取于 {taken}。" + ("这个模型的价格我没核实过。" if not m["verified"] and m is not ref else "") + ("不是 Claude 的模型，用的轮数可能差很多，所以范围放宽了。" if m["spread"] != [1.0, 1.0] else ""))
            note_en.append(f"Scaled from {len(S['basis'])} past rounds run on Claude Sonnet; prices as of {taken}." + (" This model's price is unverified." if not m["verified"] and m is not ref else "") + (" It is not a Claude model and may take a very different number of turns, so the range is wider." if m["spread"] != [1.0, 1.0] else ""))
            if not m["verified"] and m is not ref: unverified.append(f"price of {m['name']}")
        if size == "large": note_zh.append("整期里最长的一次 5 小时到点被停了，那次的花费没有记录，所以上限可能更高。"); note_en.append("The longest past round was stopped at its 5 h cap and its cost was not recorded, so the top may be higher.")
        if agent != "claude-code": unverified.append(f"{agent} on this task is untested; wall time is from Claude Code runs"); note_zh.append(f"{agent} 还没在这类任务上实测，时间按 Claude Code 的跑法估。"); note_en.append(f"{agent} has not been run on this kind of task; time is taken from Claude Code runs.")
    else:
        note_zh.append("订阅没有按次的价钱，只有额度。额度用完后 GameAnything 目前不会自动等它恢复再接着跑（还没测过）。")
        note_en.append("A subscription has a quota, not a price. When the quota runs out GameAnything does not yet wait for it to come back and carry on (untested).")
        unverified.append("what happens when the subscription limit hits mid-round (harness has only a fixed time cap, no wait-and-resume)")
        if agent != "claude-code": unverified.append(f"{agent} subscription usage on this task is unmeasured")
    if (model or "").lower().startswith(("anthropic/claude-fable", "openrouter/anthropic/claude-fable")):
        note_zh.append("Fable 非常贵：同样的活，它用掉的额度或钱比 Opus 多一倍左右，比 Sonnet 多好几倍。")
        note_en.append("Fable is very expensive: the same work uses about twice the quota or money of Opus and several times that of Sonnet.")
    est = {"wall_h": list(wall), "cost_usd": cost, "account": account, "agent": agent, "model": model or "", "note": " ".join(note_zh)}
    est_en = {**est, "wall_h": list(wall), "cost_usd": list(cost) if cost else None, "note": " ".join(note_en)}
    return {"estimate": est, "estimate_en": est_en, "sentence_zh": sentence(est, "zh", size), "sentence_en": sentence(est_en, "en", size),
            "size": size, "basis": S["basis"], "prices_taken": P["prices_taken"], "unverified": unverified}


def sentence(e, lang, size=None):
    lo, hi = e["wall_h"]
    if lang == "zh":
        s = f"这一期大约要连续跑 {lo:g}–{hi:g} 小时。"
        if e["account"] == "api": s += f"预计花费约 ${e['cost_usd'][0]}–{e['cost_usd'][1]}（按你的 API 计费）。" if e["cost_usd"] else "金额暂时估不出来。"
        else: s += "可能用完你这几个小时的额度；额度用完时这一期可能停在中途（GameAnything 还不会自动等额度恢复，没测过）。"
        return s + "你点了开工才会开始。"
    s = f"This round needs about {lo:g}-{hi:g} hours of continuous running. "
    if e["account"] == "api": s += (f"Estimated cost about ${e['cost_usd'][0]}-{e['cost_usd'][1]} on your API key. " if e["cost_usd"] else "No dollar estimate available. ")
    else: s += "It may use up your quota for those hours; if the quota runs out the round may stop part-way (GameAnything does not yet wait for it to come back; untested). "
    return s + "Nothing starts until you press start."
