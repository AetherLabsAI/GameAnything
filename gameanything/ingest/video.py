"""Videos / audio: probe, keyframes (sampled, near-identical frames dropped), audio track, local speech-to-text."""
import json
import os
import subprocess
from pathlib import Path

from . import images

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
AUDIO_EXT = {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg"}
SAMPLE_EVERY = 4.0     # seconds between candidate keyframes
FRAME_DIFF = 12        # min dhash distance to the last kept frame
MAX_FRAMES = 24


def probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)   # ffprobe writes UTF-8 (paths, tags)
    j = json.loads(r.stdout); fmt = j.get("format", {}); tags = fmt.get("tags", {})
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
    m = {"creation_time": tags.get("creation_time"), "quicktime_creationdate": tags.get("com.apple.quicktime.creationdate"),
         "quicktime_location": tags.get("com.apple.quicktime.location.ISO6709"), "make": tags.get("com.apple.quicktime.make"),
         "model": tags.get("com.apple.quicktime.model"), "software": tags.get("com.apple.quicktime.software")}
    return {"duration": round(float(fmt.get("duration", 0)), 2), "has_video": v is not None, "has_audio": a is not None,
            "raw_metadata": {k: x for k, x in m.items() if x}}


def keyframes(path: Path, duration: float, out_dir: Path) -> list:
    """One candidate every SAMPLE_EVERY s (plus the first frame); keep a frame only if it differs from the last kept one."""
    out_dir.mkdir(parents=True, exist_ok=True)
    kept, last = [], None
    t = 0.0
    while t < max(duration, 0.1) and len(kept) < MAX_FRAMES:
        dst = out_dir / f"t{int(t * 10):05d}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", str(dst)],
                       check=True, capture_output=True)
        if dst.exists():
            h = images.dhash(images.load(dst))
            if last is None or bin(h ^ last).count("1") >= FRAME_DIFF:
                kept.append({"t": round(t, 2), "file": dst}); last = h
            else:
                dst.unlink()               # derived file of our own, not user data
        t += SAMPLE_EVERY
    return kept


def extract_audio(path: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(dst)], check=True, capture_output=True)
    return dst


_model = None


def whisper_model(name=None):
    """faster-whisper model: a local path, or a name (downloaded once by faster-whisper). Runs on CPU, offline once present."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        name = name or os.environ.get("GAMEANYTHING_WHISPER_MODEL") or "large-v3-turbo"
        _model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=min(16, os.cpu_count() or 4))
    return _model


SUSPECT_LOGPROB = -0.45   # below this a segment is often noise (applause, wind) heard as words


SPARSE_CPS, SPARSE_MIN = 1.5, 6.0   # chars/s over a span of 6 s+: applause or a pause folded into the segment (CJK-oriented)


def mark_suspect(segments, duration=None):
    """Flag, never drop: low confidence, the same short text 3+ times in a row (a typical Whisper loop on noise), text past
    the end of the audio; and 'sparse' spans (long, few words: applause, a pause, or quiet speech that was missed)."""
    for i, s in enumerate(segments):
        why = []
        d = s["t1"] - s["t0"]
        if d >= SPARSE_MIN and len(s["text"]) / d < SPARSE_CPS: s["sparse"] = True
        if duration and s["t0"] >= duration - 0.5: why.append("past the end of the audio")
        if s["avg_logprob"] < SUSPECT_LOGPROB: why.append("low confidence")
        run = [x["text"] for x in segments[max(0, i - 2):i + 3]]
        if len(s["text"]) <= 4 and run.count(s["text"]) >= 3: why.append("repeated short text")
        if why: s["suspect"] = why
    return segments


def transcribe(wav: Path, dst: Path, model=None, vocab=()) -> dict:
    """vocab: names / terms from the user or the documents (e.g. the couple's names on the invitation); given to Whisper as
    a prompt, which fixes most name errors (measured: a name misheard 4/4 times without it, 0/4 with it)."""
    import wave
    import numpy as np
    with wave.open(str(wav)) as w:            # our own 16 kHz mono s16 wav (extract_audio); avoids faster-whisper's PyAV decoding
        audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
    kw = {"initial_prompt": "、".join(vocab) + "。", "hotwords": " ".join(vocab)} if vocab else {}
    segs, info = whisper_model(model).transcribe(audio, vad_filter=True, beam_size=5, **kw)
    segments = [{"t0": round(s.start, 2), "t1": round(s.end, 2), "text": s.text.strip(),
                 "avg_logprob": round(s.avg_logprob, 3), "no_speech_prob": round(s.no_speech_prob, 3)} for s in segs]
    mark_suspect(segments, info.duration)
    tr = {"vocab": list(vocab), "language": info.language, "language_prob": round(info.language_probability, 3), "duration": round(info.duration, 2),
          "speech_seconds": round(sum(s["t1"] - s["t0"] for s in segments), 1), "segments": segments}
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(tr, ensure_ascii=False, indent=1), encoding="utf-8")
    write_readable(tr, dst.with_suffix(".txt"))
    return tr


def write_readable(tr, dst: Path, gap=2.0):
    """The transcript for a person to read: one line per segment with its time, gaps without recognized speech
    (applause, pauses, or speech too quiet to recognize) shown as such, suspect segments marked."""
    out = [f"# language {tr['language']} ({tr['language_prob']}), {tr['duration']}s, speech {tr['speech_seconds']}s"
           + (f", vocabulary: {', '.join(tr['vocab'])}" if tr.get("vocab") else ""), ""]
    t = 0.0
    for s in tr["segments"]:
        if s["t0"] - t >= gap: out.append(f"[{t:6.1f}-{s['t0']:6.1f}]   (no recognized speech)")
        out.append(f"[{s['t0']:6.1f}-{s['t1']:6.1f}] {s['text']}" + (f"   <- suspect: {', '.join(s['suspect'])}" if s.get("suspect") else "")
                   + ("   <- few words for this long: applause / a pause / missed quiet speech?" if s.get("sparse") else ""))
        t = s["t1"]
    if tr["duration"] - t >= gap: out.append(f"[{t:6.1f}-{tr['duration']:6.1f}]   (no recognized speech)")
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
