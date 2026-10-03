# Note for the next session (written 10/3/26 on the work laptop)

Delete this file once you have read it and the open items are dealt with.

## Where everything is
- **Work from `gcode-import-lathe`** (PR #2). It contains everything: the importer, plus all of PR #1's main-app work
  merged in. `git checkout gcode-import-lathe && git pull`.
- **`claude/new-session-sgzhb7`** (PR #1) is the main-app branch. Shane wants main-app changes committed there first,
  then merged into `gcode-import-lathe` (so an exe built from the importer branch has them). That is the routine he
  asks for: "commit it to PR 1 and merge it in".
- **`gcode-import-lathe-p5`** is an old, superseded Phase 5 attempt, pushed only as a backup. Ignore it.
- Both PR descriptions are up to date through the cutter comp / Parallel to Axis / axes work. The sketch orbit (below)
  is NOT in either description yet.

## Rules Shane has given (keep following them)
- **Never sign anything**: no `packaging/sign_folder.py`, no signtool, no Azure.
- Commit / push only when he says so. He says it in chat ("commit it to PR 1 and merge it in", "push everything").
- Keep his exe current when he asks: `python packaging/update_app.py "<folder>"` (code-only; a rebuild is only needed
  when the runtime inputs change). On the work laptop the exe is `C:\Users\Minco\Downloads\G-SEND CADCAM Rev1`.
  `--selftest` needs a report path argument.
- He does not like jargon names for his tools ("Parallel to Axis", not "unbound line").

## Setup on a new machine
Python 3.12, a fresh venv, `pip install` the project's requirements (build123d, PySide6, pyvista(qt), shapely...).
The `.venv`, `build/`, `dist/` and the exe are not in git. Headless checks use `QT_QPA_PLATFORM=offscreen`; the mouse
drives (`tests/drive_sketch_orbit.py`) need a real screen.

## What was done in the last session (all pushed)
- Lathe **cutter comp** (Off / Machine G41-G42-G40 / Computer): `core/nose.py`, Post Process box.
- **Parallel to Axis** sketch tool (Line tool's first click on an axis does it too); typing 0 puts it on the axis.
- Sketch axes thin (1.5 px, 2 in each way); new-file start; sketch grid on the plane; ASSUMED pieces yellow.
- Importer Phase 6 "clean round values"; flip programs; negative-X programs.
- **Last change, in the newest commit:** in a sketch, Shift + left drag or Alt + left drag turns the view (a plain
  left drag still draws / selects; Shift + click without a drag is still a click). Shane said "I can't rotate after I
  draw lines"; I could not reproduce a break, only that left drag never rotated in a sketch and Shift + wheel-button
  drag does. **Ask him whether this fixed what he meant.** Not yet in his installed exe.

## Open items / things not verified by hand
- Shane has not yet run cutter comp, the 0-on-axis fix or the sketch orbit in the real window; they are tested by
  drive scripts only.
- Cutter comp assumes G42 for OD and G41 for ID (Haas convention); his own programs have no G41/G42 to confirm. It
  applies only to the turning Contour, and a G70-cycle Contour is posted line by line when comp is on.
- `tests/drive_fillet_revolve.py`, `drive_sketch_dims.py`, `drive_edit.py`, `drive_sketch_plane.py` fail (the first
  three failed before these changes too; `drive_sketch_plane` needs a DISPLAY). Not investigated.
- PR descriptions: add the sketch orbit; the PR #2 test list / count (239) is stale.
- Importer Phase 6 options he has not picked: dimension table, edit-with-neighbours-follow, check-against-drawing.
- Program O1646 (title OP1, then "(OP 1)" after "(OP2)") looks like an unusual ordering; not checked.
- A commit subject on PR #2 (Phase 5) has an invisible BOM; cosmetic, left alone.
