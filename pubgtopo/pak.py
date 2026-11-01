"""Unreal Engine pak v4 reader/extractor, as used by the PC build of PUBG
(TslGame). Written from scratch against the game's own files; the format
notes below are the empirical findings (see README, "Technical findings").

Pak v4 layout used here:

* Footer (found by scanning the file tail for the magic E1 12 6F 5A):
  u32 version, u64 index offset, u64 index size, 20-byte IndexHash.
  The index is AES-256-ECB encrypted; SHA1(decrypted index) must equal
  IndexHash — that check is built in and reported for every pak.
* Index: FString mount point, u32 entry count, then per entry:
  FString name, u64 offset, u64 compressed size, u64 uncompressed size,
  u32 compression method, 20-byte hash, [if method != 0: u32 block count
  + that many (u64 start, u64 end) absolute file offsets], u8 encrypted
  flag, u32 compression block size.
* The entry hash is the SHA1 of the *stored* bytes (the compressed blocks
  concatenated), NOT of the decompressed content — confirmed empirically;
  assuming otherwise makes every entry look corrupt.
* Compression method 16 in TslGame's registry is Oodle. Stock tools fail
  here (repak panics, pyuepak's own parser only knows methods 0–3). The
  Oodle core library itself is loaded, in order of preference, from:
  (1) an explicit path (--oodle-lib / PUBG_OODLE_LIB), (2) the user's own
  game install (--game-dir), (3) the library pyuepak provides. Nothing
  Oodle is vendored in this repo.
"""

import ctypes
import hashlib
import os
import re
import struct
from pathlib import Path

from Crypto.Cipher import AES

MAGIC = b"\xe1\x12\x6f\x5a"
OODLE_METHOD = 16
OODLE_ENV_VAR = "PUBG_OODLE_LIB"


class _CtypesOodle:
    """OodleLZ_Decompress via ctypes, for a user-supplied oo2core library
    (e.g. the one from the user's own game install). The call signature
    mirrors pyuepak's wrapper, which is proven against this data."""

    def __init__(self, path):
        self.path = str(path)
        self.lib = ctypes.CDLL(self.path)
        self._decompress = self.lib.OodleLZ_Decompress
        self._decompress.restype = ctypes.c_longlong
        try:  # silence Oodle's stdout logging
            self.lib.OodleCore_Plugins_SetPrintf(ctypes.c_void_p(0))
        except AttributeError:
            pass

    def decompress(self, data, output_size):
        out = (ctypes.c_ubyte * output_size)()
        written = self._decompress(data, len(data), out, output_size,
                                   1, 1, 0, None, 0, None, None, None, 0, 3)
        if written <= 0:
            raise ValueError(f"Oodle decompression failed ({self.path})")
        return bytes(out[:written])


_OODLE_NAME_RE = re.compile(r"oo2core.*\.(dll|so|dylib)(\.\d+)?$", re.I)


def _find_oodle_in_game_dir(game_dir):
    """Search a PUBG install for the Oodle core library. game_dir may be
    the TslGame folder or the PUBG root containing it. Likely spots:
    TslGame/Binaries/Win64 and Engine/Binaries/ThirdParty/Oodle."""
    gd = Path(game_dir)
    roots = []
    for base in (gd, gd / "TslGame"):
        roots += [base / "Binaries" / "Win64",
                  base / "Binaries" / "Linux",
                  base / "Binaries" / "Mac",
                  base / "Engine" / "Binaries" / "ThirdParty" / "Oodle"]
    if gd.name == "TslGame":
        roots.append(gd.parent / "Engine" / "Binaries" / "ThirdParty" / "Oodle")
    seen = set()
    for root in roots:
        if root in seen or not root.is_dir():
            continue
        seen.add(root)
        for dirpath, _dirs, files in os.walk(root):
            for name in sorted(files):
                if _OODLE_NAME_RE.match(name):
                    return Path(dirpath) / name
    # Last resort: a bounded walk of the whole folder the user pointed at.
    for dirpath, _dirs, files in os.walk(gd):
        for name in sorted(files):
            if _OODLE_NAME_RE.match(name):
                return Path(dirpath) / name
    return None


