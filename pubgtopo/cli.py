"""pubgtopo command line: unpack -> stitch -> render (+ artblend)."""

import argparse
import os

from . import __version__


def _extent(value):
    try:
        parts = tuple(float(v) for v in value.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(
            "extent must be four comma-separated numbers: x0,x1,y0,y1")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "extent must be four comma-separated numbers: x0,x1,y0,y1")
    return parts


def build_parser():
    p = argparse.ArgumentParser(
        prog="pubgtopo",
        description="Build topographic maps from your own PUBG install: "
                    "unpack the heightmap paks, stitch the terrain tiles "
                    "into a 16-bit heightmap, render a topographic map.")
    p.add_argument("--version", action="version",
                   version=f"pubgtopo {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    u = sub.add_parser("unpack", help="extract entries from pak files "
                                      "(--list just lists them)")
    u.add_argument("paks", nargs="+", help="pak files to read")
    u.add_argument("--out", help="output directory (required unless --list)")
    u.add_argument("--key", help="pak AES key (else PUBG_PAK_KEY env var)")
    u.add_argument("--oodle-lib", help="path to an Oodle core library "
                                       "(oo2core_*); else PUBG_OODLE_LIB "
                                       "env var, then --game-dir search, "
                                       "then pyuepak's bundled library")
    u.add_argument("--game-dir", help="your PUBG install folder (or its "
                                      "TslGame folder) — searched for the "
                                      "Oodle core library")
    u.add_argument("--list", action="store_true",
                   help="print the mount point and entries, extract nothing "
                        "(the mount point names the map — handy for "
                        "identifying unknown chunk families)")

    s = sub.add_parser("stitch", help="assemble extracted Heightmap "
                                      "packages into a 16-bit heightmap")
    s.add_argument("indir", help="directory with the extracted packages")
    s.add_argument("--out", required=True, help="output .npy path")
    s.add_argument("--png", help="also write a 16-bit PNG copy")

    r = sub.add_parser("render", help="render a topographic PNG from a "
                                      "16-bit heightmap")
    r.add_argument("heightmap", help="heightmap .npy (or 16-bit PNG)")
    r.add_argument("--out", required=True, help="output PNG path")
    r.add_argument("--span-km", type=float, default=8.16,
                   help="landscape span in km (default 8.16, Erangel)")
    r.add_argument("--grid", type=int, default=2048,
                   help="full-map render grid size (default 2048)")
    r.add_argument("--extent", type=_extent, metavar="X0,X1,Y0,Y1",
                   help="render this km window at full resolution instead "
                        "of the whole map")
    r.add_argument("--zoom-out", help="also render a centre-quarter zoom "
                                      "to this path (full-map renders only)")
    r.add_argument("--fine", action="store_true",
                   help="tiered 2 m contours instead of 10 m")
    r.add_argument("--micro-relief", action="store_true",
                   help="blend in the micro-relief layer (local dips/rises)")
    r.add_argument("--micro-sigma-m", type=float, default=40.0,
                   help="micro-relief smoothing scale in metres (default 40)")
    r.add_argument("--micro-clip-m", type=float, default=5.0,
                   help="micro-relief colour range in metres (default +-5)")
    r.add_argument("--labels", metavar="POIS",
                   help="POI JSON path, or 'erangel' for the bundled set")
    r.add_argument("--title", help="figure title")
    r.add_argument("--z-scale", type=float, default=100.0,
                   help="landscape Z scale percent (default 100)")
    r.add_argument("--dpi", type=int, default=200)

    a = sub.add_parser("artblend", help="render the topo OVER official "
                                        "map art (art must share the "
                                        "heightmap's pixel frame)")
    a.add_argument("heightmap", help="heightmap .npy (or 16-bit PNG)")
    a.add_argument("--art", required=True, help="official map art image")
    a.add_argument("--out", required=True, help="output PNG path")
    a.add_argument("--span-km", type=float, default=8.16)
    a.add_argument("--grid", type=int, default=2048)
    a.add_argument("--extent", type=_extent, metavar="X0,X1,Y0,Y1",
                   help="render this km window at full resolution")
    a.add_argument("--labels", metavar="POIS",
                   help="POI JSON path, or 'erangel' for the bundled set")
    a.add_argument("--title")
    a.add_argument("--z-scale", type=float, default=100.0)
    a.add_argument("--dpi", type=int, default=200)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.command == "unpack":
        from .keys import resolve_key
        from .pak import unpack_paks
        key = resolve_key(args.key)
        if not args.list:
            if not args.out:
                raise SystemExit("--out is required unless --list is given")
            os.makedirs(args.out, exist_ok=True)
        problems = unpack_paks(args.paks, args.out, key,
                               list_only=args.list,
                               oodle_lib=args.oodle_lib,
                               game_dir=args.game_dir)
        return 1 if problems else 0

    if args.command == "stitch":
        from .stitch import save_heightmap, stitch_directory
        canvas = stitch_directory(args.indir)
        save_heightmap(canvas, args.out, args.png)
        return 0

    if args.command == "render":
        from .render import render
        render(args.heightmap, args.out, span_km=args.span_km,
               grid=args.grid, extent=args.extent, zoom_out=args.zoom_out,
               fine=args.fine, micro_relief=args.micro_relief,
               micro_sigma_m=args.micro_sigma_m,
               micro_clip_m=args.micro_clip_m, labels=args.labels,
               title=args.title, z_scale=args.z_scale, dpi=args.dpi)
        return 0

    if args.command == "artblend":
        from .artblend import render_artblend
        render_artblend(args.heightmap, args.art, args.out,
                        span_km=args.span_km, grid=args.grid,
                        extent=args.extent, labels=args.labels,
                        title=args.title, z_scale=args.z_scale, dpi=args.dpi)
        return 0

    return 2
