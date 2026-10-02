"""Third-party licence notices: every library the built app ships, with its licence text.

Stdlib only. The list is not written by hand: it walks the installed packages the app
depends on and copies the licence files each one ships, so it cannot drift from what is
actually bundled.

    python -m gsend_cad.licenses [OUTFILE]      write / print THIRD_PARTY_LICENSES.txt

The Windows build runs this (packaging/gsend_cadcam.spec) and puts the file next to the
.exe; Help > Open-source licences shows it. When a library is added to the app, add its
package name to ROOTS - its own dependencies are found from there.
"""
from __future__ import annotations

import importlib.metadata as md
from pathlib import Path
import re
import sys

FILE_NAME = "THIRD_PARTY_LICENSES.txt"
# what the app imports directly; everything these need is followed from here
ROOTS = ("build123d", "numpy", "PySide6", "pyvista", "pyvistaqt", "shapely")
_LICENCE_FILE = re.compile(r"(^|/)(licen[cs]e|copying|notice|authors|copyright)[^/]*$", re.I)
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
RULE = "=" * 100

INTRO = """\
{app} - THIRD-PARTY SOFTWARE NOTICES

{app} is built with the open-source software listed below. Each component remains under
its own licence, reproduced here in full. Thank you to everyone who wrote them.

LGPL components (Qt / PySide6, GEOS inside Shapely, OpenCascade): these are shipped as
separate library files in the "_internal" folder beside the program, not merged into it,
so you may replace them with your own compatible builds. Their source code is available
from the project pages listed with each one.

{source}
"""
BUILT = "This file was generated from the libraries bundled in this build."
LIVE = ("Generated from the libraries installed for this copy (running from source). A built app "
        "ships its own list, limited to what that build bundles.")
STATIC = Path(__file__).with_name("third_party")       # licence texts no package ships (see its README)
LGPL3_URL = "https://www.gnu.org/licenses/lgpl-3.0.txt"
OCCT_URL = "https://github.com/Open-Cascade-SAS/OCCT/blob/master/OCCT_LGPL_EXCEPTION.txt"


def _canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _wanted(requirement: str) -> str | None:
    """The package a requirement names, or None when it only applies to an optional extra
    or to another operating system."""
    head, _, marker = requirement.partition(";")
    m = _NAME.match(head)
    if not m:
        return None
    marker = marker.lower()
    if "extra" in marker:
        return None
    if "sys_platform" in marker or "platform_system" in marker:
        here = {"win32": ("win32", "windows"), "darwin": ("darwin",), "linux": ("linux",)}.get(sys.platform, ())
        wants_here = any(f'"{h}"' in marker or f"'{h}'" in marker for h in here)
        if ("==" in marker and not wants_here) or ("!=" in marker and wants_here):
            return None
    return m.group(1)


def top_levels(dist: md.Distribution) -> set[str]:
    """The import names a package provides (PySide6_Essentials -> PySide6, Shiboken...)."""
    names = {n.split("/")[0] for n in (dist.read_text("top_level.txt") or "").split()}
    for f in dist.files or []:
        first = str(f).replace("\\", "/").split("/")[0]
        if not first.endswith((".dist-info", ".data")) and first not in ("..", "__pycache__"):
            names.add(first[:-3] if first.endswith(".py") else first.split(".")[0])
    return names


def distributions(roots=ROOTS, only: set[str] | None = None) -> list[md.Distribution]:
    """The root packages and everything they depend on that is installed, by name.

    only: the top-level modules a build actually bundles - packages providing none of them
    (pulled in by a dependency but excluded from the build) are left out."""
    seen: dict[str, md.Distribution] = {}
    todo = list(roots)
    while todo:
        name = todo.pop()
        key = _canon(name)
        if key in seen:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        seen[key] = dist
        for req in dist.requires or []:
            dep = _wanted(req)
            if dep:
                todo.append(dep)
    found = sorted(seen.values(), key=lambda d: _canon(d.metadata["Name"]))
    if only is not None:
        found = [d for d in found if top_levels(d) & only]
    return found


def licence_name(dist: md.Distribution) -> str:
    meta = dist.metadata
    if meta.get("License-Expression"):
        return meta["License-Expression"]
    lic = (meta.get("License") or "").strip()
    if lic and "\n" not in lic and len(lic) < 80:
        return lic
    named = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return ", ".join(named) or "see the licence text below"


def homepage(dist: md.Distribution) -> str:
    meta = dist.metadata
    urls = dict(u.split(",", 1) for u in meta.get_all("Project-URL") or [] if "," in u)
    for key in ("Source", "Source Code", "Repository", "Homepage", "Home", "Documentation"):
        for k, v in urls.items():
            if k.strip().lower() == key.lower():
                return v.strip()
    return (meta.get("Home-page") or next(iter(urls.values()), "")).strip()


