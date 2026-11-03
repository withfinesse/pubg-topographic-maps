# pubgtopo — topographic maps from your own PUBG install

Turn the terrain data inside your own copy of PUBG into real topographic
maps: contour lines at 10 m (or a tiered 2 m), labelled 50 m index
contours, hillshade and elevation tint — plus a micro-relief layer that
exposes the 1–5 m bowls and dips that decide late-game fights and that a
standard contour interval cannot draw at all.

> **Disclaimer.** pubgtopo is an unofficial fan tool. It is not affiliated
> with, endorsed by, or connected to KRAFTON, PUBG Studios, or
> PLAYERUNKNOWN. It requires a legally owned copy of PUBG: Battlegrounds —
> **it ships with no game data, no map art, and no encryption key**; every
> input comes from your own install or from PUBG's official public assets
> repo. Extracting data from your own game files sits in a grey area of
> most games' terms of service; what you do with your copy is your
> responsibility.

## What you get

From a map's own files (all four current competitive maps — Erangel,
Miramar, Taego, Rondo — verified end-to-end), the pipeline produces an 8192×8192 lossless 16-bit heightmap — ~0.008 m of
elevation resolution per count, ~1 m per pixel horizontally — and renders
such as:

- a full-map topographic sheet (10 m contours, 50 m index, place labels);
- full-resolution zoom windows with tiered 2 m contours, for printing or
  screenshotting a specific area;
- a micro-relief view in which every shallow dip and rise stands out —
  on the farmland south of Pochinki there is a bowl 4.8 m deep and ~90 m
  wide that is *mathematically invisible* at a 10 m interval (everything
  within 70 m of its centre lies between 32.4 m and 39.9 m, so no 10 m
  line can ever be drawn through it), yet obvious in the fine and
  micro-relief treatments;
- an art-overlay variant: the topo drawn over the official map art, tuned
  so both stay readable.

## Pipeline

```
 your PUBG install                         pubgtopo
┌───────────────────────────┐   unpack   ┌──────────────────────┐
│ TslGame/Content/Paks/     │ ─────────► │ extracted packages   │
│ pakchunkXXXX_heightmap*   │  (pak v4,  │ .umap/.uexp/.ubulk   │
└───────────────────────────┘  AES+Oodle) └─────────┬────────────┘
                                                    │ stitch
                                                    ▼
┌───────────────────────────┐   render   ┌──────────────────────┐
│ topographic PNG           │ ◄───────── │ 16-bit heightmap     │
│ (contours/hillshade/      │            │ .npy (+ .png)        │
│  labels/micro-relief)     │            └──────────────────────┘
└───────────────────────────┘
        ▲ artblend: same render drawn over the official map art
```

Calibration is not a separate step: the raw→metres conversion is an
engine constant recovered from the game data itself (see "Calibration"
under Technical findings) and is built into the render stage.

## Install

Python ≥ 3.10. From a clone of this repo:

```bash
pip install -r requirements.txt     # or: pip install .
python -m pubgtopo --help           # or the `pubgtopo` command after pip install .
```

You also need two things that are deliberately **not** in this repo:
the pak AES key (see "The AES key") and an Oodle core library (see
"Oodle"). Both are covered below — neither is a blocker.

## Adding your game data

Everything the tool eats comes from your own install. Step by step:

1. **Find the paks.** In a Steam install they live at

   ```
   ...\Steam\steamapps\common\PUBG\TslGame\Content\Paks
   ```

   Each map's terrain is one *chunk family*: a small stub
   `pakchunkXXXX-WindowsNoEditor_heightmap.pak` plus data files
   `..._heightmap_0.pak` … `_3.pak` (~60–470 MB per family in total).

