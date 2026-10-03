"""Interactive commands, split by area (this module re-exports them, so old imports keep working):

    cmd_base     Panel, NumBox, right-click helper, dialog footer, regions_for
    sketch_cmds  Sketch mode (tools, palette, trim, Rotate / Mirror / Pattern, plane pick)
    solid_cmds   Extrude, Revolve, edge Fillet / Chamfer
    cam_cmds     CAM setups, operations, toolpaths, Simulate
    cam_dialogs  Tool Library and Post Process dialogs

Each session receives mouse events from the Viewport (`on_move`, `on_click`) and keys
from the main window (`on_key`). They edit the Document only when committed.
"""
from .cmd_base import *       # noqa: F401,F403
from .sketch_cmds import *    # noqa: F401,F403
from .solid_cmds import *     # noqa: F401,F403
from .cam_cmds import *       # noqa: F401,F403
from .cam_dialogs import *    # noqa: F401,F403
