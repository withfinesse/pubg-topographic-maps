"""pubgtopo — build topographic maps from your own PUBG install.

Pipeline: unpack (pak -> files) -> stitch (files -> 16-bit heightmap)
-> render (heightmap -> topographic PNG). See README.md for the full
story, including the format research this is based on.

Designed and built by Joel Jensen in collaboration with Pip, an AI
assistant (Muse).
"""

__version__ = "0.1.1"
