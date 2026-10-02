"""Third-party licence notices (gsend_cad/licenses.py): what ships with the app is attributed.

    python -m pytest -q tests/test_licenses.py
"""
import importlib.metadata as md

import pytest

from gsend_cad import licenses

pytest.importorskip("shapely")


@pytest.fixture(scope="module")
def text():
    return licenses.notices()


def test_every_direct_dependency_is_listed_with_its_licence(text):
    index = text.split("COMPONENTS", 1)[1].split(licenses.RULE, 1)[0]
    for name in ("build123d", "numpy", "PySide6", "pyvista", "pyvistaqt", "shapely", "vtk"):
        assert any(line.strip().lower().startswith(name.lower()) for line in index.splitlines()), name


def test_shapely_and_geos_are_attributed_with_their_licence_texts(text):
    shapely = md.distribution("shapely")
    names = [f for f, _ in licenses.licence_texts(shapely)]
    assert any("GEOS" in n for n in names) and any(n.endswith("LICENSE.txt") for n in names)
    assert "GEOS (inside Shapely)" in text and "LGPL-2.1-only" in text
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text and "Version 2.1" in text       # the LGPL text itself
    assert "Redistribution and use in source and binary forms" in text                 # Shapely's BSD text


def test_the_lgpl_libraries_inside_packages_are_named(text):
    assert "Qt 6 (inside PySide6)" in text and "LGPL-3.0-only" in text
    assert "Open CASCADE Technology" in text and "OCCT-exception" in text
    assert "you may replace them" in text.replace("\n", " ")       # the LGPL relinking notice


def test_a_licence_text_that_is_not_on_disk_gives_its_official_link(tmp_path, monkeypatch):
    monkeypatch.setattr(licenses, "STATIC", tmp_path)
    assert licenses.LGPL3_URL in licenses.notices()
    (tmp_path / "LGPL-3.0.txt").write_text("THE OFFICIAL LGPL 3 TEXT")
    out = licenses.notices()
    assert "THE OFFICIAL LGPL 3 TEXT" in out and licenses.LGPL3_URL not in out


def test_python_and_the_fonts_are_listed(text):
    assert "Python Software Foundation" in text and "SIL Open Font License" in text


def test_a_build_lists_only_what_it_bundles():
    only = {"shapely", "numpy"}
    names = {d.metadata["Name"].lower() for d in licenses.distributions(only=only)}
    assert names == {"shapely", "numpy"}
    built = licenses.notices(only=only)
    assert licenses.BUILT in built and "PySide6" not in built.split(licenses.RULE, 1)[0].split("COMPONENTS")[1]


def test_optional_extras_and_other_platforms_are_not_followed():
    assert licenses._wanted('pytest ; extra == "test"') is None
    assert licenses._wanted("numpy>=1.21") == "numpy"
    assert licenses._wanted('pyobjc ; sys_platform == "darwin"') in (None, "pyobjc")
