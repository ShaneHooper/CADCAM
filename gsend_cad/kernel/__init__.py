"""Geometry kernel: turns a Document timeline into B-rep solids (build123d / OpenCascade).

    from gsend_cad.core import bracket_plate
    from gsend_cad.kernel import Kernel
    model = Kernel().build(bracket_plate())
    model.bodies[0].volume, model.export_step("part.step")

The kernel knows nothing about Qt, so G-SEND.IO's CAM side can use it headless.
"""
from .model import Body, Kernel, Model, extrude_tool, region_face, triangles

__all__ = ["Kernel", "Model", "Body", "extrude_tool", "region_face", "triangles"]
