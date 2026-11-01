"""Stitch stage: extracted Heightmap packages -> one 16-bit heightmap.

Layout (worked out empirically; see README, "Technical findings"):

* The extracted directory holds packages Heightmap_x{gx}_y{gy}_{nn}, each
  with .umap/.uexp/.ubulk files. Each package contains several landscape
  components; every component has a Texture2D export named
  Landscape_{cx}_{cy}_Heightmap in its .uexp.
* The texture's platform data in the .uexp is:
  [i32 SizeX][i32 SizeY][i32 NumSlices][FString PixelFormat]
  [i32 FirstMip][i32 NumMips], then per-mip 32-byte records:
  [u32 cooked][u32 flags][i32 ElementCount][i32 SizeOnDisk]
  [i64 OffsetInFile][i32 SizeX][i32 SizeY]. Small mips carry their payload
  inline in the .uexp after the record; bulk mips live in the .ubulk.
* CRITICAL fix-up: bulk payloads are NOT at OffsetInFile. The bulk-data
  flags (0x501) do not include BULKDATA_NoOffsetFixUp, so the true
  position is OffsetInFile + BulkDataStartOffset, a per-package i64 in
  the .umap summary (byte offset 169 in this build's layout) that equals
  TotalHeaderSize + <uexp file size> - 4. Reading at the raw offset lands
  inside neighbouring payloads and produces garbage tiles.
* Mip 0 is the tile: 512x512, PF_G16, little-endian uint16, row-major.
  (Older guides describe 32-bit pixels with elevation in bytes 2-3 — that
  was an older build's RGBA format. The current build uses G16.)
* Component (cx, cy) goes to canvas rows cy*512.., cols cx*512..,
  identity orientation (canvas is north-up).
"""

import glob
import os
import re
import struct

import numpy as np

from .uepackage import parse_package

# Byte offset of BulkDataStartOffset inside this build's package summary
# (it sits right after the AssetRegistryDataOffset field).
BULK_DATA_START_OFFSET_POS = 169


def bulk_data_start_offset(umap_path, uexp_size):
    """Per-package BulkDataStartOffset, cross-checked against the
    TotalHeaderSize + uexp_size - 4 identity (a warning, not a failure,
    if they disagree — the summary value is the one UE would use)."""
    with open(umap_path, "rb") as f:
        head = f.read(1024)
    bds, = struct.unpack_from("<q", head, BULK_DATA_START_OFFSET_POS)
    summary, *_ = parse_package(umap_path)
    expect = summary["total_header"] + uexp_size - 4
    if bds != expect:
        print(f"  warning: {os.path.basename(umap_path)}: BulkDataStartOffset "
              f"{bds} != expected {expect}; using the summary value")
    return bds


def heightmap_mips(uexp, exp, total_header):
    """Parse a Texture2D export's platform data out of the .uexp.
    Returns (pixel_format, [(w, h, element_bytes, size_on_disk, offset), ...]).
    """
    start = exp["serial_offset"] - total_header
    seg = uexp[start:start + exp["serial_size"]]
    m = re.search(rb"PF_[A-Za-z0-9_]+", seg)
    if not m:
        raise ValueError("no pixel format found in texture export")
    fmt = m.group().decode()
    # The regex lands on the format string's characters; the FString's NUL
    # terminator follows, then FirstMip/NumMips.
    p = m.start() + len(m.group()) + 1
    _first, num_mips = struct.unpack_from("<ii", seg, p)
    p += 8
    mips = []
    for _ in range(num_mips):
        cooked, flags, elem, ondisk, off = struct.unpack_from("<IIiiq", seg, p)
        p += 24
        w, h = struct.unpack_from("<ii", seg, p)
        p += 8
        mips.append((w, h, elem, ondisk, off))
        if not (elem == ondisk and flags & 0x100):
            p += elem  # inline mip payload follows its record in the .uexp
    return fmt, mips


def stitch_directory(indir):
    """Assemble the heightmap from every Heightmap package in indir.
    Returns a uint16 numpy array (north-up)."""
    umap_paths = sorted(glob.glob(os.path.join(indir, "*.umap")))
    if not umap_paths:
        raise SystemExit(f"no .umap packages found in {indir}")

    tiles = {}  # (cx, cy) -> uint16 array
    tile_shape = None
    for umap_path in umap_paths:
        stem = umap_path[:-len(".umap")]
        uexp_path, ubulk_path = stem + ".uexp", stem + ".ubulk"
        if not (os.path.exists(uexp_path) and os.path.exists(ubulk_path)):
            continue  # e.g. FoliageBlockingVolume has no bulk data
        summary, _names, _imports, exports = parse_package(umap_path)
        total_header = summary["total_header"]
        uexp = open(uexp_path, "rb").read()
        ubulk = open(ubulk_path, "rb").read()
        bds = bulk_data_start_offset(umap_path, len(uexp))
        pkg_tiles = 0
        for exp in exports:
            if exp["class_name"] != "Texture2D":
                continue
            mm = re.search(r"Landscape_(\d+)_(\d+)_Heightmap", exp["name"])
            if not mm:
                continue
            cx, cy = int(mm.group(1)), int(mm.group(2))
            fmt, mips = heightmap_mips(uexp, exp, total_header)
            w, h, elem, _ondisk, off = mips[0]
            if fmt != "PF_G16" or elem != w * h * 2:
                raise SystemExit(
                    f"{exp['name']}: expected a PF_G16 mip 0, got {fmt} "
                    f"{w}x{h} ({elem} bytes) — different build/format?")
            pos = off + bds  # the fix-up; see module docstring
            if pos + elem > len(ubulk):
                raise SystemExit(
                    f"{exp['name']}: mip 0 overruns the .ubulk "
                    f"({pos}+{elem} > {len(ubulk)})")
            raw = np.frombuffer(ubulk[pos:pos + elem],
                                dtype="<u2").reshape(h, w)
            if (cx, cy) in tiles:
                raise SystemExit(f"component {cx},{cy} placed twice")
            tiles[(cx, cy)] = raw
            tile_shape = (h, w)
            pkg_tiles += 1
        if pkg_tiles:
            print(f"{os.path.basename(stem)}: {pkg_tiles} components")

    if not tiles:
        raise SystemExit(f"no Landscape heightmap textures found in {indir}")
    max_cx = max(cx for cx, _ in tiles)
    max_cy = max(cy for _, cy in tiles)
    missing = [(cx, cy) for cy in range(max_cy + 1) for cx in range(max_cx + 1)
               if (cx, cy) not in tiles]
    if missing:
        raise SystemExit(f"missing {len(missing)} components, e.g. {missing[:8]}")

    th, tw = tile_shape
    canvas = np.zeros(((max_cy + 1) * th, (max_cx + 1) * tw), dtype=np.uint16)
    for (cx, cy), raw in tiles.items():
        canvas[cy * th:(cy + 1) * th, cx * tw:(cx + 1) * tw] = raw
    print(f"tiles placed: {len(tiles)}/{(max_cx + 1) * (max_cy + 1)}; "
          f"canvas {canvas.shape[1]}x{canvas.shape[0]}")
    return canvas


def save_heightmap(canvas, npy_path, png_path=None):
    np.save(npy_path, canvas)
    print(f"saved {npy_path}  min {canvas.min()}  max {canvas.max()}  "
          f"median {int(np.median(canvas))}")
    if png_path:
        from PIL import Image
        Image.fromarray(canvas).save(png_path)  # uint16 -> 16-bit PNG
        print(f"saved {png_path}")
