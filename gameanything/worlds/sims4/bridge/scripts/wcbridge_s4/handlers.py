"""WCP methods. Everything except hello runs on the simulation thread (dispatch.submit)."""
import services, sims4.commands
from .version import VERSION, PROTOCOL


class WcpError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg); self.wcp_code = code


def hello(channel, client=None, protocol=None):
    return {"protocol": PROTOCOL, "game": "sims4", "bridge": "wcbridge_s4", "bridge_version": VERSION, "channel": channel,
            "capabilities": ["pause", "advance", "eval_query", "commands", "reload"],
            "time_model": {"pausable": True, "tick_unit": "sim_minute"}, "frame_sources": ["x11"]}


# ---------- helpers ----------
def _now():
    t = services.time_service().sim_now
    return {"day": int(t.day()), "week": int(t.week()), "hour": int(t.hour()), "minute": int(t.minute()),
            "absolute_minutes": float(t.absolute_minutes()), "text": str(t)}


def _speed():
    c = services.game_clock_service()
    return int(c.clock_speed)


def _connection():
    c = services.client_manager().get_first_client()
    return c.id if c is not None else 0


def _name(si):
    """full_name is empty in release builds; first_name / last_name hold what CAS shows."""
    return ("%s %s" % (si.first_name or "", si.last_name or "")).strip()


def _sim_brief(si):
    d = {"sim_id": si.sim_id, "name": _name(si), "age": str(si.age).split(".")[-1], "household_id": si.household_id,
         "instanced": si.is_instanced()}
    try:
        inst = si.get_sim_instance()
        d["on_active_lot"] = bool(inst is not None and inst.is_on_active_lot())
    except Exception:
        pass
    try:
        m = si.get_mood()
        d["mood"] = getattr(m, "__name__", str(m))
        d["mood_intensity"] = si.get_mood_intensity()
    except Exception:
        pass
    return d


def _find_sim(sim):
    """sim: sim_id (int), full name, or first name (case-insensitive); None -> active sim."""
    mgr = services.sim_info_manager()
    if sim is None:
        si = services.active_sim_info()
        if si is None:
            raise WcpError(1003, "no active sim")
        return si
    if isinstance(sim, int) or (isinstance(sim, str) and sim.isdigit()):
        si = mgr.get(int(sim))
        if si is not None:
            return si
    key = str(sim).strip().lower()
    hits = [si for si in mgr.get_all() if _name(si).lower() == key] or \
           [si for si in mgr.get_all() if si.first_name.lower() == key]
    if not hits:
        raise WcpError(1004, "no sim named %r" % sim)
    return hits[0]


# ---------- both channels ----------
def health():
    z = services.current_zone()
    return {"status": "ready" if z is not None and z.is_zone_running else "loading", "tick": int(services.time_service().sim_now.absolute_ticks()),
            "paused": _speed() == 0, "speed": _speed()}


# ---------- agent channel ----------
def get_state(fields=None):
    z = services.current_zone()
    lot = services.active_lot()
    st = {"time": _now(), "speed": _speed(), "zone_id": z.id if z else None,
          "lot": {"lot_id": lot.lot_id, "name": getattr(lot, "lot_name", None)} if lot else None}
    si = services.active_sim_info()
    st["active_sim"] = _sim_brief(si) if si else None
    hh = services.active_household()
    st["household"] = [_sim_brief(s) for s in hh.sim_info_gen()] if hh else []
    st["instanced_sims"] = [_sim_brief(s.sim_info) for s in services.sim_info_manager().instanced_sims_gen()]
    if fields:
        st = {k: v for k, v in st.items() if k in fields}
    return {"tick": int(services.time_service().sim_now.absolute_ticks()), "state": st, "ui": {}, "events": []}


def list_actions():
    return {"actions": []}


def act(name, args=None, timeout_s=None):
    raise WcpError(1003, "no actions in bridge v%s yet" % VERSION)


# ---------- harness channel ----------
def reload():
    """Re-import version + handlers from the (replaced) .ts4script without restarting the game. The TCP servers and the
    Zone.update hook stay; server.py looks handlers up through the module object, so new code applies to the next request.
    A replaced archive needs a NEW zipimporter: the modules' existing loader keeps the old archive's table of contents."""
    import importlib, os, sys, zipimport
    from . import log, version
    pkg_dir = os.path.dirname(__file__)                  # ...\Mods\wcbridge_s4.ts4script\wcbridge_s4
    arch = pkg_dir[:pkg_dir.index(".ts4script") + len(".ts4script")]
    zipimport._zip_directory_cache.pop(arch, None)
    imp = zipimport.zipimporter(pkg_dir)
    sys.path_importer_cache[pkg_dir] = imp
    mods = [version, sys.modules[__name__]]
    for m in mods:
        m.__loader__ = imp
        if getattr(m, "__spec__", None) is not None:
            m.__spec__.loader = imp
    for m in mods:
        importlib.reload(m)
    v = sys.modules[__name__].VERSION
    log.write("reloaded handlers, version %s" % v)
    return {"reloaded": True, "bridge_version": v}



