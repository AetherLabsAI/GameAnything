"""Traditional -> Simplified Chinese (OpenCC, phrase-aware). Adaptation projects show everything in simplified Chinese: a work that arrives in
traditional characters is converted at ingest; the untouched original stays in 0_inbox. Quotes are then checked against the simplified text."""
import re

_CC = None
HAN = re.compile(r"[㐀-鿿]")


def _cc():
    global _CC
    if _CC is None:
        import opencc
        _CC = opencc.OpenCC("t2s")
    return _CC


def to_simplified(text: str) -> str:
    return _cc().convert(text)


def traditional_ratio(text: str, sample=20000) -> float:
    """Share of Han characters that OpenCC changes: ~0 for simplified text, typically >0.1 for traditional text."""
    han = HAN.findall(text[:sample])
    if not han: return 0.0
    cc = _cc(); memo = {}
    return sum(1 for c in han if memo.setdefault(c, cc.convert(c) != c)) / len(han)


def simplify_if_traditional(text: str, threshold=0.03):
    """-> (text, converted?, ratio)."""
    r = traditional_ratio(text)
    return (to_simplified(text), True, r) if r >= threshold else (text, False, r)
