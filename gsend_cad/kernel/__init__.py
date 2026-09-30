"""Geometry kernel: turns a Document timeline into B-rep solids (build123d / OpenCascade).

    from gsend_cad.core import bracket_plate
    from gsend_cad.kernel import Kernel
    model = Kernel().build(bracket_plate())
    model.bodies[0].volume, model.export_step("part.step")

The kernel knows nothing about Qt, so G-SEND.IO's CAM side can use it headless.
"""
from .model import (Body, Kernel, Model, bodies_bbox, edge_list, extrude_tool, face_outline, planar_face_at, plane_edges,
                    max_radius, model_snap_points, outline_loops, region_face, revolve_axis, revolve_tool, triangles)

__all__ = ["Kernel", "Model", "Body", "extrude_tool", "region_face", "triangles", "planar_face_at",
           "face_outline", "plane_edges", "revolve_tool", "revolve_axis", "edge_list", "bodies_bbox", "max_radius", "outline_loops", "model_snap_points"]
