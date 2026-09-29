# CLAUDE.md: G00 CAM (ShaneHooper/CADCAM)

Owner: Shane (CNC programmer, owner of G-SEND.IO). Big, long-running project: **keep every change
small and cheap.** Read only the file(s) the task needs, change only what he asks, keep the look.

## Where things live: go straight there, don't read around
| To change... | Edit only |
|---|---|
| App name | `gsend_cad/__init__.py` → `APP_NAME` |
| Colours (accent blue, panels, lines) | `gsend_cad/ui/theme.py` → tokens at the top (`ACCENT`, `PANEL`, ...) |
| Fonts | files in `gsend_cad/ui/fonts/` + family lists `HEAD` / `MONO` / `BRAND_*` in `theme.py` |
| Logo / app icon | `gsend_cad/ui/assets/g00code_logo.png` / `.ico` (same file names) |
| Widget styling (QSS) | `theme.py` → `qss()` |
| Ribbon tabs / tools | `gsend_cad/ui/panels.py` → `RIBBON` dict at the top |
| Toolbar/tree icons | `gsend_cad/ui/icons.py` → `PATHS` |
| Help → Documentation text | `gsend_cad/ui/docs.py` |
| Sketch tools, Extrude dialog | `gsend_cad/ui/commands.py` |
| 3D view, camera, grid, HUD, view cube | `gsend_cad/ui/viewport.py` |
| Menus, shortcuts, wiring, save/open | `gsend_cad/ui/main_window.py` |
| Startup, splash, crash logs, `--selftest` | `gsend_cad/ui/app.py` |
| Sketch entity math / closed profiles | `gsend_cad/core/sketch.py`, `core/profiles.py` |
| Features, timeline, .gcad file format | `gsend_cad/core/document.py` |
| Solids, booleans, STEP/STL | `gsend_cad/kernel/model.py` |
| Windows build | `packaging/` (spec, entry, installer .iss, update_app.py, sign_folder.py) |

Layers: `core` (stdlib only) ← `kernel` (build123d/OCC) ← `ui` (PySide6/pyvista). Never import
`ui` from `core`/`kernel`: G-SEND.IO's CAM side must be able to use them without Qt.

## Don't read these (big, rarely relevant)
`prototypes/gsend-cad/gsend_cad_prototype.html` (680 KB, visual spec only; look at its
`screenshots/` instead), `*.png`, `dist/`, `build/`, `.venv/`, `gsend_cad/screenshots/`.

## Test only what you touched
- `core` or `kernel` change: `python -m pytest -q tests/test_core.py tests/test_kernel.py` (seconds)
- UI change: `python -m gsend_cad` and look; the full UI drives (`tests/drive_ui.py`,
  `tests/drive_edit.py`) only for bigger UI work.
- Theme/font/logo/text-only change: no tests needed beyond opening the app once.

## The Windows build has two layers: DON'T rebuild the exe for normal changes
```
G00 CAM\  G00 CAM.exe + _internal\   RUNTIME: Python, Qt, VTK, OpenCascade (~800 binaries).
                                     PyInstaller + signing. Minutes, and signing costs quota.
          app\gsend_cad\             APP: our code, fonts, logo as plain files. Seconds.
```
- Code / font / logo / colour change: `python packaging/update_app.py "<built folder>"`.
  **No PyInstaller, no re-signing** (Smart App Control checks .exe/.dll, not .py).
- Rebuild the runtime (`pyinstaller packaging/g00cam.spec`) **only** when a dependency is
  added or upgraded, or the spec / `packaging/g00cam_main.py` changes. Then re-sign it:
  `python packaging/sign_folder.py "dist/G00 CAM"` (Azure Trusted Signing, same
  `signing.local.json` as G-SEND.IO; never commit that file).
- CI (`.github/workflows/build-windows.yml`) caches the runtime by a hash of spec + entry +
  pyproject, so a code-only push skips PyInstaller and also uploads a small
  "G00 CAM app update" artifact (just `app/`).
- A new *import* of a library the runtime doesn't bundle yet does need a runtime rebuild.
  `--selftest` catches it (ModuleNotFoundError).

## Signing (Smart App Control)
CI signs with Azure Artifact Signing exactly like G-SEND.IO's `release.yml` (same account
`gsendio-prod-signing`, profile `gsendio-public-trust`, OIDC, no stored certificate). The job
runs in this repo's **`production-signing`** environment. For it to sign, Shane must (once):
1. GitHub → CADCAM → Settings → Environments → `production-signing`: add secrets
   `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` (same values as REV5's).
2. Azure → the Entra app REV5 uses → Certificates & secrets → Federated credentials → add one
   for GitHub: org `ShaneHooper`, repo `CADCAM`, entity **Environment**, name `production-signing`.
Without these the build still runs but is UNSIGNED (a warning says so). The runtime (~800
binaries) is signed once per runtime rebuild and cached signed; each build then signs only the
installer (1 signature).

## Git rules
Branch `claude/new-session-sgzhb7` (PR #1). Never commit to `main`. If `main` moves, merge it in
(no rebase). Commit messages end with the harness's Co-Authored-By line; no model names.
