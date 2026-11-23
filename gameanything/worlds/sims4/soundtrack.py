"""A generated soundtrack for the launch-event videos (numpy only, no samples, no downloads, nothing copyrighted).

The Sims 4 seat has no sound device, so the game's own music / sound effects can neither be heard nor recorded there; the show logs named moments
("MARK <seconds> <name>", from the project's story mod) and this module turns them into a score: a synth-wave bed (bass, arpeggio, pad), engine risers, whooshes, impact
booms, a crowd swell and a driving beat for the race. `render(marks, duration)` -> float32 stereo array; `write_wav(path, ...)`.
  python -m gameanything.worlds.sims4.soundtrack marks.txt out.wav duration_s"""
import math
import sys
import wave

import numpy as np

SR = 44100


def _t(n):
    return np.arange(n) / float(SR)


def _env(n, a=0.01, d=0.2, s=0.7, r=0.2):
    e = np.ones(n)
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    if na:
        e[:na] = np.linspace(0, 1, na)
    if nd and na + nd < n:
        e[na:na + nd] = np.linspace(1, s, nd)
        e[na + nd:] = s
    if nr and nr < n:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e


def _saw(f, n):
    ph = np.cumsum(np.broadcast_to(f, (n,)) / SR) % 1.0
    return 2.0 * ph - 1.0


def _lp(x, cutoff):
    a = math.exp(-2.0 * math.pi * cutoff / SR)
    out = np.empty_like(x)
    y = 0.0
    for i in range(len(x)):
        y = (1 - a) * x[i] + a * y
        out[i] = y
    return out


def _noise(n, seed=1):
    return np.random.RandomState(seed).uniform(-1, 1, n)


def whoosh(dur, f0=300, f1=3000, seed=2):
    n = int(dur * SR)
    x = _noise(n, seed)
    k = np.exp(np.linspace(math.log(f0), math.log(f1), n))
    b = np.zeros(n)
    y1 = y2 = 0.0
    for i in range(0, n):
        a = math.exp(-2.0 * math.pi * k[i] / SR)
        y1 = (1 - a) * x[i] + a * y1
        y2 = (1 - a) * y1 + a * y2
        b[i] = y1 - y2
    b /= (np.abs(b).max() + 1e-9)
    return b * np.sin(np.linspace(0, math.pi, n)) ** 1.5


def boom(dur=1.6):
    n = int(dur * SR)
    t = _t(n)
    f = 38 + 90 * np.exp(-t * 9)
    x = np.sin(2 * math.pi * np.cumsum(f) / SR) * np.exp(-t * 2.6)
    nz = _noise(n, 5) * np.exp(-t * 14) * 0.5
    return x + nz


def riser(dur, f0, f1):
    n = int(dur * SR)
    f = np.linspace(f0, f1, n)
    x = _saw(f, n) * 0.5 + _saw(f * 1.005, n) * 0.5
    return _lp(x, 1800) * np.linspace(0.1, 1.0, n) ** 1.5


def crowd(dur):
    n = int(dur * SR)
    x = _lp(_noise(n, 9), 2600) - _lp(_noise(n, 9), 300)
    return x / (np.abs(x).max() + 1e-9) * np.sin(np.linspace(0, math.pi, n)) ** 0.8


def kick():
    n = int(0.22 * SR)
    t = _t(n)
    return np.sin(2 * math.pi * np.cumsum(55 + 140 * np.exp(-t * 28)) / SR) * np.exp(-t * 14)


def pluck(f, dur=0.28):
    n = int(dur * SR)
    return _lp(_saw(f, n), 2500) * np.exp(-_t(n) * 9)


def pad(freqs, dur):
    n = int(dur * SR)
    x = sum(_saw(f, n) + _saw(f * 1.004, n) for f in freqs) / (2 * len(freqs))
    return _lp(x, 900) * _env(n, 1.2, 0.3, 0.8, 1.5)


NOTE = {"A": 110.0, "F": 87.31, "C": 130.81, "G": 98.0}
CHORDS = [("A", (110.0, 164.8, 220.0)), ("F", (87.31, 174.6, 220.0)), ("C", (130.81, 164.8, 196.0)), ("G", (98.0, 146.8, 196.0))]


def _add(buf, x, t, gain=1.0, pan=0.0):
    i = int(t * SR)
    if i >= buf.shape[1] or i < 0:
        return
    n = min(len(x), buf.shape[1] - i)
    buf[0, i:i + n] += x[:n] * gain * (1.0 - max(0.0, pan))
    buf[1, i:i + n] += x[:n] * gain * (1.0 + min(0.0, pan))


def parse_marks(text):
    out = []
    for ln in text.splitlines():
        if "MARK " in ln:
            parts = ln.split("MARK ", 1)[1].split()
            if len(parts) >= 2:
                out.append((float(parts[0]), parts[1]))
    return out


