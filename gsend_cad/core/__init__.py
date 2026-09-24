"""Pure-Python CAD data model: sketch entities, profiles, features, timeline.

No third-party imports here, so G-SEND.IO (CAM side, translator, EXE build) can read and
write CAD documents without pulling in Qt or OpenCascade.
"""
from . import sketch
from .document import DENSITY, FORMAT, UNITS, Document, bracket_plate
from .profiles import Region, region_at, resolve, sketch_regions

__all__ = ["sketch", "Document", "bracket_plate", "DENSITY", "FORMAT", "UNITS",
           "Region", "region_at", "resolve", "sketch_regions"]