class OodleProvider:
    """Resolves the Oodle decompressor lazily, in precedence order:
    explicit path / PUBG_OODLE_LIB -> game-install search -> pyuepak.
    (The game-install routes are untested on the development machine —
    no game binaries there; the pyuepak fallback is the tested path.)
    """

    def __init__(self, explicit_path=None, game_dir=None):
        self.explicit_path = explicit_path or os.environ.get(OODLE_ENV_VAR)
        self.game_dir = game_dir
        self._handle = None
        self.source = None

    def get(self):
        if self._handle is None:
            self._resolve()
            print(f"  Oodle library: {self.source}")
        return self._handle

    def _resolve(self):
        if self.explicit_path:
            if not os.path.isfile(self.explicit_path):
                raise SystemExit(f"Oodle library not found: {self.explicit_path}")
            self._handle = _CtypesOodle(self.explicit_path)
            self.source = f"{self.explicit_path} (explicit)"
            return self._handle
        if self.game_dir:
            found = _find_oodle_in_game_dir(self.game_dir)
            if found is not None:
                self._handle = _CtypesOodle(found)
                self.source = f"{found} (game install)"
                return self._handle
            print(f"  note: no oo2core library found under {self.game_dir}; "
                  "falling back to pyuepak's library")
        try:
            from pyuepak.oodle import oodle
            self._handle = oodle()
        except Exception as exc:  # pragma: no cover - depends on environment
            raise SystemExit(
                "Decompressing these paks needs an Oodle core library: "
                "point --oodle-lib at one (or set PUBG_OODLE_LIB), pass "
                "--game-dir so it can be taken from your PUBG install, or "
                "pip install pyuepak for its bundled library."
            ) from exc
        self.source = "pyuepak bundled library"
        return self._handle


def read_fstring(buf, off):
    """UE FString: i32 length (negative = UTF-16), bytes, NUL included."""
    n = struct.unpack_from("<i", buf, off)[0]
    if n < 0:
        ln = -n
        s = buf[off + 4: off + 4 + 2 * ln].decode("utf-16-le").rstrip("\x00")
        return s, off + 4 + 2 * ln
    s = buf[off + 4: off + 4 + n].rstrip(b"\x00").decode("ascii")
    return s, off + 4 + n


def parse_pak(path, key):
    """Decrypt and parse a pak index. Returns a dict with the raw file
    bytes (entry payloads are sliced out of it later), pak version, mount
    point, whether the index SHA1 verified, and the entry list."""
    data = open(path, "rb").read()
    tail = data[-1024:]
    mpos = tail.rfind(MAGIC)
    if mpos < 0:
        raise ValueError(f"{path}: pak magic not found — not a pak v4 file?")
    fpos = len(data) - 1024 + mpos
    version = struct.unpack_from("<I", data, fpos + 4)[0]
    idx_off, idx_size = struct.unpack_from("<qq", data, fpos + 8)
    idx_hash = data[fpos + 24: fpos + 44]

    plain = AES.new(key, AES.MODE_ECB).decrypt(data[idx_off: idx_off + idx_size])
    sha_ok = hashlib.sha1(plain).digest() == idx_hash

    mount, p = read_fstring(plain, 0)
    count = struct.unpack_from("<i", plain, p)[0]
    p += 4
    entries = []
    for _ in range(count):
        name, p = read_fstring(plain, p)
        off, csize, usize = struct.unpack_from("<qqq", plain, p)
        p += 24
        method = struct.unpack_from("<I", plain, p)[0]
        p += 4
        entry_hash = plain[p: p + 20]
        p += 20
        blocks = []
        if method != 0:
            nb = struct.unpack_from("<I", plain, p)[0]
            p += 4
            for _ in range(nb):
                s, e = struct.unpack_from("<qq", plain, p)
                p += 16
                blocks.append((s, e))
        encrypted = plain[p]
        p += 1
        block_size = struct.unpack_from("<I", plain, p)[0]
        p += 4
        entries.append(dict(name=name, off=off, csize=csize, usize=usize,
                            method=method, hash=entry_hash, blocks=blocks,
                            encrypted=encrypted, block_size=block_size))
    return dict(data=data, version=version, mount=mount, sha_ok=sha_ok,
                entries=entries)


