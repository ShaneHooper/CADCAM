# HANDOVER — G-SEND CAD prototype

**To the new session:** this folder holds a working prototype I like. **Do not start over, and do not redesign it.** Continue from `gsend_cad_prototype.html` exactly as it is, and change only what I ask for. The screenshots in `screenshots/` show the look I approved. Anything you build next must keep that look.

I'm Shane, owner and lead developer of G-SEND.IO, a Python 3 CNC machining app packaged as a Windows EXE. I'm a CNC programmer, not a software engineer by background. I work direct and task-first, often by voice. I prefer durable fixes over workarounds.

---

## What's in this folder

| File | What it is |
|---|---|
| `gsend_cad_prototype.html` | **The prototype. This is the source of truth.** Everything is in one file (~1,800 lines, ~680 KB). |
| `screenshots/01_main_view.png` | Main view: the approved layout and blue theme |
| `screenshots/02_sketch_mode.png` | Sketch mode in use (circle tool, palette, live dimension readout) |
| `screenshots/03_sketch_finished.png` | After Finish Sketch: Sketch3 in the timeline and browser, drawn over the solid |
| `HANDOVER.md` | This file |

**First thing to do:** open the screenshots and read the HTML. If this folder isn't in the repo yet, put it at `prototypes/gsend-cad/` on a new branch. Never commit to `main` directly.

The file has no `<html>/<head>/<body>` tags because it was published as a claude.ai artifact, which adds that wrapper. To open it in a browser locally, wrap it in `<!doctype html><html><head><meta charset="utf-8"></head><body> … </body></html>`, or just open it as-is (browsers tolerate it).

---

## What the prototype is

A Fusion 360-style CAD UI shell, branded G-SEND.IO. It's HTML for now; the real product will be Python 3.

- **Top bar:** G-SEND.IO wordmark (blue square Squada One "G" + Anton "-SEND.IO", then "CAD"), save/undo/redo, document tab "Bracket Plate v3", units pill set to inches, user name.
- **Ribbon:** a DESIGN workspace dropdown, then Solid / Surface / Utilities tabs (Mesh, Sheet Metal and Plastic were removed at Shane's request; don't add them back). Each tab has tool groups (Create, Modify, Assemble, Construct, Inspect, Insert, Select). Tools open a mock command dialog with realistic inch values. Shortcuts: E extrude, H hole, F fillet, L sketch, I measure.
- **Browser tree (left):** Origin (XY/XZ/YZ), Bodies, Sketches, with visibility dots. Below it is a properties panel: bounding box, volume, and mass in 6061-T6.
- **3D viewport (Three.js, Z-up like Fusion):** a 4 × 3 × 0.5 in plate with 0.25 corner radii, a Ø1.25 × 0.75 boss, 4× Ø0.266 thru holes, and a Ø0.5 bore. Orbit (left drag), pan (right drag), zoom (wheel). There's a view cube (TOP/FRT/L/R/isos/home), a nav bar (orbit, look, pan, zoom, fit, display mode), a 0.25 in grid with a 1 in major grid, a HUD, and a live cursor XY readout in the status bar.
- **Timeline (bottom):** Sketch1, Extrude1, Sketch2, Extrude2, Hole1, Hole2. Clicking a feature, or using start/back/play/forward/end, rolls the model and the browser back and forth.
- **Sketch mode (working):** click Sketch or press L. The view snaps to TOP, orbit locks, and a SKETCH ribbon tab appears with Line, Rectangle, Center Rect, Circle, Polygon, Undo, Clear, Measure, and Finish Sketch.
  - Snaps to the grid, 0.250 by default. The size is selectable in the Sketch Palette; Shift gives 1/4 steps.
  - A live dimension tag follows the cursor: length, angle, ΔX/ΔY, diameter, or size.
  - Line chains until Esc. Ctrl+Z undoes. Enter or Finish Sketch commits.
  - The finished sketch becomes SketchN in the timeline and browser, rolls back like other features, and draws on top of the solid (depthTest off).
- **Sketch entities are plain data**, deliberately, so they port straight to Python:
  ```
  {type:'line',    pts:[[x,y],[x,y]]}
  {type:'circle',  c:[x,y], r:R}
  {type:'rect',    pts:[[x,y]×4]}            // closed loop
  {type:'polygon', pts:[[x,y]×n], r:R}       // closed loop
  ```
  They're stored on the timeline feature as `FEATURES[i].ents`.

## Where things are in the HTML (line numbers approximate)

