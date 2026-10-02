"""G-code import (lathe): rebuild part geometry from an existing program.

A self-contained module. Nothing else in gsend_cad imports from here; the app loads it
with one guarded call (register), so if this package breaks or is deleted the app still
starts - it just has no File > Import G-code... entry.

    parser.py   lathe G-code -> one canonical list of moves   (stdlib only)
    detect.py   lathe / mill tells                              (stdlib only)
    stock.py    stock + Z0 guesses for the Setup screen         (stdlib only)
    keywords.py comment keywords: table, JSON, matching         (stdlib only)
    inserts.py  insert codes (ANSI / ISO) and sizes in comments (stdlib only)
    tooling.py  the tool list: READ / GUESSED / UNKNOWN / DEFINED (stdlib only)
    wizard.py, tools_page.py, keywords_page.py, widgets.py    the import window
                                                (Qt; imported only by register)

The stdlib half never imports Qt, so G-SEND.IO's CAM side can use it headless.
"""
from __future__ import annotations

from .detect import Detection, Tell, detect_machine
from .parser import CMove, Flag, Program, parse_program
from .stock import StockGuess, guess_stock, stock_z_range

__all__ = ["parse_program", "Program", "CMove", "Flag", "detect_machine", "Detection", "Tell",
           "guess_stock", "StockGuess", "stock_z_range", "register"]


def register(win) -> None:
    """Add File > Import G-code... to the main window. The only hook the host calls."""
    from .wizard import register as _register      # Qt is imported here, not at package import
    _register(win)
