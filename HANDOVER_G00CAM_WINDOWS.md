# HANDOVER: build and test the G00 CAM .exe on Shane's Windows laptop

**To the local Claude Code session:** you're on Shane's Windows work laptop. Your job is to
build **G00 CAM** into a Windows program with PyInstaller, check that it runs, and put the
finished folder at:

```
%USERPROFILE%\Downloads\G00 CAM Rev1\
    G00 CAM.exe
    _internal\            (everything the exe needs; keep it next to the exe)
    READ_ME_FIRST.txt
```

Then help Shane test it. Most of the work is done and was verified on Linux, including a
packaged Linux build. What hasn't happened yet is a Windows build on a real Windows machine.
That's this job.

## About Shane and the rules

- Shane is a CNC programmer and owner/lead developer of G-SEND.IO (a Python 3 CNC app shipped
  as a Windows EXE). He works direct and task-first, often by voice, and prefers durable fixes
  to workarounds.
- **Work on branch `claude/new-session-sgzhb7`.** Never commit or push to `main`. If `main`
  moves, merge it into the branch (no rebase).
- Change only what he asks for. **Keep the look**: dark industrial theme, blue accent
  `#2f9bff`, Fusion-360-style layout, the G00 logo.
- Commit messages end with the Co-Authored-By line your harness gives you. Don't put model
  names in commits.

## Repo and where things are

