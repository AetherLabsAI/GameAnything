"""Java .class files, read only (JVMS 4.1, 4.4): the class file version and the classes one refers to, for `gameanything native check`
(a Slay the Spire mod must be Java 8 bytecode, and every game / ModTheSpire / BaseMod class it names must exist in those jars).

    info(data)        -> {"name", "major", "refs": {"com/megacrit/cardcrawl/core/AbstractCreature", ...}}
    jar_classes(path) -> the set of class names in a jar ("a/b/C")
"""
import re
import struct
import zipfile

JAVA = {52: 8, 55: 11, 61: 17, 65: 21, 69: 25}                          # class file major -> Java release
_DESC = re.compile(r"L([^;<]+)[;<]")


class BadClass(ValueError):
    pass


def info(data: bytes) -> dict:
    if data[:4] != b"\xca\xfe\xba\xbe": raise BadClass("not a class file")
    try:
        major = struct.unpack_from(">H", data, 6)[0]; n = struct.unpack_from(">H", data, 8)[0]
        p = 10; utf8 = {}; classes = {}; descs = []; i = 1
        while i < n:
            tag = data[p]; p += 1
            if tag == 1:
                ln = struct.unpack_from(">H", data, p)[0]; utf8[i] = data[p + 2:p + 2 + ln].decode("utf-8", "replace"); p += 2 + ln
            elif tag == 7: classes[i] = struct.unpack_from(">H", data, p)[0]; p += 2
            elif tag in (8, 16, 19, 20): p += 2                         # String, MethodType, Module, Package
            elif tag == 12: descs.append(struct.unpack_from(">H", data, p + 2)[0]); p += 4      # NameAndType: its descriptor
            elif tag in (3, 4, 9, 10, 11, 17, 18): p += 4               # Integer, Float, Field/Method/InterfaceMethodref, Dynamic, InvokeDynamic
            elif tag == 15: p += 3                                      # MethodHandle
            elif tag in (5, 6): p += 8; i += 1                          # Long, Double take two slots
            else: raise BadClass(f"unknown constant pool tag {tag}")
            i += 1
        this = struct.unpack_from(">H", data, p + 2)[0]
    except (struct.error, IndexError) as e: raise BadClass(f"cut short: {e}")
    refs = set()
    for c in classes.values():
        s = utf8.get(c, "")
        if s.startswith("["): refs |= set(_DESC.findall(s))               # an array type: its element class, if any
        elif s: refs.add(s)
    for d in descs: refs |= set(_DESC.findall(utf8.get(d, "")))
    name = utf8.get(classes.get(this), "")                                # this_class: a Class entry of the pool
    refs.discard(name)
    return {"name": name, "major": major, "refs": refs}


def jar_classes(path) -> set:
    with zipfile.ZipFile(path) as z:
        return {n[:-6] for n in z.namelist() if n.endswith(".class") and not n.startswith("META-INF/")}
