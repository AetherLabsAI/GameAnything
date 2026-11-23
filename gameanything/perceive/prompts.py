"""Per-item prompts. The model sees one item at a time and only reports what is in it."""

RULES = """Rules:
- Report only what you can see / read in THIS item. Do not assume what the whole collection is about.
- Every guess (a role, which part of the day, who is speaking) is a guess: say what it is based on, and give a confidence.
- People: describe appearance (clothing, hair, glasses, approximate age) and position. Never guess names or identities
  beyond the role in the scene (e.g. "the person giving a speech"); the user will name people later.
- Quotes from a transcript are copied verbatim; corrections go in likely_transcription_errors, never into the quote.
- Write descriptions in {lang}. Keep text in images and quotes in their original language.
- Read the files listed below with the Read tool, then answer with the structured output only."""

PHOTO = """You are looking at one photo from a personal collection of memories.

File: {image}

""" + RULES

VIDEO = """You are looking at one video clip from a personal collection of memories: {n} keyframes (in time order) and the
automatic speech-to-text transcript of its audio. The transcript was made offline and can contain errors (names, homophones);
lines marked "suspect" or "few words for this long" may be noise, applause or missed speech.

Clip length: {duration:.0f} s.
Keyframes (time in seconds -> file):
{frames}
Transcript: {transcript}

""" + RULES

DOCUMENT = """You are reading one document from a personal collection of memories ({pages} pages). For each page there is
an image of the page and its extracted text; use both (the text can miss layout, the image can be hard to read).

{page_list}

""" + RULES