def pause():
    services.game_clock_service().set_clock_speed(0)
    return {"paused": True, "tick": int(services.time_service().sim_now.absolute_ticks())}


def resume(speed=1):
    services.game_clock_service().set_clock_speed(int(speed))
    return {"paused": False, "speed": _speed()}


set_speed = resume


def advance(minutes=None, seconds=None, speed=3):
    """Non-blocking in v0: set the speed and return; the caller polls get_state.time (the sim thread cannot sleep)."""
    services.game_clock_service().set_clock_speed(int(speed))
    return {"speed": _speed(), "time": _now(), "note": "poll get_state and pause when the target time is reached"}


def _capture(orig, out):
    def f(s, context=0):
        out.append(str(s))
        return orig(s, context)
    return f


def run_command(line):
    """Execute a console command as the player would type it and capture what it prints."""
    out = []
    names = ("output", "cheat_output", "automation_output")
    saved = {n: getattr(sims4.commands, n) for n in names}
    try:
        for n in names:
            setattr(sims4.commands, n, _capture(saved[n], out))
        sims4.commands.execute(line, _connection())
    finally:
        for n, f in saved.items():
            setattr(sims4.commands, n, f)
    return {"command": line, "output": out}


def _q_sims(scope="instanced"):
    mgr = services.sim_info_manager()
    gen = (s.sim_info for s in mgr.instanced_sims_gen()) if scope == "instanced" else mgr.get_all()
    return {"sims": [_sim_brief(s) for s in gen]}


def _q_sim(sim=None):
    si = _find_sim(sim)
    d = _sim_brief(si)
    d["buffs"] = []
    for b in si.Buffs:
        d["buffs"].append({"buff": getattr(getattr(b, "buff_type", None), "__name__", type(b).__name__), "mood": getattr(getattr(b, "mood_type", None), "__name__", None),
                           "mood_weight": getattr(b, "mood_weight", None)})
    d["skills"] = {}
    try:
        for sk in si.all_skills():
            d["skills"][type(sk).__name__] = sk.get_user_value()
    except Exception as e:
        d["skills_error"] = repr(e)
    d["motives"] = {}
    try:
        for st in si.commodity_tracker:
            n = type(st).__name__
            if n.lower().startswith("motive_"):
                d["motives"][n] = round(st.get_value(), 1)
    except Exception as e:
        d["motives_error"] = repr(e)
    return d


def _q_relationships(sim=None):
    si = _find_sim(sim)
    rs = services.relationship_service()
    out = []
    for rel in rs.get_all_sim_relationships(si.sim_id):
        other = rel.get_other_sim_id(si.sim_id)
        osi = services.sim_info_manager().get(other)
        tracks = {}
        trackers = [getattr(rel, "bidirectional_track_tracker", None)]
        try:
            trackers.append(rel.get_track_tracker(si.sim_id, other))
        except Exception:
            pass
        for tr in trackers:
            if tr is None:
                continue
            for t in tr:
                tracks[type(t).__name__] = round(t.get_value(), 1)
        bits = [type(b).__name__ if not isinstance(b, type) else b.__name__ for b in rel.get_bits(si.sim_id)]
        out.append({"other_id": other, "other": _name(osi) if osi else None, "tracks": tracks, "bits": bits})
    return {"sim": _name(si), "relationships": out}


def _dev_enabled():
    import os
    from . import log
    return os.path.exists(os.path.join(os.path.dirname(log._path()), "wcbridge_s4.dev"))


def _q_py(code):
    """Development only (Mods/wcbridge_s4.dev must exist): run Python on the simulation thread. The last expression's
    value is returned as repr; `services`, `sims4` and `_find_sim` are in scope."""
    if not _dev_enabled():
        raise WcpError(1002, "py query disabled (no Mods/wcbridge_s4.dev)")
    import ast
    tree = ast.parse(code)
    env = {"services": services, "sims4": sims4, "_find_sim": _find_sim}
    last = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last = ast.Expression(tree.body.pop().value)
    exec(compile(tree, "<wc-py>", "exec"), env)
    return {"value": repr(eval(compile(last, "<wc-py>", "eval"), env)) if last else None}


