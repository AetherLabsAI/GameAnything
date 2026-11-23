"""Capture times are hints, not facts. Messaging apps, AirDrop, exports and edits rewrite or strip them, so every time gets
a trust level and a reason; synthesize weighs them against documents and image content.

trust: medium = camera / phone original metadata, nothing suspicious; low = re-saved file or a suspicious pattern.
Nothing here is ever "high": only the user or an authored document (an invitation, a schedule) makes a time a fact."""
from datetime import datetime, timedelta

BURST_WINDOW = timedelta(minutes=10)
BURST_SHARE = 0.3       # this share of timed items inside one window looks like a transfer / export, not a shoot


def _parse_exif(v, off=None):
    try:
        t = datetime.strptime(v, "%Y:%m:%d %H:%M:%S")
    except (TypeError, ValueError):
        return None, None
    return t, off


def _parse_iso(v):
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None, None
    return t.replace(tzinfo=None), (t.strftime("%z") or None)


def candidate(item) -> dict:
    m = item.get("raw_metadata") or {}
    camera = bool(m.get("make") or m.get("model"))
    if item["kind"] == "photo" and m.get("exif_datetime_original"):
        t, tz = _parse_exif(m["exif_datetime_original"], m.get("exif_offset_original"))
        src = "EXIF DateTimeOriginal"
    elif item["kind"] in ("video", "audio") and m.get("quicktime_creationdate"):
        t, tz = _parse_iso(m["quicktime_creationdate"]); src = "QuickTime creationdate"
    elif item["kind"] in ("video", "audio") and m.get("creation_time"):
        t, tz = _parse_iso(m["creation_time"]); src = "container creation_time"; camera = False
    else:
        return None
    if t is None: return None
    why = [] if camera else ["no camera make/model: the file was probably re-saved by an app, the time may be the save time"]
    if tz is None: why.append("no time zone in the file")
    return {"value": t, "tz": tz, "source": src, "trust": "medium" if camera else "low", "why": why}


def assess(items):
    """Sets item['capture_time'] (or None) for every item; returns pack-level notes."""
    timed = []
    for it in items:
        c = candidate(it); it["capture_time"] = c
        if c: timed.append(it)
    notes = []
    if len(timed) >= 5:
        ts = sorted(timed, key=lambda it: it["capture_time"]["value"])
        best = (0, 0)
        j = 0
        for i in range(len(ts)):
            while ts[i]["capture_time"]["value"] - ts[j]["capture_time"]["value"] > BURST_WINDOW: j += 1
            if i - j + 1 > best[1] - best[0]: best = (j, i + 1)
        n = best[1] - best[0]
        if n >= max(5, BURST_SHARE * len(ts)):
            t0, t1 = ts[best[0]]["capture_time"]["value"], ts[best[1] - 1]["capture_time"]["value"]
            msg = f"{n} of {len(ts)} timed items fall within {t0:%Y-%m-%d %H:%M}-{t1:%H:%M}: looks like a transfer / export time, not when they were taken"
            notes.append(msg)
            for it in ts[best[0]:best[1]]:
                c = it["capture_time"]; c["trust"] = "low"; c["why"].append(msg)
    days = {}
    for it in timed:
        d = it["capture_time"]["value"].date().isoformat(); days[d] = days.get(d, 0) + 1
    if days: notes.append("capture dates in metadata (unverified): " + ", ".join(f"{d} x{n}" for d, n in sorted(days.items())))
    untimed = len(items) - len(timed)
    if untimed: notes.append(f"{untimed} of {len(items)} items have no capture time in their metadata")
    for it in timed:
        c = it["capture_time"]; c["value"] = c["value"].isoformat(sep=" ")
    return notes
