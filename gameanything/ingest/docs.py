"""Documents (PDF, text): text per page + page images, so perceive can read both the words and the layout."""
from pathlib import Path

import pypdfium2 as pdfium

DOC_EXT = {".pdf", ".txt", ".md", ".epub"}
PAGE_SCALE = 1.5


def _simp(text, simplify):
    """Adaptation projects: traditional Chinese -> simplified (the original file stays in 0_inbox)."""
    if not simplify: return text, False
    from ..textconv import simplify_if_traditional
    t, done, _ = simplify_if_traditional(text)
    return t, done


def epub_chapters(path: Path) -> list:
    """An EPUB (zip of XHTML files) -> [(title, text)] in reading order (the OPF spine). No DRM support: a protected book raises ValueError."""
    import posixpath, re, zipfile
    from html.parser import HTMLParser
    from xml.etree import ElementTree as ET
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    if "META-INF/encryption.xml" in names and b"EncryptedData" in z.read("META-INF/encryption.xml"):
        raise ValueError("这本 EPUB 有 DRM 加密，读不出文字：请换成没有加密的版本，或把需要的章节复制成 txt")
    opf = ET.fromstring(z.read("META-INF/container.xml")).find(".//{*}rootfile").get("full-path")
    root = ET.fromstring(z.read(opf)); base = posixpath.dirname(opf)
    items = {i.get("id"): i.get("href") for i in root.iter("{http://www.idpf.org/2007/opf}item")}
    order = [items[r.get("idref")] for r in root.iter("{http://www.idpf.org/2007/opf}itemref") if r.get("idref") in items]

    class T(HTMLParser):
        def __init__(self):
            super().__init__(); self.out = []; self.title = ""; self._t = False; self._skip = 0
        def handle_starttag(self, tag, a):
            if tag in ("script", "style"): self._skip += 1
            if tag in ("h1", "h2", "h3", "title"): self._t = True
            if tag in ("p", "div", "br", "h1", "h2", "h3", "li", "tr"): self.out.append("\n")
        def handle_endtag(self, tag):
            if tag in ("script", "style"): self._skip -= 1
            if tag in ("h1", "h2", "h3", "title"): self._t = False
        def handle_data(self, d):
            if self._skip: return
            if self._t and not self.title.strip() and d.strip(): self.title = d.strip()
            self.out.append(d)

    out = []
    for href in order:
        name = posixpath.normpath(posixpath.join(base, href.split("#")[0]))
        if name not in names: continue
        t = T(); t.feed(z.read(name).decode("utf-8", errors="replace"))
        text = re.sub(r"\n\s*\n+", "\n\n", "".join(t.out)).strip()
        if len(text) >= 20: out.append((t.title or posixpath.basename(name), text))
    return out


def process(path: Path, out_dir: Path, simplify=False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".epub":                              # one page per chapter (spine item), in reading order
        pages = []; conv_any = False
        for i, (title, text) in enumerate(epub_chapters(path)):
            text, conv = _simp(text, simplify); conv_any = conv_any or conv; title = _simp(title, simplify)[0]
            f = out_dir / f"page{i + 1}.txt"; f.write_text(text, encoding="utf-8")
            pages.append({"n": i + 1, "title": title, "text": f, "chars": len(text)})
        return {"pages": pages, **({"simplified": True} if conv_any else {})}
    if path.suffix.lower() != ".pdf":
        text, conv = _simp(path.read_text(encoding="utf-8", errors="replace"), simplify)
        (out_dir / "text.txt").write_text(text, encoding="utf-8")
        return {"pages": [{"n": 1, "text": out_dir / "text.txt", "chars": len(text)}], **({"simplified": True} if conv else {})}
    pdf = pdfium.PdfDocument(str(path)); pages = []; any_conv = False
    for i in range(len(pdf)):
        page = pdf[i]
        text = page.get_textpage().get_text_range()
        img = out_dir / f"page{i + 1}.jpg"; txt = out_dir / f"page{i + 1}.txt"
        page.render(scale=PAGE_SCALE).to_pil().convert("RGB").save(img, "JPEG", quality=85)
        text, conv = _simp(text, simplify); any_conv = any_conv or conv
        txt.write_text(text, encoding="utf-8")
        pages.append({"n": i + 1, "image": img, "text": txt, "chars": len(text.strip())})
    return {"pages": pages, **({"simplified": True} if any_conv else {})}