2. **Pick your map** from the chunk table:

   | Chunk | Internal name | Map | Status |
   |------:|---------------|-----|--------|
   | 5100 | Desert | Miramar | identified, fully tested |
   | 5200 | Savage | Sanhok | identified |
   | 5300 | DihorOtok | Vikendi | identified |
   | **5500** | **Baltic** | **Erangel** | **identified, fully tested** |
   | 5700 | Chimera | Paramo | identified |
   | 5900 | Tiger | Taego | identified, fully tested |
   | 6300 | Neon | Rondo | identified, fully tested |
   | 5400 / 5600 / 5800 / 6000 | — | — | unconfirmed (6000 is Deston by file size only) |

   Don't trust the table blindly — verify: the small stub paks contain
   plaintext asset paths, so `strings` on a stub reveals its map; and
   once you have the key, `pubgtopo unpack --list <stub.pak>` prints the
   mount point (e.g. `.../Maps/Baltic/Art/HeightMap/` = Erangel).

3. **Copy the family's files** (stub + `_0`…`_3`) anywhere convenient and
   point `unpack` at them. The tool never writes to your install.

4. **(Optional) Official map art** — needed only for place labels beyond
   the bundled Erangel set and for the `artblend` stage. PUBG publishes
   it in the official
   [pubg/api-assets](https://github.com/pubg/api-assets) repo:
   `Erangel_Main_No_Text_High_Res.png` (the artblend base) and
   `Erangel_Main_High_Res.png` (with printed labels). The files are
   Git LFS — a plain `git clone` may fetch pointer stubs instead of
   images; use the repo's download button, a `git lfs pull`, or the
   `media.githubusercontent.com` URL. For Erangel the art's pixel grid
   is identical to the heightmap grid (verified — see Technical
   findings), so no alignment step is needed.

5. **Where inputs go:** `unpack` takes the pak paths directly and writes
   an extracted folder; `stitch` takes that folder; `render`/`artblend`
   take the `.npy` heightmap `stitch` writes (plus `--art` for artblend).

## The AES key

The pak indexes are AES-256 encrypted, so `unpack` needs the TslGame pak
key. Following the pattern of tools like FModel, **pubgtopo ships without
the key — you supply your own**, via `--key` or the `PUBG_PAK_KEY`
environment variable. The value is a widely published, community-known
constant: it has circulated in public UE4 key lists and forum posts since
~2018 (Gildor's forums, the cs.rin.ru community list, the QuickBMS
script's built-in key) and, remarkably, still decrypts current builds.

**The ASCII trap** (this burned real time — learn from it): the key is a
32-character string that *looks* like hexadecimal. It isn't — **the key
bytes are the ASCII text of the string itself.** Hex-decoding the string
and using the result as the key fails. (In key lists the value is often
printed as `0x3435…` — that is the hex encoding *of the ASCII text*, and
hex-decoding *that* lands on the right bytes.) pubgtopo accepts the key
as the raw 32-character string, as 64 hex characters, or as base64, and
normalises it for you.

You can verify any candidate key without extracting anything:
`pubgtopo unpack --list some.pak` decrypts the index and checks its
SHA1 against the hash stored in the pak footer — `index_sha1_ok=True`
means the key is right, cryptographically, not just plausibly.

## Oodle

Every entry in these paks is Oodle-compressed (method 16 — see
Technical findings), and Oodle is proprietary, so the decompressor is
loaded at runtime, in this order:

1. **Explicit path** — `--oodle-lib /path/to/oo2core_9_win64.dll`, or
   the `PUBG_OODLE_LIB` environment variable.
2. **Your own game install** — `--game-dir <folder>` (the PUBG root or
   its `TslGame` folder). The tool searches the likely locations
   (`TslGame/Binaries/Win64`, `Engine/Binaries/ThirdParty/Oodle`, …)
   for `oo2core_*` and uses the copy the game itself ships. This is the
   preferred route: nothing third-party is involved.
3. **pyuepak's library (fallback)** — the `pyuepak` pip package provides
   an Oodle core library (downloading it, hash-verified, on first use).
   This is the path the pipeline was developed and tested against.

Nothing Oodle is vendored in this repo, and no route is required if your
paks are uncompressed (these aren't, but the code path exists).

## Usage

```bash
export PUBG_PAK_KEY='…'   # or pass --key to unpack

# 1. Unpack one map's chunk family (~194 entries for Erangel)
pubgtopo unpack pakchunk5500-WindowsNoEditor_heightmap.pak \
                pakchunk5500-WindowsNoEditor_heightmap_0.pak \
                pakchunk5500-WindowsNoEditor_heightmap_1.pak \
                pakchunk5500-WindowsNoEditor_heightmap_2.pak \
                pakchunk5500-WindowsNoEditor_heightmap_3.pak \
  --out extracted/erangel --game-dir "C:\Program Files (x86)\Steam\steamapps\common\PUBG\TslGame"

# Identify an unknown chunk family without extracting (prints the mount point)
pubgtopo unpack --list pakchunk5400-WindowsNoEditor_heightmap.pak

# 2. Stitch the terrain tiles into one 16-bit heightmap
pubgtopo stitch extracted/erangel --out erangel_heightmap.npy --png erangel_heightmap.png

# 3a. Full-map topo sheet, with the bundled Erangel place labels + a centre zoom
pubgtopo render erangel_heightmap.npy --out erangel-topo.png \
  --labels erangel --zoom-out erangel-topo-zoom.png

# 3b. A print-ready zoom window: tiered 2 m contours + micro-relief
#     (farmland south of Pochinki, x 2.8–4.8 km, y 3.0–4.6 km)
pubgtopo render erangel_heightmap.npy --out pochinki-fine.png \
  --extent 2.8,4.8,3.0,4.6 --fine --micro-relief

# 3c. Topo drawn over the official map art
pubgtopo artblend erangel_heightmap.npy \
  --art Erangel_Main_No_Text_High_Res.png --out erangel-blend.png --labels erangel

# 4. Contour linework as vector data for an interactive viewer
#    (the website draws these live — crisp at any zoom — over
#    line-free shading tiles)
pubgtopo vectors erangel_heightmap.npy --out erangel.bin.gz
```

Render options worth knowing: `--span-km` (landscape size; 8.16 for
Erangel), `--grid` (full-map render resolution, default 2048),
`--extent x0,x1,y0,y1` (full-resolution km window), `--labels <pois.json>`
(custom label set in the bundled format), `--micro-sigma-m` /
`--micro-clip-m` (micro-relief scale/range), `--z-scale` (landscape Z
scale if a map ever differs from 100).

## Technical findings

The interesting part. Everything below was determined empirically from
the game's own files (October 2026 build) and is implemented in the code.

### Pak format (v4, TslGame flavour)

- Footer found by scanning the tail for magic `E1 12 6F 5A`: version,
  index offset/size, and a 20-byte IndexHash. The index is
  **AES-256-ECB**; `SHA1(decrypted index) == IndexHash` is verified on
  every run.
- A compressed entry's index record is **57 + 16×nblocks bytes** after
  the filename (offset/size/usize, method, hash, block array of absolute
  offsets, encrypted flag, block size of 65536). (An early "fixed
  53-byte stride" theory was wrong — it only holds for uncompressed
  entries.)
- The entry hash is the **SHA1 of the stored (compressed) block bytes**,
  not of the decompressed content. Assuming the latter makes all 194
  Erangel entries look corrupt; with the right definition they verify
  194/194, as do the extracted sizes.
- **Compression method 16 = Oodle** in TslGame's own method registry.
  This is why stock tools fail on these paks: repak panics
  ("compression list len 3, index 15") and pyuepak's parser only knows
  methods 0–3. pubgtopo parses the pak itself and uses an Oodle library
  only for decompression. No Erangel entry had the per-entry encryption
  flag set.

### Heightmap textures: PF_G16, and the offset fix-up

- **Older guides are out of date.** They describe 512×512×32-bit tiles
  with elevation packed in bytes 2–3. The current build stores a
  dedicated **`PF_G16`** texture per landscape component: mip 0 is
  512×512 little-endian uint16, plain row-major.
- Erangel's landscape is a 16×16 grid of components (256 total), shipped
  as 64 packages of 4 components each (a 2×2 block per package).
- **The fix-up that cost hours:** bulk payloads are *not* at the
  `OffsetInFile` in their headers. The bulk flags (0x501) lack
  `BULKDATA_NoOffsetFixUp`, so the real position is
  `OffsetInFile + BulkDataStartOffset`, a per-package i64 in the .umap
  summary (byte offset 169 in this build's layout) equal to
  `TotalHeaderSize + <uexp size> − 4`. Reading at the raw offset lands
  121–193 KB too early, inside neighbouring payloads, and produces
  plausible-looking garbage. With the fix-up, the last payload of every
  package ends exactly at its .ubulk's EOF, and the stitched map
  correlates with an independent community heightmap at **r = 0.99992**
  (land/sea masks agree on 99.4% of pixels).

### Calibration: the engine constant, not a fit

- Every package's landscape proxy root carries
  `RelativeScale3D = (100, 100, 100)` and Z location 0, so Unreal's
  standard landscape decode is exact:

  ```
  elevation_m = (raw − 32767.5) × 512 / 65535      (≈128 counts/m)
  ```

- Evidence it is right: the Military Base plateau — 153,731 flat
  pixels — sits at raw exactly 32768, i.e. **0.00 m**; shoreline pixels
  straddle zero (median +0.04 m land-side, −0.06 m sea-side); the deep
  sea floor medians at −53.1 m. Erangel's range is **−81.5 m to
  +248.2 m; Stalber is 247.1 m.**
- Cautionary tale: the widely circulated mortar-tool calibration
  ((R−127)×2.08 on an 8-bit copy) is a ranging fit, not a terrain
  measurement — its slope is 3.5% off and it puts Stalber ~10 m too
  high. If a number didn't come from the landscape data, distrust it.
- XY for the record: 8192 samples over an 8160 m span (~0.996 m/px),
  matching PUBG telemetry's 816000 cm Erangel extent.

### Labels and art alignment

- The official art's pixel space is the heightmap grid
  (pixel = world_cm / 816000 × 8192): the best-fit transform is identity
  (land-mask agreement 97.0%; nearly all disagreement is the art's
  painted sand apron around coastlines, not misalignment).
- The bundled Erangel POI anchors were measured **from the printed
  labels on the official with-text art** and then verified against the
  terrain (Stalber's anchor sits at 239.5 m with the summit 83 px away;
  the Military Base anchor is on the 0.00 m plateau; all 27 check out).
  A popular community POI dataset was tried first and rejected — its
  hand-placed points are off by up to ~1.1 km.

### Vector linework for interactive viewers

- Raster tiles cap out at their native resolution: zoom past it and
  the contour lines stretch and blur — exactly where players zoom.
  The website therefore keeps only the soft parts (hillshade, tint,
  micro-relief) as tiles and draws **all linework and text live**
  from vector data (`pubgtopo vectors`, format spec in
  `pubgtopo/vectors.py`). Lines stay screen-crisp at any zoom, and
  stripping them from the tiles also shrank the site by ~30 MB.
- Segments must be read from `QuadContourSet.allsegs`.
  `Path.to_polygons()` applies the path's simplification and
  silently decimates — a 6,594-point contour came back with 18
  points, which only becomes visible when you actually draw it.
- Chunked tracing (needed for memory at 8192²) must share edge
  rows/columns between chunks: both sides then interpolate a seam
  crossing to the same point and the segments meet exactly.

## Design notes

- **Why 10 m by default:** Erangel's total relief is 248 m. At 20 m the
  lowlands go blank; at 5 m everywhere, the hills turn to noise. 10 m
  with labelled 50 m index contours is the readable whole-map choice.
- **Why fine contours exist:** competitive play turns on 2–5 m features
  — a dip deep enough to move through prone, a rise that breaks a
  sightline. They are invisible at 10 m (see the Pochinki bowl above)
  but a uniform 2 m interval wrecks the full map. The resolution is
  scale: **the contour interval belongs to the zoom level** — 10 m for
  the island, tiered 2 m inside a window. On an interactive map this
  happens automatically as you zoom; for print, render the window.
- **Micro-relief** is elevation minus a smoothed copy of itself
  (40 m smoothing scale, ±5 m range): it ignores absolute height, so a
  3 m bowl at 30 m elevation pops as clearly as one at 100 m. Of the
  three treatments it is the single best dip-spotter.
- **Art overlay balance:** lines can be strong (they cover ~nothing);
  fills must be faint (they cover everything). So: art at 0.72
  saturation, hillshade ghosted at 0.28, tint at 0.10, contours dark
  umber over a thin white underlay, the art's own water untouched. A
  half-and-half blend of two full-strength colour systems — the obvious
  first attempt — makes both layers unreadable.
- **Water** is drawn only where z < 0 *and* connected to the map edge,
  so interior depressions and river bottoms stay land — and the
  exactly-0.00 m Military Base plateau doesn't speckle.

## Map support

- **Erangel: complete and verified** end-to-end (unpack → stitch →
  calibrated render → labels → art overlay).
- **Miramar: verified end-to-end** (unpack → stitch → calibrated
  render; no bundled labels). 256/256 components stitched; against an
  independent reference heightmap the stitch correlates at
  r = 0.99998 with 99.76% land/sea agreement, and the engine
  calibration needed no per-map adjustment. Calibrated range −90.4 m
  to +256.0 m. Caveat: Miramar's *source* height data saturates at
  the top (1.23% of pixels at the maximum value), so its highest
  plateaus are flat-topped in the game data itself — true peak is
  ≥ ~253 m; the sheet tops out at 256.0 m.
- **Taego: verified end-to-end** (unpack → stitch → calibrated
  render; no bundled labels). 256/256 components; correlation
  r = 0.99996 against the reference, land/sea agreement 98.26% —
  every disagreeing pixel sits within ±3 m of sea level (Taego's
  shallow west-coast flats). Calibrated range −222.3 m to +181.1 m;
  no saturation. Note the surrounding sea is genuinely deep here.
- **Rondo: verified end-to-end** (unpack → stitch → calibrated
  render; no bundled labels). 256/256 components; correlation
  r = 0.99907 against the current community reference (r = 0.99959
  against its older revision — the two references disagree with
  each other at the same scale, so the residual is reference build
  drift, not stitch error; the pipeline's own SHA1/coverage checks
  pass independently). Land/sea agreement 98.54%. Calibrated range
  −32.6 m to +244.6 m; no saturation. Rondo is mostly land (0.926)
  with only a shallow sea skirt.
- Together these four are the full current PGS/PGC competitive map
  pool, and the single engine calibration constant held on all four
  with no per-map adjustment.
- Other maps: `unpack` is generic pak v4 and their chunk families are
  identified above; `stitch` expects the same Heightmap package layout
  and has not been run on the rest yet. Expect it to work; verify before
  trusting (the stitcher refuses to emit a map with missing components).
- Game updates can change any of this (pak version, texture format,
  offsets). The verification built into each stage — index SHA1, entry
  SHA1/size, component coverage — is there to fail loudly when they do.

## Repo rules

These are standing rules of the project, not suggestions:

1. **The README is updated in the same change as any code or process
   change.** No exceptions. Every change also adds a Changelog entry.
2. **Code only.** No game data (paks, extracted files, heightmaps), no
   official art, no AES key is ever committed. `.gitignore` enforces
   this; if you force-add around it, you're breaking the project.
3. **Oodle is never vendored** — it is loaded from the user's install,
   an explicit path, or pyuepak (see "Oodle").

## Authors & credits

Designed and built by **Joel Jensen** in collaboration with **Pip**
(an AI assistant, Muse). Joel directed the project, supplied the game
data from his own install, and made the product calls; Pip wrote the
extraction/rendering pipeline and the format research behind it.

Thanks to the communities whose public work this builds on: Gildor's
UE Viewer forums, the cs.rin.ru UE4 key list, the QuickBMS script, the
pubg/api-assets maintainers, and pyuepak.

## Changelog

### v0.4.1 — 2026-11-02

- `water_mask` takes a `level=` argument (default 0.0, the true
  waterline; `artblend._composite` passes it through). The website
  builds with level −0.5 m: PUBG's shoreline aprons hover within
  ±0.5 m of zero (one Erangel transect sits at −0.0…−0.1 m for
  80 m), so the literal 0 line paints dry beach as blue inlets.
  Scored against the official art's coastline (the align-check
  classifier, ±50 m coastal band): the 0 line paints 1,069k m² of
  art-land as water; −0.5 m cuts that to 675k m² while adding
  48k m² of false land, all of it the ankle-deep 0…−0.5 m fringe —
  roughly 8 m² of false water removed per 1 m² of false land
  added. A width-based cleanup (morphological opening at 0) was
  tested and rejected: the apron channels are 20–30 m wide
  swales, not hairlines.

### v0.4.0 — 2026-11-02

- Two new hypsometric ramps in `pubgtopo.render`, for viewers that
  treat height colour as its own toggleable layer (the website does,
  from its ?v=18): `VIVID_STOPS` — a topographic-map.com-style ramp
  weighted hard into the low range (yellow by ~25 m, orange by
  ~90 m on the fixed 0–250 m scale), because PUBG's low-relief maps
  leave most land in the first colour of an even spread; and
  `SAND_STOPS` — an atlas sand→tan→rust ramp whose hues sit inside
  the official art's colour family. `_base_rgb` and
  `artblend._composite` take a `stops=` argument (default: the
  classic ramp, unchanged), and art blends for the website now pass
  `SAND_STOPS` so the tint reinforces the art instead of washing
  over it.
- New `pubgtopo.render._relief_rgb`: hillshade only on a warm paper
  tone, water in the same flat `WATER_RGB` — the "height colour
  off" base that pairs with the tinted base in the viewer.

### v0.3.0 — 2026-11-01

- New `vectors` stage: contour linework extracted as geometry for
  interactive viewers, which draw the lines live at screen
  resolution instead of stretching raster tiles. Traced from the
  full-res heightmap in seam-sharing chunks (segments meet exactly
  at chunk edges), read from `QuadContourSet.allsegs` —
  `Path.to_polygons()` silently decimates and must not be used —
  Douglas-Peucker simplified at 0.35 m, and packed into the PTV1
  binary format (master-pixel frame quantised ×8, ~0.25 m;
  gzipped). Output for the four competitive maps: Erangel 1.3 MB,
  Miramar 4.2 MB, Taego 1.9 MB, Rondo 2.5 MB. The website
  (withfinesse/pubg-topo-site) rebuilt its sheets line-free and
  draws all contours and labels from this data.

### v0.2.0 — 2026-11-01

- Taego and Rondo verified end-to-end with the packaged pipeline
  (chunks 5900 / 6300), completing the current PGS/PGC competitive
  map pool: Taego 196 entries, Rondo 296 entries, zero verification
  failures; 256/256 components stitched for both; correlations
  r = 0.99996 (Taego) and r = 0.99907 (Rondo, reference build
  drift — see Map support); calibrated ranges −222.3…+181.1 m and
  −32.6…+244.6 m. No code changes — verification and documentation
  only.

### v0.1.1 — 2026-11-01

- Miramar verified end-to-end with the packaged pipeline (chunk
  5100): 326 entries unpacked with zero verification failures,
  256/256 components stitched, full-res correlation r = 0.99998 and
  99.76% land/sea agreement against an independent reference
  heightmap, calibrated range −90.4 m to +256.0 m. The calibration
  is confirmed generic — no per-map adjustment needed.
- Documented Miramar's source-data saturation at the top of its
  range (see Map support). No code changes — verification and
  documentation only.

### v0.1.0 — 2026-11-01

- Initial public consolidation of the research pipeline into the
  `pubgtopo` package: `unpack` (pak v4 + AES index + Oodle, key from
  env/flag, Oodle from install/explicit path/pyuepak), `stitch`
  (PF_G16 tiles + BulkDataStartOffset fix-up), `render` (engine
  calibration, 10 m / tiered 2 m contours, micro-relief, labels) and
  `artblend` stages.
- Erangel verified end-to-end; bundled Erangel POI set measured from
  the official map art.
- This README, including the format findings (pak record layout,
  stored-bytes entry hash, method 16 = Oodle, PF_G16, the offset
  fix-up, landscape calibration) and the chunk→map table.

## License

MIT — see [LICENSE](LICENSE).
