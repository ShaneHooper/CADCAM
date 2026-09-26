# PyInstaller spec for G00 CAM.   pyinstaller packaging/g00cam.spec --noconfirm
# Builds a one-folder app: dist/G00 CAM/ holding "G00 CAM.exe" plus _internal/.
# One-folder (not one-file) on purpose: OpenCascade + VTK + Qt are several hundred MB and a
# one-file exe would unpack all of that to %TEMP% on every start.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent
UI = ROOT / "gsend_cad" / "ui"
NAME = "G00 CAM"

datas = [(str(UI / "assets"), "gsend_cad/ui/assets"), (str(UI / "fonts"), "gsend_cad/ui/fonts")]
binaries = []
hiddenimports = []

# OpenCascade (OCP) is one big compiled package with its own DLLs next to it
hiddenimports += collect_submodules("OCP")
binaries += collect_dynamic_libs("OCP")
for extra in ("cadquery_ocp_novtk", "cadquery_ocp"):
    try:
        binaries += collect_dynamic_libs(extra)
    except Exception:
        pass
# build123d and the small OCP helpers it imports lazily
for pkg in ("build123d", "ocp_gordon", "ocpsvg", "ezdxf", "lib3mf", "svgpathtools", "anytree", "trianglesolver"):
    try:
        hiddenimports += collect_submodules(pkg)
        datas += collect_data_files(pkg)
    except Exception:
        pass
binaries += collect_dynamic_libs("lib3mf")
# pyvista loads VTK modules by name at runtime; take its own modules and the VTK pieces it uses
hiddenimports += collect_submodules("pyvista", filter=lambda m: ".examples" not in m and ".demos" not in m)
datas += collect_data_files("pyvista")
hiddenimports += ["pyvistaqt", "qtpy", "scooby", "pooch"]
hiddenimports += [
    "vtkmodules.vtkRenderingOpenGL2",
    "vtkmodules.vtkRenderingFreeType",
    "vtkmodules.vtkRenderingUI",
    "vtkmodules.vtkInteractionStyle",
    "vtkmodules.vtkRenderingAnnotation",
    "vtkmodules.vtkRenderingVolumeOpenGL2",
    "vtkmodules.vtkRenderingContextOpenGL2",
    "vtkmodules.qt.QVTKRenderWindowInteractor",
]
hiddenimports += collect_submodules("gsend_cad")

# ---- keep the build small (fewer files = faster unzip / install / antivirus scan) ----
# VTK ships ~150 compiled modules; G00 CAM imports ~40. The list below is what the app loads
# (measured by running tests/drive_ui.py, tests/drive_edit.py, export and save/open) plus a
# few common pyvista filters as margin. Every other compiled vtkmodules.vtk* module is left
# out, and with it the VTK libraries only those modules need. If a future feature needs one,
# add it here; --selftest fails on a missing import.
VTK_KEEP = {
    "vtkChartsCore", "vtkCommonColor", "vtkCommonComputationalGeometry", "vtkCommonCore",
    "vtkCommonDataModel", "vtkCommonExecutionModel", "vtkCommonMath", "vtkCommonMisc",
    "vtkCommonSystem", "vtkCommonTransforms", "vtkFiltersCore", "vtkFiltersExtraction",
    "vtkFiltersGeneral", "vtkFiltersGeometry", "vtkFiltersModeling", "vtkFiltersPython",
    "vtkFiltersSources", "vtkFiltersTexture", "vtkIOCore", "vtkIOImage", "vtkIOLegacy", "vtkIOXML",
    "vtkImagingCore", "vtkImagingMath", "vtkImagingSources", "vtkInteractionStyle",
    "vtkInteractionWidgets", "vtkParallelCore", "vtkPythonContext2D", "vtkRenderingAnnotation",
    "vtkRenderingContext2D", "vtkRenderingContextOpenGL2", "vtkRenderingCore",
    "vtkRenderingFreeType", "vtkRenderingHyperTreeGrid", "vtkRenderingLabel",
    "vtkRenderingMatplotlib", "vtkRenderingOpenGL2", "vtkRenderingUI", "vtkRenderingVolume",
    "vtkRenderingVolumeOpenGL2", "vtkViewsContext2D", "vtkViewsCore",
}
import vtkmodules
VTK_DROP = sorted({f"vtkmodules.{f.name.split('.')[0]}" for f in Path(vtkmodules.__file__).parent.iterdir()
                   if f.name.startswith("vtk") and f.suffix in (".pyd", ".so")
                   and f.name.split(".")[0] not in VTK_KEEP})

a = Analysis(
    [str(ROOT / "packaging" / "g00cam_main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "notebook", "trame", "PyQt5", "PyQt6", "PySide2",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick3D", "PySide6.QtMultimedia", "pytest",
              # IPython's code completion; never imported by G00 CAM (jedi alone was 5,500 files)
              "jedi", "parso", "prompt_toolkit",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtPdf",
              "PySide6.QtNetwork"] + VTK_DROP,
    noarchive=False,
)
# Qt plugins that pull in Quick/QML (virtual keyboard) or the PDF engine: not used.
QT_DROP = ("qt6quick", "qt6qml", "qt6virtualkeyboard", "virtualkeyboard", "qt6pdf", "qpdf")
a.binaries = [b for b in a.binaries if not any(k in Path(b[0]).name.lower() for k in QT_DROP)]
pyz = PYZ(a.pure)
icon = str(UI / "assets" / "g00code_logo.ico") if sys.platform == "win32" else None
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, icon=icon,
          upx=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
