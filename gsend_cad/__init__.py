"""G-SEND.IO CAD module.

Three layers, so G-SEND.IO can take only what it needs:

    gsend_cad.core    pure Python: sketches, profiles, features, timeline, .gcad files
    gsend_cad.kernel  build123d/OpenCascade: solids, mass properties, STEP/STL export
    gsend_cad.ui      PySide6 + pyvista window (Fusion-style), `launch()`

    import gsend_cad
    gsend_cad.launch()                    # demo part, blocks when standalone
    gsend_cad.launch("part.gcad")
"""
__version__ = "0.1.0"


def launch(document=None, block=None):
    from .ui import launch as _launch   # Qt is imported only when a window is wanted
    return _launch(document, block)
