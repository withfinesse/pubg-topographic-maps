"""Extract contour linework as vector data for interactive viewers.

Raster tile pyramids stretch when a viewer zooms past their native
resolution — lines go soft exactly where players zoom in. The fix is
to ship the contours as geometry and let the viewer draw them at
screen resolution: trace the contours once, at full heightmap
resolution, simplify, and pack them into a compact binary the
browser inflates and strokes onto canvas tiles.

Format ("PTV1", little-endian throughout, gzipped on disk):
    char[4]  magic "PTV1"
    u32      number of base segments (10 m levels)
    per segment: i16 level (m), u32 point count,
                 points as (u16 x, u16 y) pairs
    u32      number of fine segments (2 m levels, excluding
             multiples of 10), same record layout
Coordinates are in the viewer's master-pixel frame (4096 px across
the map span), quantised x8 — so x = km_east / span * 4096 * 8 and
y = (span - km_north) / span * 4096 * 8, a resolution of ~0.25 m.

Two hard-won extraction notes:
- Read segments from QuadContourSet.allsegs. Path.to_polygons()
  silently decimates (a 6,594-point contour came back with 18
  points) — the geometry looks fine numerically until you draw it.
- Trace in chunks that SHARE their edge row/column: a contour
  crossing a chunk seam is then traced by both sides to the same
  interpolated point, so segments meet exactly at the seams.
"""
import gzip
import struct

import numpy as np


def _prep_z(heightmap_path, grid=8192, z_scale=100.0):
    """Heightmap -> elevation on the working grid (render path)."""
    from scipy.ndimage import gaussian_filter

    from .render import block_mean, load_heightmap, to_elevation
    raw = load_heightmap(heightmap_path)
    zfull = to_elevation(raw, z_scale=z_scale)
    del raw
    n = zfull.shape[0]
    f = max(1, round(n / grid))
    z = gaussian_filter(block_mean(zfull, f), 0.8)
    del zfull
    return z


def _simplify(pts, tol_km=0.00035):
    """Douglas-Peucker; pts are (x_km_east, y_km_north) rows."""
    if len(pts) < 3:
        return pts
    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i0, i1 = stack.pop()
        a, b = pts[i0], pts[i1]
        ab = b - a
        denom = max(float(ab @ ab), 1e-12)
        seg = pts[i0 + 1:i1]
        if len(seg) == 0:
            continue
        t = np.clip(((seg - a) @ ab) / denom, 0, 1)
        d = np.linalg.norm(seg - (a + np.outer(t, ab)), axis=1)
        k = int(np.argmax(d))
        if d[k] > tol_km:
            keep[i0 + 1 + k] = True
            stack.append((i0, i0 + 1 + k))
            stack.append((i0 + 1 + k, i1))
    return pts[keep]


def _extract(z, levels, span_km, chunk=2048):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ppk = z.shape[0] / span_km
    out = []
    for r0 in range(0, z.shape[0], chunk):
        r1 = min(z.shape[0], r0 + chunk)
        for c0 in range(0, z.shape[1], chunk):
            c1 = min(z.shape[1], c0 + chunk)
            sub = z[r0:min(z.shape[0], r1 + 1),
                    c0:min(z.shape[1], c1 + 1)]
            ext = [c0 / ppk, c1 / ppk,
                   span_km - r1 / ppk, span_km - r0 / ppk]
            fig, ax = plt.subplots()
            cs = ax.contour(sub, levels=levels, extent=ext,
                            origin="upper")
            plt.close(fig)
            for lvl, segs in zip(cs.levels, cs.allsegs):
                for poly in segs:
                    if len(poly) < 2:
                        continue
                    sp = _simplify(np.asarray(poly, dtype=np.float64))
                    if len(sp) >= 2:
                        out.append((float(lvl), sp))
    return out


def _pack(segs, span_km):
    buf = bytearray()
    buf += struct.pack("<I", len(segs))
    npts = 0
    for lvl, poly in segs:
        q = np.empty((len(poly), 2), dtype=np.uint16)
        q[:, 0] = np.clip(np.round(poly[:, 0] / span_km * 4096 * 8),
                          0, 32768)
        q[:, 1] = np.clip(np.round((span_km - poly[:, 1]) / span_km
                                   * 4096 * 8), 0, 32768)
        buf += struct.pack("<hI", int(round(lvl)), len(poly))
        buf += q.astype("<u2").tobytes()
        npts += len(poly)
    return buf, npts


def extract_vectors(heightmap_path, out_path, span_km=8.16,
                    z_scale=100.0):
    """Trace base (10 m) + fine (2 m) contours -> gzipped PTV1 file.

    Returns a small stats dict (segment/point counts, byte sizes).
    """
    z = _prep_z(heightmap_path, z_scale=z_scale).astype(np.float32)
    top = float(np.floor(z.max()))
    base_levels = [v for v in np.arange(10, top + 1, 10)]
    fine_levels = [v for v in np.arange(2, top + 1, 2) if v % 10 != 0]
    base = _extract(z, base_levels, span_km)
    fine = _extract(z, fine_levels, span_km)
    bb, bp = _pack(base, span_km)
    fb, fp = _pack(fine, span_km)
    raw = b"PTV1" + bb + fb
    with open(out_path, "wb") as f:
        f.write(gzip.compress(raw, 9))
    import os
    return {"base_segments": len(base), "fine_segments": len(fine),
            "base_points": bp, "fine_points": fp,
            "raw_bytes": len(raw),
            "gz_bytes": os.path.getsize(out_path)}
