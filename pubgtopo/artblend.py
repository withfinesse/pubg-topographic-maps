"""Art-overlay render: topo data drawn OVER the official map art.

The balance that works (an earlier attempt at ~half-strength everything
failed — two full colour systems fight and both lose):

* the art is the base, calmed slightly (saturation x0.72, small value
  lift) so towns/roads/forests stay recognisable;
* the topo contributes only a ghosted hillshade (multiply at 0.28,
  pivoted at the flat-terrain value so plains keep the art's true
  colours) and a whisper of hypsometric tint (alpha 0.10), land only;
* the contour geometry itself is thin, so it can be strong: dark umber
  lines over a thin white underlay that cuts them free of forest/urban
  texture; 50 m index contours bolder, with haloed elevation labels;
* the art's own water is left untouched.

The art must be in the same pixel frame as the heightmap (for Erangel
the official api-assets art is exactly that — identity transform; see
README). Labels (optional) come from the render stage's POI JSON.
"""

import numpy as np

from .render import (HYPSOMETRIC_STOPS, block_mean, load_heightmap,
                     load_labels, to_elevation, water_mask)

ART_SAT = 0.72        # saturation multiplier on the art
ART_VLIFT = 0.06      # value lift: v -> v*(1-lift) + lift
SHADE_ALPHA = 0.28    # ghost hillshade strength (multiply, flat-pivoted)
TINT_ALPHA = 0.10     # hypsometric tint alpha, land only
VERT_EXAG = 6.0


def _muted_art(art_img, shape, box=None):
    """Resize/crop the art to the working grid and calm it down.
    Returns float RGB in 0..1."""
    from matplotlib.colors import hsv_to_rgb, rgb_to_hsv
    from PIL import Image
    im = art_img.crop(box) if box else art_img
    im = im.resize((shape[1], shape[0]), Image.LANCZOS)
    a = np.asarray(im).astype(np.float64) / 255.0
    hsv = rgb_to_hsv(a)
    hsv[..., 1] = np.clip(hsv[..., 1] * ART_SAT, 0, 1)
    hsv[..., 2] = np.clip(hsv[..., 2] * (1 - ART_VLIFT) + ART_VLIFT, 0, 1)
    return hsv_to_rgb(hsv)


def _composite(z, art_rgb, px_m):
    """Ghost shade + whisper tint over muted art. Returns (rgb, land)."""
    from matplotlib.colors import LightSource, LinearSegmentedColormap
    land = ~water_mask(z)
    hs = LightSource(azdeg=315, altdeg=45).hillshade(
        z, vert_exag=VERT_EXAG, dx=px_m, dy=px_m)
    base = art_rgb.copy()
    if TINT_ALPHA > 0:
        hyp = LinearSegmentedColormap.from_list("hyp", HYPSOMETRIC_STOPS)
        tint = hyp(np.clip(z / 250.0, 0, 1))[..., :3]
        base[land] = base[land] * (1 - TINT_ALPHA) + tint[land] * TINT_ALPHA
    flat = np.sin(np.radians(45))  # LightSource value for flat terrain
    f = np.clip((1 - SHADE_ALPHA) + SHADE_ALPHA * hs / flat, 0.55, 1.20)
    base[land] *= f[land][..., None]
    return np.clip(base, 0, 1), land


def _draw(ax, z, base, ext, title, pois=None, label_fs=7.5):
    import matplotlib.patheffects as pe
    ax.imshow(base, extent=ext, origin="upper", aspect="equal")
    levels = np.arange(10, float(np.floor(z.max())) + 1, 10)
    ax.contour(z, levels=levels, extent=ext, origin="upper",
               colors="white", alpha=0.36, linewidths=1.5)
    ax.contour(z, levels=levels, extent=ext, origin="upper",
               colors="#33241a", alpha=0.70, linewidths=0.40)
    idx = np.arange(50, float(np.floor(z.max())) + 1, 50)
    ax.contour(z, levels=idx, extent=ext, origin="upper",
               colors="white", alpha=0.30, linewidths=2.2)
    cs = ax.contour(z, levels=idx, extent=ext, origin="upper",
                    colors="#221507", alpha=0.90, linewidths=1.00)
    texts = ax.clabel(cs, fmt="%d m", fontsize=label_fs, inline=True,
                      inline_spacing=8)
    lbl_halo = [pe.withStroke(linewidth=2.4, foreground="white", alpha=0.9)]
    for t in texts:
        t.set_path_effects(lbl_halo)
    if pois:
        from .render import _draw_labels
        _draw_labels(ax, pois, ext)
    ax.set_title(title, fontsize=13)
    ax.set_xlabel("km")
    ax.set_ylabel("km")
    ax.set_xticks(range(int(np.ceil(ext[0])), int(ext[1]) + 1))
    ax.set_yticks(range(int(np.ceil(ext[2])), int(ext[3]) + 1))
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    ax.grid(color="white", lw=0.4, alpha=0.30)


def render_artblend(heightmap_path, art_path, out_path, span_km=8.16,
                    grid=2048, extent=None, labels=None, title=None,
                    z_scale=100.0, dpi=200):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    from scipy.ndimage import gaussian_filter
    Image.MAX_IMAGE_PIXELS = None

    raw = load_heightmap(heightmap_path)
    zfull = to_elevation(raw, z_scale)
    del raw
    n = zfull.shape[0]
    art_img = Image.open(art_path).convert("RGB")
    pois = load_labels(labels) if labels else None
    if title is None:
        title = "Topographic overlay on official art (contours 10 m, index 50 m)"

    if extent is not None:
        x0, x1, y0, y1 = extent
        ppk = n / span_km
        c0, c1 = int(round(x0 * ppk)), int(round(x1 * ppk))
        r0 = int(round((span_km - y1) * ppk))
        r1 = int(round((span_km - y0) * ppk))
        z = gaussian_filter(zfull[r0:r1, c0:c1], 0.8)
        aw, ah = art_img.size
        box = (int(x0 / span_km * aw), int((span_km - y1) / span_km * ah),
               int(x1 / span_km * aw), int((span_km - y0) / span_km * ah))
        art = _muted_art(art_img, z.shape, box=box)
        px_m = span_km * 1000.0 / n
        ext = [x0, x1, y0, y1]
    else:
        f = max(1, round(n / grid))
        z = gaussian_filter(block_mean(zfull, f), 0.8)
        art = _muted_art(art_img, z.shape)
        px_m = span_km * 1000.0 / z.shape[0]
        ext = [0, span_km, 0, span_km]
    del zfull

    base, _land = _composite(z, art, px_m)
    fig, ax = plt.subplots(figsize=(13, 13), dpi=dpi)
    _draw(ax, z, base, ext, title, pois=pois)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print("saved", out_path)