def _tuning(kind, name):
    import sims4.resources
    mgr = services.get_instance_manager(getattr(sims4.resources.Types, kind))
    for t in mgr.types.values():
        if t.__name__ == name:
            return t
    raise WcpError(1004, "no %s tuning named %r" % (kind.lower(), name))


def _obj_brief(o, origin=None):
    p = o.position
    d = {"id": o.id, "tuning": type(o).__name__, "definition_id": getattr(getattr(o, "definition", None), "id", None),
         "pos": [round(p.x, 2), round(p.y, 2), round(p.z, 2)], "level": getattr(o, "level", None), "is_sim": bool(getattr(o, "is_sim", False))}
    try:
        d["on_active_lot"] = bool(o.is_on_active_lot())
    except Exception:
        pass
    if origin is not None:
        d["dist"] = round(((p.x - origin.x) ** 2 + (p.z - origin.z) ** 2) ** 0.5, 2)
    return d


def _q_objects(name=None, r=None, limit=200, sims=False, on_lot=None):
    """Objects in the zone. name: case-insensitive substring of the tuning name; r: radius (m) around the active Sim;
    on_lot: True/False filter on the active lot."""
    si = services.active_sim_info(); sim = si.get_sim_instance() if si else None
    origin = sim.position if sim is not None else None
    out = []
    for o in services.object_manager().valid_objects():
        if getattr(o, "is_sim", False) and not sims:
            continue
        if name and name.lower() not in type(o).__name__.lower():
            continue
        b = _obj_brief(o, origin)
        if r is not None and b.get("dist", 0) > float(r):
            continue
        if on_lot is not None and b.get("on_active_lot") != bool(on_lot):
            continue
        out.append(b)
    out.sort(key=lambda b: b.get("dist", 0))
    return {"count": len(out), "objects": out[:int(limit)]}


def _q_interactions(sim=None):
    si = _find_sim(sim); s = si.get_sim_instance()
    if s is None:
        return {"sim": _name(si), "instanced": False}
    name = lambda i: getattr(getattr(i, "affordance", None), "__name__", str(i))
    tgt = lambda i: getattr(getattr(i, "target", None), "id", None)
    return {"sim": _name(si), "running": [{"affordance": name(i), "target": tgt(i)} for i in s.si_state],
            "queued": [{"affordance": name(i), "target": tgt(i)} for i in s.queue]}


def _q_push(affordance, target=None, sim=None):
    """Push interaction <affordance> (tuning name) for <sim> (default active) on object/Sim id <target>, as if the player
    picked it from the pie menu."""
    from interactions.context import InteractionContext
    from interactions.priority import Priority
    si = _find_sim(sim); s = si.get_sim_instance()
    if s is None:
        raise WcpError(1003, "%s is not instanced" % _name(si))
    aff = _tuning("INTERACTION", affordance)
    tobj = None
    if target is not None:
        tobj = services.object_manager().get(int(target))
        if tobj is None:
            raise WcpError(1004, "no object with id %s" % target)
    client = services.client_manager().get_first_client()
    ctx = InteractionContext(s, InteractionContext.SOURCE_PIE_MENU, Priority.High, client=client, pick=None)
    res = s.push_super_affordance(aff, tobj, ctx)
    return {"pushed": bool(res), "result": str(res)[:300]}


def _q_camera(sim=None, object=None):
    import camera
    if object is not None:
        o = services.object_manager().get(int(object))
        camera.focus_on_object(o, follow=False)
    else:
        camera.focus_on_sim(_find_sim(sim).get_sim_instance(), follow=False)
    return {"focused": True}


def _loc_hash(ls):
    """A LocalizedString (or a callable returning one) -> '0xHASH' (text is resolved on the client; the harness maps
    hashes to text with the game's and the mod's string tables)."""
    try:
        if callable(ls):
            ls = ls()
        h = getattr(ls, "hash", None)
        return "0x%08X" % h if h else None
    except Exception:
        return None


def _q_dialogs():
    svc = services.ui_dialog_service()
    out = []
    for did, d in list(getattr(svc, "_active_dialogs", {}).items()):
        resp = []
        try:
            for r in d._get_responses_gen():
                resp.append({"id": int(r.dialog_response_id), "text": _loc_hash(getattr(r, "text", None))})
        except Exception:
            pass
        out.append({"id": did, "type": type(d).__name__, "title": _loc_hash(getattr(d, "title", None)),
                    "text": _loc_hash(getattr(d, "text", None)), "responses": resp,
                    "modal": getattr(d, "DIALOG_MSG_TYPE", None) is not None and type(d).__name__ != "UiDialogNotification"})
    return {"dialogs": out, "modal_open": bool(svc.has_active_modal_dialogs())}


