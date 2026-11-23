"""Project directory layout: one folder per pipeline stage, numbered in the order they run, plus the user's own inputs
(config/) and the user's answers (feedback/). Every stage reads and writes only through these names.

    <project>/
      README.md            where the project is now, what each folder holds (written by GameAnything)
      0_inbox/             files the user dropped into the browser UI, waiting for the agent to ingest (kept as uploaded; ingest never edits it)
      config/              what the user provides to the pipeline (vocab.txt: names / terms for speech-to-text)
      1_ingest/            stage A, local: pack.yaml + derived/ (images, thumbs, contact sheets, frames, audio, transcripts, docs)
      2_perceive/          stage B: cards/ (one observation card per item), requests/ and agent_output/ (agent-native mode)
      3_remember/          stage C: board.yaml, people.yaml, motifs.yaml, quotes.yaml (+ tags.yaml from the tagging UI)
      4_design/            design: world_plan.yaml (+ art/: looks.yaml, portraits, walk sprites, previews)
      feedback/            questions to the user (questions.md, design_questions.md), answers.md (verbatim), ui_edits.jsonl
      privacy_ledger.yaml  every request that sent memory content to a model API (`requests:`) and every backup run (`backups:`)
      config/backup.yaml   optional automatic backup, off unless the user turned it on (backup.py)
"""
from pathlib import Path

CONFIG, INGEST, PERCEIVE, REMEMBER, DESIGN, FEEDBACK = "config", "1_ingest", "2_perceive", "3_remember", "4_design", "feedback"
INBOX = "0_inbox"
LEDGER = "privacy_ledger.yaml"
# what the browser UI may show at /media/<path>: any picture / video / sound file inside a pipeline work folder. A rule, not a list of
# folders, so a card picture an agent saves in a new folder (4_design/targets_ucsd/, 2_perceive/keyframes/...) is not a 404.
# Never served: config/, conversation/, the inbox originals, the privacy ledger, and any hidden (.name) path part.
MEDIA_ROOTS = (INGEST, PERCEIVE, REMEMBER, DESIGN, "5_build", FEEDBACK)
MEDIA_SUFFIXES = frozenset(".jpg .jpeg .png .gif .webp .bmp .svg .mp4 .webm .mov .m4v .mp3 .wav .ogg .m4a".split())
MEDIA_DIRS = MEDIA_ROOTS                                                # old name, kept for callers outside this package


def media_file(project: Path, rel: str):
    """The file /media/<rel> may serve for `project`, or None (outside the work folders, hidden, not a media file, or missing)."""
    rel = str(rel or "").split("?", 1)[0].strip().removeprefix("/media/").lstrip("/")
    if not rel: return None
    root = Path(project).resolve(); f = (root / rel).resolve()
    try: parts = f.relative_to(root).parts
    except ValueError: return None
    if len(parts) < 2 or parts[0] not in MEDIA_ROOTS or any(x.startswith(".") for x in parts): return None
    if f.suffix.lower() not in MEDIA_SUFFIXES or not f.is_file(): return None
    return f


def ledger_requests(data) -> list:
    """The `requests:` of a loaded privacy ledger; tolerates a ledger an agent wrote as a bare list of requests."""
    if isinstance(data, list): return data
    return (data or {}).get("requests", []) if isinstance(data, dict) else []


def inbox(project: Path) -> Path: return project / INBOX
def pack(project: Path) -> Path: return project / INGEST / "pack.yaml"
def derived(project: Path) -> Path: return project / INGEST / "derived"
def cards(project: Path) -> Path: return project / PERCEIVE / "cards"
def requests(project: Path) -> Path: return project / PERCEIVE / "requests"
def agent_output(project: Path) -> Path: return project / PERCEIVE / "agent_output"
def vocab(project: Path) -> Path: return project / CONFIG / "vocab.txt"
