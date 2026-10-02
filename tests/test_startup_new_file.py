"""The standalone app opens as a new, empty file; only a .gcad on the command line is opened.

    python -m pytest -q tests/test_startup_new_file.py
"""
import os
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gsend_cad.ui import app                                          # noqa: E402


def _main(argv):
    seen = {}
    with mock.patch.object(app, "launch", lambda document=None, block=None: seen.setdefault("doc", document)), \
            mock.patch.object(app, "_start_logs", lambda: None):
        app.main(argv)
    return seen["doc"]


def test_no_file_opens_a_new_empty_part():
    doc = _main([])
    assert (doc.name, doc.features, doc.setups, doc.marker) == ("Untitled", [], [], 0)


def test_a_file_on_the_command_line_is_still_opened():
    assert _main(["C:/shop/part.gcad"]) == "C:/shop/part.gcad"


def test_launch_itself_still_defaults_to_the_demo_part_for_hosts_and_the_drive_scripts():
    import inspect
    assert "bracket_plate()" in inspect.getsource(app.launch)