GitHub: `ShaneHooper/CADCAM`, branch `claude/new-session-sgzhb7` (open pull request:
ShaneHooper/CADCAM#1).

| Path | What it is |
|---|---|
| `gsend_cad/` | The Python app. **G00 CAM** is the working name; `APP_NAME` in `gsend_cad/__init__.py` is the one place to change it. The package name stays `gsend_cad` because it's meant to become a G-SEND.IO module. |
| `gsend_cad/core/` | Pure Python (stdlib only): sketch entities, profile detection, feature timeline `Document`, `.gcad` JSON files |
| `gsend_cad/kernel/` | build123d / OpenCascade: builds real B-rep solids from the timeline, volume/bbox/mass, STEP export |
| `gsend_cad/ui/` | PySide6 + pyvista window. `ui/assets/` holds the G00 logo (`g00code_logo.png` / `.ico`, copied from `ShaneHooper/G-SEND-IO-REV5/assets`). `ui/fonts/` has Anton + Squada One (OFL). |
| `gsend_cad/README.md` | Full feature list and G-SEND.IO integration notes |
| `packaging/g00cam.spec` | **PyInstaller spec** (one-folder build, windowed, G00 icon) |
| `packaging/g00cam_main.py` | Frozen entry point |
| `packaging/READ_ME_FIRST.txt` | Goes into the finished folder for Shane |
| `.github/workflows/build-windows.yml` | Same build on a GitHub Windows runner (backup route, see the end) |
| `G00CAM.bat` | Run-from-source launcher (makes a `.venv` on first run). Not the exe. |
| `prototypes/gsend-cad/` | The HTML prototype and its HANDOVER: the visual spec |
| `tests/` | `test_core.py`, `test_kernel.py` (pytest); `drive_ui.py` drives the real window (Linux/xvfb script, see below) |

## What the app does now (all verified on Linux)

- **Sketch (L):** line, rectangle, center rect, circle, polygon, grid snap, live dimension tag, sketch-plane Z offset.
- **Extrude (E):** click closed profiles; Join / Cut / New Body; one side or symmetric; live OpenCascade preview.
- **Timeline:** rollback, play, and right-click delete. Failed features turn red.
- **Editing and files:** undo/redo, save/open `.gcad`, and Export STEP / STL (Utilities tab).
- **Crash handling and self-test:** crash log at `%LOCALAPPDATA%\G00CAM\crash.log` plus an error box. `--selftest REPORT` mode (see below).

## Steps

### 1. Prerequisites
- **Python 3.12, 64-bit**, from python.org. Anything from 3.10 to 3.13 works; **not 3.14**,
  because build123d/OCP has no wheels for it. Check with `py -0p`.
- Git. About 5 GB free disk (venv plus build).

### 2. Get the code
```powershell
cd $HOME\source          # or wherever Shane keeps repos
git clone https://github.com/ShaneHooper/CADCAM.git
cd CADCAM
git checkout claude/new-session-sgzhb7
git pull
```

### 3. Environment and tests
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process Bypass
python -m pip install --upgrade pip
python -m pip install -e ".[ui,dev]" pyinstaller
python -m pytest -q tests/test_core.py tests/test_kernel.py     # expect 17 passed
```

### 4. Run from source first (proves Qt + OpenGL work on this laptop)
```powershell
python -m gsend_cad
```
The window should show the G00 logo top-left, the dark ribbon, and the grey Bracket Plate. Try
**L**, draw a rectangle, press **Enter**, then **E**, then **OK**. If this fails, fix it before
building; see Troubleshooting.

### 5. Build the exe
```powershell
pyinstaller packaging/g00cam.spec --noconfirm
```
Output: `dist\G00 CAM\` (about 1.4 GB; OpenCascade, VTK and Qt are big). It takes several minutes.

### 6. Self-test the built exe (it's windowed, so results go to a file)
```powershell
$p = Start-Process "dist\G00 CAM\G00 CAM.exe" -ArgumentList "--selftest","$PWD\selftest.txt" -Wait -PassThru
Get-Content selftest.txt; $p.ExitCode        # expect "... G00 CAM selftest OK" and 0
```
To also open, render and close the real window:
`$env:G00CAM_SELFTEST_WINDOW="1"` before the same command (expect a `window: 1400x820 ...` line).

### 7. Deliver the folder
```powershell
$dst = "$env:USERPROFILE\Downloads\G00 CAM Rev1"
New-Item -ItemType Directory -Force $dst | Out-Null
robocopy "dist\G00 CAM" $dst /E /NFL /NDL /NJH /NJS
Copy-Item packaging\READ_ME_FIRST.txt $dst
```
If Shane already made the folder, copy into it. Don't delete anything else he put there.
Then have him double-click `G00 CAM.exe`.

### 8. Test checklist with Shane
1. It starts, the taskbar shows the G00 logo (not the Python logo), and the title is "G00 CAM".
2. Orbit (left drag), pan (right drag), zoom (wheel). View cube buttons and Home work.
3. **L**, then a rectangle, then a circle inside it, then **Enter**, then **E**. Click the ring
   between the two, set Operation **Cut**, Distance **0.5**, **OK**. You get a pocket with a pin
   left standing, and VOLUME in the properties drops.
4. **L**, set Plane Z to 0.5 in the palette, draw a circle on the plate, **Enter**, **E**, Join 0.75. You get a boss.
5. Click timeline features to roll back and forward; right-click → Delete; **Ctrl+Z** brings it back.
6. **Ctrl+S** to save a `.gcad`, close, reopen it with **Ctrl+O**.
7. Utilities → Export writes STEP. Open it in Fusion to confirm the geometry.

Fix anything he finds on the branch (from source first, then rebuild), commit, and push.

## Troubleshooting (already known)

- **Don't exclude `IPython` or `sklearn` in the spec.** build123d imports both at startup; the
  frozen app dies with `ModuleNotFoundError` without them. `--selftest` catches this.
- **"Windows protected your PC" (SmartScreen):** the exe is unsigned. More info → Run anyway.
  Work antivirus may quarantine files in `_internal`. If the self-test passes in `dist` but the
  copy fails, check the AV log or ask IT to allow the folder.
- **Blank or black 3D view, or a crash creating the window:** VTK needs **OpenGL 3.2+**. Remote
  Desktop sessions and some VMs only offer OpenGL 1.1. Test at the laptop itself, not over
  RDP. If it's really missing, the fallback is Mesa's software `opengl32.dll`
  (mesa-dist-win, the "llvmpipe" build) placed next to `G00 CAM.exe`.
- **Qt platform plugin error:** make sure `_internal\PySide6\plugins\platforms\qwindows.dll`
  exists. If not, reinstall PySide6 in the venv and rebuild.
- **Path length:** keep the repo in a short path (e.g. `C:\src\CADCAM`) if pip or PyInstaller
  complains about long paths.
- Startup takes a few seconds (OpenCascade loading); that's normal for a one-folder build.
- **The size (about 1.4 GB)** is mostly VTK pulled in by pyvista. Leave slimming for later: remove
  modules only with a self-test after each change.

## Backup route: GitHub builds it

The last push to the branch includes `.github/workflows/build-windows.yml`, which runs the same
build and self-test on a GitHub Windows runner. It uploads an artifact named **"G00 CAM Rev1"**
from the run's Summary page in ShaneHooper/CADCAM → Actions. Download the zip and extract it
into `Downloads\G00 CAM Rev1`. It's useful if the laptop can't build (no admin rights, proxy
blocks PyPI). Its self-test skips the window check, because the runner has no GPU.

## Linux-only bits you can ignore on Windows

`tests/drive_ui.py` uses `xvfb-run` and a PIL X11 screenshot. On Windows, run it without
xvfb (`python tests/drive_ui.py outdir`). It may work, but the screenshot part is
X11-specific, so the Step 8 checklist by hand is the real test.

## After the test: the open roadmap (ask Shane which is next)
- Hole and Fillet/Chamfer as real features (they show "not in this build yet" now).
- Connect the kernel's solids to the G-SEND.IO CAM side (`gsend_cad.core` / `kernel` run headless).
  G-SEND.IO's UI is Tkinter, so CAD runs as its own window/process and shares `.gcad`/`.step` files.