def render(marks, duration, offset=0.0, bpm=112.0):
    """marks = [(seconds, name)] (show-relative); `offset` seconds are added (video time = show time + offset)."""
    m = {}
    for t, name in marks:
        m.setdefault(name, t + offset)
    n = int(duration * SR)
    buf = np.zeros((2, n), dtype=np.float64)
    beat = 60.0 / bpm
    t0 = m.get("host_opens", offset + 6.0)
    # the bed: pad chords and a plucked arpeggio from the host's first line to the end, a beat and bass joining at the race
    race0 = m.get("act2_race")
    bar = 4 * beat
    k = 0
    t = t0
    while t < duration - 0.5:
        name, ch = CHORDS[k % 4]
        _add(buf, pad(ch, bar + 0.8), t, 0.16)
        for j in range(8):
            f = ch[j % 3] * (2 if j % 4 == 3 else 4)
            _add(buf, pluck(f), t + j * beat / 2, 0.08, pan=(-0.4 if j % 2 else 0.4))
        if race0 is not None and t >= race0 - 0.1 and t < m.get("act2_leave", duration):
            for j in range(4):
                _add(buf, kick(), t + j * beat, 0.5)
                _add(buf, pluck(ch[0] * 1.0, 0.4), t + j * beat + beat / 2, 0.22)
        t += bar
        k += 1
    # the cues
    if "setup" in m or True:
        _add(buf, riser(max(2.0, t0 - offset + 1.0 if t0 > 2 else 2.0), 60, 220), max(0.0, t0 - 4.0), 0.25)
    _add(buf, whoosh(1.2, 400, 4000), t0 - 0.3, 0.35)
    if "car_run" in m:
        _add(buf, riser(m.get("car_climb", m["car_run"] + 3.5) - m["car_run"], 70, 420), m["car_run"], 0.30)
    if "car_climb" in m:
        _add(buf, riser(m.get("car_air", m["car_climb"] + 3.6) - m["car_climb"], 420, 900), m["car_climb"], 0.30)
    if "car_air" in m:
        _add(buf, boom(1.4), m["car_air"], 0.8)
        _add(buf, whoosh(3.0, 500, 5000, 3), m["car_air"], 0.45)
    if "car_settle" in m:
        _add(buf, boom(2.0), m["car_settle"] - 0.15, 1.0)
        _add(buf, crowd(3.2), m["car_settle"], 0.55)
    if "elon_speaks" in m:
        _add(buf, whoosh(0.8, 600, 2500, 4), m["elon_speaks"] - 0.4, 0.25)
    if "on_stage" in m:
        _add(buf, crowd(2.4), m["on_stage"] - 0.6, 0.45)
    if "gift" in m:
        for j, f in enumerate((523.25, 659.25, 783.99, 1046.5, 1318.5)):
            _add(buf, pluck(f, 0.7), m["gift"] + j * 0.14, 0.18, pan=(j % 2) * 0.6 - 0.3)
        _add(buf, whoosh(2.5, 300, 3500, 6), m["gift"], 0.3)
    if "drive_home" in m:
        _add(buf, riser(3.0, 80, 300), m["drive_home"], 0.25)
    if "act2_takeoff" in m:
        _add(buf, riser(4.0, 70, 500), m["act2_takeoff"], 0.35)
        _add(buf, boom(1.2), m["act2_takeoff"], 0.6)
    if "act2_iron_arrives" in m:
        _add(buf, whoosh(3.0, 4000, 300, 7), m["act2_iron_arrives"], 0.55)
        _add(buf, boom(1.8), m["act2_iron_arrives"] + 2.6, 0.9)
    if "act2_race" in m:
        _add(buf, riser(1.6, 100, 800), m["act2_race"] - 1.4, 0.35)
        _add(buf, boom(1.5), m["act2_race"], 0.9)
        _add(buf, whoosh(4.0, 300, 6000, 8), m["act2_race"], 0.4)
    if "act2_leave" in m:
        _add(buf, whoosh(3.0, 500, 7000, 9), m["act2_leave"], 0.5)
    end = m.get("act2_end", m.get("act1_end", duration - 3.0))
    for f in (110.0, 164.8, 220.0, 329.6):
        _add(buf, pad((f,), 3.5), end, 0.18)
    buf *= np.minimum(1.0, np.minimum(np.arange(n) / (SR * 0.5), (n - np.arange(n)) / (SR * 2.0)))
    pk = np.abs(buf).max() or 1.0
    return (buf / pk * 0.89).astype(np.float32)


def write_wav(path, stereo):
    pcm = (np.clip(stereo.T, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    marks = parse_marks(open(sys.argv[1], encoding="utf-8").read())
    write_wav(sys.argv[2], render(marks, float(sys.argv[3]), offset=float(sys.argv[4]) if len(sys.argv) > 4 else 0.0))