def _q_dialog_respond(id=None, response=None):
    """Answer an open dialog: response = a response id from `dialogs` (default: the first one). id default: the first modal one."""
    svc = services.ui_dialog_service(); ds = _q_dialogs()["dialogs"]
    cand = [d for d in ds if id is None or d["id"] == int(id)]
    if not cand:
        raise WcpError(1003, "no open dialog" + (" with id %s" % id if id else ""))
    d = cand[0]
    rid = int(response) if response is not None else (d["responses"][0]["id"] if d["responses"] else None)
    if rid is None:
        svc.dialog_cancel(d["id"]); return {"dialog": d, "cancelled": True}
    return {"dialog": d, "response": rid, "ok": bool(svc.dialog_respond(d["id"], rid))}


def _tunable_desc(t, depth=0):
    """A compact description of a Tunable object: its class name, default, and (for containers) the nested tunables."""
    name = type(t).__name__
    d = {"type": name}
    desc = getattr(t, "description", None) or getattr(t, "_description", None)
    if desc:
        d["doc"] = " ".join(str(desc).split())[:240]
    for attr in ("tunable_type", "_type"):
        v = getattr(t, attr, None)
        if isinstance(v, type):
            d["value_type"] = v.__name__
    try:
        dv = getattr(t, "default", None)
        if dv is not None and not callable(dv) and len(repr(dv)) < 80:
            d["default"] = repr(dv)
    except Exception:
        pass
    if depth < 2:
        tun = getattr(t, "tunable_items", None) or getattr(t, "_tunable_items", None)
        if isinstance(tun, dict) and tun:
            d["fields"] = {k: _tunable_desc(v, depth + 1) for k, v in list(tun.items())[:60]}
        inner = getattr(t, "_template", None) or getattr(t, "tunable", None)
        if inner is not None and inner is not t and hasattr(inner, "__class__") and "Tunable" in type(inner).__name__:
            d["item"] = _tunable_desc(inner, depth + 1)
    return d


def _q_tunables(kind=None, name=None, field=None):
    """The tuning fields the RUNNING game accepts for a tuning class: kind = a tuning kind (buff, interaction, object,
    venue, situation ...) and name = a tuning instance of that kind whose class you want (e.g. kind=interaction
    name=seating_Sit). Returns the class, its parents and every INSTANCE_TUNABLES field (type, doc, default, nested
    fields two levels deep). field=NAME returns only that field, deeper."""
    import sims4.resources
    if not kind or not name:
        raise WcpError(-32602, "give kind=<tuning kind> name=<a tuning instance of that kind>")
    T = getattr(sims4.resources.Types, kind.upper(), None)
    if T is None:
        raise WcpError(-32602, "unknown kind %r" % kind)
    inst = None
    for t in services.get_instance_manager(T).types.values():
        if t.__name__ == name:
            inst = t; break
    if inst is None:
        raise WcpError(1004, "no %s tuning named %r" % (kind, name))
    tun = {}
    mro = getattr(inst, "__mro__", None)
    if mro:
        for c in reversed(mro):
            tun.update(getattr(c, "INSTANCE_TUNABLES", None) or {})
    else:                                   # lazily loaded TuningBlueprint: its INSTANCE_TUNABLES are already merged
        tun.update(getattr(inst, "INSTANCE_TUNABLES", None) or {})
    if field:
        if field not in tun:
            raise WcpError(1004, "%s has no field %r" % (name, field))
        return {"tuning": name, "field": field, "desc": _tunable_desc(tun[field], depth=-2)}
    cls = [c.__module__ + "." + c.__name__ for c in (mro or ())[1:6]] or [repr(getattr(inst, "_tuned_classes", None) or type(inst).__name__)]
    return {"tuning": name, "class": cls,
            "fields": {k: _tunable_desc(v, depth=1) for k, v in sorted(tun.items())}}


QUERIES = {"py": _q_py, "tunables": _q_tunables, "dialogs": _q_dialogs, "dialog_respond": _q_dialog_respond, "objects": _q_objects, "interactions": _q_interactions, "push": _q_push, "camera": _q_camera, "command": run_command, "sims": _q_sims, "sim": _q_sim, "relationships": _q_relationships,
           "time": lambda: {"time": _now(), "speed": _speed()}}


def eval_query(query, args=None, timeout_s=None):
    fn = QUERIES.get(query)
    if fn is None:
        raise WcpError(-32602, "unknown query %r (have: %s)" % (query, ", ".join(sorted(QUERIES))))
    return fn(**(args or {}))
