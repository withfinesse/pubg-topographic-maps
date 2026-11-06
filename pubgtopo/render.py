"""Render stage: 16-bit heightmap -> topographic PNG.

Calibration (engine-derived, see README): the landscape actors in the
game data carry scale (100, 100, 100) and zero Z offset, so Unreal's
standard landscape decode applies exactly:

    elevation_m = (raw - 32767.5) * 512 / 65535        (at Z scale 100)

~128 counts per metre; for Erangel that gives -81.5 m (sea floor) to
+248.2 m (Stalber). --z-scale adjusts if a map's landscape Z scale ever
differs from 100.

Style: float pipeline end to end (no 8-bit banding), hillshade +
hypsometric tint, 10 m contours with labelled 50 m index contours.
Water is z < 0 restricted to regions connected to the map edge, so flat
low land (and interior below-zero depressions) render as land.

Options:
* --fine: tiered 2 m contours (faint 2 m minors, medium 10 m, bold
  labelled 50 m) — reveals 2-5 m bowls/dips that a 10 m interval cannot
  draw at all. Intended for --extent windows at full resolution.
* --micro-relief: blend in a micro-relief layer (elevation minus a
  smoothed copy of itself, +-5 m) that makes 1-5 m local dips and rises
  pop regardless of absolute elevation.
* --labels: place-name labels from a POI JSON ({"pois": [{"name": ...,
  "km": [x, y], "tier": 1|2|"R"}]}), or the bundled Erangel set with
  --labels erangel.
"""

import json
import os

import numpy as np

WATER_RGB = np.array([0.62, 0.76, 0.86])

HYPSOMETRIC_STOPS = [
    (0.0, "#a8c686"), (0.12, "#c5d6a4"), (0.30, "#e6ddb0"),
    (0.50, "#d9b77c"), (0.70, "#b08954"), (0.88, "#8a6d4f"),
    (1.0, "#e8e3da"),
]

# Vivid ramp in the style of topographic-map.com, weighted hard into
# the low range (yellow by ~25 m, orange by ~90 m on the 0-250 m
# scale): PUBG maps are low-relief, so an even spread leaves most
# land in the first colour. Land only — water keeps WATER_RGB.
VIVID_STOPS = [
    (0.00, "#4cc95e"), (0.04, "#a4dd4f"), (0.10, "#e9e83e"),
    (0.18, "#f9cf2e"), (0.28, "#fdb913"), (0.38, "#fb9e13"),
    (0.48, "#f98e09"), (0.60, "#ef6a12"), (0.72, "#e8571e"),
    (0.84, "#dd3550"), (0.92, "#e85d8a"), (1.00, "#f2a7c3"),
]

# Sand/terrain ramp (atlas palette: sand -> tan -> rust -> pale
# summit). Chosen for the art blend: its hues sit inside the official
# art's own colour family, so the tint reinforces the art instead of
# washing over it.
SAND_STOPS = [
    (0.00, "#ddd29b"), (0.10, "#e3d68f"), (0.22, "#e8c877"),
    (0.36, "#eab54f"), (0.50, "#e09a3e"), (0.62, "#cf7a2e"),
    (0.74, "#b85c24"), (0.84, "#96431f"), (0.92, "#7c4a2d"),
    (1.00, "#e8e3da"),
]


def load_heightmap(path):
    """Load a uint16 heightmap from .npy or a 16-bit image file."""
    if path.lower().endswith(".npy"):
        return np.load(path)
    from PIL import Image
    return np.asarray(Image.open(path))


def to_elevation(raw, z_scale=100.0):
    """Raw uint16 counts -> metres (UE landscape decode; see docstring)."""
    return (raw.astype(np.float64) - 32767.5) * 512.0 / 65535.0 * (z_scale / 100.0)


def block_mean(a, f):
    n0, n1 = a.shape[0] // f, a.shape[1] // f
    return a[:n0 * f, :n1 * f].reshape(n0, f, n1, f).mean(axis=(1, 3))


