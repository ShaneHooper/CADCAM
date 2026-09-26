# G00 CAM (package `gsend_cad`): the G-SEND.IO CAD/CAM module

**G00 CAM** is the working name. It's set once in `gsend_cad/__init__.py` (`APP_NAME`), and
the logo is the G00 logo from the G-SEND.IO repo (`ui/assets/g00code_logo.png` / `.ico`).

This is the real app that the HTML prototype in `prototypes/gsend-cad/` was sketching out.
It keeps the same look (dark industrial, blue accent, same layout and icons) and the same
sketch-entity data model, and it has a real B-rep kernel (OpenCascade via build123d).

## Try it (Windows)

1. Install **Python 3.12** from python.org and tick "Add python.exe to PATH". Any version
   from 3.10 to 3.13 works; build123d has no 3.14 build yet.
2. Get this branch (`claude/new-session-sgzhb7`) onto your PC: `git clone`, or download the ZIP
   from GitHub.
3. Double-click **`G00CAM.bat`**. The first run sets up a private `.venv` folder, which takes
   a few minutes and downloads about 1 GB (Qt, VTK, OpenCascade). After that it opens
   straight away. Drag a `.gcad` file onto it to open that file.

By hand, on any OS:

```
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on Linux/macOS)
pip install -e .[ui,dev]
g00cam                             # or: python -m gsend_cad [part.gcad]
```

On Linux, Qt also needs the system GL/xcb libraries (`libegl1 libgl1 libxkbcommon0
libxcb-cursor0 ...`).

## What works

- **Layout like the prototype:** top bar, ribbon (Solid / Surface / Utilities, plus
  Sketch while sketching), browser tree with properties, 3D viewport, status bar, timeline.
- **Viewport:** Z-up, left drag orbits, right drag pans, wheel zooms. View cube, nav bar,
  and display modes (shaded + edges / shaded / wireframe). The 0.25 in grid has 1 in
  major lines. Only sharp B-rep edges are drawn: seam and tangent edges are hidden.
- **Sketch (L):** Line (chains until Esc), Rectangle, Center Rect, Circle and Polygon, with
  grid snap. The snap size is set in the palette, and Shift gives 1/4 steps. A live
  dimension tag follows the cursor. The sketch plane is XY at any Z height (Plane field in
  the palette). Ctrl+Z undoes, × in the palette list deletes one shape, Enter finishes,
  Cancel discards.
- **Edit Sketch:** right-click (or double-click) a sketch in the timeline or browser. Add or
  delete shapes, or change its plane; Finish rebuilds the extrudes made from it
  (`Document.update_sketch` remaps their profile references; one that used a deleted
  shape turns red).
- **Hide / Show Sketch:** the browser's eye dot, or right-click in the timeline/browser.
  Stored as `"show"` on the sketch feature; hidden sketches can't be picked by Extrude.
- **Extrude (E):** click closed profiles (rect, circle, polygon, closed line chains; loops
  inside other loops become holes). Direction is One side or Symmetric; a negative
  distance flips it. Operation is Join, Cut or New Body. The preview is the real
  OpenCascade tool body, drawn blue, or red for Cut.
- **Timeline:** click a feature to roll back to it; start/back/play/forward/end buttons.
  Right-click to roll or delete. A feature that fails turns red with the reason in its
  tooltip, and the rest of the model still builds.
- **Undo/redo** (Ctrl+Z / Ctrl+Y) of timeline edits. **Save/open** `.gcad` (JSON) with
  Ctrl+S / Ctrl+O.
- **Export:** Utilities → Export writes STEP, and 3D Print writes STL.
- **Properties:** exact volume, bounding box and mass (6061-T6 by default) from the B-rep.
- **Rename / Delete:** right-click a sketch or body in the browser (or F2 / Delete). Deleting
  a sketch offers to delete the extrudes made from it; deleting a body adds a `remove`
  feature (roll back to see it again). Body names live in `Document.body_names`.
- **Help → Documentation (F1):** how to sketch, edit and hide sketches, and extrude
  (`gsend_cad/ui/docs.py`).

Hole, Fillet, Chamfer and the rest of the ribbon show "not in this build yet".

## Layers (built to drop into G-SEND.IO)

| Package | Depends on | Use it for |
|---|---|---|
| `gsend_cad.core` | nothing (stdlib) | Sketch entities, profile detection, features, the `Document` timeline, `.gcad` read/write. Safe to import anywhere in G-SEND.IO, including the CAM side and the EXE. |
| `gsend_cad.kernel` | build123d, numpy | `Kernel().build(doc)` gives solids with volume, bbox and mass, plus STEP export. Runs headless: this is what the CAM/toolpath side would call to get real geometry. |
| `gsend_cad.ui` | PySide6, pyvista, pyvistaqt | The window. `gsend_cad.launch(doc_or_path, block=None)` returns the `MainWindow`. `MainWindow.document_changed` fires on every edit. |

### Hooking into G-SEND.IO

- **G-SEND.IO's UI is Tkinter** (the simulators are). A Qt window can't be embedded
  inside a Tk window, so open CAD as its own window in its own process:
  `subprocess.Popen([sys.executable, "-m", "gsend_cad", path])`. In the frozen EXE, add a
  `--cad` switch that calls `gsend_cad.ui.main()`. The two sides share `.gcad` and
  `.step` files. The CAM side reads them with `gsend_cad.core` / `gsend_cad.kernel`, and
  neither of those needs Qt.
- **If G-SEND.IO moves to Qt later,** call `gsend_cad.launch(doc, block=False)` from inside
  its running `QApplication`, or take `MainWindow` apart and dock the viewport, browser
  and timeline into its own windows.
- **The document format** (`gsend-cad/1`) is plain JSON. Features store sketch entities
  and profile references (`{sketch, outer:[entIdx], holes:[[entIdx]]}`) exactly like the
  HTML prototype.
- **Packaging:** build123d (OCP/OpenCascade) and VTK are large, adding a few hundred MB to a
  PyInstaller build. Keep CAD in the optional `[ui]` extra so a CAM-only build can leave
  it out.

## Fonts

The prototype uses Rajdhani, Share Tech Mono, Squada One and Anton (Google Fonts, OFL).
Anton and Squada One are included in `ui/fonts/`, copied from the G-SEND.IO repo with
their licenses. To match the prototype exactly, add `Rajdhani-*.ttf` and
`ShareTechMono-Regular.ttf` there too. Until then the app falls back to Bahnschrift / Consolas
on Windows.

## Screenshots

`screenshots/` holds the main view, a Cut preview, and the part after three extrudes, taken from `tests/drive_ui.py`.

## Tests

```
pytest                                                   # core + kernel
xvfb-run -a python tests/drive_ui.py OUTDIR              # drives the real window, saves screenshots
```