def _align16(n):
    return (n + 15) & ~15


def _stored_bytes(data, entry):
    """The entry's bytes exactly as stored in the pak (still compressed) —
    this is what the index entry hash is taken over."""
    if entry["method"] == 0:
        # Uncompressed entries repeat the index record as a data-area
        # header at the entry offset; payload follows it (53 bytes).
        hdr = 24 + 4 + 20 + 1 + 4
        start = entry["off"] + hdr
        return data[start: start + entry["csize"]]
    return b"".join(data[s:e] for (s, e) in entry["blocks"])


def _decrypt_stored(stored, entry, key):
    if not entry["encrypted"]:
        return stored
    if entry["method"] == 0:
        raw = AES.new(key, AES.MODE_ECB).decrypt(stored[:_align16(len(stored))])
        return raw[: entry["csize"]]
    out = bytearray()
    pos = 0
    for (s, e) in entry["blocks"]:
        n = e - s
        blk = AES.new(key, AES.MODE_ECB).decrypt(stored[pos: pos + _align16(n)])
        out += blk[:n]
        pos += n
    return bytes(out)


def extract_entry(data, entry, key, oodle_provider=None):
    """Return the entry's decompressed bytes."""
    stored = _decrypt_stored(_stored_bytes(data, entry), entry, key)
    if entry["method"] == 0:
        return stored
    if entry["method"] != OODLE_METHOD:
        raise ValueError(
            f"{entry['name']}: compression method {entry['method']} not "
            f"supported (only 0 = stored and {OODLE_METHOD} = Oodle are)"
        )
    if oodle_provider is None:
        oodle_provider = OodleProvider()
    handle = oodle_provider.get()
    out = bytearray()
    remaining = entry["usize"]
    pos = 0
    for (s, e) in entry["blocks"]:
        n = e - s
        expected = min(entry["block_size"], remaining)
        out += handle.decompress(stored[pos: pos + n], expected)
        pos += n
        remaining -= expected
    return bytes(out)


def _safe_join(outdir, name):
    parts = [p for p in name.replace("\\", "/").split("/")
             if p not in ("", ".", "..")]
    return os.path.join(outdir, *parts)


def unpack_paks(pak_paths, outdir, key, list_only=False,
                oodle_lib=None, game_dir=None):
    """Extract (or with list_only, just list) every entry of every pak.
    Returns a list of problem strings (empty = clean run)."""
    problems = []
    provider = OodleProvider(explicit_path=oodle_lib, game_dir=game_dir)
    total = 0
    for path in pak_paths:
        pak = parse_pak(path, key)
        print(f"{os.path.basename(path)}: pak v{pak['version']} "
              f"index_sha1_ok={pak['sha_ok']} mount={pak['mount']} "
              f"entries={len(pak['entries'])}")
        if not pak["sha_ok"]:
            problems.append(f"{path}: index SHA1 does not match the footer "
                            "hash — wrong key, or not a pak v4 file")
            continue
        for entry in pak["entries"]:
            total += 1
            if list_only:
                print(f"    {entry['name']}  size={entry['usize']} "
                      f"method={entry['method']}")
                continue
            try:
                blob = extract_entry(pak["data"], entry, key, provider)
            except Exception as exc:
                problems.append(f"{entry['name']}: extract failed: {exc}")
                continue
            stored_hash = hashlib.sha1(
                _stored_bytes(pak["data"], entry)).digest()
            if stored_hash != entry["hash"]:
                problems.append(f"{entry['name']}: stored-bytes SHA1 mismatch")
            if len(blob) != entry["usize"]:
                problems.append(f"{entry['name']}: size mismatch — got "
                                f"{len(blob)}, want {entry['usize']}")
                continue
            outpath = _safe_join(outdir, entry["name"])
            os.makedirs(os.path.dirname(outpath), exist_ok=True)
            if os.path.exists(outpath):
                problems.append(f"{entry['name']}: duplicate name, overwrote")
            with open(outpath, "wb") as f:
                f.write(blob)
    print(f"\ntotal entries processed: {total}")
    print(f"problems: {len(problems)}")
    for p in problems:
        print("  !", p)
    return problems