def water_mask(z, level=0.0):
    """True where z < level AND connected to the map edge
    (8-connectivity). level defaults to the true waterline; the
    website passes -0.5 m because PUBG's shoreline aprons hover
    within +/-0.5 m of zero, so the literal line paints dry beach
    as inlets — measured against the official art's coastline,
    -0.5 m trades ~8 m^2 of false water removed per 1 m^2 of
    (ankle-deep) false land added."""
    from scipy.ndimage import label
    below = z < level
    lab, _ = label(below, structure=np.ones((3, 3), int))
    border = set(np.unique(np.concatenate(
        [lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    return np.isin(lab, list(border))


def classify_art_water(rgb, loose=False):
    """Classify water in official map art (uint8 RGB, any resolution).

    Strict (default): B > R + 12 and G > R + 4 — the align-check
    referee used since v0.4.1. Loose (B > R + 6, G > R + 2) exists
    only to define 'decisively not water' for the coastline veto:
    it catches the dark seas the strict test misses (Taego's
    south-west sea is RGB ~(16,22,25), B-R ~= 9), at the cost of
    firing on shadowed vegetation, so it is never used as a water
    source directly."""
    a = rgb.astype(np.int16)
    if loose:
        return (a[..., 2] > a[..., 0] + 6) & (a[..., 1] > a[..., 0] + 2)
    return (a[..., 2] > a[..., 0] + 12) & (a[..., 1] > a[..., 0] + 4)


def coastline_mask(z, art_water_strict, art_water_loose, art_rgb):
    """Art-derived water mask (the website's rule since v0.6.0).

    All inputs on the same grid: z in metres, the two classifier
    outputs for the official art, and the art itself (float or uint8
    RGB) for the land veto. Candidates are the terrain flood below
    -0.5 m plus strict art-water; the water is their edge-connected
    components, MINUS solid art-land: pixels the art decisively
    paints as land (not loose-blue, and red >= blue — sand, roads,
    fields, vegetation) belonging to a decisive-land component with
    a 'core' pixel >= 4 px from any non-land pixel.

    Why each piece (all measured 2026-11-05, website audit): the
    flood alone drowns land the heightmap carries below its own
    water plane — Miramar's south causeway is a submerged ridge
    (-11..+11 m) that is drivable land in the art (35.6% of art-land
    in the band painted water; the veto cuts that to 0.1%) — while a
    real land strip has a core, the veto costs rivers only their
    1-3 px painted banks. The art alone fails the other way: Rondo's
    rivers are painted dark (B-R ~= 11) and every bridge breaks
    their connectivity, so the terrain flood carries their spine,
    and Taego's dark sea is flood-only. Blue classifier speckle on
    shadowed cliffs never survives: strict classification plus the
    edge filter plus the veto keep it land."""
    from scipy.ndimage import distance_transform_edt, label
    decisive = (~art_water_loose) & (art_rgb[..., 0] >= art_rgb[..., 2] - 2)
    dist = distance_transform_edt(decisive)
    core = decisive & (dist >= 4)
    lab, _ = label(decisive, structure=np.ones((3, 3), int))
    solid_ids = set(np.unique(lab[core])) - {0}
    solid_land = np.isin(lab, list(solid_ids))
    cand = water_mask(z, level=-0.5) | art_water_strict
    lab, _ = label(cand, structure=np.ones((3, 3), int))
    border = set(np.unique(np.concatenate(
        [lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    return np.isin(lab, list(border)) & ~solid_land


def load_labels(spec):
    """spec is a path to a POI JSON, or 'erangel' for the bundled set
    (anchors measured from the official map art — see README)."""
    if spec == "erangel":
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "erangel_pois.json")
    else:
        path = spec
    with open(path) as f:
        data = json.load(f)
    return data["pois"] if isinstance(data, dict) else data


def _hypsometric_cmap(stops=None):
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list("hyp", stops or HYPSOMETRIC_STOPS)


def _base_rgb(z, land, tint_top=250.0, vert_exag=6.0, px_m=4.0, stops=None):
    from matplotlib.colors import LightSource
    ls = LightSource(azdeg=315, altdeg=45)
    hs = ls.hillshade(z, vert_exag=vert_exag, dx=px_m, dy=px_m)
    tint = _hypsometric_cmap(stops)(np.clip(z / tint_top, 0, 1))
    rgb = tint[..., :3] * (0.35 + 0.65 * hs[..., None])
    rgb[~land] = WATER_RGB
    return rgb


def _relief_rgb(z, land, vert_exag=6.0, px_m=4.0):
    """Hillshade only, on a warm paper tone — the 'height colour off'
    base. Water keeps the same flat WATER_RGB as the tinted bases so
    toggling colour never changes the sea."""
    from matplotlib.colors import LightSource
    ls = LightSource(azdeg=315, altdeg=45)
    hs = ls.hillshade(z, vert_exag=vert_exag, dx=px_m, dy=px_m)
    rgb = np.repeat((0.30 + 0.70 * hs)[..., None], 3, axis=2)
    rgb = rgb * np.array([0.96, 0.95, 0.92])
    rgb[~land] = WATER_RGB
    return rgb


def _micro_relief_rgb(z, px_m, sigma_m=40.0, clip_m=5.0):
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    from scipy.ndimage import gaussian_filter
    hp = z - gaussian_filter(z, sigma_m / px_m)
    cmap = LinearSegmentedColormap.from_list(
        "micro", [(0.0, "#5e3c99"), (0.35, "#a79bc9"), (0.5, "#f2efe9"),
                  (0.65, "#d9a05a"), (1.0, "#8c4a12")])
    return cmap(Normalize(-clip_m, clip_m)(np.clip(hp, -clip_m, clip_m)))[..., :3]


def _draw_labels(ax, pois, ext):
    import matplotlib.patheffects as pe
    halo = [pe.withStroke(linewidth=3.2, foreground="white", alpha=0.88)]
    for q in pois:
        x, y = q["km"]
        if not (ext[0] <= x <= ext[1] and ext[2] <= y <= ext[3]):
            continue
        name = q["name"]
        if q.get("tier") == 1:
            fs, fw, col = 13.5, "bold", "#141210"
        elif q.get("tier") == "R":
            fs, fw, col = 12.5, "normal", "#3d3a33"
            name = " ".join(name.replace(" ", "  "))  # letter-spaced region label
        else:
            fs, fw, col = 10.5, "normal", "#1c1a17"
        ax.text(x, y, name, fontsize=fs, fontweight=fw, color=col,
                ha="center", va="center", path_effects=halo, zorder=8)


def _draw(ax, z, rgb, land, ext, title, fine=False, pois=None):
    ax.imshow(rgb, extent=ext, origin="upper", aspect="equal")
    top = float(np.floor(z.max()))
    if fine:
        minors = [v for v in np.arange(2, top + 1, 2) if v % 10 != 0]
        if minors:
            ax.contour(z, levels=minors, extent=ext, origin="upper",
                       colors="#5a4632", linewidths=0.22, alpha=0.5)
        mediums = [v for v in np.arange(10, top + 1, 10) if v % 50 != 0]
        if mediums:
            ax.contour(z, levels=mediums, extent=ext, origin="upper",
                       colors="#5a4632", linewidths=0.55, alpha=0.85)
        idx = np.arange(50, top + 1, 50)
        cs = ax.contour(z, levels=idx, extent=ext, origin="upper",
                        colors="#3d2c1c", linewidths=1.0, alpha=0.95)
        ax.clabel(cs, fmt="%d m", fontsize=8, inline=True)
    else:
        levels = np.arange(10, top + 1, 10)
        if len(levels):
            ax.contour(z, levels=levels, extent=ext, origin="upper",
                       colors="#5a4632", linewidths=0.35, alpha=0.75)
        idx = np.arange(50, top + 1, 50)
        if len(idx):
            cs = ax.contour(z, levels=idx, extent=ext, origin="upper",
                            colors="#3d2c1c", linewidths=0.8, alpha=0.9)
            ax.clabel(cs, fmt="%d m", fontsize=7, inline=True)
    if pois:
        _draw_labels(ax, pois, ext)
    ax.set_title(title, fontsize=13)
    ax.set_xlabel("km")
    ax.set_ylabel("km")
    ax.set_xticks(range(int(np.ceil(ext[0])), int(ext[1]) + 1))
    ax.set_yticks(range(int(np.ceil(ext[2])), int(ext[3]) + 1))
    ax.set_xlim(ext[0], ext[1])  # re-assert: set_xticks can relimit
    ax.set_ylim(ext[2], ext[3])
    ax.grid(color="white", lw=0.4, alpha=0.35)


def _save(fig, path):
    fig.tight_layout()
    fig.savefig(path)
    import matplotlib.pyplot as plt
    plt.close(fig)
    print("saved", path)


def render(heightmap_path, out_path, span_km=8.16, grid=2048, extent=None,
           zoom_out=None, fine=False, micro_relief=False, micro_sigma_m=40.0,
           micro_clip_m=5.0, labels=None, title=None, z_scale=100.0,
           dpi=200):
    """Render a topographic PNG. extent = (x0, x1, y0, y1) in km renders a
    full-resolution window instead of the downsampled full map."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.ndimage import gaussian_filter

    raw = load_heightmap(heightmap_path)
    zfull = to_elevation(raw, z_scale)
    del raw
    print(f"elevation range: {zfull.min():.1f} .. {zfull.max():.1f} m")
    n = zfull.shape[0]
    px_per_km = n / span_km

    pois = load_labels(labels) if labels else None
    if title is None:
        title = ("Topographic — 2 m contours, tiered" if fine else
                 "Topographic — contours 10 m, index 50 m")

    if extent is not None:
        x0, x1, y0, y1 = extent
        c0, c1 = int(round(x0 * px_per_km)), int(round(x1 * px_per_km))
        r0 = int(round((span_km - y1) * px_per_km))
        r1 = int(round((span_km - y0) * px_per_km))
        water = water_mask(zfull)
        z = gaussian_filter(zfull[r0:r1, c0:c1], 1.0)
        land = ~water[r0:r1, c0:c1]
        px_m = span_km * 1000.0 / n
        rgb = _base_rgb(z, land, px_m=px_m)
        if micro_relief:
            micro = _micro_relief_rgb(z, px_m, micro_sigma_m, micro_clip_m)
            rgb = 0.45 * rgb + 0.55 * micro
            rgb[~land] = WATER_RGB
        fh = min(19.5, max(4.0, 13.0 * z.shape[0] / z.shape[1]))
        fig, ax = plt.subplots(figsize=(13, fh), dpi=dpi)
        _draw(ax, z, rgb, land, [x0, x1, y0, y1], title,
              fine=fine, pois=pois)
        _save(fig, out_path)
        return

    # Full map on a downsampled grid (float block mean — no quantisation)
    f = max(1, round(n / grid))
    z = gaussian_filter(block_mean(zfull, f), 0.8)
    del zfull
    land = ~water_mask(z)
    px_m = span_km * 1000.0 / z.shape[0]
    rgb = _base_rgb(z, land, px_m=px_m)
    if micro_relief:
        micro = _micro_relief_rgb(z, px_m, micro_sigma_m, micro_clip_m)
        rgb = 0.45 * rgb + 0.55 * micro
        rgb[~land] = WATER_RGB
    fig, ax = plt.subplots(figsize=(13, 13), dpi=dpi)
    _draw(ax, z, rgb, land, [0, span_km, 0, span_km], title,
          fine=fine, pois=pois)
    _save(fig, out_path)

    if zoom_out:
        g = z.shape[0]
        c = slice(g // 4, 3 * g // 4)
        q = span_km / 4
        fig, ax = plt.subplots(figsize=(13, 13), dpi=dpi)
        _draw(ax, z[c, c], rgb[c, c], land[c, c], [q, 3 * q, q, 3 * q],
              title + " — centre zoom", fine=fine, pois=pois)
        _save(fig, zoom_out)
