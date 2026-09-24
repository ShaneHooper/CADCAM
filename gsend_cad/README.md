# gsend_cad: the G-SEND.IO CAD module (Python)

This is the real app that the HTML prototype in `prototypes/gsend-cad/` was sketching out.
It keeps the same look (dark industrial, blue accent, same layout, fonts and icons) and the
same sketch-entity data model, and it has a real B-rep kernel (OpenCascade via build123d).

## Run it

```
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on Linux/macOS)
pip install -e .[ui,dev]
python -m gsend_cad                # opens the demo Bracket Plate
python -m gsend_cad part.gcad      # opens a saved document
```

On Linux, Qt also needs the system GL/xcb libraries (`libegl1 libgl1 libxkbcommon0
libxcb-cursor0 ...`). Windows needs nothing extra.

## What works

- **Layout like the prototype:** top bar, ribbon (Solid / Surface / Utilities, plus
  Sketch while sketching), browser tree with properties, 3D viewport, status bar, timeline.
- **Viewport:** Z-up, left drag orbits, right drag pans, wheel zooms. View cube, nav bar,
  and display modes (shaded + edges / shaded / wireframe). The 0.25 in grid has 1 in
  major lines. Only sharp B-rep edges are drawn: seam and tangent edges are hidden.
- **Sketch (L):** Line (chains until Esc), Rectangle, Center Rect, Circle and Polygon, with
  grid snap. The snap size is set in the palette, and Shift gives 1/4 steps. A live
  dimension tag follows the cursor. The sketch plane is XY at any Z height (Plane field in
  the palette). Ctrl+Z undoes, Enter finishes.
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
Put their `.ttf` files in `gsend_cad/ui/fonts/` and the app loads them. Without them it
falls back to Bahnschrift / Consolas on Windows.

## Screenshots

`screenshots/` holds the main view, a Cut preview, and the part after three extrudes, taken from `tests/drive_ui.py`.

## Tests

```
pytest                                                   # core + kernel
xvfb-run -a python tests/drive_ui.py OUTDIR              # drives the real window, saves screenshots
```
