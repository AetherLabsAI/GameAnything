"""Observation cards: what one model call says about one item. Facts only, no interpretation of the whole pack (that is
synthesize's job), and every guess says how sure it is. JSON Schema, passed to the model as structured-output schema."""

S = {"type": "string"}
SL = {"type": "array", "items": S}
CONF = {"type": "string", "enum": ["low", "medium", "high"]}

PERSON = {"type": "object", "additionalProperties": False, "required": ["ref", "position", "appearance", "role_guess", "confidence"],
          "properties": {"ref": S, "position": S, "appearance": S, "role_guess": S, "confidence": CONF}}
PEOPLE = {"type": "object", "additionalProperties": False, "required": ["count_visible", "persons", "groups"],
          "properties": {"count_visible": {"type": "integer"}, "persons": {"type": "array", "items": PERSON},
                         "groups": {"description": "who seems to be together, e.g. 'p2-p5: an older couple with the subjects'", **SL}}}
SETTING = {"type": "object", "additionalProperties": False, "required": ["place", "indoor_outdoor", "description"],
           "properties": {"place": S, "indoor_outdoor": {"type": "string", "enum": ["indoor", "outdoor", "both", "unclear"]}, "description": S}}
LOOK = {"objects_and_motifs": SL, "light_and_weather": S, "palette": SL, "mood": S}
COMMON_REQ = ["setting", "activity", "event_phase_guess", "people", "objects_and_motifs", "light_and_weather", "palette", "mood", "uncertain"]

PHOTO = {"type": "object", "additionalProperties": False,
         "required": [*COMMON_REQ, "text_in_image", "third_party_content", "quality"],
         "properties": {
             "setting": SETTING, "activity": S,
             "event_phase_guess": {"description": "which part of an event or day this looks like, and the visual cues for it", **S},
             "people": PEOPLE, **LOOK,
             "text_in_image": SL,
             "third_party_content": {"type": "object", "additionalProperties": False, "required": ["is_third_party", "why"],
                                     "properties": {"is_third_party": {"type": "boolean"}, "why": S}},
             "quality": {"type": "object", "additionalProperties": False, "required": ["representative", "why"],
                         "properties": {"representative": {"type": "integer", "minimum": 0, "maximum": 3}, "why": S}},
             "uncertain": SL}}

QUOTE = {"type": "object", "additionalProperties": False, "required": ["t", "text"], "properties": {"t": {"type": "number"}, "text": S}}
FIX = {"type": "object", "additionalProperties": False, "required": ["t", "heard", "likely", "why"],
       "properties": {"t": {"type": "number"}, "heard": S, "likely": S, "why": S}}
VIDEO = {"type": "object", "additionalProperties": False, "required": [*COMMON_REQ, "changes_over_time", "speech"],
         "properties": {
             "setting": SETTING, "activity": S, "event_phase_guess": PHOTO["properties"]["event_phase_guess"], "people": PEOPLE, **LOOK,
             "changes_over_time": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["t", "what"],
                                                              "properties": {"t": {"type": "number"}, "what": S}}},
             "speech": {"type": "object", "additionalProperties": False,
                        "required": ["present", "speaker_guess", "speaker_cues", "summary", "themes", "notable_quotes",
                                     "likely_transcription_errors", "completeness"],
                        "properties": {"present": {"type": "boolean"}, "speaker_guess": S, "speaker_cues": S, "summary": S, "themes": SL,
                                       "notable_quotes": {"description": "verbatim from the transcript, unchanged", "type": "array", "items": QUOTE},
                                       "likely_transcription_errors": {"type": "array", "items": FIX},
                                       "completeness": {"description": "does the clip start or end mid-speech; gaps (applause, pauses)", **S}}},
             "uncertain": SL}}

DOCUMENT = {"type": "object", "additionalProperties": False,
            "required": ["doc_type", "title", "language", "dates", "places", "people_named", "schedule", "other_facts", "images_in_document", "tone", "uncertain"],
            "properties": {
                "doc_type": S, "title": S, "language": S, "dates": SL,
                "places": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "address", "role"],
                                                      "properties": {"name": S, "address": S, "role": S}}},
                "people_named": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "role"],
                                                            "properties": {"name": S, "role": S}}},
                "schedule": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["time", "what", "where"],
                                                        "properties": {"time": S, "what": S, "where": S}}},
                "other_facts": SL,
                "images_in_document": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["page", "what", "same_occasion"],
                                                                  "properties": {"page": {"type": "integer"}, "what": S,
                                                                                 "same_occasion": {"description": "does the image look like it is from the event the document is about, or another occasion (and why)", **S}}}},
                "tone": S, "uncertain": SL}}

BY_KIND = {"photo": PHOTO, "video": VIDEO, "document": DOCUMENT}