- Lines 1–150: CSS. Tokens are on `:root` (`--accent`, `--accent-dim`, fonts), then TOP BAR, RIBBON, BROWSER, VIEWPORT, SKETCH MODE, STATUS, TIMELINE.
- Lines 150–320: HTML layout (`#stage > #app` grid).
- Lines ~320–1325: **inlined Three.js r128 + OrbitControls. Leave this block alone.**
- Line ~1330 onward, the app script, with section comments to search for:
  `icons` · `sketch state` · `ribbon` (the `RIBBON` object defines every tab and tool) · `dialog` (the `DIALOGS` object) · `three.js scene` (part params in `P`, and `plateShape`/`mkPlate`/`mkBoss`) · `timeline` (the `FEATURES` array, `applyTimeline`) · `browser tree` · `views` (`fitStage` scaling) · `SKETCH ENGINE` (`SK` state, `buildEntity`, `enterSketch`, `finishSketch`) · keyboard shortcuts.

## Decisions to keep

1. **The layout is a fixed 1400 × 820 design frame, scaled as one unit** to fit any window (`#stage`/`#app` + `fitStage()`). That's why it looks identical on my phone, in narrow panels, and on a big monitor. Don't switch to a responsive layout that reflows. An earlier version did, and it broke the look.
2. **Three.js and OrbitControls are inlined, not loaded from a CDN.** OrbitControls isn't on cdnjs. When it came from the CDN, the script crashed after the ribbon, and the tree, viewport, and timeline never rendered.
3. **Theme:** dark industrial CNC. `#0a0a0a` background, `#111` panels, 1px borders, flat (no gradients or shadows), Rajdhani headers, Share Tech Mono body, uppercase letter-spaced labels.
4. **The accent is BLUE, `#2f9bff`, with dim `#0c3457`.** It's a placeholder until I give the exact G-SEND blue. Changing it means editing `--accent`/`--accent-dim` in the CSS, the `0x2f9bff` values in the JS, and the selection emissive `0x0a2a4a`. Don't reintroduce orange.
5. **Units are inches.** It's aimed at machined parts: plates, bosses, holes, shafts.
6. **The stock part is still hard-coded** (Sketch1 to Hole2). Extrude is the one real command; the other dialogs (Hole, Fillet, etc.) are still mock and their OK does nothing.

## Extrude (done)

Press E (or the Extrude tool) after finishing a sketch. Closed profiles are found in each user sketch (rect, circle, polygon, and line chains that close on themselves); a loop inside another becomes a hole, so each click picks a region, like Fusion. Click regions to select or deselect them. The dialog has Direction (One side / Symmetric), Distance (negative flips it), and Operation (Join / Cut / New Body) with a live preview (blue, or red for Cut). OK adds ExtrudeN to the timeline; it rolls back like the others, and the sketch it used hides. Join and Cut are real booleans: a small BSP CSG engine is inlined (section `SOLID ENGINE`), and edges on boolean results come from `featureEdges`. Cut hits every body it reaches. The volume and mass in the properties panel update. The feature stores plain data for the Python port: `{op, distance, direction, profiles:[{sketch, outer:[entIdx], holes:[[entIdx]]}]}`.

Known limits: sketches are on the XY plane at Z 0 only; overlapping profiles that cross each other are not split into regions; a line chain with a branch (a vertex joining 3 or more lines) is not detected as a loop.

## Next steps (ask me which one first)

1. ~~**Extrude a user sketch in the HTML prototype.**~~ Done, see above. Detect closed profiles (rect, circle, polygon, and closed line chains), let me pick one, build it with `THREE.ExtrudeGeometry` (distance, Join/Cut/New Body), and add an ExtrudeN feature to the timeline that rolls back like the others. Show the Extrude dialog with a live preview.
2. ~~**Start the real Python 3 app.**~~ Started: see `gsend_cad/README.md`. It has sketch, extrude (Join/Cut/New Body on a real OpenCascade kernel), timeline rollback, undo, save/open, and STEP/STL export, in the same look. What follows is the original plan. Recommended stack:
   - **build123d** (OpenCascade kernel) for sketch → extrude → booleans → fillet/chamfer → STEP export
   - **PySide6 / Qt** for the ribbon, browser tree, timeline, and dockable panels
   - **pyvista or vedo** (VTK) viewport embedded in Qt. Tkinter can't do shaded B-rep with orbit.

   Match the prototype's look (same layout, fonts, blue accent) and reuse the same sketch-entity data model. The HTML stays as the visual spec.
3. **Wire it into G-SEND.IO** so CAD features feed the existing CAM, translator, and toolpath side.

## How to check work before showing me

Render the page in headless Chromium and look at it before telling me it's done: Playwright, `--use-gl=swiftshader`, 1400 × 820 viewport, plus a phone-size check at 412 × 915. Confirm there are no page errors, and that the tree, 3D part, and timeline all render. Compare against the screenshots in this folder.

## Rules for this repo

- Work on a branch. Never commit to or push to `main`.
- If `main` moves, merge main into your branch. No rebase.
- Only change what I ask for. Keep the look.