def licence_texts(dist: md.Distribution) -> list[tuple[str, str]]:
    """(file name, text) for every licence / notice / authors file the package ships."""
    out = []
    for f in dist.files or []:
        path = str(f).replace("\\", "/")
        if ".dist-info/" not in path or not _LICENCE_FILE.search(path):
            continue
        try:
            text = Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            out.append((path.split(".dist-info/", 1)[1], text))
    return out


def _static(name: str, url: str) -> tuple[str, str]:
    f = STATIC / name
    if f.exists():
        return name, f.read_text(encoding="utf-8", errors="replace").strip()
    return name, f"The full text of this licence is at:\n    {url}"


def _lgpl21() -> list[tuple[str, str]]:
    """The LGPL 2.1 text, which Shapely ships for GEOS."""
    try:
        for fname, text in licence_texts(md.distribution("shapely")):
            if "GEOS" in fname.upper() and "LESSER GENERAL PUBLIC LICENSE" in text.upper():
                return [("GNU LGPL 2.1", text)]
    except md.PackageNotFoundError:
        pass
    return [("GNU LGPL 2.1", "The full text of this licence is at:\n"
                             "    https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt")]


def _native(names: set[str]) -> list[tuple[str, str, str, list[tuple[str, str]]]]:
    """Compiled libraries that ride inside a Python package and carry their own licence."""
    out = []
    if "pyside6" in names or "pyside6-essentials" in names:
        out.append(("Qt 6 (inside PySide6)", "LGPL-3.0-only", "https://code.qt.io  /  https://www.qt.io/licensing",
                    [_static("LGPL-3.0.txt", LGPL3_URL)]))
    if any(n.startswith("cadquery-ocp") for n in names):
        out.append(("Open CASCADE Technology (inside cadquery-ocp)", "LGPL-2.1-only WITH OCCT-exception-1.0",
                    "https://github.com/Open-Cascade-SAS/OCCT",
                    _lgpl21() + [_static("OCCT_LGPL_EXCEPTION.txt", OCCT_URL)]))
    if "shapely" in names:
        out.append(("GEOS (inside Shapely)", "LGPL-2.1-only", "https://libgeos.org", _lgpl21()))
    return out


def _extras() -> list[tuple[str, str, str, list[tuple[str, str]]]]:
    """Bundled things that are not Python packages: the interpreter and the fonts."""
    out = []
    for name in ("LICENSE.txt", "LICENSE"):
        f = Path(sys.base_prefix) / name
        if f.exists():
            out.append((f"Python {sys.version.split()[0]}", "Python Software Foundation License",
                        "https://www.python.org", [(name, f.read_text(encoding="utf-8", errors="replace").strip())]))
            break
    fonts = Path(__file__).with_name("ui") / "fonts"
    for f in sorted(fonts.glob("OFL*.txt")) if fonts.is_dir() else []:
        out.append((f"Font: {f.stem.replace('OFL-', '').replace('OFL', '').strip('-') or 'bundled fonts'}",
                    "SIL Open Font License 1.1", "https://openfontlicense.org",
                    [(f.name, f.read_text(encoding="utf-8", errors="replace").strip())]))
    return out


def notices(roots=ROOTS, app: str | None = None, only: set[str] | None = None) -> str:
    if app is None:
        from . import APP_NAME as app
    parts = [INTRO.format(app=app, source=LIVE if only is None else BUILT)]
    dists = distributions(roots, only)
    entries = [(f"{d.metadata['Name']} {d.version}", licence_name(d), homepage(d), licence_texts(d)) for d in dists]
    entries += _native({_canon(d.metadata["Name"]) for d in dists}) + _extras()
    parts.append("COMPONENTS\n" + "\n".join(f"  {name:<34} {lic}" for name, lic, _, _ in entries) + "\n")
    for name, lic, url, texts in entries:
        block = [RULE, name, f"Licence: {lic}"]
        if url:
            block.append(f"Project: {url}")
        block.append(RULE)
        if not texts:
            block.append("(this package ships no licence file; see the project page above)")
        for fname, text in texts:
            block += ["", f"--- {fname} ---", "", text]
        parts.append("\n".join(block) + "\n")
    return "\n".join(parts)


def write(path, only: set[str] | None = None) -> Path:
    path = Path(path)
    path.write_text(notices(only=only), encoding="utf-8")
    return path


def shipped() -> Path | None:
    """The notices file of a built app (next to the .exe), if this is one."""
    for folder in (Path(sys.executable).parent, Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", "") else None):
        if folder and (folder / FILE_NAME).exists():
            return folder / FILE_NAME
    return None


def text() -> str:
    """What Help > Open-source licences shows: the shipped file, or a live list when run from source."""
    f = shipped()
    return f.read_text(encoding="utf-8", errors="replace") if f else notices()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(write(sys.argv[1]))
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(notices())
