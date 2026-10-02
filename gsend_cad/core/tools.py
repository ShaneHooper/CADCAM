"""Tool library (stdlib only): the cutting tools an operation picks from.

    from gsend_cad.core import tools
    lib = tools.load(path)                    # default tools when the file doesn't exist yet
    tools.choices(lib, "milling", "contour")  # the tools that fit a 2D Contour
    tools.save(path, lib)

A tool: {"id", "number" (T number on the machine), "name", "kind", "machine" ("milling" |
"turning"), "dia" (cutting diameter; a grooving insert's width; 0 for a turning insert), "nose_r" (insert nose radius)}.
An operation copies what it needs (op["tool"] = number, op["tool_dia"], op["tool_name"]), so a
saved part still posts the same after the library changes.
"""
from __future__ import annotations

import copy
import json
import os

KINDS = {"face mill": "Face mill", "end mill": "End mill", "drill": "Drill",
         "od turn": "OD turning", "drill-t": "Drill", "groove": "Grooving"}
MACHINE_KINDS = {"milling": ["face mill", "end mill", "drill"], "turning": ["od turn", "drill-t", "groove"]}
# which tool kinds an operation can use, per machine
FITS = {("milling", "face"): ("face mill", "end mill"), ("milling", "contour"): ("end mill",),
        ("milling", "drill"): ("drill",), ("milling", "rough"): ("end mill",), ("turning", "face"): ("od turn",), ("turning", "rough"): ("od turn",),
        ("turning", "finish"): ("od turn",), ("turning", "drill"): ("drill-t",),
        ("turning", "groove"): ("groove",)}

DEFAULT = [
    {"id": "m1", "number": 1, "name": "2.0 Face mill", "kind": "face mill", "machine": "milling", "dia": 2.0, "nose_r": 0.0},
    {"id": "m2", "number": 2, "name": "1/2 End mill", "kind": "end mill", "machine": "milling", "dia": 0.5, "nose_r": 0.0},
    {"id": "m4", "number": 4, "name": "1/4 Drill", "kind": "drill", "machine": "milling", "dia": 0.25, "nose_r": 0.0},
    {"id": "t1", "number": 1, "name": "CNMG Face", "kind": "od turn", "machine": "turning", "dia": 0.0,
     "nose_r": 0.031},
    {"id": "t2", "number": 2, "name": "CNMG Rough", "kind": "od turn", "machine": "turning", "dia": 0.0,
     "nose_r": 0.031},
    {"id": "t3", "number": 3, "name": "VNMG Finish", "kind": "od turn", "machine": "turning", "dia": 0.0,
     "nose_r": 0.016},
    {"id": "t5", "number": 5, "name": "1/4 Drill", "kind": "drill-t", "machine": "turning", "dia": 0.25, "nose_r": 0.0},
    {"id": "t6", "number": 6, "name": "Groove", "kind": "groove", "machine": "turning", "dia": 0.125, "nose_r": 0.0},
]


def validate(t: dict) -> dict:
    t = {"nose_r": 0.0, "dia": 0.0, **copy.deepcopy(t)}
    if t.get("machine") not in MACHINE_KINDS:
        raise ValueError("machine must be milling or turning")
    if t.get("kind") not in MACHINE_KINDS[t["machine"]]:
        raise ValueError(f"a {t['machine']} tool must be one of: " +
                         ", ".join(KINDS[k] for k in MACHINE_KINDS[t["machine"]]))
    t["number"] = int(round(float(t.get("number", 1))))
    if not 1 <= t["number"] <= 99:
        raise ValueError("tool number must be 1 to 99")
    t["dia"], t["nose_r"] = float(t["dia"]), float(t["nose_r"])
    if t["kind"] != "od turn" and t["dia"] <= 0:
        raise ValueError("diameter must be greater than 0")
    if t["dia"] < 0 or t["nose_r"] < 0:
        raise ValueError("sizes can't be negative")
    t["name"] = str(t.get("name") or describe(t))
    return t


def describe(t: dict) -> str:
    """'T2 · 1/2 End mill · Ø0.5000' - what a tool box shows."""
    size = (f"W{t['dia']:.4f}" if t.get("kind") == "groove" else f"Ø{t['dia']:.4f}") if t.get("dia") else \
        f"R{t.get('nose_r', 0):.4f}"
    return f"T{t['number']} · {t.get('name') or KINDS.get(t['kind'], t['kind'])} · {size}"


def choices(lib: list, machine: str, op_kind: str) -> list:
    """The tools an operation of `op_kind` on a `machine` setup can use, by T number."""
    ok = FITS.get((machine, op_kind), ())
    return sorted((t for t in lib if t["machine"] == machine and t["kind"] in ok), key=lambda t: t["number"])


def find(lib: list, op: dict, machine: str, op_kind: str):
    """The library tool an operation uses (same T number and size), else None."""
    for t in choices(lib, machine, op_kind):
        if t["number"] == int(op.get("tool", -1)) and abs(t["dia"] - op.get("tool_dia", t["dia"])) < 1e-9:
            return t
    return None


def apply(op: dict, t: dict) -> dict:
    """The operation using tool t: T number, diameter (when it has one) and name copied in."""
    op = dict(op)
    op["tool"], op["tool_name"] = t["number"], t["name"]
    if t.get("dia"):
        op["tool_dia"] = t["dia"]
    return op


def new_id(lib: list) -> str:
    n = 1
    while f"u{n}" in {t["id"] for t in lib}:
        n += 1
    return f"u{n}"


def load(path: str) -> list:
    """The saved library, or the defaults when there is none (or it can't be read)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        lib = [validate(t) for t in data.get("tools", [])]
        if data.get("version", 1) < 2 and not any(t["kind"] == "groove" for t in lib):
            lib += [copy.deepcopy(t) for t in DEFAULT if t["kind"] == "groove"   # grooving came in v2
                    and t["id"] not in {x["id"] for x in lib}]
        return lib
    except (OSError, ValueError, TypeError, AttributeError):
        return copy.deepcopy(DEFAULT)


def save(path: str, lib: list):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "tools": [validate(t) for t in lib]}, f, indent=1)
    os.replace(tmp, path)
