"""Minimal cooked UE package (.umap) summary parser.

Reads just enough of a package summary to support the stitch stage: the
name map, import table and export table (object names, classes, serial
offsets/sizes). Export entries are 104 bytes in this build of the game.
"""

import struct


class Reader:
    def __init__(self, data, off=0):
        self.d = data
        self.p = off

    def i32(self):
        v, = struct.unpack_from("<i", self.d, self.p)
        self.p += 4
        return v

    def u32(self):
        v, = struct.unpack_from("<I", self.d, self.p)
        self.p += 4
        return v

    def i64(self):
        v, = struct.unpack_from("<q", self.d, self.p)
        self.p += 8
        return v

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def bytes(self, n):
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def fstring(self):
        ln = self.i32()
        if ln == 0:
            return ""
        if ln > 0:
            raw = self.bytes(ln)
            return raw[:-1].decode("utf-8", "replace")
        raw = self.bytes(-2 * ln)
        return raw.decode("utf-16-le", "replace").rstrip("\x00")

    def fname(self, names):
        idx = self.i32()
        num = self.i32()
        base = names[idx] if 0 <= idx < len(names) else f"<badidx {idx}>"
        return base if num == 0 else f"{base}_{num - 1}"


def parse_package(umap_path):
    """Parse a cooked package summary.

    Returns (summary, names, imports, exports). Each export dict carries
    name, class_name, serial_size and serial_offset (offset into the
    package's serialised data, i.e. relative to the whole .umap file —
    callers working in the .uexp subtract summary['total_header']).
    """
    d = open(umap_path, "rb").read()
    r = Reader(d)
    tag = r.u32()
    assert tag == 0x9E2A83C1, hex(tag)
    legacy = r.i32()
    r.i32()  # ue3 version
    filever = r.i32()
    r.i32()  # licensee version
    ncustom = r.i32()
    for _ in range(ncustom):
        r.bytes(16)
        r.i32()
    total_header = r.i32()
    r.fstring()  # folder name
    r.u32()      # package flags
    name_count = r.i32()
    name_offset = r.i32()
    r.i32()      # gatherable text count (0 in practice)
    r.i32()      # gatherable text offset
    export_count = r.i32()
    export_offset = r.i32()
    import_count = r.i32()
    import_offset = r.i32()
    depends_offset = r.i32()
    summary = dict(legacy=legacy, filever=filever, total_header=total_header,
                   name_count=name_count, name_offset=name_offset,
                   export_count=export_count, export_offset=export_offset,
                   import_count=import_count, import_offset=import_offset,
                   depends_offset=depends_offset)

    # Name map
    r = Reader(d, name_offset)
    names = []
    for _ in range(name_count):
        names.append(r.fstring())
        r.u32()  # hash

    # Imports
    r = Reader(d, import_offset)
    imports = []
    for _ in range(import_count):
        cp = r.fname(names)
        cn = r.fname(names)
        outer = r.i32()
        on = r.fname(names)
        imports.append(dict(class_package=cp, class_name=cn,
                            outer=outer, name=on))

    # Exports (104-byte entries for this build)
    r = Reader(d, export_offset)
    exports = []
    for _ in range(export_count):
        start = r.p
        class_idx = r.i32()
        r.i32()  # super index
        r.i32()  # template index
        outer_idx = r.i32()
        obj_name = r.fname(names)
        r.u32()  # object flags
        serial_size = r.i64()
        serial_offset = r.i64()
        r.i32(); r.i32(); r.i32()  # forced / not-client / not-server
        r.bytes(16)                # guid
        r.u32()                    # package flags
        r.i32(); r.i32()           # not-always-loaded / is-asset
        for _ in range(5):
            r.i32()                # dependency counts
        assert r.p - start == 104, (r.p - start)

        def resolve(idx, _exports=exports, _imports=imports):
            if idx > 0:
                return (_exports[idx - 1]["name"]
                        if idx - 1 < len(_exports) else f"export#{idx - 1}")
            if idx < 0:
                return _imports[-idx - 1]["name"]
            return "None"

        exports.append(dict(name=obj_name, class_idx=class_idx,
                            class_name=resolve(class_idx),
                            outer_idx=outer_idx, serial_size=serial_size,
                            serial_offset=serial_offset))
    return summary, names, imports, exports
